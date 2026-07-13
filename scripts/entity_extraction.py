#!/usr/bin/env python3
"""
Stage 2: spaCy Entity Extraction
Script executor interface: reads JSON from stdin, writes JSON to stdout.

Input (via Studio context):
  additional_context: YAML string with spacy_model
  previous_outputs.epub-parse: { title, author, chapters: [{id, title, content}] }

Output (stdout — passed to entity-resolution as previous_stage_output):
  {
    "entities_for_resolution": {
      "entity_001": { "type": "PERSON", "raw_mentions": ["David Martín"], "first_seen": "ch01" }
    }
  }

Side effects (files written to project root):
  persons_full.json, places_full.json, orgs_full.json — full entity registry split by type,
  read by wiki-generation via repo_manager-read_file.

Standalone test mode:
  python scripts/entity_extraction.py --test
  Runs on hardcoded English chapters, prints entity count + 3-entity sample.
  Does not write persons_full.json, places_full.json, or orgs_full.json.
"""

import functools
import json
import re
import sys
from pathlib import Path
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
from wiki_creator import studio_io
from wiki_creator.chapters import is_frontmatter_chapter
from wiki_creator.lang import infer_language as _infer_lang, load_lang_config as _load_lang_config


DEFAULT_MIN_MENTIONS_ABSOLUTE = 3


def _get_min_mentions_absolute(input_data: dict) -> int:
    """Parse min_mentions_absolute from YAML config with safe fallback."""
    value = input_data.get("min_mentions_absolute", DEFAULT_MIN_MENTIONS_ABSOLUTE)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    if "min_mentions_absolute" in input_data:
        print(
            f"[WARN] invalid min_mentions_absolute={value!r}; "
            f"falling back to {DEFAULT_MIN_MENTIONS_ABSOLUTE}",
            file=sys.stderr,
        )
    return DEFAULT_MIN_MENTIONS_ABSOLUTE


def _entity_total_mentions(entity: dict) -> int:
    """Return entity total mentions, preferring mention_count when available."""
    mention_count = entity.get("mention_count")
    if isinstance(mention_count, int) and mention_count >= 0:
        return mention_count
    return sum(len(mentions) for mentions in entity.get("mentions_by_chapter", {}).values())


def filter_entities_by_min_mentions(entities_full: dict, min_mentions_absolute: int) -> dict:
    """Keep only entities whose total mentions are >= min_mentions_absolute."""
    return {
        entity_id: entity
        for entity_id, entity in entities_full.items()
        if _entity_total_mentions(entity) >= min_mentions_absolute
    }


def _spacy_model_candidates(requested_model: str) -> list[str]:
    """Return ordered candidate models for robust loading."""
    candidates = [requested_model]
    if requested_model.startswith("en_core_web_") and requested_model != "en_core_web_sm":
        candidates.append("en_core_web_sm")
    if requested_model.startswith("fr_core_news_"):
        if requested_model != "fr_core_news_lg":
            candidates.append("fr_core_news_lg")
        if requested_model != "fr_core_news_sm":
            candidates.append("fr_core_news_sm")
    # De-duplicate while preserving order.
    return list(dict.fromkeys(candidates))


def _ensure_sentencizer(nlp) -> None:
    """Add a sentencizer to *nlp* if no sentence-boundary component is present.

    Fine-tuned models trained with only tok2vec+ner don't include a parser or
    senter, so doc.sents raises E030.  Adding a sentencizer fixes this without
    altering NER behaviour.
    """
    if not any(p in nlp.pipe_names for p in ("parser", "senter", "sentencizer")):
        nlp.add_pipe("sentencizer", first=True)


def _load_spacy_model_with_fallback(spacy_load, requested_model: str):
    """Try requested spaCy model, then language-appropriate fallbacks."""
    errors = []
    for model in _spacy_model_candidates(requested_model):
        try:
            return spacy_load(model), model
        except OSError as exc:
            errors.append(f"{model}: {exc}")
    raise OSError("Unable to load spaCy model. Tried: " + " | ".join(errors))


