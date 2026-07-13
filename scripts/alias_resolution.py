#!/usr/bin/env python3
"""
Stage: alias-resolution

Consumes resolved entities from resolve-clusters and conservatively merges PERSON
entities when local mention context contains strong alias or reveal evidence.
"""

import json
import os
import re
import sys
import warnings
from pathlib import Path

import yaml
from collections.abc import Callable
from typing import Literal, TypedDict

from wiki_creator import studio_io
from wiki_creator.lang import load_lang_config, infer_language
from wiki_creator.llm import ollama
from wiki_creator.registry import EntityRecord, Registry, normalize_name


class AliasPair(TypedDict):
    entity_a: str
    entity_b: str
    confidence: Literal["high", "medium"]
    source: Literal["pattern", "cooccurrence", "title_alias"]
    snippet: str


_WINDOW_SIZE = 300  # tokens


def _empty_stats() -> dict:
    return {
        "candidates_considered": 0,
        "merges_applied": 0,
        "merges_by_method": {"pattern": 0, "cooccurrence": 0, "llm": 0, "title_alias": 0, "role_symmetric": 0, "pure_title": 0, "series_seed": 0},
        "ambiguous_pairs": 0,
        "embedding_vetoes": 0,
        "llm_attempts": 0,
        "llm_confirmed": 0,
        "llm_failed": 0,
    }


_LLM_PROMPT_TEMPLATE = """\
Given two character entities from a novel, determine if they refer to the same person.

Entity A: "{name_a}"
Snippets:
{snippets_a}

Entity B: "{name_b}"
Snippets:
{snippets_b}

Signal: "{signal}"

Reply ONLY with valid JSON:
{{"same_person": true/false, "confidence": "high"/"medium"/"low", "evidence": "<one sentence>"}}"""


def _fmt_snippets(snippets: list[str]) -> str:
    if not snippets:
        return "- (no context available)"
    return "\n".join(f"- {s[:200]}" for s in snippets)


def make_ollama_confirmer(model: str, url: str, timeout: int) -> Callable:
    """Return an llm_confirmer callable backed by Ollama."""

    def confirmer(candidate: dict) -> dict | None:
        entity_a = candidate["entity_a"]
        entity_b = candidate["entity_b"]
        evidence = candidate["evidence"]
        persons_full = candidate.get("persons_full", {})

        snippets_a = _pick_snippets(entity_a, persons_full)
        snippets_b = _pick_snippets(entity_b, persons_full)

        prompt = _LLM_PROMPT_TEMPLATE.format(
            name_a=entity_a.get("canonical_name", ""),
            name_b=entity_b.get("canonical_name", ""),
            snippets_a=_fmt_snippets(snippets_a),
            snippets_b=_fmt_snippets(snippets_b),
            signal=evidence.get("snippet", "")[:300],
        )

        return ollama.generate_json(prompt, model=model, url=url, timeout=timeout, num_predict=128)

    return confirmer


def _load_persons_full(processing_dir: Path) -> dict:
    path = processing_dir / "persons_full.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("persons_full", {})


def _entity_names(entity: dict) -> list[str]:
    names = [entity.get("canonical_name", "")]
    names.extend(entity.get("aliases", []))
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        cleaned = str(name or "").strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def _gather_contexts(entity: dict, persons_full: dict) -> list[str]:
    snippets: list[str] = []
    for source_id in entity.get("source_ids", []):
        entry = persons_full.get(source_id, {})
        for mentions in entry.get("mentions_by_chapter", {}).values():
            for snippet in mentions:
                if isinstance(snippet, str) and snippet.strip():
                    snippets.append(snippet.strip())
    return snippets


def _pick_snippets(entity: dict, persons_full: dict, n: int = 3) -> list[str]:
    """Return up to n snippets for entity, prioritising those containing the canonical name."""
    all_snippets = _gather_contexts(entity, persons_full)
    name = (entity.get("canonical_name") or "").lower()
    with_name = [s for s in all_snippets if name and name in s.lower()]
    without_name = [s for s in all_snippets if s not in with_name]
    ordered = with_name + without_name
    return ordered[:n]


