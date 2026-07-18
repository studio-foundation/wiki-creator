import json
from pathlib import Path

_CUE_WORDS_DIR = Path(__file__).parent / "cue_words"
_DOCS = "docs/lang-packs.md"


class LangPackError(Exception):
    """A lang pack is missing, unreadable, or incomplete.

    Raised loudly at load time so an unsupported language fails with an
    actionable message instead of silently degrading to English cue-words.
    """


# Keys every lang pack must declare — populated in both shipped packs (en, fr).
# A missing one silently corrupts a core subsystem: entity classification/retag,
# POV attribution, alias resolution, or event/temporal detection. See docs/lang-packs.md.
REQUIRED_KEYS = frozenset(
    {
        "place_cue_words",
        "person_cue_words",
        "place_prepositions",
        "event_suffixes",
        "pronouns",
        "determiners",
        "noise_words",
        "coordination_connectors",
        "reveal_words",
        "geo_keywords",
        "event_keywords",
        "action_cues",
        "geo_suffixes",
        "role_words",
        "role_patterns",
        "flashback_cues",
        "first_person_pronouns",
        "third_person_thought_markers",
        "name_connectors",
        "editorial_stance_markers",
    }
)

# Keys a pack may omit: a language that doesn't need them (English has no
# elisions), or advisory tuning lists. Absent → the consumer degrades to empty.
OPTIONAL_KEYS = frozenset(
    {
        "false_positive_words",
        "first_person_prefixes",
        "elision_prefixes",
        "first_person_artifact_tails",
        "language_id_markers",
        "placeholder_markers",
        "masculine_titles",
        "feminine_titles",
        "title_prefixes",
        "geographic_keywords",
        "status_markers",
        "affiliation_markers",
        "species_markers",
        "pipeline_metric_terms",
    }
)

# Stock-model name prefixes that carry an unambiguous language signal. A local
# path or a community model (fr_solipcysme_lg) matches none of these — its
# language cannot be inferred and must be declared explicitly (STU-453).
_LANG_MODEL_PREFIXES = {
    "fr": ("fr_core_news_", "fr_dep_news_"),
    "en": ("en_core_web_",),
    "es": ("es_core_news_",),
}


def infer_language(spacy_model: str) -> str | None:
    """Infer language code from a spaCy model name.

    Returns 'fr'/'en' for recognizable stock-model names, or None when the name
    carries no language signal (a local path like `models/wiki-ner-fr/model-best`
    or a community model like `fr_solipcysme_lg`) — the caller must then rely on
    an explicit `language:`.
    """
    model = (spacy_model or "").strip().lower()
    for lang, prefixes in _LANG_MODEL_PREFIXES.items():
        if model.startswith(prefixes):
            return lang
    return None


def book_language(ctx: dict) -> str:
    """Resolve the book language from its YAML config dict.

    Explicit top-level `language:` wins. Otherwise infer from `spacy_model`; a
    model whose name carries no language signal (local path, community model)
    demands an explicit `language:` and raises loudly when it is missing — a
    silent 'en' default would run the wrong cue-words/POV/alias patterns on the
    text (STU-453). With no model at all, defaults to 'fr' (historical default of
    this repo's corpus).
    """
    explicit = (ctx.get("language") or "").strip().lower()
    if explicit:
        return explicit
    spacy_model = (ctx.get("spacy_model") or "").strip()
    if not spacy_model:
        return "fr"
    inferred = infer_language(spacy_model)
    if inferred is None:
        raise ValueError(
            f"Cannot infer language from spaCy model {spacy_model!r}. "
            "Set an explicit top-level `language:` in the book YAML."
        )
    return inferred


def load_lang_config(language: str, *, allow_en_fallback: bool = False) -> dict:
    """Load and validate wiki_creator/cue_words/<language>.json as a plain dict.

    Raises LangPackError if the file is missing, unreadable, or missing a
    required key (see REQUIRED_KEYS / docs/lang-packs.md). The English fallback
    is opt-in per call via `allow_en_fallback`; it never happens implicitly, so
    a book in an unsupported language fails loudly instead of being processed
    with the wrong cue-words.

    Values are plain lists (not frozensets) to stay JSON-round-trip friendly.
    """
    path = _CUE_WORDS_DIR / f"{language}.json"
    if not path.exists():
        if allow_en_fallback and language != "en":
            return load_lang_config("en")
        raise LangPackError(
            f"No lang pack for language '{language}': {path} does not exist. "
            f"Create it (see {_DOCS}), or pass allow_en_fallback=True to process "
            f"this book with English cue-words."
        )
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise LangPackError(
            f"Lang pack {path} is unreadable ({exc}). See {_DOCS}."
        ) from exc
    if not isinstance(cfg, dict):
        raise LangPackError(
            f"Lang pack {path} must be a JSON object, got {type(cfg).__name__}. "
            f"See {_DOCS}."
        )
    missing = sorted(REQUIRED_KEYS - cfg.keys())
    if missing:
        raise LangPackError(
            f"Lang pack {path} (language '{language}') is missing required "
            f"key(s): {', '.join(missing)}. See {_DOCS} for each key's role."
        )
    return cfg
