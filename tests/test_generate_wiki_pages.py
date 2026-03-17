"""Tests for scripts/generate_wiki_pages.py."""

import json

from scripts.generate_wiki_pages import (
    _contains_template_placeholder,
    _extract_stage_output_from_run_payload,
    _is_page_complete,
    _run_generation_for_entity,
    build_prompt,
    call_ollama,
    generation_profile,
    make_stub_page,
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
    assert '"title": "John Doe"' in prompt
    assert '"content": "## Infobox\\n\\n' in prompt
    assert '## Biographie\\n\\n' in prompt
    assert '## Relations\\n\\n' in prompt
    assert '"content": "<Markdown string with \\\\n for newlines>"' in prompt


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

    assert "Related entities (disambiguation only — do not derive narrative from cooccurrence):" in prompt
    assert "Name: Celaena" in prompt
    assert "Cooccurrence count: 175" in prompt
    assert "Do NOT turn cooccurrence between entities into narrative causality." in prompt


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

    assert "Chapter summaries (orientation context — lower priority than excerpts):" in prompt
    assert "Chapter: Chapter 1" in prompt
    assert "Dorian meets Chaol at court." in prompt
    assert "Chapter summaries serve as orientation only. Direct excerpts take priority." in prompt


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


def test_extract_stage_output_from_run_payload_reads_successful_stage_output() -> None:
    run_payload = {
        "id": "run-123",
        "pipeline_name": "wiki-page-item",
        "status": "success",
        "stages": [
            {
                "stage_name": "wiki-page-item",
                "status": "success",
                "output": {
                    "title": "Victor Grandes",
                    "importance": "secondary",
                    "entity_type": "PERSON",
                    "infobox_fields": {},
                    "content": "## Biographie\n\nTexte.",
                },
            }
        ],
    }

    output = _extract_stage_output_from_run_payload(run_payload, "wiki-page-item")

    assert output == {
        "title": "Victor Grandes",
        "importance": "secondary",
        "entity_type": "PERSON",
        "infobox_fields": {},
        "content": "## Biographie\n\nTexte.",
    }


def test_run_generation_for_entity_uses_item_runner_when_not_dry(monkeypatch, tmp_path):
    entity = {
        "canonical_name": "Victor Grandes",
        "importance": "secondary",
        "type": "PERSON",
        "context_by_chapter": {"ch01": ["Victor entre dans la pièce."]},
    }
    debug_dir = tmp_path / "wiki_page_item_debug"
    calls = []

    def fake_runner(*, entity, book_title, model, timeout, sections, max_tokens):
        calls.append((entity["canonical_name"], book_title, model, timeout, sections, max_tokens))
        return {
            "title": "Victor Grandes",
            "importance": "secondary",
            "entity_type": "PERSON",
            "infobox_fields": {},
            "content": "## Biographie\n\nTexte.",
        }

    monkeypatch.setattr("scripts.generate_wiki_pages._run_wiki_page_item", fake_runner)

    page = _run_generation_for_entity(
        entity=entity,
        book_title="Mon Livre",
        model="qwen2.5",
        timeout=120,
        sections=["infobox", "biography"],
        max_tokens=800,
        dry_run=False,
        debug_dir=debug_dir,
    )

    assert calls == [("Victor Grandes", "Mon Livre", "qwen2.5", 120, ["infobox", "biography"], 800)]
    assert page["title"] == "Victor Grandes"


def test_run_generation_for_entity_returns_retryable_failed_stub_and_logs_on_runner_failure(monkeypatch, tmp_path):
    entity = {
        "canonical_name": "Victor Grandes",
        "importance": "secondary",
        "type": "PERSON",
        "context_by_chapter": {"ch01": ["Victor entre dans la pièce."]},
    }
    debug_dir = tmp_path / "wiki_page_item_debug"

    monkeypatch.setattr(
        "scripts.generate_wiki_pages._run_wiki_page_item",
        lambda **_: {
            "error": "studio_run_failed",
            "raw_response": "plain string response",
            "run_metadata": {"pipeline": "wiki-page-item", "attempts": 3},
        },
    )

    page = _run_generation_for_entity(
        entity=entity,
        book_title="Mon Livre",
        model="qwen2.5",
        timeout=120,
        sections=["infobox", "biography"],
        max_tokens=800,
        dry_run=False,
        debug_dir=debug_dir,
    )

    assert page["_failed"] is True
    assert page["title"] == "Victor Grandes"
    debug_files = sorted(debug_dir.glob("*.json"))
    assert len(debug_files) == 1
    payload = json.loads(debug_files[0].read_text(encoding="utf-8"))
    assert payload["error"] == "studio_run_failed"


# --- STU-263: infobox_fields key normalisation and artifact filtering ---

def test_parse_response_strips_dash_prefix_from_infobox_keys():
    """Keys like '- nom' returned by the LLM must be cleaned to 'nom'."""
    raw = json.dumps({
        "title": "Celaena Sardothien",
        "importance": "principal",
        "entity_type": "PERSON",
        "infobox_fields": {
            "- nom": "Celaena Sardothien",
            "- occupation": "King's Champion",
            "- alias": "Aelin",
        },
        "content": "## Biographie\n\nTexte.",
    })
    page = parse_response(raw, {
        "canonical_name": "Celaena Sardothien",
        "importance": "principal",
        "type": "PERSON",
    })
    assert "- nom" not in page["infobox_fields"]
    assert "- occupation" not in page["infobox_fields"]
    assert page["infobox_fields"]["nom"] == "Celaena Sardothien"
    assert page["infobox_fields"]["occupation"] == "King's Champion"


def test_parse_response_removes_internal_artifact_keys_from_infobox():
    """Internal fields like cooccurrence_count must not appear in infobox_fields."""
    raw = json.dumps({
        "title": "Hollin",
        "importance": "secondary",
        "entity_type": "PERSON",
        "infobox_fields": {
            "nom": "Hollin",
            "cooccurrence_count": "6",
            "entity_type": "PERSON",
        },
        "content": "## Biographie\n\nTexte.",
    })
    page = parse_response(raw, {
        "canonical_name": "Hollin",
        "importance": "secondary",
        "type": "PERSON",
    })
    assert "cooccurrence_count" not in page["infobox_fields"]
    assert "entity_type" not in page["infobox_fields"]
    assert page["infobox_fields"]["nom"] == "Hollin"


def test_build_prompt_instructs_plain_infobox_keys():
    """Prompt must contain explicit instruction ruling out '- ' prefixed keys."""
    entity = {
        "canonical_name": "Celaena Sardothien",
        "importance": "principal",
        "type": "PERSON",
        "aliases": [],
        "context_by_chapter": {},
    }
    prompt = build_prompt(entity, "Throne of Glass", ["infobox", "biography"])
    assert '"- nom"' in prompt or "no leading" in prompt or 'without "- "' in prompt or "plain string" in prompt


def test_build_prompt_includes_typed_relationships_block():
    """Typed relationships[] must appear in the prompt with entity_b and relationship_type."""
    entity = {
        "canonical_name": "Celaena Sardothien",
        "importance": "principal",
        "type": "PERSON",
        "aliases": [],
        "context_by_chapter": {},
        "relationships": [
            {
                "entity_a": "Celaena Sardothien",
                "entity_b": "Elena",
                "cooccurrence_count": 61,
                "relationship_type": "allié",
                "direction": "B→A",
                "evolution": "Elena aide Celaena.",
            },
            {
                "entity_a": "Celaena Sardothien",
                "entity_b": "Dorian Havilliard",
                "cooccurrence_count": 48,
                "relationship_type": "employeur/employé",
                "direction": "B→A",
                "evolution": None,
            },
        ],
    }
    prompt = build_prompt(entity, "Throne of Glass", ["infobox", "biography", "relationships"])
    assert "entity_b: Elena" in prompt
    assert "relationship_type: allié" in prompt
    assert "entity_b: Dorian Havilliard" in prompt
    assert "relationship_type: employeur/employé" in prompt
    assert "Elena aide Celaena." in prompt
    assert "ALWAYS include" in prompt


def test_build_prompt_no_relationships_omits_section_rule():
    """When no relationships[], the prompt must not mandate the Relations section."""
    entity = {
        "canonical_name": "Celaena Sardothien",
        "importance": "principal",
        "type": "PERSON",
        "aliases": [],
        "context_by_chapter": {},
        "relationships": [],
    }
    prompt = build_prompt(entity, "Throne of Glass", ["infobox", "biography", "relationships"])
    assert "no typed relationships available" in prompt


def test_build_prompt_instructs_no_training_knowledge():
    """Prompt must contain instruction to not use prior training knowledge."""
    entity = {
        "canonical_name": "Celaena Sardothien",
        "importance": "principal",
        "type": "PERSON",
        "aliases": [],
        "context_by_chapter": {},
    }
    prompt = build_prompt(entity, "Throne of Glass", ["infobox", "biography"])
    lower = prompt.lower()
    assert "prior knowledge" in lower or "training knowledge" in lower or "do not use" in lower


def test_build_prompt_normalizes_xhtml_chapter_keys():
    entity = {
        "canonical_name": "Celaena",
        "importance": "principal",
        "type": "PERSON",
        "aliases": [],
        "context_by_chapter": {
            "C25.xhtml": ["She crossed the hall."],
            "C03.xhtml": ["She entered the palace."],
        },
        "chapter_summary_context": [],
        "related_context": [],
        "relationships": [],
    }
    prompt = build_prompt(entity, "Throne of Glass", ["biography"])
    assert "C25.xhtml" not in prompt
    assert "C03.xhtml" not in prompt
    assert "Chapter 25" in prompt
    assert "Chapter 3" in prompt


def test_build_prompt_keeps_non_xhtml_chapter_keys_unchanged():
    entity = {
        "canonical_name": "Celaena",
        "importance": "principal",
        "type": "PERSON",
        "aliases": [],
        "context_by_chapter": {
            "Chapter 5": ["She crossed the hall."],
        },
        "chapter_summary_context": [],
        "related_context": [],
        "relationships": [],
    }
    prompt = build_prompt(entity, "Throne of Glass", ["biography"])
    assert "Chapter 5" in prompt


def test_build_prompt_warns_against_citing_chapter_labels():
    entity = {
        "canonical_name": "Celaena",
        "importance": "principal",
        "type": "PERSON",
        "aliases": [],
        "context_by_chapter": {"C01.xhtml": ["mention"]},
        "chapter_summary_context": [],
        "related_context": [],
        "relationships": [],
    }
    prompt = build_prompt(entity, "Throne of Glass", ["biography"])
    assert "never mention" in prompt.lower() and "internal reference" in prompt.lower()


@pytest.mark.parametrize("key,expected", [
    ("C25.xhtml", "Chapter 25"),
    ("C03.xhtml", "Chapter 3"),
    ("c1.xhtml", "Chapter 1"),
    ("sinopsis.xhtml", "sinopsis.xhtml"),
    ("Chapter 5", "Chapter 5"),
    ("", ""),
])
def test_label_chapter_key(key, expected):
    from scripts.generate_wiki_pages import _label_chapter_key
    assert _label_chapter_key(key) == expected
