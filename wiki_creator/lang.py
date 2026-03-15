import json
from pathlib import Path

_CUE_WORDS_DIR = Path(__file__).parent / "cue_words"


def infer_language(spacy_model: str) -> str:
    """Infer language code from spaCy model name. Returns 'fr' or 'en'."""
    model = (spacy_model or "").strip().lower()
    if model.startswith("fr_core_news_"):
        return "fr"
    return "en"


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