def _audit_ner_labels(nlp) -> None:
    """
    Warn (never raise) if the loaded model can emit NER labels that the
    extraction filter would silently drop — i.e. labels in neither
    KEPT_LABELS nor IGNORED_LABELS. Guards against a custom ontology
    being half-disconnected again (STU-439).
    """
    if "ner" not in nlp.pipe_names:
        return
    unknown = sorted(set(nlp.get_pipe("ner").labels) - KEPT_LABELS - IGNORED_LABELS)
    if unknown:
        print(
            "[WARN] NER model emits labels outside KEPT_LABELS/IGNORED_LABELS; "
            f"these entities will be dropped: {', '.join(unknown)}",
            file=sys.stderr,
        )


def _warn_if_no_pos_tagger(nlp) -> None:
    """
    The _BAD_POS filters in _is_valid_span need POS annotation. Fine-tuned
    ['tok2vec','ner'] models have no tagger, so those filters cannot apply.
    Make that explicit instead of silent (STU-439).
    """
    if not any(p in nlp.pipe_names for p in ("tagger", "morphologizer")):
        print(
            "[WARN] POS filters disabled: model has no tagger/morphologizer, "
            "_BAD_POS span filtering will not apply",
            file=sys.stderr,
        )

# Map every NER label we can type to its canonical entity type. Covers both
# standard spaCy models (PER/LOC/GPE/FAC/ORG/NORP/PERSON) and the project's
# custom fantasy-NER model (wiki-ner-en: PERSON/PLACE/FACTION/ORG/EVENT).
LABEL_TO_TYPE = {
    "PER": "PERSON",
    "PERSON": "PERSON",
    "LOC": "PLACE",
    "GPE": "PLACE",
    "FAC": "PLACE",
    "PLACE": "PLACE",
    "ORG": "ORG",
    "NORP": "ORG",
    # FACTION → ORG: downstream type vocabulary is frozen to
    # PERSON/PLACE/ORG/EVENT/OTHER (wiki_creator/types.py).
    "FACTION": "ORG",
    "EVENT": "EVENT",
}

# Stock-model labels we deliberately do NOT extract. Kept explicit so the
# load-time audit (_audit_ner_labels) can tell "intentionally dropped"
# from "silently disconnected" (STU-439).
# en_core_web_*: numerics/dates/works.  fr_core_news_*: MISC.
IGNORED_LABELS = {
    "CARDINAL", "DATE", "TIME", "MONEY", "PERCENT", "QUANTITY", "ORDINAL",
    "LANGUAGE", "LAW", "PRODUCT", "WORK_OF_ART", "MISC",
}
# Keep any label we know how to type — derived so the two can never drift.
KEPT_LABELS = frozenset(LABEL_TO_TYPE)

CUE_WORDS_DIR = PROJECT_ROOT / "wiki_creator" / "cue_words"

# Load language-specific word lists from cue_words JSON files.
# FALSE_POSITIVE_WORDS: French-only; loaded from fr.json at import time.
# COORDINATION_CONNECTORS: merged EN+FR (both languages use coordinating conjunctions).
# FIRST_PERSON_ARTIFACT_TAILS_EN: English-only OCR artifact patterns.
_en_lang_cfg = _load_lang_config("en")
_fr_lang_cfg = _load_lang_config("fr")

FALSE_POSITIVE_WORDS: frozenset[str] = frozenset(_fr_lang_cfg.get("false_positive_words", []))
COORDINATION_CONNECTORS: frozenset[str] = frozenset(
    _en_lang_cfg.get("coordination_connectors", [])
) | frozenset(_fr_lang_cfg.get("coordination_connectors", []))
FIRST_PERSON_ARTIFACT_TAILS_EN: frozenset[str] = frozenset(
    _en_lang_cfg.get("first_person_artifact_tails", [])
)

