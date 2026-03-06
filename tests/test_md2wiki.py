# tests/test_md2wiki.py
import pytest
from wiki_creator.md2wiki import convert


def test_h2_heading():
    assert convert("## Biographie") == "== Biographie =="


def test_h3_heading():
    assert convert("### Première apparition") == "=== Première apparition ==="


def test_h4_heading():
    assert convert("#### Détail") == "==== Détail ===="


def test_bold():
    assert convert("**texte**") == "'''texte'''"


def test_italic():
    assert convert("*texte*") == "''texte''"


def test_cross_ref_passthrough():
    """[[Nom]] must not be altered."""
    assert convert("[[David Martín]]") == "[[David Martín]]"


def test_category_passthrough():
    assert convert("[[Category:Personnages]]") == "[[Category:Personnages]]"


def test_blockquote_removed():
    """Blockquote lines (spoiler warnings) are stripped."""
    md = "> ⚠️ **Spoilers** — Cette section révèle des événements."
    assert convert(md).strip() == ""


def test_multiline():
    md = "## Biographie\n\n**Pedro Vidal** rencontre [[David Martín]]."
    expected = "== Biographie ==\n\n'''Pedro Vidal''' rencontre [[David Martín]]."
    assert convert(md) == expected


def test_italic_not_bold():
    """Single asterisk = italic, double = bold. No cross-contamination."""
    assert convert("*seul*") == "''seul''"
    assert convert("**double**") == "'''double'''"
