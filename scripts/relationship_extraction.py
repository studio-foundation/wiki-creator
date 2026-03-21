#!/usr/bin/env python3
"""
Stage: Relationship Extraction (STU-229)
Builds a weighted co-occurrence graph between resolved PERSON entities.

Pipeline position:
  epub-parse → entity-extraction → entity-clustering → entity-resolution
  → relationship-extraction → wiki-generation

Input (via Studio context):
  previous_outputs.entity-resolution: { "entities": [{canonical_name, type, aliases, source_ids, relevant}] }
  Files read from repo root: persons_full.json, places_full.json, orgs_full.json

Output (stdout):
  {
    "relationships": [
      {
        "entity_a": "David Martín",
        "entity_b": "Pedro Vidal",
        "cooccurrence_count": 45,
        "chapters": ["ch01", "ch03"],
        "sample_contexts": ["Vidal tendit le manuscrit à Martín..."],
        "relationship_type": null,
        "direction": null,
        "evolution": null,
        "key_moments": []
      }
    ],
    "stats": {
      "total_pairs_checked": 120,
      "pairs_above_threshold": 18,
      "classified": 0,
      "window_size": 5,
      "threshold": 5
    }
  }

Standalone test:
  python scripts/relationship_extraction.py --test
  python scripts/relationship_extraction.py --test --classify --model qwen2.5
  python scripts/relationship_extraction.py --test --window 3 --threshold 2
  python scripts/relationship_extraction.py --test --coref
  python scripts/relationship_extraction.py --live --coref
  python scripts/relationship_extraction.py --live --coref --workers 4
  python scripts/relationship_extraction.py --test --coref --workers 2

Workers / RAM budget (LingMessCoref ~590M params per worker):
  --workers 1  :  ~3 GB  (default, safe on any machine)
  --workers 2  :  ~5 GB
  --workers 4  :  ~10 GB (recommended on 16 GB machines)
  --workers 8  :  ~20 GB (recommended on 32 GB machines)
  If a worker runs out of memory, it returns [] for its chapter (graceful skip).
"""

import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

import yaml

# Ensure project root is importable when running as `python scripts/<file>.py`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from wiki_creator.paths import book_paths_from_epub, book_paths_from_yaml, BookPaths
from wiki_creator.lang import load_lang_config, infer_language


def _paths_from_payload(payload: dict) -> BookPaths | None:
    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    file_path = ctx.get("file_path")
    if not file_path:
        return None
    return book_paths_from_epub(file_path)


DEFAULT_WINDOW = 5
DEFAULT_THRESHOLD = 5
DEFAULT_MIN_COOCCURRENCE = 3
DEFAULT_MIN_CHAPTERS_TOGETHER = 2
_OLLAMA_URL = "http://localhost:11434"


def _tightest_span(window: list[str], name_a: str, name_b: str) -> str:
    """Return the minimal contiguous sub-sequence of ``window`` that contains
    both ``name_a`` and ``name_b`` (case-insensitive, word-boundary match).

    Falls back to ``window[0]`` if either name is not found in any sentence.
    """
    idx_a: int | None = None
    idx_b: int | None = None
    for i, sent in enumerate(window):
        sent_lower = sent.lower()
        if idx_a is None and re.search(r'\b' + re.escape(name_a.lower()) + r'\b', sent_lower):
            idx_a = i
        if idx_b is None and re.search(r'\b' + re.escape(name_b.lower()) + r'\b', sent_lower):
            idx_b = i
    if idx_a is None or idx_b is None:
        return window[0]
    lo, hi = min(idx_a, idx_b), max(idx_a, idx_b)
    return " ".join(window[lo : hi + 1])