_DEFAULT_CUE_WORDS = {
    "en": {
        "place_cue_words": [
            "city", "town", "capital", "kingdom", "continent", "country",
            "castle", "palace", "camp", "mine", "mines", "forest", "woods",
            "river", "sea", "port", "harbor", "street", "road", "avenue",
        ],
        "person_cue_words": [
            "prince", "princess", "king", "queen", "duke", "lady", "lord",
            "captain", "sir", "mr", "mrs", "miss",
        ],
        "place_prepositions": [
            "in", "at", "from", "to", "into", "through", "within", "inside", "outside",
        ],
        "event_suffixes": [
            "ball", "festival", "feast", "ceremony", "celebration",
            "prayer", "prayers", "blessing", "blessings", "morning", "night", "eve",
        ],
    },
    "fr": {
        "place_cue_words": [
            "ville", "royaume", "continent", "pays", "château", "chateau", "palais",
            "camp", "mine", "forêt", "foret", "rivière", "riviere", "mer",
            "port", "rue", "route", "avenue",
        ],
        "person_cue_words": [
            "prince", "princesse", "roi", "reine", "duc", "dame", "seigneur",
            "capitaine", "sir", "monsieur", "madame", "mademoiselle",
        ],
        "place_prepositions": [
            "dans", "à", "a", "de", "depuis", "vers", "au", "aux", "en",
        ],
        "event_suffixes": [
            "bal", "festival", "fête", "fete", "cérémonie", "ceremonie",
            "célébration", "celebration", "prières", "prieres", "bénédiction",
            "benediction", "matin", "nuit", "veille",
        ],
    },
}


def _infer_cue_words_language(spacy_model: str) -> str:
    """Infer cue-word language from spaCy model name. Delegates to wiki_creator.lang."""
    return _infer_lang(spacy_model)


def _resolve_cue_words_language(spacy_model: str, override: str | None) -> str:
    """
    Resolve cue-word language.
    Accepted override values: auto, en, fr, all.
    """
    if override is None:
        return _infer_cue_words_language(spacy_model)

    value = str(override).strip().lower()
    if value in {"auto", ""}:
        return _infer_cue_words_language(spacy_model)
    if value in {"en", "fr", "all"}:
        return value
    print(
        f"[WARN] invalid cue_words_language={override!r}; "
        f"falling back to auto ({_infer_cue_words_language(spacy_model)})",
        file=sys.stderr,
    )
    return _infer_cue_words_language(spacy_model)


def _load_single_cue_words_file(language: str) -> dict[str, frozenset[str]]:
    """Load one cue-word JSON file with fallback to defaults."""
    path = CUE_WORDS_DIR / f"{language}.json"
    data = _DEFAULT_CUE_WORDS.get(language, {})
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return {
        "place_cue_words": frozenset(data.get("place_cue_words", [])),
        "person_cue_words": frozenset(data.get("person_cue_words", [])),
        "place_prepositions": frozenset(data.get("place_prepositions", [])),
        "event_suffixes": frozenset(data.get("event_suffixes", [])),
    }


def _load_cue_words(language: str) -> dict[str, frozenset[str]]:
    """Load cue words for 'en', 'fr', or merged 'all'."""
    if language == "all":
        en = _load_single_cue_words_file("en")
        fr = _load_single_cue_words_file("fr")
        return {
            key: en[key] | fr[key]
            for key in ("place_cue_words", "person_cue_words", "place_prepositions", "event_suffixes")
        }
    if language in {"en", "fr"}:
        return _load_single_cue_words_file(language)
    # Safe fallback
    return _load_single_cue_words_file("en")



# POS tags that disqualify a span from being a named entity.
# Capitalized verb/adjective/adverb at sentence start is a common false positive
# in French dialogue (e.g. "— Regarde", "— Avez-vous", "— Sériez-vous").
_BAD_POS: frozenset[str] = frozenset({"VERB", "AUX", "ADJ", "ADV"})