def _is_pure_title(name: str, role_words: list[str]) -> bool:
    """Return True if name is a bare title, not a title + proper name.

    Recognises:
      * single-word roles: 'Master', 'King'
      * enumerated role phrases: 'Crown Prince' when 'crown prince' ∈ role_words
      * modifier + role head: 'Crown Prince', 'High Lord' — a multi-word phrase whose
        HEAD noun (last token) is a role word, so the leading modifier need not be
        enumerated (STU-471). English titles are head-final, so the head carries the
        role. A title + surname ('Captain Westfall') keeps a non-role head and is
        therefore NOT pure — it is handled by _detect_title_alias instead.
    """
    name_lower = name.lower()
    if not name_lower:
        return False
    role_set = {r.lower() for r in role_words}
    # Match the full name as a role phrase (e.g. "Crown Prince" in {"crown prince", ...})
    if name_lower in role_set:
        return True
    tokens = name_lower.split()
    # Match token-by-token (e.g. "Master" where "master" in role_set)
    if all(t in role_set for t in tokens):
        return True
    # Modifier + role head: last token is a role word ("Crown Prince" -> "prince").
    return len(tokens) > 1 and tokens[-1] in role_set


def _pick_canonical_name(
    entity_a: dict,
    entity_b: dict,
    persons_full: dict,
    role_words: list[str] | None = None,
) -> str:
    role_words = role_words or []
    counts: dict[str, int] = {}
    for entity in (entity_a, entity_b):
        for name in _entity_names(entity):
            counts[name] = 0
    for entity in (entity_a, entity_b):
        contexts = " ".join(_gather_contexts(entity, persons_full)).lower()
        for name in counts:
            counts[name] += contexts.count(name.lower())
    return sorted(
        counts,
        key=lambda name: (
            _is_pure_title(name, role_words),   # False (0) sorts before True (1) — proper names first
            -counts[name],
            -len(name.split()),
            -len(name),
            name.lower(),
        ),
    )[0]


def _merge_entities(
    entity_a: dict,
    entity_b: dict,
    evidence: dict,
    persons_full: dict,
    role_words: list[str] | None = None,
) -> dict:
    canonical = _pick_canonical_name(entity_a, entity_b, persons_full, role_words=role_words)
    alias_names = sorted({name for entity in (entity_a, entity_b) for name in _entity_names(entity)}, key=str.lower)
    source_ids = sorted({sid for entity in (entity_a, entity_b) for sid in entity.get("source_ids", [])})
    merged_from = [
        entity.get("canonical_name", "")
        for entity in (entity_a, entity_b)
        if entity.get("canonical_name") and entity.get("canonical_name") != canonical
    ]
    return {
        "canonical_name": canonical,
        "type": "PERSON",
        "aliases": alias_names,
        "source_ids": source_ids,
        "relevant": bool(entity_a.get("relevant", True) or entity_b.get("relevant", True)),
        "alias_resolution": {
            "merged_from": merged_from,
            "evidence": [evidence],
            "confidence": evidence["confidence"],
            "method": evidence["method"],
        },
    }


def _detect_series_seed(
    entity_a: dict,
    entity_b: dict,
    seed_lookup: dict[str, EntityRecord] | None,
) -> dict | None:
    """Series seeding (STU-485): two entities whose names are known aliases of
    the same series-registry entity are the same person — identity established
    in a prior tome, no local evidence needed. Names must be *distinct*
    surfaces (normalize_name) so this only replays known alias links, never
    folds same-name duplicates that upstream stages deliberately kept apart.
    """
    if not seed_lookup:
        return None
    for name_a in _entity_names(entity_a):
        record = seed_lookup.get(normalize_name(name_a))
        if record is None:
            continue
        for name_b in _entity_names(entity_b):
            if normalize_name(name_b) == normalize_name(name_a):
                continue
            if seed_lookup.get(normalize_name(name_b)) is record:
                books = ", ".join(record.books) or "prior tomes"
                return {
                    "method": "series_seed",
                    "confidence": "high",
                    "snippet": (
                        f"series registry: '{name_a}' and '{name_b}' are known "
                        f"aliases of '{record.canonical_name}' (books: {books})"
                    ),
                }
    return None


def _detect_pattern_for_names(
    name_a: str,
    name_b: str,
    snippets: list[str],
    pattern_templates: tuple[str, ...] = (),
) -> str | None:
    """Return the first snippet matching an alias pattern for name_a/name_b, or None."""
    if name_a.lower() == name_b.lower():
        return None
    pattern_a_b = [
        t.format(a=re.escape(name_a.lower()), b=re.escape(name_b.lower()))
        for t in pattern_templates
    ]
    pattern_b_a = [
        t.format(a=re.escape(name_b.lower()), b=re.escape(name_a.lower()))
        for t in pattern_templates
    ]
    for snippet in snippets:
        lowered = snippet.lower()
        for pattern in pattern_a_b + pattern_b_a:
            if re.search(pattern, lowered):
                return snippet
    return None


