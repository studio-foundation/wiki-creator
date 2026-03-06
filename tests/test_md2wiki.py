# tests/test_md2wiki.py
from wiki_creator.md2wiki import convert


def test_h1_heading():
    assert convert("# Titre principal") == "= Titre principal ="


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


def test_bold_and_italic_same_line():
    assert convert("**bold** and *italic*") == "'''bold''' and ''italic''"


from wiki_creator.md2wiki import make_infobox_call


def test_infobox_person():
    fields = {"name": "David Martín", "status": "Vivant", "occupation": "Écrivain"}
    result = make_infobox_call("PERSON", fields)
    assert result.startswith("{{Infobox character")
    assert "|name=David Martín" in result
    assert "|status=Vivant" in result
    assert "|occupation=Écrivain" in result
    assert result.strip().endswith("}}")


def test_infobox_place():
    fields = {"name": "Barcelone", "type": "Ville"}
    result = make_infobox_call("PLACE", fields)
    assert result.startswith("{{Infobox location")


def test_infobox_org():
    fields = {"name": "La Roseraie"}
    result = make_infobox_call("ORG", fields)
    assert result.startswith("{{Infobox organization")


def test_infobox_empty_fields_omitted():
    """Fields with empty/None values must not appear in the call."""
    fields = {"name": "X", "status": "", "occupation": None}
    result = make_infobox_call("PERSON", fields)
    assert "|status=" not in result
    assert "|occupation=" not in result


def test_infobox_format():
    """Each field on its own line, no trailing whitespace."""
    fields = {"name": "X", "status": "Vivant"}
    result = make_infobox_call("PERSON", fields)
    lines = result.strip().splitlines()
    assert lines[0] == "{{Infobox character"
    assert lines[-1] == "}}"
    # Middle lines are |key=value
    for line in lines[1:-1]:
        assert line.startswith("|")
        assert "=" in line


def test_infobox_unknown_type_uses_generic_fallback():
    fields = {"name": "La Bataille"}
    result = make_infobox_call("EVENT", fields)
    assert result.startswith("{{Infobox\n")
    assert "|name=La Bataille" in result