def _is_valid_span(span) -> bool:
    """
    Return True if the spaCy span looks like a proper-noun entity.

    For mono-token spans: reject if the token's POS is a verb, aux, adjective, or adverb.
    For multi-token spans: use the syntactic head (span.root); reject if its POS is bad.

    Additionally, rejects spans that are immediately preceded by a dialogue dash (—).
    French NER models often misclassify sentence-initial verbs/adjectives after dialogue
    dashes as PROPN (e.g. "— Regarde" → PER with pos=PROPN). The preceding dash is the
    reliable signal since POS tagging itself is confused in these contexts.

    Tagger-less pipelines (e.g. fine-tuned ['tok2vec','ner'] models) carry no
    POS annotation; the _BAD_POS checks are then deliberately skipped
    (warned once at load time by _warn_if_no_pos_tagger). The dialogue-dash
    rejection below does not depend on POS and always applies.
    """
    tokens = list(span)
    # Tagger-less pipelines (e.g. fine-tuned ['tok2vec','ner'] models) carry no
    # POS annotation; the _BAD_POS checks are then deliberately skipped
    # (warned once at load time by _warn_if_no_pos_tagger). The dialogue-dash
    # rejection below does not depend on POS and always applies.
    has_pos = span.doc.has_annotation("POS")
    if len(tokens) == 1:
        tok = tokens[0]
        if has_pos and tok.pos_ in _BAD_POS:
            return False
        # Reject if immediately preceded by a dialogue dash (French dialogue marker)
        if tok.i > 0 and span.doc[tok.i - 1].text in {"—", "–", "-"}:
            return False
    else:
        head = span.root
        if has_pos and head.pos_ in _BAD_POS:
            return False
        # Reject multi-token spans that start immediately after a dialogue dash
        if span.start > 0 and span.doc[span.start - 1].text in {"—", "–", "-"}:
            return False
    return True


def _is_valid_mention(text: str) -> bool:
    """
    Return True if `text` looks like a valid proper-noun mention.

    Rejects:
    - Strings shorter than 3 characters (single letters, "Ah", "II", etc.)
    - Strings whose first non-whitespace character is not an uppercase letter
      (lowercase verbs, dash-prefixed dialog fragments, punctuation artifacts)
    - Single-word strings that match FALSE_POSITIVE_WORDS (French salutations,
      standalone titles, functional words captured via initial uppercase).
      Multi-word entities like "Le Cher" or "Monsieur Lefebvre" are not blocked.
    """
    stripped = text.strip()
    if len(stripped) < 3:
        return False
    if not stripped[0].isupper():
        return False
    # Reject coordinated multi-name artifacts: "X and Y", "X et Y", etc.
    tokens = stripped.split()
    if len(tokens) >= 3:
        for i in range(1, len(tokens) - 1):
            if tokens[i].lower() not in COORDINATION_CONNECTORS:
                continue
            left, right = tokens[i - 1], tokens[i + 1]
            if left[:1].isupper() and right[:1].isupper():
                return False
    if " " not in stripped:
        lowered = stripped.lower()
        if lowered in FALSE_POSITIVE_WORDS:
            return False
        # Reject collapsed first-person artifacts like "Iwould", "Isuppose", etc.
        if lowered.startswith("i") and lowered[1:] in FIRST_PERSON_ARTIFACT_TAILS_EN:
            return False
    return True


@functools.lru_cache(maxsize=32)
def _word_set_pattern(words: frozenset) -> "re.Pattern | None":
    """Compile a word-boundary alternation for a cue-word set.

    Whole-word matching only: 'sea' must not hit 'seawall', 'port' must not
    hit 'important', 'miss' must not hit 'mission'. Cached per frozenset —
    cue-word sets are loaded once and reused across the whole registry.
    """
    if not words:
        return None
    alternation = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
    return re.compile(rf"\b(?:{alternation})\b")