def _detect_pattern_match(
    entity_a: dict,
    entity_b: dict,
    persons_full: dict,
    pattern_templates: tuple[str, ...] = (),
) -> dict | None:
    contexts = _gather_contexts(entity_a, persons_full) + _gather_contexts(entity_b, persons_full)
    names_a = _entity_names(entity_a)
    names_b = _entity_names(entity_b)
    for name_a in names_a:
        for name_b in names_b:
            snippet = _detect_pattern_for_names(name_a, name_b, contexts, pattern_templates)
            if snippet:
                return {"method": "pattern", "confidence": "high", "snippet": snippet}
    return None


def _detect_cooccurrence_window(
    name_a: str,
    name_b: str,
    text: str,
    threshold: int = 2,
) -> str | None:
    """
    Returns a ~200-character snippet from the first co-occurrence zone, or None.

    Tokenizes by whitespace. A name matches if its lowercased tokens appear
    consecutively in the token list.
    """
    tokens = text.split()
    if not tokens:
        return None

    na = name_a.lower()
    nb = name_b.lower()

    def find_positions(name: str) -> list[int]:
        name_tokens = name.split()
        n = len(name_tokens)
        positions = []
        for idx in range(len(tokens) - n + 1):
            if " ".join(tokens[idx: idx + n]).lower() == name:
                positions.append(idx)
        return positions

    pos_a = find_positions(na)
    pos_b = find_positions(nb)

    if not pos_a or not pos_b:
        return None

    # Collect all positions of name_a that have name_b within _WINDOW_SIZE tokens
    # (symmetric: either name can precede the other).
    cooccurrence_centers: list[int] = []
    for pa in pos_a:
        for pb in pos_b:
            if abs(pa - pb) < _WINDOW_SIZE:
                center = min(pa, pb)
                cooccurrence_centers.append(center)
                break

    if len(cooccurrence_centers) < threshold:
        return None

    ws = max(0, cooccurrence_centers[0])
    snippet_tokens = tokens[ws: ws + _WINDOW_SIZE]
    snippet = " ".join(snippet_tokens)
    return snippet[:200]


def _tokens_between_are_connective(between: str, connective_words: set[str]) -> bool:
    """True when every word in ``between`` is a connective (article/preposition) or
    pure punctuation — the marker of apposition rather than conjunction.

    "" / " - the " -> apposition (only 'the' + punctuation).
    ", of course, sat with " -> NOT apposition ('course', 'sat', 'with' are content words).
    """
    for raw in between.split():
        core = raw.strip(".,;:!?\"'”“’‘—–-()[]").lower()
        if not core:
            continue  # pure punctuation between the two names
        if core not in connective_words:
            return False
    return True


def _is_apposition(sentence: str, title: str, name: str, connective_words: set[str]) -> bool:
    """True when ``name`` sits in apposition to ``title`` within ``sentence``.

    Apposition = the two phrases are adjacent, separated only by connective words
    and/or punctuation ("Master Brullo", "Brullo - the Master -", "Crown Prince Dorian").
    A conjunction like "The Crown Prince sat with Perrington" is NOT apposition:
    content words sit between the two, so they denote distinct people (STU-430).
    """
    low = sentence.lower()
    title_spans = [(m.start(), m.end()) for m in re.finditer(re.escape(title.lower()), low)]
    name_spans = [(m.start(), m.end()) for m in re.finditer(re.escape(name.lower()), low)]
    if not title_spans or not name_spans:
        return False
    for t0, t1 in title_spans:
        for n0, n1 in name_spans:
            if n0 >= t0 and n1 <= t1:
                continue  # name is a substring of the title occurrence — not evidence
            if n0 >= t1:
                between = sentence[t1:n0]
            elif t0 >= n1:
                between = sentence[n1:t0]
            else:
                continue  # spans overlap without nesting — inconclusive
            if _tokens_between_are_connective(between, connective_words):
                return True
    return False