def build_cooccurrence_graph(
    entities: list[dict],
    mentions_by_entity: dict[str, dict[str, list[str]]],
    window_size: int = DEFAULT_WINDOW,
    threshold: int = DEFAULT_THRESHOLD,
    min_cooccurrence: int | None = None,
    min_chapters_together: int = DEFAULT_MIN_CHAPTERS_TOGETHER,
) -> tuple[list[dict], dict]:
    """
    Build weighted co-occurrence graph between PERSON entities.

    Args:
        entities: resolved entities with canonical_name, aliases, relevant, type
        mentions_by_entity: {canonical_name: {chapter_id: [sentence, ...]}}
        window_size: sliding window of N sentences
        threshold: minimum co-occurrence count to include in output
        min_cooccurrence: minimum co-occurrence count to include. Overrides threshold
            when provided. Defaults to None (falls back to threshold).
        min_chapters_together: minimum number of distinct chapters the pair must
            co-occur in. Defaults to DEFAULT_MIN_CHAPTERS_TOGETHER (2).

    Returns:
        (relationships list, stats dict)
    """
    effective_min_cooc = min_cooccurrence if min_cooccurrence is not None else threshold

    # Filter to PERSON entities that are relevant
    persons = [e for e in entities if e.get("type") == "PERSON" and e.get("relevant", True)]

    # Build lookup: all known names (canonical + aliases ≥4 chars) → canonical_name
    name_to_canonical: dict[str, str] = {}
    for entity in persons:
        canonical = entity["canonical_name"]
        key = canonical.lower()
        if key in name_to_canonical and name_to_canonical[key] != canonical:
            print(f"[WARN] Name collision: '{canonical}' conflicts with '{name_to_canonical[key]}'", file=sys.stderr)
        name_to_canonical[key] = canonical
        for alias in entity.get("aliases", []):
            if len(alias) >= 4:
                alias_key = alias.lower()
                if alias_key in name_to_canonical and name_to_canonical[alias_key] != canonical:
                    print(f"[WARN] Alias collision: '{alias}' maps to both '{name_to_canonical[alias_key]}' and '{canonical}'", file=sys.stderr)
                else:
                    name_to_canonical[alias_key] = canonical

    # Co-occurrence matrix: {(canonical_a, canonical_b): {"count": int, "chapters": set, "contexts": list}}
    cooc: dict[tuple[str, str], dict] = {}

    total_pairs_checked = len(persons) * (len(persons) - 1) // 2

    persons_canonical = {e["canonical_name"] for e in persons}

    # Build unified chapter sentences (deduplicated, order-preserved) across all entity mentions
    chapter_sentences: dict[str, list[str]] = {}
    chapter_seen: dict[str, set[str]] = {}
    for canonical, chapters in mentions_by_entity.items():
        if canonical not in persons_canonical:
            continue
        for chapter_id, sentences in chapters.items():
            if chapter_id not in chapter_sentences:
                chapter_sentences[chapter_id] = []
            if chapter_id not in chapter_seen:
                chapter_seen[chapter_id] = set()
            for sent in sentences:
                if sent not in chapter_seen[chapter_id]:
                    chapter_seen[chapter_id].add(sent)
                    chapter_sentences[chapter_id].append(sent)

    # Slide window once per chapter
    for chapter_id, sentences in chapter_sentences.items():
        for i in range(len(sentences)):
            window = sentences[i : i + window_size]
            window_text = " ".join(window)

            # Find which entities appear in this window
            present: set[str] = set()
            for name, canon in name_to_canonical.items():
                if re.search(r'\b' + re.escape(name) + r'\b', window_text.lower()):
                    present.add(canon)

            # Record all pairs in this window
            present_list = sorted(present)
            for idx_a in range(len(present_list)):
                for idx_b in range(idx_a + 1, len(present_list)):
                    a, b = present_list[idx_a], present_list[idx_b]
                    key = (a, b)
                    if key not in cooc:
                        cooc[key] = {"count": 0, "chapters": set(), "contexts": []}
                    cooc[key]["count"] += 1
                    cooc[key]["chapters"].add(chapter_id)
                    if len(cooc[key]["contexts"]) < 3:
                        cooc[key]["contexts"].append(_tightest_span(window, a, b))

    # Build output: filter by min_cooccurrence and min_chapters_together
    relationships = []
    for (a, b), data in cooc.items():
        if data["count"] >= effective_min_cooc and len(data["chapters"]) >= min_chapters_together:
            relationships.append({
                "entity_a": a,
                "entity_b": b,
                "cooccurrence_count": data["count"],
                "chapters": sorted(data["chapters"]),
                "sample_contexts": data["contexts"],
                "relationship_type": None,
                "direction": None,
                "evolution": None,
                "key_moments": [],
            })

    relationships.sort(key=lambda r: r["cooccurrence_count"], reverse=True)

    pairs_above = len(relationships)
    stats = {
        "total_pairs_checked": total_pairs_checked,
        "pairs_above_threshold": pairs_above,
        "classified": 0,
        "window_size": window_size,
        "threshold": effective_min_cooc,
        "min_cooccurrence": effective_min_cooc,
        "min_chapters_together": min_chapters_together,
    }

    return relationships, stats


def enrich_mentions_with_coref(
    chapters: dict[str, str],
    entities: list[dict],
    mentions_by_entity: dict[str, dict[str, list[str]]],
    silence_window: int = 5,
    nlp=None,
    pronouns=None,
) -> dict[str, dict[str, list[str]]]:
    """
    Enrich mentions_by_entity with pronoun sentences via a spaCy-only heuristic.

    For each chapter, process sentences with fr_core_news_lg. Track the last known
    PERSON canonical entity ("active entity"). When a sentence has French pronouns
    but no PERSON entity, add it to the active entity's mentions. Reset the active
    entity after `silence_window` consecutive sentences with no PERSON mention.

    Args:
        chapters: {chapter_id: full_text} from chapters.json
        entities: resolved entities list (canonical_name, aliases, type, relevant)
        mentions_by_entity: existing {canonical → {chapter_id → [sentences]}}
        silence_window: reset active entity after this many sentences with no PERSON
        nlp: optional pre-loaded spaCy model; if None, loads fr_core_news_lg
        pronouns: optional frozenset of pronoun strings; if None, loads from fr lang config

    Returns:
        mentions_by_entity enriched in-place (also returned for convenience)
    """
    import spacy

    if pronouns is None:
        pronouns = frozenset(load_lang_config("fr").get("pronouns", []))

    if not chapters:
        return mentions_by_entity

    # Build name→canonical lookup
    persons = [e for e in entities if e.get("type") == "PERSON" and e.get("relevant", True)]
    name_to_canonical: dict[str, str] = {}
    for entity in persons:
        canonical = entity["canonical_name"]
        name_to_canonical[canonical.lower()] = canonical
        for alias in entity.get("aliases", []):
            if len(alias) >= 4:
                name_to_canonical[alias.lower()] = canonical

    if not name_to_canonical:
        return mentions_by_entity

    if nlp is None:
        try:
            nlp = spacy.load("fr_core_news_lg")
        except Exception as e:
            print(f"[WARN] spaCy load failed: {e}", file=sys.stderr)
            return mentions_by_entity

    total_added = 0

    for chapter_id, text in chapters.items():
        if not text or not text.strip():
            continue

        try:
            doc = nlp(text)
        except Exception as e:
            print(f"[WARN] spaCy failed on {chapter_id}: {e}", file=sys.stderr)
            continue

        active_entity: str | None = None
        silence_count: int = 0

        for sent in doc.sents:
            # Find PERSON entities in this sentence
            sent_persons = []
            for ent in sent.ents:
                if ent.label_ == "PER":
                    canon = name_to_canonical.get(ent.text.lower())
                    if canon:
                        sent_persons.append(canon)

            if sent_persons:
                # Update active entity (last seen person in sentence)
                active_entity = sent_persons[-1]
                silence_count = 0
                continue

            # No PERSON in this sentence
            silence_count += 1
            if silence_count > silence_window:
                active_entity = None

            if active_entity is None:
                continue

            # Check for pronouns
            has_pronoun = any(
                token.pos_ == "PRON" and token.text.lower() in pronouns
                for token in sent
            )
            if not has_pronoun:
                continue

            # Add sentence to active entity's mentions
            sentence = sent.text.strip()
            if not sentence:
                continue

            if active_entity not in mentions_by_entity:
                mentions_by_entity[active_entity] = {}
            if chapter_id not in mentions_by_entity[active_entity]:
                mentions_by_entity[active_entity][chapter_id] = []
            existing = mentions_by_entity[active_entity][chapter_id]
            if sentence not in existing:
                existing.append(sentence)
                total_added += 1

    print(f"[coref] Pronoun sentences added: {total_added}", file=sys.stderr)
    return mentions_by_entity