def _retag_entity_type_from_context(
    entity: dict,
    cue_words: dict[str, frozenset[str]] | None = None,
) -> str:
    """
    Conservative type correction for frequent PERSON/ORG/PLACE false positives.

    Uses lexical cues from mention contexts to retag PERSON entities as EVENT
    when evidence is strong, and ORG/PLACE entities as PERSON when person
    cues dominate. It no longer retags PERSON to PLACE: the custom NER model
    now labels places directly, so a model-asserted PERSON is trusted even
    when its introduction is place-dense (e.g. a person found on a riverbank).
    All cue matching is whole-word (boundary-anchored) — substring matching
    retagged every protagonist of place-heavy prose ('sea' in 'seawall',
    'port' in 'Port Saffron').
    """
    current = entity.get("type", "OTHER")
    if current not in {"PERSON", "PLACE", "ORG"}:
        return current
    if cue_words is None:
        cue_words = _load_cue_words("all")

    mentions = [m.strip() for m in entity.get("raw_mentions", []) if m and m.strip()]
    if not mentions:
        return current
    mention = mentions[0]
    mention_l = mention.lower()
    mention_re = re.compile(rf"\b{re.escape(mention_l)}\b")
    place_cues_re = _word_set_pattern(frozenset(cue_words["place_cue_words"]))
    person_cues_re = _word_set_pattern(frozenset(cue_words["person_cue_words"]))

    place_score = 0
    event_score = 0
    person_score = 0

    event_cue_hits = 0
    place_preps = "|".join(
        re.escape(p) for p in sorted(cue_words["place_prepositions"], key=len, reverse=True)
    )
    event_suffixes = "|".join(
        re.escape(e) for e in sorted(cue_words["event_suffixes"], key=len, reverse=True)
    )

    for chapter_mentions in entity.get("mentions_by_chapter", {}).values():
        for sentence in chapter_mentions:
            s = sentence.lower()
            if not s:
                continue

            if mention_re.search(s):
                if place_cues_re and place_cues_re.search(s):
                    place_score += 2
                if person_cues_re and person_cues_re.search(s):
                    person_score += 2

            if place_preps and re.search(rf"\b({place_preps})\s+{re.escape(mention_l)}\b", s):
                place_score += 1
            person_titles = "|".join(
                re.escape(t) for t in sorted(cue_words["person_cue_words"], key=len, reverse=True)
            )
            if person_titles and re.search(rf"\b({person_titles})\s+{re.escape(mention_l)}\b", s):
                person_score += 2
            # Narrative verbs strongly associated with persons in prose.
            if re.search(
                rf"\b{re.escape(mention_l)}\s+"
                r"(said|asked|replied|looked|smiled|laughed|nodded|walked|whispered)\b",
                s,
            ):
                person_score += 1
            if event_suffixes and re.search(
                rf"\b{re.escape(mention_l)}\s+"
                rf"({event_suffixes})\b",
                s,
            ):
                event_score += 2
                event_cue_hits += 1
            if re.search(rf"\b{re.escape(mention_l)}'s\b", s):
                person_score += 1

    if current == "PERSON" and event_cue_hits >= 1 and event_score >= 2 and event_score > max(place_score, person_score):
        return "EVENT"
    if current in {"ORG", "PLACE"} and person_score >= 2 and person_score > max(place_score, event_score):
        return "PERSON"
    if current in {"ORG", "PLACE"} and person_score >= 1 and place_score == 0 and event_score == 0:
        return "PERSON"
    return current


