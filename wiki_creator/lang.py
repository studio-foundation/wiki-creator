import json
from pathlib import Path

_CUE_WORDS_DIR = Path(__file__).parent / "cue_words"

# Stock-model name prefixes that carry an unambiguous language signal. A local
# path or a community model (fr_solipcysme_lg) matches none of these — its
# language cannot be inferred and must be declared explicitly (STU-453).
_LANG_MODEL_PREFIXES = {
    "fr": ("fr_core_news_", "fr_dep_news_"),
    "en": ("en_core_web_",),
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


def load_lang_config(language: str) -> dict:
    """Load wiki_creator/cue_words/<language>.json as a plain dict.

    Falls back to 'en' if the requested language file is not found.
    Values are plain lists (not frozensets) to stay JSON-round-trip friendly.
    """
    path = _CUE_WORDS_DIR / f"{language}.json"
    if not path.exists():
        path = _CUE_WORDS_DIR / "en.json"
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