# Alias for public API used in tests and main()
enrich_mentions_with_heuristic = enrich_mentions_with_coref


# ---------------------------------------------------------------------------
# fastcoref / LingMessCoref — accurate coreference (STU-237)
# ---------------------------------------------------------------------------

def _patch_attn_eager() -> None:
    """Force attn_implementation='eager' for AutoModel.from_config.

    LingMessCoref (LongformerModel) doesn't support SDPA in transformers >= 4.45.
    See: https://github.com/huggingface/transformers/issues/28005
    """
    import transformers

    if getattr(transformers.AutoModel.from_config, "_patched_eager", False):
        return
    _orig = transformers.AutoModel.from_config.__func__

    @classmethod  # type: ignore[misc]
    def _patched(cls, config, **kwargs):  # type: ignore[misc]
        kwargs.setdefault("attn_implementation", "eager")
        return _orig(cls, config, **kwargs)

    _patched._patched_eager = True  # type: ignore[attr-defined]
    transformers.AutoModel.from_config = _patched


_SENT_BOUNDARY = re.compile(r'(?<=[.!?»])\s+(?=[A-ZÀÂÇÈÉÊÎÔÙÛÜ\u2014«])')


def _find_sentence_containing(text: str, char_start: int) -> str:
    """Return the sentence in text that contains the character at char_start."""
    boundaries = [0] + [m.end() for m in _SENT_BOUNDARY.finditer(text)] + [len(text)]
    for i in range(len(boundaries) - 1):
        if boundaries[i] <= char_start < boundaries[i + 1]:
            return text[boundaries[i]:boundaries[i + 1]].strip()
    return text[max(0, char_start - 80):min(len(text), char_start + 120)].strip()


def _decode_mention_offsets(mention: object) -> tuple[int, int] | None:
    """Extract (start_char, end_char) from a fastcoref mention object."""
    if hasattr(mention, "start_char"):
        return mention.start_char, mention.end_char  # type: ignore[attr-defined]
    if isinstance(mention, (tuple, list)) and len(mention) == 2:
        try:
            return int(mention[0]), int(mention[1])
        except (ValueError, TypeError):
            pass
    # String repr "(110, 112)"
    try:
        coords = str(mention).strip("()").split(",")
        return int(coords[0].strip()), int(coords[1].strip())
    except Exception:
        return None


def _process_chapter_clusters(
    raw_clusters: list,
    chunk: str,
    chapter_id: str,
    name_to_canonical: dict[str, str],
    pronouns: frozenset | None = None,
) -> list[tuple[str, str, str]]:
    """Process fastcoref clusters for one chapter chunk.

    Returns a deduplicated list of (canonical_name, chapter_id, sentence) tuples.
    """
    if pronouns is None:
        pronouns = frozenset(load_lang_config("fr").get("pronouns", []))

    results: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    for cluster in raw_clusters:
        decoded: list[tuple[str, int, int]] = []
        for mention in cluster:
            offsets = _decode_mention_offsets(mention)
            if offsets is None:
                continue
            start, end = offsets
            if 0 <= start < end <= len(chunk):
                decoded.append((chunk[start:end], start, end))

        if not decoded:
            continue

        canonical: str | None = None
        for m_text, _, _ in sorted(decoded, key=lambda x: -len(x[0])):
            candidate = name_to_canonical.get(m_text.lower())
            if candidate:
                canonical = candidate
                break
            first_word = m_text.split()[0].lower() if m_text.split() else ""
            candidate = name_to_canonical.get(first_word)
            if candidate:
                canonical = candidate
                break

        if not canonical:
            continue

        for m_text, start, _ in decoded:
            tokens = m_text.lower().split()
            is_pronoun = (len(tokens) == 1 and tokens[0] in pronouns) or (
                len(tokens) <= 2
                and any(t in pronouns for t in tokens)
                and m_text.lower() not in name_to_canonical
            )
            if not is_pronoun:
                continue

            sentence = _find_sentence_containing(chunk, start)
            if sentence:
                key = (canonical, chapter_id, sentence)
                if key not in seen:
                    seen.add(key)
                    results.append((canonical, chapter_id, sentence))

    return results


def _coref_worker(args: tuple) -> list[tuple[str, str, str]]:
    """Worker function for ProcessPoolExecutor: load model + process one chapter.

    Each worker process loads its own LingMessCoref instance (~590 MB RAM).
    Must be a top-level function (picklable by multiprocessing).

    Args:
        args: (chapter_id, text, name_to_canonical, spacy_model)
            name_to_canonical: {lowercased_name: canonical_name}
            spacy_model: spaCy model name to load (e.g. "fr_core_news_lg")

    Returns:
        List of (canonical_name, chapter_id, sentence) tuples to be merged
        by the parent process. Returns [] on any error (graceful degradation).
    """
    chapter_id, text, name_to_canonical, spacy_model = args
    if not text or not text.strip():
        return []

    chunk = text[:8000]

    try:
        import spacy
        from fastcoref import spacy_component  # noqa: F401

        _patch_attn_eager()
        nlp = spacy.load(
            spacy_model,
            exclude=["parser", "lemmatizer", "ner", "textcat"],
        )
        nlp.add_pipe(
            "fastcoref",
            config={
                "model_architecture": "LingMessCoref",
                "model_path": "biu-nlp/lingmess-coref",
                "device": "cpu",
            },
        )
        doc = nlp(chunk, component_cfg={"fastcoref": {"resolve_text": True}})
    except MemoryError:
        import sys as _sys
        print(f"[coref/worker] MemoryError on {chapter_id} — skipping", file=_sys.stderr)
        return []
    except Exception as e:
        import sys as _sys
        print(f"[coref/worker] Error on {chapter_id}: {e}", file=_sys.stderr)
        return []

    raw_clusters = doc._.coref_clusters or []
    return _process_chapter_clusters(raw_clusters, chunk, chapter_id, name_to_canonical)