def _truncate_span(span):
    """
    Tronque un span spaCy au dernier token qui ressemble à un nom propre.

    Un token est considéré "propre" si son texte commence par une majuscule
    (is_title) ou si son POS tag est PROPN.

    Si aucun token n'est propre (cas dégénéré), retourne le span complet.
    Retourne un span (pas un texte) pour que start_char/end_char restent
    disponibles — les offsets de mention sont persistés (STU-489).

    Exemples :
      "Barcelone de ténèbres" → "Barcelone"
      "Victor Grandes me sourit" → "Victor Grandes"
      "Victor Hugo" → "Victor Hugo" (inchangé)
    """
    tokens = list(span)
    last_proper = 0  # fallback : 0 → on retournera le span complet si aucun propre
    for i in range(len(tokens) - 1, -1, -1):
        if tokens[i].is_title or tokens[i].pos_ == "PROPN":
            last_proper = i + 1
            break
    if last_proper == 0:
        return span
    return span.doc[span.start : span.start + last_proper]


def _truncate_mention(span) -> str:
    return _truncate_span(span).text


# Hardcoded chapters for --test mode (English, uses en_core_web_sm)
TEST_CHAPTERS = [
    {
        "id": "ch01",
        "title": "Chapter 1",
        "content": (
            "David Martin was a young writer who lived in Barcelona. "
            "He worked for a publisher named Vidal. "
            "The city of Barcelona was his home."
        ),
    },
    {
        "id": "ch02",
        "title": "Chapter 2",
        "content": (
            "David was walking through the old quarter when he met Pedro Vidal again. "
            "Barcelona was beautiful that evening. "
            "Martin stopped in front of the cathedral."
        ),
    },
    {
        "id": "ch03",
        "title": "Chapter 3",
        "content": (
            "The Vidal house was located on the main boulevard. "
            "David Martin knocked on the door. "
            "The Raval publishing house had closed its doors."
        ),
    },
]


def extract_context(doc, span) -> str:
    """
    Extract ~2-3 sentences of context around the entity span.
    Returns the sentence containing the entity plus one sentence on each side.
    """
    sentences = list(doc.sents)
    if not sentences:
        return span.text

    span_sent_start = span.sent.start
    try:
        sent_idx = next(
            i for i, s in enumerate(sentences) if s.start == span_sent_start
        )
    except StopIteration:
        return span.sent.text

    start = max(0, sent_idx - 1)
    end = min(len(sentences), sent_idx + 2)
    return " ".join(s.text.strip() for s in sentences[start:end])


def extract_entities(
    chapters: list[dict],
    nlp,
    cue_words: dict[str, frozenset[str]] | None = None,
) -> dict:
    """
    Process all chapters in order and build the entity registry.

    Returns:
      {"entities": {entity_id: {type, raw_mentions, first_seen,
                                mentions_by_chapter, mention_spans_by_chapter}}}

    Grouped by normalized mention text (lowercase + stripped).
    Same surface form in multiple chapters → one entry, multiple chapter keys.
    Alias resolution is left to the LLM stage.

    mention_spans_by_chapter (STU-489) records EVERY occurrence as
    {surface, start, end} — character offsets into the chapter content
    (the same text saved to chapters.json), so downstream consumers can
    extract a window centered on the mention. Unlike mentions_by_chapter
    (contexts, capped at 3 per chapter), it is not capped: offsets are cheap.
    Contexts pair with the first spans of a chapter (both appended in
    occurrence order).
    """
    registry: dict[str, dict] = {}
    entity_counter = 0

    for chapter in chapters:
        if "content" not in chapter or "id" not in chapter:
            raise ValueError(f"chapter missing required fields 'content' or 'id': {list(chapter.keys())}")
        if is_frontmatter_chapter(chapter):
            continue
        chapter_id = chapter["id"]
        doc = nlp(chapter["content"])
        for ent in doc.ents:
            if ent.label_ not in KEPT_LABELS:
                continue

            mention_span = _truncate_span(ent)
            mention_text = mention_span.text
            key = mention_text.lower().strip()
            if not key:
                continue
            if not _is_valid_mention(mention_text):
                continue
            if not _is_valid_span(ent):          # ← new line
                continue

            context = extract_context(doc, ent)

            if key not in registry:
                entity_counter += 1
                registry[key] = {
                    "id": f"entity_{entity_counter:03d}",
                    "type": LABEL_TO_TYPE.get(ent.label_, "OTHER"),
                    "raw_mentions": [mention_text],
                    "first_seen": chapter_id,
                    "mentions_by_chapter": {},
                    "mention_spans_by_chapter": {},
                    "mention_count": 1,
                }
            else:
                if mention_text not in registry[key]["raw_mentions"]:
                    registry[key]["raw_mentions"].append(mention_text)
                registry[key]["mention_count"] += 1

            registry[key]["mentions_by_chapter"].setdefault(chapter_id, [])
            if len(registry[key]["mentions_by_chapter"][chapter_id]) < 3:
                registry[key]["mentions_by_chapter"][chapter_id].append(context)
            registry[key]["mention_spans_by_chapter"].setdefault(chapter_id, []).append(
                {
                    "surface": mention_text,
                    "start": mention_span.start_char,
                    "end": mention_span.end_char,
                }
            )

    entities = {
        "entities": {
            v["id"]: {k: v[k] for k in v if k != "id"}
            for v in registry.values()
        }
    }
    for entity in entities["entities"].values():
        entity["type"] = _retag_entity_type_from_context(entity, cue_words=cue_words)
    return entities