def _detect_pure_title_in_context(
    entity_a: dict,
    entity_b: dict,
    persons_full: dict,
    role_words: list[str] | None = None,
    connective_words: list[str] | None = None,
) -> dict | None:
    """
    Return evidence if one entity's canonical name is a pure role title (e.g. "Master")
    AND the other entity's name appears in apposition to the title in either entity's
    context snippets.

    This handles the case where NER produces a bare title entity ("Master") that refers
    to a named character ("Brullo") — a case _detect_title_alias cannot cover because the
    title entity has no surname remainder.

    Both entities' contexts are scanned because NER attributes an appositive span like
    "Dorian Havilliard, Crown Prince of Adarlan" to the proper-name entity, so the
    decisive sentence may never appear in the title entity's own snippets (STU-440).
    """
    role_words = role_words or []
    if not role_words:
        return None
    connective_set = {w.lower() for w in (connective_words or [])}
    for title_entity, proper_entity in ((entity_a, entity_b), (entity_b, entity_a)):
        title_name = title_entity.get("canonical_name", "")
        if not _is_pure_title(title_name, role_words):
            continue
        proper_names = [n for n in _entity_names(proper_entity) if n]
        if not proper_names:
            continue
        title_lower = title_name.lower()
        for snippet in _gather_contexts(title_entity, persons_full) + _gather_contexts(
            proper_entity, persons_full
        ):
            # Split into sentences so that names in adjacent sentences don't create false matches.
            # Within a sentence, the proper name must sit in apposition to the title.
            sentences = re.split(r'(?<=[.!?])[\u201d\u2019\u201c\u2018"\']?\s+', snippet)
            for sentence in sentences:
                if title_lower not in sentence.lower():
                    continue
                if any(_is_apposition(sentence, title_name, pn, connective_set) for pn in proper_names):
                    return {
                        "method": "pure_title",
                        "confidence": "medium",
                        "snippet": sentence,
                    }
    return None


def _detect_reveal_signal(entity_a: dict, entity_b: dict, persons_full: dict, reveal_words: tuple[str, ...] = ()) -> dict | None:
    contexts = _gather_contexts(entity_a, persons_full) + _gather_contexts(entity_b, persons_full)
    names_a = [name.lower() for name in _entity_names(entity_a)]
    names_b = [name.lower() for name in _entity_names(entity_b)]
    matches: list[str] = []
    seen_a = False
    seen_b = False
    for snippet in contexts:
        lowered = snippet.lower()
        has_a = any(name in lowered for name in names_a)
        has_b = any(name in lowered for name in names_b)
        if not (has_a or has_b):
            continue
        if any(word in lowered for word in reveal_words):
            matches.append(snippet)
            seen_a = seen_a or has_a
            seen_b = seen_b or has_b
    if len(matches) >= 2 and seen_a and seen_b:
        return {
            "method": "cooccurrence",
            "confidence": "medium",
            "snippet": matches[0],
        }
    return None


def _detect_title_alias(
    entity_a: dict,
    entity_b: dict,
    role_words: list[str],
) -> dict | None:
    """
    Return evidence dict if one entity's name starts with a role_word and the
    remainder appears in the other entity's canonical name.

    Example: "Captain Westfall" + role_word "captain"
             → remainder "westfall" in "Chaol Westfall" → match.
    """
    if not role_words:
        return None
    names_a = _entity_names(entity_a)
    names_b = _entity_names(entity_b)
    for names_title, names_full in ((names_a, names_b), (names_b, names_a)):
        for name in names_title:
            name_lower = name.lower()
            for role in role_words:
                role_lower = role.lower()
                if not name_lower.startswith(role_lower + " "):
                    continue
                remainder = name_lower[len(role_lower) + 1:].strip()
                if not remainder:
                    continue
                for full_name in names_full:
                    if remainder in full_name.lower():
                        return {
                            "method": "title_alias",
                            "confidence": "medium",
                            "snippet": f"{name} / {full_name}",
                        }
    return None