def enrich_mentions_with_fastcoref(
    chapters: dict[str, str],
    entities: list[dict],
    mentions_by_entity: dict[str, dict[str, list[str]]],
    workers: int = 1,
    spacy_model: str = "fr_core_news_lg",
) -> dict[str, dict[str, list[str]]]:
    """Enrich mentions using fastcoref + LingMessCoref for accurate coreference.

    For each chapter (first 8 000 chars), run LingMessCoref to get coreference
    clusters. For each cluster containing a known PERSON entity mention, find
    pronoun mentions in the same cluster and attribute their sentences to that
    entity.

    Falls back silently to the naive heuristic if fastcoref is not installed.

    Args:
        chapters: {chapter_id: full_text} from chapters.json
        entities: resolved entities (canonical_name, aliases, type, relevant)
        mentions_by_entity: existing {canonical → {chapter_id → [sentences]}}
        workers: number of parallel processes (default 1 = sequential).
                 Each worker loads its own model (~590 MB RAM per worker).
                 RAM budget: 1 worker=~3 GB, 4 workers=~10 GB, 8 workers=~20 GB.
        spacy_model: spaCy model name to load (default "fr_core_news_lg").

    Returns:
        mentions_by_entity enriched in-place (also returned for convenience)
    """
    if not chapters:
        return mentions_by_entity

    # Build name → canonical lookup for PERSON entities
    persons = [e for e in entities if e.get("type") == "PERSON" and e.get("relevant", True)]
    name_to_canonical: dict[str, str] = {}
    for entity in persons:
        canonical = entity["canonical_name"]
        name_to_canonical[canonical.lower()] = canonical
        for alias in entity.get("aliases", []):
            if len(alias) >= 3:
                name_to_canonical[alias.lower()] = canonical

    if not name_to_canonical:
        return mentions_by_entity

    total_added = 0

    if workers <= 1:
        # Sequential path — load model once, iterate chapters
        try:
            import spacy
            from fastcoref import spacy_component  # noqa: F401

            _patch_attn_eager()
            nlp = spacy.load(
                spacy_model,
                exclude=["parser", "lemmatizer", "ner", "textcat"],
            )
            nlp.add_pipe(
                "fastcoref",
                config={
                    "model_architecture": "LingMessCoref",
                    "model_path": "biu-nlp/lingmess-coref",
                    "device": "cpu",
                },
            )
        except Exception as e:
            print(
                f"[WARN] fastcoref unavailable ({e}) — falling back to heuristic",
                file=sys.stderr,
            )
            return enrich_mentions_with_coref(chapters, entities, mentions_by_entity)

        for chapter_id, text in chapters.items():
            if not text or not text.strip():
                continue
            chunk = text[:8000]
            try:
                doc = nlp(chunk, component_cfg={"fastcoref": {"resolve_text": True}})
            except Exception as e:
                print(f"[WARN] fastcoref inference failed on {chapter_id}: {e}", file=sys.stderr)
                continue

            raw_clusters = doc._.coref_clusters or []
            for canonical, cid, sentence in _process_chapter_clusters(raw_clusters, chunk, chapter_id, name_to_canonical):
                if canonical not in mentions_by_entity:
                    mentions_by_entity[canonical] = {}
                if cid not in mentions_by_entity[canonical]:
                    mentions_by_entity[canonical][cid] = []
                existing = mentions_by_entity[canonical][cid]
                if sentence not in existing:
                    existing.append(sentence)
                    total_added += 1

    else:
        # Parallel path — one worker process per chapter, each loads own model
        from concurrent.futures import ProcessPoolExecutor
        import multiprocessing

        chapter_items = [
            (cid, text, name_to_canonical, spacy_model)
            for cid, text in chapters.items()
            if text and text.strip()
        ]

        actual_workers = min(workers, len(chapter_items), multiprocessing.cpu_count())
        print(
            f"[coref/parallel] {len(chapter_items)} chapters, {actual_workers} workers",
            file=sys.stderr,
        )

        try:
            with ProcessPoolExecutor(max_workers=actual_workers) as executor:
                all_results = list(executor.map(_coref_worker, chapter_items))
        except Exception as e:
            print(
                f"[WARN] Parallel coref failed ({type(e).__name__}: {e}) — falling back to sequential (workers=1)",
                file=sys.stderr,
            )
            return enrich_mentions_with_fastcoref(chapters, entities, mentions_by_entity, workers=1, spacy_model=spacy_model)

        # Merge results from all workers
        for worker_results in all_results:
            for canonical, chapter_id, sentence in worker_results:
                if canonical not in mentions_by_entity:
                    mentions_by_entity[canonical] = {}
                if chapter_id not in mentions_by_entity[canonical]:
                    mentions_by_entity[canonical][chapter_id] = []
                existing = mentions_by_entity[canonical][chapter_id]
                if sentence not in existing:
                    existing.append(sentence)
                    total_added += 1

    print(f"[coref/fastcoref] Pronoun sentences added: {total_added}", file=sys.stderr)
    return mentions_by_entity


