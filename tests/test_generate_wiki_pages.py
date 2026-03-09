"""Tests for scripts/generate_wiki_pages.py."""

import json

from scripts.generate_wiki_pages import (
    build_prompt,
    call_ollama,
    parse_response,
)


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


def test_parse_response_populates_infobox_fields_from_infobox_section_bullets():
    raw = (
        '{"title":"Victor Grandes","importance":"secondary","entity_type":"PERSON",'
        '"infobox_fields":{},"content":"## Infobox\\n\\n- Nom: Victor Grandes\\n- Statut: Vivant\\n\\n## Biographie\\n\\nTexte."}'
    )
    page = parse_response(raw, _entity())
    assert page["infobox_fields"] == {
        "nom": "Victor Grandes",
        "statut": "Vivant",
    }


def test_parse_response_populates_infobox_fields_from_infobox_section_plain_lines():
    raw = (
        '{"title":"Victor Grandes","importance":"secondary","entity_type":"PERSON",'
        '"infobox_fields":{},"content":"## Infobox\\n\\nNom: Victor Grandes\\nStatut: Vivant\\n\\n## Biographie\\n\\nTexte."}'
    )
    page = parse_response(raw, _entity())
    assert page["infobox_fields"] == {
        "nom": "Victor Grandes",
        "statut": "Vivant",
    }


def test_parse_response_keeps_existing_infobox_fields_when_already_present():
    raw = (
        '{"title":"Victor Grandes","importance":"secondary","entity_type":"PERSON",'
        '"infobox_fields":{"nom":"Existant"},"content":"## Infobox\\n\\n- Nom: Victor Grandes\\n\\n## Biographie\\n\\nTexte."}'
    )
    page = parse_response(raw, _entity())
    assert page["infobox_fields"] == {"nom": "Existant"}


def test_build_prompt_includes_requested_sections_in_order():
    entity = {
        "canonical_name": "Victor Grandes",
        "importance": "principal",
        "type": "PERSON",
        "aliases": [],
        "context_by_chapter": {},
    }
    prompt = build_prompt(
        entity,
        "Mon Livre",
        sections=["infobox", "biography", "relationships", "references"],
    )
    assert "Use exactly these sections in this order: infobox, biography, relationships, references." in prompt
    assert '## Infobox\\n\\n' in prompt
    assert '## Biographie\\n\\n' in prompt
    assert '## Relations\\n\\n' in prompt
    assert '## Références\\n\\n' in prompt


def test_call_ollama_uses_custom_num_predict(monkeypatch):
    captured = {}

    class DummyResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def read(self):
            return b'{"response":"ok"}'

    def fake_urlopen(req, timeout):
        captured["timeout"] = timeout
        captured["body"] = json.loads(req.data.decode())
        return DummyResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    response = call_ollama("prompt", "qwen2.5", timeout=30, num_predict=2222)

    assert response == "ok"
    assert captured["timeout"] == 30
    assert captured["body"]["options"]["num_predict"] == 2222