def detect_named_aliases(
    mentions: dict[str, list[str]],
    text: str,
    reveal_words: tuple[str, ...] | None = None,
    pattern_templates: tuple[str, ...] = (),
) -> list[AliasPair]:
    """
    Detect alias pairs using two deterministic heuristics (zero LLM).

    Args:
        mentions: mapping of entity canonical_name -> list of context snippets
        text: raw concatenated book text, used for token-window co-occurrence
        reveal_words: optional override for reveal signal words
        pattern_templates: regex templates for alias pattern detection

    Returns:
        list of AliasPair, each with entity_a, entity_b, confidence, source, snippet
    """
    if reveal_words is None:
        reveal_words = ()
    names = list(mentions.keys())
    pairs: list[AliasPair] = []

    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            name_a = names[i]
            name_b = names[j]

            # Strategy 1: pattern matching
            all_snippets = mentions[name_a] + mentions[name_b]
            evidence = _detect_pattern_for_names(name_a, name_b, all_snippets, pattern_templates)
            if evidence:
                pairs.append(AliasPair(
                    entity_a=name_a,
                    entity_b=name_b,
                    confidence="high",
                    source="pattern",
                    snippet=evidence,
                ))
                continue

            # Strategy 2: token-window co-occurrence
            if text:
                window_evidence = _detect_cooccurrence_window(name_a, name_b, text)
                if window_evidence:
                    pairs.append(AliasPair(
                        entity_a=name_a,
                        entity_b=name_b,
                        confidence="medium",
                        source="cooccurrence",
                        snippet=window_evidence,
                    ))

    return pairs


def _build_role_index(relationships: list[dict]) -> dict[tuple[str, str], list[str]]:
    """
    Build an inverted index: (third_party_canonical, relationship_type) → [entity names with this role].

    For each relationship (A ↔ B, rel_type), B is a third party for A and vice versa.
    Skips relationships with null relationship_type.
    """
    index: dict[tuple[str, str], list[str]] = {}
    for rel in relationships:
        rel_type = rel.get("relationship_type")
        if not rel_type:
            continue
        entity_a: str = rel.get("entity_a", "")
        entity_b: str = rel.get("entity_b", "")
        if not entity_a or not entity_b:
            continue
        # A plays a role toward B
        key_a = (entity_b, rel_type)
        index.setdefault(key_a, [])
        # Normalize to lowercase for case-insensitive matching
        if entity_a.lower() not in index[key_a]:
            index[key_a].append(entity_a.lower())
        # B plays a role toward A
        key_b = (entity_a, rel_type)
        index.setdefault(key_b, [])
        if entity_b.lower() not in index[key_b]:
            index[key_b].append(entity_b.lower())
    return index


def _direct_cooccurrence(name_a: str, name_b: str, relationships: list[dict]) -> int:
    """Return the cooccurrence_count for the direct A↔B relationship, or 0."""
    na, nb = name_a.lower(), name_b.lower()
    for rel in relationships:
        ea = rel.get("entity_a", "").lower()
        eb = rel.get("entity_b", "").lower()
        if (ea == na and eb == nb) or (ea == nb and eb == na):
            return rel.get("cooccurrence_count", 0)
    return 0


def _bucket_is_clean(
    bucket: tuple[str, str],
    role_index: dict[tuple[str, str], list[str]],
    relationships: list[dict],
    direct_cooc_max: int,
) -> bool:
    """Return True if no two co-inhabitants of the bucket have high direct cooccurrence."""
    names_in_bucket = role_index.get(bucket, [])
    for ii in range(len(names_in_bucket)):
        for jj in range(ii + 1, len(names_in_bucket)):
            if _direct_cooccurrence(names_in_bucket[ii], names_in_bucket[jj], relationships) > direct_cooc_max:
                return False
    return True


def _names_share_token(entity_a: dict, entity_b: dict) -> bool:
    """Return True if any name token of entity_a appears in any name of entity_b."""
    tokens_a: set[str] = set()
    for name in _entity_names(entity_a):
        tokens_a.update(t.lower() for t in name.split() if len(t) > 1)
    for name in _entity_names(entity_b):
        for token in name.split():
            if len(token) > 1 and token.lower() in tokens_a:
                return True
    return False