def run_test_mode(
    window_size: int,
    threshold: int,
    coref: bool = False,
    workers: int = 1,
    min_cooccurrence: int | None = None,
    min_chapters_together: int = DEFAULT_MIN_CHAPTERS_TOGETHER,
) -> None:
    """Run with hardcoded Le Jeu de l'Ange data."""
    entities = [
        {"canonical_name": "David Martín", "type": "PERSON", "aliases": ["Martín", "David"], "relevant": True},
        {"canonical_name": "Pedro Vidal", "type": "PERSON", "aliases": ["Vidal"], "relevant": True},
        {"canonical_name": "Andreas Corelli", "type": "PERSON", "aliases": ["Corelli"], "relevant": True},
        {"canonical_name": "Isabella", "type": "PERSON", "aliases": ["Isa"], "relevant": True},
        {"canonical_name": "Cristina", "type": "PERSON", "aliases": [], "relevant": True},
    ]

    mentions_by_entity = {
        "David Martín": {
            "ch01": [
                "Vidal tendit le manuscrit à Martín en souriant.",
                "Martín retrouva Vidal au café de la rue Fernando.",
                "Martín écrivit toute la nuit.",
                "Vidal encouragea Martín à continuer son roman.",
                "Martín pensait souvent à Isabella.",
            ],
            "ch02": [
                "Martín reçut une lettre de Corelli.",
                "Corelli proposa un contrat à Martín.",
                "Martín hésita longtemps avant d'accepter.",
                "Cristina observait Martín depuis le couloir.",
                "Martín ne remarqua pas Cristina.",
            ],
            "ch03": [
                "Isabella retrouva Martín dans le parc.",
                "Martín et Isabella parlèrent des heures.",
                "Vidal arriva et interrompit leur conversation.",
                "Martín regarda Vidal avec méfiance.",
                "Corelli attendait Martín dans son bureau.",
            ],
            "ch04": [
                "Il s'assit près de la fenêtre et contempla la nuit.",
                "Elle lui tendit la lettre sans un mot.",
                "Il la prit et la lut lentement.",
            ],
        },
        "Pedro Vidal": {
            "ch01": [
                "Vidal tendit le manuscrit à Martín en souriant.",
                "Martín retrouva Vidal au café de la rue Fernando.",
                "Vidal encouragea Martín à continuer son roman.",
                "Vidal rentra chez lui à minuit.",
            ],
            "ch03": [
                "Vidal arriva et interrompit leur conversation.",
                "Martín regarda Vidal avec méfiance.",
            ],
            "ch04": [
                "Il s'assit près de la fenêtre et contempla la nuit.",
            ],
        },
        "Andreas Corelli": {
            "ch02": [
                "Martín reçut une lettre de Corelli.",
                "Corelli proposa un contrat à Martín.",
                "Martín hésita longtemps avant d'accepter.",
                "Corelli attendait Martín dans son bureau.",
            ],
            "ch03": [
                "Corelli attendait Martín dans son bureau.",
            ],
        },
        "Isabella": {
            "ch01": [
                "Martín pensait souvent à Isabella.",
            ],
            "ch03": [
                "Isabella retrouva Martín dans le parc.",
                "Martín et Isabella parlèrent des heures.",
                "Vidal arriva et interrompit leur conversation.",
            ],
        },
        "Cristina": {
            "ch02": [
                "Cristina observait Martín depuis le couloir.",
                "Martín ne remarqua pas Cristina.",
            ],
        },
    }

    if coref:
        # In test mode, chapters.json is not available.
        # Build a minimal chapters dict from existing mentions for demo.
        chapters_demo: dict[str, str] = {}
        for canonical, by_chapter in mentions_by_entity.items():
            for chapter_id, sentences in by_chapter.items():
                text = " ".join(sentences)
                if chapter_id in chapters_demo:
                    chapters_demo[chapter_id] += " " + text
                else:
                    chapters_demo[chapter_id] = text
        mentions_by_entity = enrich_mentions_with_fastcoref(chapters_demo, entities, mentions_by_entity, workers=workers)

    relationships, stats = build_cooccurrence_graph(
        entities, mentions_by_entity, window_size, threshold,
        min_cooccurrence=min_cooccurrence,
        min_chapters_together=min_chapters_together,
    )

    print(f"=== TEST MODE — relationship-extraction ===\n")
    print(f"Window size: {window_size}  |  Threshold: {threshold}\n")
    print(f"Top relationships (cooccurrence_count desc):\n")
    for rel in relationships[:20]:
        classified = f"  → {rel['relationship_type']}" if rel.get("relationship_type") else ""
        print(f"  {rel['entity_a']} ↔ {rel['entity_b']}")
        print(f"    count={rel['cooccurrence_count']}  chapters={rel['chapters']}{classified}")
        if rel.get("sample_contexts"):
            print(f"    sample: {rel['sample_contexts'][0][:80]}...")
        print()

    # Validation
    top_pairs = {
        (r["entity_a"], r["entity_b"]) for r in relationships
    } | {
        (r["entity_b"], r["entity_a"]) for r in relationships
    }
    expected = [
        ("David Martín", "Pedro Vidal"),
        ("David Martín", "Andreas Corelli"),
        ("David Martín", "Isabella"),
        ("David Martín", "Cristina"),
    ]
    print("\n=== VALIDATION ===")
    all_ok = True
    for a, b in expected:
        found = (a, b) in top_pairs or (b, a) in top_pairs
        status = "✓" if found else "✗ MISSING"
        print(f"  {status}  {a} ↔ {b}")
        if not found:
            all_ok = False
    print(f"\n{'All expected pairs found.' if all_ok else 'SOME PAIRS MISSING — check algorithm.'}")

    if "--classify" in sys.argv:
        try:
            model_idx = sys.argv.index("--model")
            cli_model = sys.argv[model_idx + 1] if model_idx + 1 < len(sys.argv) else None
        except ValueError:
            cli_model = None
        if not cli_model:
            print(
                "[ERROR] --classify requires --model <model_name> (e.g. --model qwen2.5)",
                file=sys.stderr,
            )
            sys.exit(1)
        print("\n=== CLASSIFY MODE ===")
        relationships = classify_relationships(relationships, model=cli_model)
        classified_count = sum(1 for r in relationships if r.get("relationship_type"))
        print(f"Classified {classified_count}/{len(relationships)} relationships")
        for r in relationships[:5]:
            print(f"  {r['entity_a']} ↔ {r['entity_b']}: {r['relationship_type']} ({r['direction']})")
            if r.get("evolution"):
                print(f"    evolution: {r['evolution']}")
        stats["classified"] = classified_count

    print(f"\n=== STATS ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")