def split_entities(entities: dict) -> tuple[dict, dict]:
    """
    Split the full entity registry into two structures:
    - entities_for_resolution: lightweight (type, raw_mentions, first_seen, mention_count)
    - entities_full: complete (includes mentions_by_chapter, mention_spans_by_chapter)

    Returns (entities_for_resolution, entities_full).
    """
    _FULL_ONLY = {"mentions_by_chapter", "mention_spans_by_chapter"}
    entities_for_resolution = {
        entity_id: {k: v for k, v in entity.items() if k not in _FULL_ONLY}
        for entity_id, entity in entities.items()
    }
    return entities_for_resolution, entities


def split_by_type(entities_full: dict) -> dict[str, dict]:
    """
    Partition entities_full by entity type.

    Returns a dict with keys "PERSON", "PLACE", "ORG", "EVENT".
    Entities with other types (e.g. "OTHER") are silently dropped.
    """
    result: dict[str, dict] = {"PERSON": {}, "PLACE": {}, "ORG": {}, "EVENT": {}}
    for entity_id, entity in entities_full.items():
        t = entity.get("type", "OTHER")
        if t in result:
            result[t][entity_id] = entity
    return result


def run_test_mode() -> None:
    """
    Standalone test mode: run entity extraction on hardcoded chapters.
    Prints entity count by type and a sample of 3 entities.
    Does not read stdin or write persons_full.json, places_full.json, or orgs_full.json.
    """
    import spacy

    print("Loading en_core_web_sm...", file=sys.stderr)
    nlp, _ = _load_spacy_model_with_fallback(spacy.load, "en_core_web_sm")

    print("Extracting entities from 3 hardcoded chapters...", file=sys.stderr)
    try:
        result = extract_entities(TEST_CHAPTERS, nlp)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    entities = result["entities"]
    entities_for_resolution, _ = split_entities(entities)

    type_counts: dict[str, int] = {}
    for entity in entities.values():
        t = entity["type"]
        type_counts[t] = type_counts.get(t, 0) + 1

    print(f"\n=== Test Mode Results ===")
    print(f"Total entities extracted: {len(entities)}")
    for t, count in sorted(type_counts.items()):
        print(f"  {t}: {count}")

    print(f"\nSample (first 3 entities in entities_for_resolution):")
    for entity_id, entity in list(entities_for_resolution.items())[:3]:
        print(
            f"  [{entity_id}] mentions={entity['raw_mentions']} "
            f"type={entity['type']} first_seen={entity['first_seen']}"
        )

    full_size = len(json.dumps(entities, ensure_ascii=False))
    slim_size = len(json.dumps(entities_for_resolution, ensure_ascii=False))
    print(
        f"\nSize: entities_full={full_size} chars, entities_for_resolution={slim_size} chars "
        f"({100 * slim_size // full_size if full_size else 0}% of full)"
    )

    by_type = split_by_type(entities)
    print("\nPer-type file sizes (chars):")
    for type_key, (filename, json_key) in [
        ("PERSON", ("persons_full.json", "persons_full")),
        ("PLACE", ("places_full.json", "places_full")),
        ("ORG", ("orgs_full.json", "orgs_full")),
        ("EVENT", ("events_full.json", "events_full")),
    ]:
        size = len(json.dumps({json_key: by_type[type_key]}, ensure_ascii=False))
        print(f"  {filename}: {size} chars ({len(by_type[type_key])} entities)")