def _detect_role_symmetric_pairs(
    entities: list[dict],
    relationships: list[dict],
    min_shared: int = 2,
    direct_cooc_max: int = 3,
) -> list[tuple[dict, dict, dict]]:
    """
    Return (entity_a, entity_b, evidence) triples where A and B share ≥ min_shared
    (third_party, relationship_type) buckets AND their direct cooccurrence is ≤ direct_cooc_max.

    Evidence dict has keys: method, confidence, snippet, shared_roles.
    """
    role_index = _build_role_index(relationships)
    persons = [e for e in entities if e.get("type") == "PERSON" and e.get("relevant", True)]

    # Pre-compute signatures for all PERSON entities (once, not per-pair)
    entity_signatures: dict[str, set[tuple[str, str]]] = {}
    for entity in persons:
        name = entity.get("canonical_name", "").lower()
        sig: set[tuple[str, str]] = set()
        for (third_party, rel_type), names in role_index.items():
            if name in names:
                sig.add((third_party, rel_type))
        entity_signatures[name] = sig

    pairs: list[tuple[dict, dict, dict]] = []
    for i in range(len(persons)):
        for j in range(i + 1, len(persons)):
            a, b = persons[i], persons[j]
            name_a = a.get("canonical_name", "").lower()
            name_b = b.get("canonical_name", "").lower()
            if _direct_cooccurrence(name_a, name_b, relationships) > direct_cooc_max:
                continue
            if not _names_share_token(a, b):
                continue
            shared = entity_signatures.get(name_a, set()) & entity_signatures.get(name_b, set())
            if len(shared) < min_shared:
                continue
            # Check for contaminated buckets (shared via confirmed-distinct characters)
            clean_shared = {
                bucket for bucket in shared
                if _bucket_is_clean(bucket, role_index, relationships, direct_cooc_max)
            }
            if len(clean_shared) < min_shared:
                continue
            shared_list = sorted(clean_shared)
            # Use original (non-lowercased) names for the snippet
            orig_name_a = a.get("canonical_name", "")
            orig_name_b = b.get("canonical_name", "")
            snippet = "; ".join(
                f"{orig_name_a} and {orig_name_b} both have '{rel}' relation toward '{third}'"
                for third, rel in shared_list[:2]
            )
            evidence = {
                "method": "role_symmetric",
                "confidence": "medium",
                "snippet": snippet,
                "shared_roles": [{"third_party": t, "relationship_type": r} for t, r in shared_list],
            }
            pairs.append((a, b, evidence))
    return pairs


def _detect_embedding_alias(index, candidate_index, judge, centroids) -> dict | None:
    """Semantic merge proposal for a pair with no lexical signal (STU-468).

    Returns an evidence dict in the same shape as the lexical detectors, or
    None to abstain. `method` flows verbatim into MergeDecision.strategy via
    Registry.from_artifacts.
    """
    verdict = judge.propose(index, candidate_index, centroids)
    if verdict.decision != "merge":
        return None
    return {
        "method": "embedding_disambiguation",
        "confidence": verdict.confidence,
        "snippet": f"context cosine={verdict.score:.3f} (embedding disambiguation)",
    }