def _check_ollama_available(url: str, timeout: int = 2) -> bool:
    """Return True if Ollama is reachable at url/api/tags."""
    try:
        req = urllib.request.Request(f"{url}/api/tags", method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except (urllib.error.URLError, socket.timeout, OSError):
        return False


def _call_ollama_classify_json(
    prompt: str, model: str, ollama_url: str, timeout: int = 30
) -> dict | None:
    """Call Ollama /api/generate and parse JSON response. Returns None on any failure."""
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 300},
    }).encode()
    req = urllib.request.Request(
        f"{ollama_url}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        raw = data.get("response", "")
        return json.loads(raw)
    except (urllib.error.URLError, socket.timeout, OSError, json.JSONDecodeError):
        return None


def _run_studio_classifier_item(
    rel: dict,
    *,
    novel_summary: str,
    additional_context: str,
    timeout_seconds: int = 120,
) -> dict:
    """Invoke Studio to classify one relationship pair via relationship-classifier-item pipeline."""
    item_input = {
        "entity_a": rel["entity_a"],
        "entity_b": rel["entity_b"],
        "cooccurrence_count": rel.get("cooccurrence_count", 0),
        "sample_contexts": rel.get("sample_contexts", []),
        "novel_summary": novel_summary or "",
    }

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".yaml", delete=False) as tmp:
        yaml.safe_dump(item_input, tmp, sort_keys=False, allow_unicode=True)
        input_path = tmp.name

    cmd = ["studio", "run", "relationship-classifier-item", "--input-file", input_path, "--json"]
    try:
        result = subprocess.run(
            cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=timeout_seconds
        )
    except FileNotFoundError:
        return {"error": "studio_cli_missing"}
    except subprocess.TimeoutExpired:
        return {"error": "studio_run_timeout"}
    finally:
        Path(input_path).unlink(missing_ok=True)

    if result.returncode != 0:
        return {"error": "studio_run_failed", "stderr": result.stderr}

    try:
        run_payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"error": "studio_output_json_parse_error"}

    stages = run_payload.get("stages", [])
    if not isinstance(stages, list):
        return {"error": "studio_run_output_missing"}
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        if stage.get("stage_name") in ("relationship-classifier", "relationship-classifier-item"):
            if stage.get("status") == "success":
                output = stage.get("output")
                if isinstance(output, dict):
                    return output
    return {"error": "studio_run_output_missing"}


_NON_INTERPERSONAL_TYPES = frozenset({"PLACE", "OTHER"})


def _should_classify_pair(rel: dict, entity_types: dict[str, str]) -> bool:
    """Return False if either entity has a non-interpersonal type (PLACE, OTHER)."""
    for key in ("entity_a", "entity_b"):
        etype = entity_types.get(rel.get(key, ""), "")
        if etype in _NON_INTERPERSONAL_TYPES:
            return False
    return True


def classify_relationships(
    relationships: list[dict],
    *,
    model: str,
    ollama_url: str = _OLLAMA_URL,
    novel_summary: str | None = None,
    additional_context: str = "",
    entity_types: dict[str, str] | None = None,
) -> list[dict]:
    """Classify relationships using Studio relationship-classifier-item pipeline.

    ``model`` and ``ollama_url`` are kept for API compatibility but unused —
    the model is now configured in the relationship-classifier agent YAML.
    """
    _etypes = entity_types or {}
    result = []
    for rel in relationships:
        if not _should_classify_pair(rel, _etypes):
            result.append(rel)
            continue
        classification = _run_studio_classifier_item(
            rel,
            novel_summary=novel_summary or "",
            additional_context=additional_context,
        )
        if classification and not classification.get("error"):
            rel = {
                **rel,
                "relationship_type": classification.get("relationship_type"),
                "direction": classification.get("direction"),
                "evolution": classification.get("evolution"),
                "key_moments": classification.get("key_moments", []),
                "evidence": classification.get("evidence"),
            }
        else:
            print(
                f"  [WARN] Studio classification failed for "
                f"{rel['entity_a']}↔{rel['entity_b']}: "
                f"{classification.get('error', 'unknown')}",
                file=sys.stderr,
            )
        result.append(rel)
    return result


def _load_mentions_from_files(processing_dir: Path) -> dict[str, dict[str, list[str]]]:
    """
    Load mentions_by_chapter from per-type entity files written by entity-extraction.
    Returns {first_raw_mention: {chapter_id: [sentences]}}.
    Files are read from the processing_dir for the book.
    """
    mentions: dict[str, dict[str, list[str]]] = {}
    type_files = {
        "persons_full.json": "persons_full",
        "places_full.json": "places_full",
        "orgs_full.json": "orgs_full",
    }

    for filename, key in type_files.items():
        p = processing_dir / filename
        if not p.exists():
            continue
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        for entity_id, entry in data.get(key, {}).items():
            raw = entry.get("raw_mentions", [])
            name = raw[0] if raw else entity_id
            mentions[name] = entry.get("mentions_by_chapter", {})

    return mentions


