"""STU-551: affiliation is the faction a character belongs to at the end of the tome."""
import json
from pathlib import Path

CUE_WORDS = Path(__file__).resolve().parents[1] / "wiki_creator" / "cue_words"


def test_both_languages_declare_affiliation_markers():
    # The vocabulary is data, never a constant in a .py (CLAUDE.md).
    for lang in ("en", "fr"):
        cues = json.loads((CUE_WORDS / f"{lang}.json").read_text(encoding="utf-8"))
        assert cues["affiliation_markers"], f"{lang} has no affiliation_markers"
        assert all(isinstance(m, str) and m for m in cues["affiliation_markers"])