def resolve_aliases(
    entities: list[dict],
    persons_full: dict,
    narrator=None,
    llm_confirmer=None,
    reveal_words: tuple[str, ...] = (),
    role_words: list[str] | None = None,
    connective_words: list[str] | None = None,
    pattern_templates: tuple[str, ...] = (),
    relationships: list[dict] | None = None,
    role_symmetric_min_shared: int = 2,
    seed_lookup: dict[str, EntityRecord] | None = None,
    judge=None,
) -> dict:
    stats = _empty_stats()
    role_words = role_words or []
    connective_words = connective_words or []
    relationships = relationships or []
    resolved: list[dict] = []
    consumed: set[int] = set()

    centroids: dict = {}
    if judge is not None:
        contexts_by_key = {i: _gather_contexts(e, persons_full) for i, e in enumerate(entities)}
        centroids = judge.build_centroids(contexts_by_key)

    # Pre-compute role-symmetric candidate pairs.
    role_sym_map: dict[tuple[int, int], dict] = {}
    if relationships:
        sym_candidates = _detect_role_symmetric_pairs(
            entities, relationships,
            min_shared=role_symmetric_min_shared,
        )
        name_to_idx = {e.get("canonical_name", ""): i for i, e in enumerate(entities)}
        for ea, eb, ev in sym_candidates:
            ia = name_to_idx.get(ea.get("canonical_name", ""))
            ib = name_to_idx.get(eb.get("canonical_name", ""))
            if ia is not None and ib is not None:
                role_sym_map[(min(ia, ib), max(ia, ib))] = ev

    for index, entity in enumerate(entities):
        if index in consumed:
            continue
        if entity.get("type") != "PERSON" or not entity.get("relevant", True):
            resolved.append(entity)
            continue

        merged = None
        for candidate_index in range(index + 1, len(entities)):
            if candidate_index in consumed:
                continue
            candidate = entities[candidate_index]
            if candidate.get("type") != "PERSON" or not candidate.get("relevant", True):
                continue

            stats["candidates_considered"] += 1

            seed = _detect_series_seed(entity, candidate, seed_lookup)
            if seed:
                merged = _merge_entities(entity, candidate, seed, persons_full, role_words=role_words)
                stats["merges_applied"] += 1
                stats["merges_by_method"]["series_seed"] = stats["merges_by_method"].get("series_seed", 0) + 1
                consumed.add(candidate_index)
                break

            evidence = _detect_pattern_match(entity, candidate, persons_full, pattern_templates)
            if evidence:
                merged = _merge_entities(entity, candidate, evidence, persons_full, role_words=role_words)
                stats["merges_applied"] += 1
                stats["merges_by_method"]["pattern"] += 1
                consumed.add(candidate_index)
                break

            title = _detect_title_alias(entity, candidate, role_words)
            if title:
                merged = _merge_entities(entity, candidate, title, persons_full, role_words=role_words)
                stats["merges_applied"] += 1
                stats["merges_by_method"]["title_alias"] += 1
                consumed.add(candidate_index)
                break

            pure_title = _detect_pure_title_in_context(
                entity, candidate, persons_full,
                role_words=role_words, connective_words=connective_words,
            )
            if pure_title:
                merged = _merge_entities(entity, candidate, pure_title, persons_full, role_words=role_words)
                stats["merges_applied"] += 1
                stats["merges_by_method"]["pure_title"] = stats["merges_by_method"].get("pure_title", 0) + 1
                consumed.add(candidate_index)
                break

            reveal = _detect_reveal_signal(entity, candidate, persons_full, reveal_words=reveal_words)

            # Check role-symmetric signal only when reveal is absent
            role_sym = None
            if not reveal:
                pair_key = (min(index, candidate_index), max(index, candidate_index))
                role_sym = role_sym_map.get(pair_key)

            signal = reveal or role_sym
            if not signal:
                if judge is not None:
                    emb = _detect_embedding_alias(index, candidate_index, judge, centroids)
                    if emb:
                        merged = _merge_entities(entity, candidate, emb, persons_full, role_words=role_words)
                        stats["merges_applied"] += 1
                        stats["merges_by_method"]["embedding_disambiguation"] = (
                            stats["merges_by_method"].get("embedding_disambiguation", 0) + 1
                        )
                        consumed.add(candidate_index)
                        break
                continue

            if judge is not None and judge.veto(index, candidate_index, centroids):
                stats["embedding_vetoes"] += 1
                stats["ambiguous_pairs"] += 1
                continue

            if llm_confirmer is None:
                stats["ambiguous_pairs"] += 1
                continue

            stats["llm_attempts"] += 1
            try:
                decision = llm_confirmer({
                    "entity_a": entity,
                    "entity_b": candidate,
                    "evidence": signal,
                    "persons_full": persons_full,
                }) or {}
            except Exception:
                stats["llm_failed"] += 1
                stats["ambiguous_pairs"] += 1
                continue

            if decision.get("same_person"):
                method = signal.get("method", "llm")
                merged_evidence = {
                    "method": method if method == "role_symmetric" else "llm",
                    "confidence": decision.get("confidence", "medium"),
                    "snippet": decision.get("evidence", signal["snippet"]),
                }
                merged = _merge_entities(entity, candidate, merged_evidence, persons_full, role_words=role_words)
                stats["merges_applied"] += 1
                stat_key = "role_symmetric" if method == "role_symmetric" else "llm"
                stats["merges_by_method"][stat_key] += 1
                stats["llm_confirmed"] += 1
                consumed.add(candidate_index)
                break

            stats["ambiguous_pairs"] += 1

        resolved.append(merged or entity)

    return {"entities": resolved, "narrator": narrator, "stats": stats}