def run_live_mode(
    window_size: int,
    threshold: int,
    paths: "BookPaths | None" = None,
    coref: bool = False,
    workers: int = 1,
    min_cooccurrence: int | None = None,
    min_chapters_together: int = DEFAULT_MIN_CHAPTERS_TOGETHER,
) -> None:
    """Live mode: read persons_full.json, cluster entities, then run co-occurrence on real data."""
    import sys as _sys
    import importlib.util

    if paths is None:
        print("--live requires --book <path/to/book.yaml>", file=sys.stderr)
        sys.exit(1)

    persons_path = paths.processing / "persons_full.json"
    if not persons_path.exists():
        print(f"{persons_path} not found. Run make test-extraction first.", file=sys.stderr)
        sys.exit(1)

    # Load entity_clustering to reuse its build_clusters function
    clustering_path = os.path.join(os.path.dirname(__file__), "entity_clustering.py")
    spec = importlib.util.spec_from_file_location("entity_clustering", clustering_path)
    clustering_mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(clustering_mod)  # type: ignore[union-attr]

    with open(persons_path, encoding="utf-8") as f:
        data = json.load(f)

    persons_data = data.get("persons_full", {})

    # Build entities dict in format expected by build_clusters
    clustering_input = {}
    raw_mentions_map: dict[str, dict[str, list[str]]] = {}  # entity_id → mentions_by_chapter
    for entity_id, entry in persons_data.items():
        raw = entry.get("raw_mentions", [])
        if not raw:
            continue
        mention_count = sum(len(v) for v in entry.get("mentions_by_chapter", {}).values())
        clustering_input[entity_id] = {
            "type": "PERSON",
            "raw_mentions": raw,
            "first_seen": entry.get("first_seen", ""),
            "mention_count": mention_count or len(raw),
        }
        raw_mentions_map[entity_id] = entry.get("mentions_by_chapter", {})

    clusters, unclustered = clustering_mod.build_clusters(clustering_input)

    # Build entities list from clusters
    entities = []
    # maps canonical_name → list of entity_ids in the cluster
    cluster_members: dict[str, list[str]] = {}

    _SALUTATION_PREFIXES = frozenset({"cher", "chère", "dear", "très"})

    def _pick_canonical(all_mentions: list[str], member_ids: list[str]) -> str:
        """
        Pick the best canonical name from a cluster's mentions.
        Prefer the most-mentioned form that:
          1. Is not all-caps
          2. Does not start with a salutation ('Cher', etc.)
          3. Has 1-3 real tokens after title stripping
        Falls back to the entity_clustering candidate if nothing qualifies.
        """
        # Score each mention by how many sentences it appears in across the book
        scores: dict[str, int] = {}
        for mention in all_mentions:
            count = 0
            for eid in member_ids:
                for sents in raw_mentions_map.get(eid, {}).values():
                    count += sum(1 for s in sents if mention.lower() in s.lower())
            scores[mention] = count

        def is_good(mention: str) -> bool:
            if mention == mention.upper() and len(mention) > 2:
                return False  # skip ALL-CAPS forms
            words = mention.split()
            if words and words[0].lower() in _SALUTATION_PREFIXES:
                return False  # skip salutations
            return True

        good_mentions = [m for m in all_mentions if is_good(m)]
        if not good_mentions:
            good_mentions = all_mentions

        return max(good_mentions, key=lambda m: scores.get(m, 0))

    for c in clusters:
        canonical = _pick_canonical(c["all_mentions"], c["entity_ids"])
        entities.append({
            "canonical_name": canonical,
            "type": "PERSON",
            "aliases": [m for m in c["all_mentions"] if m != canonical],
            "relevant": True,
        })
        cluster_members[canonical] = c["entity_ids"]

    for entity_id, entry in unclustered.items():
        raw = entry.get("raw_mentions", [])
        if not raw:
            continue
        canonical = max(raw, key=lambda n: len(n))
        entities.append({
            "canonical_name": canonical,
            "type": "PERSON",
            "aliases": [m for m in raw if m != canonical],
            "relevant": True,
        })
        cluster_members[canonical] = [entity_id]

    # Build mentions_by_entity: merge mentions_by_chapter across all cluster members
    mentions_by_entity: dict[str, dict[str, list[str]]] = {}
    for canonical, member_ids in cluster_members.items():
        merged: dict[str, list[str]] = {}
        for eid in member_ids:
            for chapter_id, sentences in raw_mentions_map.get(eid, {}).items():
                if chapter_id not in merged:
                    merged[chapter_id] = []
                merged[chapter_id].extend(sentences)
        mentions_by_entity[canonical] = merged

    if coref:
        chapters_path = paths.processing / "chapters.json"
        if not chapters_path.exists():
            print("[WARN] chapters.json not found — run make test first.", file=sys.stderr)
        else:
            with open(chapters_path, encoding="utf-8") as f:
                chapters_data = json.load(f)
            chapters = chapters_data.get("chapters", {})
            mentions_by_entity = enrich_mentions_with_fastcoref(chapters, entities, mentions_by_entity, workers=workers)

    print(f"=== LIVE MODE — relationship-extraction ===\n")
    print(f"Loaded {len(entities)} persons from {persons_path}")
    print(f"Window size: {window_size}  |  Threshold: {threshold}\n")

    relationships, stats = build_cooccurrence_graph(
        entities, mentions_by_entity, window_size, threshold,
        min_cooccurrence=min_cooccurrence,
        min_chapters_together=min_chapters_together,
    )

    print(f"Top 20 relations (cooccurrence_count desc):\n")
    for rel in relationships[:20]:
        print(f"  {rel['entity_a']} ↔ {rel['entity_b']}")
        print(f"    count={rel['cooccurrence_count']}  chapters={len(rel['chapters'])}")
        if rel.get("sample_contexts"):
            snippet = rel["sample_contexts"][0][:80]
            print(f"    sample: {snippet}...")
        print()

    print(f"=== STATS ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    # Fuzzy validation: look for expected pairs in top 20 using word-token matching
    def pair_found(name_a: str, name_b: str) -> bool:
        words_a = {w.lower() for w in name_a.split() if len(w) >= 4}
        words_b = {w.lower() for w in name_b.split() if len(w) >= 4}
        for rel in relationships[:20]:
            ea = rel["entity_a"].lower()
            eb = rel["entity_b"].lower()
            if any(w in ea for w in words_a) and any(w in eb for w in words_b):
                return True
            if any(w in eb for w in words_a) and any(w in ea for w in words_b):
                return True
        return False

    # Also check top 40 for rank reporting
    def pair_rank(name_a: str, name_b: str) -> int | None:
        words_a = {w.lower() for w in name_a.split() if len(w) >= 4}
        words_b = {w.lower() for w in name_b.split() if len(w) >= 4}
        for i, rel in enumerate(relationships):
            ea = rel["entity_a"].lower()
            eb = rel["entity_b"].lower()
            if any(w in ea for w in words_a) and any(w in eb for w in words_b):
                return i + 1
            if any(w in eb for w in words_a) and any(w in ea for w in words_b):
                return i + 1
        return None

    expected = [
        ("David Martín", "Pedro Vidal"),
        ("David Martín", "Andreas Corelli"),
        ("David Martín", "Isabella"),
    ]
    print(f"\n=== VALIDATION (top 20) ===")
    for a, b in expected:
        if pair_found(a, b):
            print(f"  ✓  {a} ↔ {b}")
        else:
            rank = pair_rank(a, b)
            rank_info = f" (rank #{rank})" if rank else " (not found)"
            print(f"  ✗ NOT IN TOP 20{rank_info}  {a} ↔ {b}")


def main() -> None:
    args = sys.argv[1:]

    window_size = DEFAULT_WINDOW
    threshold = DEFAULT_THRESHOLD

    if "--window" in args:
        idx = args.index("--window")
        window_size = int(args[idx + 1])

    if "--threshold" in args:
        idx = args.index("--threshold")
        threshold = int(args[idx + 1])

    coref = "--coref" in args

    workers = 1
    if "--workers" in args:
        idx = args.index("--workers")
        workers = int(args[idx + 1])

    min_cooccurrence = None
    if "--min-cooccurrence" in args:
        idx = args.index("--min-cooccurrence")
        min_cooccurrence = int(args[idx + 1])

    min_chapters_together = DEFAULT_MIN_CHAPTERS_TOGETHER
    if "--min-chapters" in args:
        idx = args.index("--min-chapters")
        min_chapters_together = int(args[idx + 1])

    if "--test" in args:
        run_test_mode(
            window_size, threshold, coref=coref, workers=workers,
            min_cooccurrence=min_cooccurrence,
            min_chapters_together=min_chapters_together,
        )
        return

    if "--live" in args:
        book_yaml = None
        if "--book" in args:
            idx = args.index("--book")
            book_yaml = args[idx + 1]
        live_paths = book_paths_from_yaml(book_yaml) if book_yaml else None
        if live_paths is None:
            run_live_mode(
                window_size, threshold, coref=coref, workers=workers,
                min_cooccurrence=min_cooccurrence,
                min_chapters_together=min_chapters_together,
            )
        else:
            run_live_mode(
                window_size, threshold, live_paths, coref=coref, workers=workers,
                min_cooccurrence=min_cooccurrence,
                min_chapters_together=min_chapters_together,
            )
        return

    payload = json.load(sys.stdin)

    prev_outputs = payload.get("previous_outputs", {})
    resolution_output = (
        prev_outputs.get("alias-resolution")
        or prev_outputs.get("merge-entities")
        or prev_outputs.get("entity-resolution")
        or {}
    )
    entities = resolution_output.get("entities", [])

    if not entities:
        json.dump({"error": "missing alias-resolution or merge-entities output"}, sys.stdout, ensure_ascii=False)
        sys.exit(1)

    # Parse classify flag from additional_context (YAML string)
    do_classify = False
    do_coref = False
    min_cooccurrence_val = None
    min_chapters_together = DEFAULT_MIN_CHAPTERS_TOGETHER
    spacy_model = "fr_core_news_lg"
    llm_model: str | None = None
    ollama_url = os.environ.get("OLLAMA_URL", _OLLAMA_URL)
    pronouns: frozenset = frozenset(load_lang_config("fr").get("pronouns", []))
    novel_summary: str | None = None
    raw_context = payload.get("additional_context", "")
    if raw_context:
        try:
            additional = yaml.safe_load(raw_context) or {}
            do_classify = bool(additional.get("classify", False))
            llm_model = additional.get("llm_model") or additional.get("model")
            novel_summary = (additional.get("novel_summary") or "").strip() or None
            ollama_url = additional.get("ollama_url", os.environ.get("OLLAMA_URL", _OLLAMA_URL))
            do_coref = bool(additional.get("coref", False))
            window_size = int(additional.get("window", window_size))
            threshold = int(additional.get("threshold", threshold))
            workers = int(additional.get("workers", workers))
            min_cooccurrence_val = additional.get("min_cooccurrence")
            if min_cooccurrence_val is not None:
                min_cooccurrence_val = int(min_cooccurrence_val)
            min_chapters_together = int(additional.get("min_chapters_together", DEFAULT_MIN_CHAPTERS_TOGETHER))
            spacy_model = additional.get("spacy_model", "fr_core_news_lg")
            language = (
                additional.get("export", {}).get("categories", {}).get("language")
                or infer_language(spacy_model)
            )
            lang_cfg = load_lang_config(language)
            pronouns = frozenset(lang_cfg.get("pronouns", []))
        except Exception:
            min_cooccurrence_val = None
            min_chapters_together = DEFAULT_MIN_CHAPTERS_TOGETHER
            spacy_model = "fr_core_news_lg"
            pronouns = frozenset(load_lang_config("fr").get("pronouns", []))

    paths = _paths_from_payload(payload)
    mentions_by_entity = _load_mentions_from_files(paths.processing) if paths else {}

    if do_coref and paths:
        chapters_path = paths.processing / "chapters.json"
        if chapters_path.exists():
            with open(chapters_path, encoding="utf-8") as f:
                chapters_data = json.load(f)
            chapters = chapters_data.get("chapters", {})
            mentions_by_entity = enrich_mentions_with_fastcoref(
                chapters, entities, mentions_by_entity, workers=workers, spacy_model=spacy_model
            )

    relationships, stats = build_cooccurrence_graph(
        entities, mentions_by_entity, window_size, threshold,
        min_cooccurrence=min_cooccurrence_val,
        min_chapters_together=min_chapters_together,
    )

    if do_classify:
        if not llm_model:
            print(
                "  [ERROR] classify=true but no llm_model/model in additional_context — classification skipped.",
                file=sys.stderr,
            )
        else:
            relationships = classify_relationships(
                relationships,
                model=llm_model,
                ollama_url=ollama_url,
                novel_summary=novel_summary,
            )
            stats["classified"] = sum(1 for r in relationships if r.get("relationship_type"))

    narrator = resolution_output.get("narrator", None)

    json.dump({
        "entities": entities,
        "relationships": relationships,
        "stats": stats,
        "narrator": narrator,
    }, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
