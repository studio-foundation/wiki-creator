"""Tests for scripts/generate_wiki_pages.py."""

import json

from scripts.generate_wiki_pages import (
    _contains_template_placeholder,
    _is_page_complete,
    build_prompt,
    call_ollama,
    generation_profile,
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


def test_build_prompt_includes_related_context_block_and_strict_rules():
    entity = {
        "canonical_name": "Dorian Havilliard",
        "importance": "principal",
        "type": "PERSON",
        "aliases": ["Dorian"],
        "context_by_chapter": {
            "ch01": ["Dorian entra dans la salle du conseil."],
        },
        "related_context": [
            {
                "related_name": "Celaena",
                "cooccurrence_count": 175,
                "related_type": "PERSON",
                "related_importance": "principal",
                "support_snippets": [
                    "Celaena observa Dorian sans parler.",
                    "Dorian et Celaena discutent du Test.",
                ],
            }
        ],
    }
    prompt = build_prompt(
        entity,
        "Mon Livre",
        sections=["infobox", "biography", "relationships", "references"],
    )

    assert "Known related entities (disambiguation context):" in prompt
    assert "Name: Celaena" in prompt
    assert "Cooccurrence count: 175" in prompt
    assert "Use this block only to disambiguate likely related entities." in prompt
    assert "If ambiguous, omit rather than infer." in prompt
    assert "Do NOT turn cooccurrence into narrative causality." in prompt


def test_build_prompt_includes_chapter_summary_context_block_and_rules():
    entity = {
        "canonical_name": "Dorian Havilliard",
        "importance": "principal",
        "type": "PERSON",
        "aliases": ["Dorian"],
        "context_by_chapter": {
            "Chapter 1": ["Dorian entered the hall."],
        },
        "chapter_summary_context": [
            {
                "chapter_key": "Chapter 1",
                "summary_bullets": [
                    "Dorian meets Chaol at court.",
                    "The King issues new orders.",
                ],
            }
        ],
    }
    prompt = build_prompt(
        entity,
        "Mon Livre",
        sections=["infobox", "biography", "relationships", "references"],
    )

    assert "Chapter summaries for chapters where this entity appears:" in prompt
    assert "Chapter: Chapter 1" in prompt
    assert "Dorian meets Chaol at court." in prompt
    assert "Direct excerpts have priority over chapter summaries." in prompt
    assert "Treat chapter summaries as orientation context, not strong evidence." in prompt


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


def test_generation_profile_prefers_sections_by_type_override():
    cfg = {
        "principal": {
            "sections": ["infobox", "biography", "personality", "references"],
            "sections_by_type": {
                "PLACE": ["infobox", "biography", "physical", "references"],
            },
            "max_tokens_per_page": 900,
        }
    }

    sections, max_tokens = generation_profile(cfg, "principal", "PLACE")

    assert sections == ["infobox", "biography", "physical", "references"]
    assert max_tokens == 900


def test_parse_response_marks_empty_content_as_failed_stub():
    raw = (
        '{"title":"Yulemas","importance":"principal","entity_type":"EVENT",'
        '"infobox_fields":{},"content":""}'
    )
    entity = {
        "canonical_name": "Yulemas",
        "importance": "principal",
        "type": "EVENT",
    }

    page = parse_response(raw, entity)

    assert page["_failed"] is True
    assert page["title"] == "Yulemas"
    assert page["content"] != ""


def test_is_page_complete_rejects_empty_or_whitespace_content():
    assert _is_page_complete({"title": "A", "content": "## Biographie\n\nTexte."}) is True
    assert _is_page_complete({"title": "A", "content": ""}) is False
    assert _is_page_complete({"title": "A", "content": "   \n\t"}) is False


def test_parse_response_rejects_template_placeholder_leak():
    raw = (
        '{"title":"Assassin","importance":"secondary","entity_type":"PERSON",'
        '"infobox_fields":{"nom":"<si connu>"},"content":"## Infobox\\n\\n- Nom: <si connu>\\n\\n## Biographie\\n\\nTexte."}'
    )
    page = parse_response(raw, _entity())
    assert page["_failed"] is True


def test_contains_template_placeholder_detects_marker_in_infobox():
    page = {"content": "## Biographie\n\nTexte.", "infobox_fields": {"nom": "<si connu>"}}
    assert _contains_template_placeholder(page) is True