def main() -> None:
    payload = studio_io.read_payload()
    previous_outputs = payload.get("previous_outputs", {})
    all_stage_outputs = payload.get("all_stage_outputs", {})
    # New pipeline: entities come from merge-entities; fall back to resolve-clusters for compat.
    entity_source = (
        all_stage_outputs.get("merge-entities")
        or previous_outputs.get("merge-entities")
        or previous_outputs.get("resolve-clusters")
        or {}
    )
    entities = entity_source.get("entities", [])
    narrator = entity_source.get("narrator")
    # Relationships from relationship-extraction (empty list if stage not run yet).
    relationships: list[dict] = (
        all_stage_outputs.get("relationship-extraction", {}).get("relationships", [])
    )

    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    spacy_model = ctx.get("spacy_model", "en_core_web_lg")
    export_categories = ctx.get("export", {}).get("categories", {})
    language = export_categories.get("language") or infer_language(spacy_model)
    lang_cfg = load_lang_config(language)
    reveal_words = tuple(lang_cfg.get("reveal_words", ()))
    pattern_templates = tuple(lang_cfg.get("alias_pattern_templates", ()))
    classification_cfg = ctx.get("classification", {}) or {}
    role_words: list[str] = list(classification_cfg.get("role_words", []))
    cue_role_words = [w.lower() for w in lang_cfg.get("person_cue_words", [])]
    role_words = list(dict.fromkeys(role_words + cue_role_words))  # dedup, preserve order
    # Apposition-safe words: articles/determiners + name connectors. Absent keys degrade
    # to an empty collection (only adjacency/punctuation counts as apposition then).
    connective_words = list(dict.fromkeys(
        [w.lower() for w in lang_cfg.get("determiners", [])]
        + [w.lower() for w in lang_cfg.get("name_connectors", [])]
    ))

    persons_full = {}
    seed_lookup: dict[str, EntityRecord] = {}
    try:
        paths = studio_io.paths_from_payload(payload)
        persons_full = _load_persons_full(paths.processing)
        # Series seeding (STU-485): tome N starts from the identities
        # accumulated over tomes 1..N-1.
        seed_lookup = Registry.load_seed_table(paths.series_registry)
        if seed_lookup:
            print(
                f"[alias-resolution] series seeding active: "
                f"{len(seed_lookup)} known surfaces from {paths.series_registry}",
                file=sys.stderr,
            )
    except ValueError:
        persons_full = {}

    llm_confirmer = None
    use_llm = ctx.get("use_llm", False)
    if not use_llm:
        print(
            "UserWarning: LLM alias confirmation is disabled (use_llm not set in book config). "
            "Title-based aliases (e.g. 'Captain Westfall', 'Crown Prince') will NOT be resolved. "
            "Set use_llm: true in your book YAML to enable.",
            file=sys.stderr,
        )
    if use_llm:
        ollama_url = os.environ.get("OLLAMA_URL", ollama.DEFAULT_URL)
        llm_model = ctx.get("llm_model", "mistral")
        if ollama.is_available(ollama_url):
            llm_confirmer = make_ollama_confirmer(llm_model, ollama_url, timeout=30)
        else:
            warnings.warn(
                f"Ollama not available at {ollama_url} — LLM alias confirmation skipped.",
                stacklevel=1,
            )

    emb_cfg = ctx.get("embedding_disambiguation", {}) or {}
    judge = None
    if emb_cfg.get("enabled"):
        warnings.warn(
            "embedding_disambiguation is enabled, but its STU-468 eval falsified the "
            "centroid-cosine approach on single-book data (same/different pairs are not "
            "separable; the proposer over-merges). See "
            "docs/superpowers/specs/2026-07-12-embedding-disambiguation-EVAL-RESULTS.md.",
            stacklevel=1,
        )
        try:
            from wiki_creator.embedding_disambiguation import (
                EmbeddingBackend,
                EmbeddingJudge,
                DEFAULT_MODEL,
                DEFAULT_PROPOSE_THRESHOLD,
                DEFAULT_VETO_THRESHOLD,
            )

            backend = EmbeddingBackend(
                model_name=emb_cfg.get("model", DEFAULT_MODEL),
                device=emb_cfg.get("device"),
            )
            judge = EmbeddingJudge(
                backend,
                propose_threshold=emb_cfg.get("propose_threshold", DEFAULT_PROPOSE_THRESHOLD),
                veto_threshold=emb_cfg.get("veto_threshold", DEFAULT_VETO_THRESHOLD),
            )
        except ImportError as exc:
            warnings.warn(
                f"embedding_disambiguation enabled but deps missing ({exc}); "
                f"install with pip install -e '.[embeddings]' — skipping.",
                stacklevel=1,
            )
            judge = None

    result = resolve_aliases(
        entities, persons_full=persons_full, narrator=narrator,
        llm_confirmer=llm_confirmer, reveal_words=reveal_words,
        role_words=role_words, connective_words=connective_words,
        pattern_templates=pattern_templates,
        relationships=relationships,
        role_symmetric_min_shared=ctx.get("role_symmetric_min_shared", 2),
        seed_lookup=seed_lookup,
        judge=judge,
    )
    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
