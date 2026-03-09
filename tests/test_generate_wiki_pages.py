"""Tests for scripts/generate_wiki_pages.py."""

from scripts.generate_wiki_pages import parse_response


def _entity() -> dict:
    return {
        "canonical_name": "Victor Grandes",
        "importance": "secondary",
        "type": "PERSON",
    }


def test_parse_response_extracts_json_wrapped_in_text():
    raw = (
        "Voici la sortie demandee.\n"
        '{"title":"Victor Grandes","importance":"secondary","entity_type":"PERSON",'
        '"infobox_fields":{},"content":"## Biographie\\n\\nTexte."}\n'
        "Fin."
    )
    page = parse_response(raw, _entity())
    assert page["title"] == "Victor Grandes"
    assert page["entity_type"] == "PERSON"
    assert page["content"] == "## Biographie\n\nTexte."


def test_parse_response_extracts_json_from_fenced_block():
    raw = (
        "```json\n"
        '{"title":"Victor Grandes","importance":"secondary","entity_type":"PERSON",'
        '"infobox_fields":{},"content":"## Biographie\\n\\nTexte."}\n'
        "```\n"
    )
    page = parse_response(raw, _entity())
    assert page["title"] == "Victor Grandes"
    assert page["importance"] == "secondary"
    assert page["content"] == "## Biographie\n\nTexte."


def test_parse_response_ignores_trailing_text_after_fenced_json():
    raw = (
        "```json\n"
        '{"title":"Victor Grandes","importance":"secondary","entity_type":"PERSON",'
        '"infobox_fields":{},"content":"## Biographie\\n\\nTexte."}\n'
        "```\n"
        "Note: generation complete.\n"
    )
    page = parse_response(raw, _entity())
    assert page["title"] == "Victor Grandes"
    assert page["entity_type"] == "PERSON"
    assert page["content"] == "## Biographie\n\nTexte."