def save_chapters_json(chapters: list[dict], path: str = "chapters.json") -> None:
    """Save raw chapter text to chapters.json for downstream coref stage."""
    data = {"chapters": {ch["id"]: ch["content"] for ch in chapters}}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def main() -> None:
    if "--test" in sys.argv:
        run_test_mode()
        return

    payload = studio_io.read_payload()

    input_data = yaml.safe_load(payload.get("additional_context", "")) or {}
    prev_outputs = payload.get("previous_outputs", {})
    epub_output = next(iter(prev_outputs.values()), {}) if prev_outputs else {}
    chapters = epub_output.get("chapters", [])
    spacy_model = input_data.get("spacy_model", "en_core_web_sm")

    if not chapters:
        json.dump({"error": "missing field: chapters"}, sys.stdout)
        sys.exit(1)

    import spacy
    try:
        nlp, loaded_model = _load_spacy_model_with_fallback(spacy.load, spacy_model)
    except OSError as e:
        json.dump({"error": str(e)}, sys.stdout, ensure_ascii=False)
        sys.exit(1)
    if loaded_model != spacy_model:
        print(f"[WARN] spaCy model '{spacy_model}' not available; using '{loaded_model}'", file=sys.stderr)
    _ensure_sentencizer(nlp)
    _audit_ner_labels(nlp)
    _warn_if_no_pos_tagger(nlp)

    try:
        cue_words_language = _resolve_cue_words_language(
            loaded_model,
            input_data.get("cue_words_language", "auto"),
        )
        cue_words = _load_cue_words(cue_words_language)
        result = extract_entities(chapters, nlp, cue_words=cue_words)
    except ValueError as e:
        json.dump({"error": str(e)}, sys.stdout)
        sys.exit(1)

    min_mentions_absolute = _get_min_mentions_absolute(input_data)
    filtered_entities = filter_entities_by_min_mentions(result["entities"], min_mentions_absolute)
    entities_for_resolution, entities_full = split_entities(filtered_entities)

    if not entities_for_resolution:
        json.dump(
            {"error": "no entities extracted after min_mentions_absolute filter — verify spaCy model and input chapters"},
            sys.stdout,
        )
        sys.exit(1)

    # Write full entities to disk split by type, for wiki-generation to read via repo_manager-read_file
    paths = studio_io.paths_from_payload(payload)
    paths.processing.mkdir(parents=True, exist_ok=True)
    by_type = split_by_type(entities_full)
    type_files = {
        "PERSON": ("persons_full.json", "persons_full"),
        "PLACE": ("places_full.json", "places_full"),
        "ORG": ("orgs_full.json", "orgs_full"),
        "EVENT": ("events_full.json", "events_full"),
    }
    for type_key, (filename, json_key) in type_files.items():
        with open(paths.processing / filename, "w", encoding="utf-8") as f:
            json.dump({json_key: by_type[type_key]}, f, ensure_ascii=False)

    save_chapters_json(chapters, path=str(paths.processing / "chapters.json"))

    # Output lightweight entities to stdout → becomes entity-resolution's previous_stage_output
    json.dump({"entities_for_resolution": entities_for_resolution}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
