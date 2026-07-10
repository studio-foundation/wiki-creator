"""Tests for scripts/generate_wiki_pages.py."""

import json

import pytest

from scripts.generate_wiki_pages import (
    _check_forbidden_names,
    _contains_template_placeholder,
    _extract_stage_output_from_run_payload,
    _is_page_complete,
    _print_generation_summary,
    _run_generation_for_entity,
    _strip_relations_section,
    build_prompt,
    generation_profile,
    make_stub_page,
    parse_response,
)


def _entity() -> dict:
    return {
        "canonical_name": "Victor Grandes",
        "importance": "secondaire",
        "type": "PERSON",
    }


def test_parse_response_extracts_json_wrapped_in_text():
    raw = (
        "Voici la sortie demandee.\n"
        '{"title":"Victor Grandes","importance":"secondaire","entity_type":"PERSON",'
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
        '{"title":"Victor Grandes","importance":"secondaire","entity_type":"PERSON",'
        '"infobox_fields":{},"content":"## Biographie\\n\\nTexte."}\n'
        "```\n"
    )
    page = parse_response(raw, _entity())
    assert page["title"] == "Victor Grandes"
    assert page["importance"] == "secondaire"
    assert page["content"] == "## Biographie\n\nTexte."


def test_parse_response_ignores_trailing_text_after_fenced_json():
    raw = (
        "```json\n"
        '{"title":"Victor Grandes","importance":"secondaire","entity_type":"PERSON",'
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
        '{"title":"Victor Grandes","importance":"secondaire","entity_type":"PERSON",'
        '"infobox_fields":{},"content":"## Infobox\\n\\n- Nom: Victor Grandes\\n- Statut: Vivant\\n\\n## Biographie\\n\\nTexte."}'
    )
    page = parse_response(raw, _entity())
    assert page["infobox_fields"] == {
        "nom": "Victor Grandes",
        "statut": "Vivant",
    }


def test_parse_response_populates_infobox_fields_from_infobox_section_plain_lines():
    raw = (
        '{"title":"Victor Grandes","importance":"secondaire","entity_type":"PERSON",'
        '"infobox_fields":{},"content":"## Infobox\\n\\nNom: Victor Grandes\\nStatut: Vivant\\n\\n## Biographie\\n\\nTexte."}'
    )
    page = parse_response(raw, _entity())
    assert page["infobox_fields"] == {
        "nom": "Victor Grandes",
        "statut": "Vivant",
    }


def test_parse_response_keeps_existing_infobox_fields_when_already_present():
    raw = (
        '{"title":"Victor Grandes","importance":"secondaire","entity_type":"PERSON",'
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
        '{"title":"Assassin","importance":"secondaire","entity_type":"PERSON",'
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
                    "importance": "secondaire",
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
        "importance": "secondaire",
        "entity_type": "PERSON",
        "infobox_fields": {},
        "content": "## Biographie\n\nTexte.",
    }


def test_run_generation_for_entity_uses_item_runner_when_not_dry(monkeypatch, tmp_path):
    entity = {
        "canonical_name": "Victor Grandes",
        "importance": "secondaire",
        "type": "PERSON",
        "context_by_chapter": {"ch01": ["Victor entre dans la pièce."]},
    }
    debug_dir = tmp_path / "wiki_page_item_debug"
    calls = []

    def fake_runner(*, entity, book_title, model, timeout, sections, max_tokens,
                    forbidden_names=None, language="fr", file_path="", grounding=None):
        calls.append((entity["canonical_name"], book_title, model, timeout, sections, max_tokens))
        return {
            "title": "Victor Grandes",
            "importance": "secondaire",
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
        "importance": "secondaire",
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
        "importance": "secondaire",
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
        "importance": "secondaire",
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
    """Typed relationships[] must appear in the prompt with related_entity and relationship_type."""
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
    assert "related_entity: Elena" in prompt
    assert "relationship_type: allié" in prompt
    assert "related_entity: Dorian Havilliard" in prompt
    assert "relationship_type: employeur/employé" in prompt
    assert "Elena aide Celaena." in prompt
    assert "ALWAYS include" in prompt


def test_build_prompt_relationships_normalizes_subject_as_entity_b():
    """When the subject is entity_b, the prompt should show entity_a as the related entity."""
    entity = {
        "canonical_name": "Chaol Westfall",
        "importance": "principal",
        "type": "PERSON",
        "aliases": [],
        "context_by_chapter": {},
        "relationships": [
            {
                "entity_a": "Celaena Sardothien",
                "entity_b": "Chaol Westfall",
                "cooccurrence_count": 45,
                "relationship_type": "garde",
                "direction": "A→B",
                "evolution": None,
            },
        ],
    }
    prompt = build_prompt(entity, "Throne of Glass", ["infobox", "biography", "relationships"])
    assert "related_entity: Celaena Sardothien" in prompt
    assert "related_entity: Chaol Westfall" not in prompt


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


def test_build_prompt_opens_with_fictional_world_framing():
    """Prompt must start with a positive fictional-world framing before any context."""
    entity = {
        "canonical_name": "Celaena Sardothien",
        "importance": "principal",
        "type": "PERSON",
        "aliases": [],
        "context_by_chapter": {},
    }
    prompt = build_prompt(entity, "Throne of Glass", ["infobox", "biography"])
    # The fictional world framing must appear early (before the entity block)
    framing_pos = prompt.lower().find("fictional world")
    entity_pos = prompt.find("Entity to write:")
    assert framing_pos != -1, "Prompt must contain 'fictional world' framing"
    assert entity_pos != -1, "Prompt must contain 'Entity to write:' marker"
    assert framing_pos < entity_pos, "Fictional world framing must appear before entity block"


def test_build_prompt_uses_positive_grounding_constraint():
    """Prompt must use a positive grounding constraint anchored to excerpts."""
    entity = {
        "canonical_name": "Celaena Sardothien",
        "importance": "principal",
        "type": "PERSON",
        "aliases": [],
        "context_by_chapter": {},
    }
    prompt = build_prompt(entity, "Throne of Glass", ["infobox", "biography"])
    lower = prompt.lower()
    assert "every factual claim" in lower, "Prompt must contain 'every factual claim' positive grounding"
    assert "grounding excerpts" in lower, "Positive grounding constraint must reference 'GROUNDING EXCERPTS'"


def test_build_prompt_grounding_excerpts_header_is_prominent():
    """Excerpt block header must use 'GROUNDING EXCERPTS' to reinforce salience."""
    entity = {
        "canonical_name": "Celaena Sardothien",
        "importance": "principal",
        "type": "PERSON",
        "aliases": [],
        "context_by_chapter": {"C01.xhtml": ["She crossed the hall."]},
    }
    prompt = build_prompt(entity, "Throne of Glass", ["biography"])
    assert "GROUNDING EXCERPTS" in prompt


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


def test_build_prompt_puts_flashback_chapters_in_backstory_block():
    entity = {
        "canonical_name": "Celaena",
        "type": "PERSON",
        "importance": "principal",
        "aliases": [],
        "context_by_chapter": {},
        "related_context": [],
        "relationships": [],
        "chapter_summary_context": [
            {
                "chapter_key": "ch01",
                "summary_bullets": ["She arrived at the castle."],
                "temporal_context": "present",
            },
            {
                "chapter_key": "ch02",
                "summary_bullets": ["Five years earlier, she trained under Arobynn."],
                "temporal_context": "flashback",
            },
        ],
    }
    prompt = build_prompt(entity, "Throne of Glass", ["## Biographie", "## Relations"])
    assert "## Chapter summary context" in prompt
    assert "She arrived at the castle." in prompt
    assert "## Backstory context" in prompt
    assert "Five years earlier" in prompt
    backstory_start = prompt.index("## Backstory context")
    present_start = prompt.index("## Chapter summary context")
    assert present_start < backstory_start
    assert prompt.index("She arrived at the castle.") < backstory_start


def test_build_prompt_omits_backstory_block_when_no_flashbacks():
    entity = {
        "canonical_name": "Dorian",
        "type": "PERSON",
        "importance": "secondaire",
        "aliases": [],
        "context_by_chapter": {},
        "related_context": [],
        "relationships": [],
        "chapter_summary_context": [
            {
                "chapter_key": "ch01",
                "summary_bullets": ["Dorian met Chaol in the hall."],
                "temporal_context": "present",
            },
        ],
    }
    prompt = build_prompt(entity, "Throne of Glass", ["## Biographie"])
    assert "## Backstory context" not in prompt
    assert "Dorian met Chaol" in prompt


def test_build_prompt_references_constraint_present():
    """build_prompt must include an explicit rule constraining the Références section."""
    entity = {
        "canonical_name": "Celaena",
        "type": "PERSON",
        "importance": "principal",
        "aliases": [],
        "context_by_chapter": {},
        "related_context": [],
        "relationships": [],
        "chapter_summary_context": [],
    }
    prompt = build_prompt(entity, book_title="Throne of Glass", sections=["infobox", "biography", "references"])
    assert "Throne of Glass" in prompt
    assert 'must list ONLY "Throne of Glass"' in prompt


# --- STU-291: generation summary log ---

def test_print_generation_summary_reports_counts(capsys):
    """_print_generation_summary prints total, succeeded, and failed counts."""
    pages = [
        {"title": "Celaena", "content": "## Bio\n\nHero.", "_failed": False},
        {"title": "Arobynn Hamel", "content": "", "_failed": True},
        {"title": "Dorian", "content": "## Bio\n\nPrince."},
    ]
    _print_generation_summary(pages)
    captured = capsys.readouterr()
    assert "3" in captured.err   # total
    assert "2" in captured.err   # succeeded
    assert "1" in captured.err   # failed
    assert "Arobynn Hamel" in captured.err


def test_print_generation_summary_no_failures(capsys):
    """When no pages failed, summary should report 0 failures."""
    pages = [
        {"title": "Celaena", "content": "## Bio\n\nHero."},
        {"title": "Dorian", "content": "## Bio\n\nPrince."},
    ]
    _print_generation_summary(pages)
    captured = capsys.readouterr()
    assert "0" in captured.err   # zero failures
    assert "2" in captured.err   # total / succeeded


# --- STU-303: ## Relations must not bleed into content ---

def test_build_prompt_forbids_relations_when_not_in_sections():
    """When 'relationships' is absent from sections, prompt must explicitly forbid ## Relations."""
    entity = {
        "canonical_name": "Hollin",
        "importance": "figurant",
        "type": "PERSON",
        "aliases": [],
        "context_by_chapter": {},
        "relationships": [
            {"entity_a": "Hollin", "entity_b": "Dorian", "relationship_type": "frères", "cooccurrence_count": 5}
        ],
    }
    prompt = build_prompt(entity, "Throne of Glass", ["infobox", "biography"])
    assert "Do NOT include" in prompt or "do not include" in prompt.lower() or "## Relations" in prompt and "DO NOT" in prompt
    # Must not instruct LLM to produce ## Relations
    assert "ALWAYS include" not in prompt


def test_build_prompt_forbids_relations_when_no_typed_rels():
    """When typed relationships are empty, prompt must not instruct LLM to produce ## Relations."""
    entity = {
        "canonical_name": "Celaena Sardothien",
        "importance": "principal",
        "type": "PERSON",
        "aliases": [],
        "context_by_chapter": {},
        "relationships": [],
    }
    prompt = build_prompt(entity, "Throne of Glass", ["infobox", "biography", "relationships"])
    # The strong negative rule must appear, not just the soft omit hint
    assert "Do NOT include a ## Relations" in prompt or "do not include a ## Relations" in prompt.lower()


def _make_content_with_relations() -> str:
    return (
        "## Biographie\n\nCelaena est une assassin.\n\n"
        "## Relations\n\n**[[Dorian Havilliard]]** — ami (42 mentions communes).\n\n"
        "## Anecdotes\n\nElle aime la musique."
    )


def test_strip_relations_section_removes_section_from_content():
    """_strip_relations_section must remove the ## Relations section entirely from content."""
    content = _make_content_with_relations()
    result = _strip_relations_section(content)
    assert "## Relations" not in result
    assert "Dorian Havilliard" not in result


def test_strip_relations_section_preserves_surrounding_sections():
    """_strip_relations_section must not remove other sections."""
    content = _make_content_with_relations()
    result = _strip_relations_section(content)
    assert "## Biographie" in result
    assert "Celaena est une assassin." in result
    assert "## Anecdotes" in result
    assert "Elle aime la musique." in result


def test_strip_relations_section_no_op_when_absent():
    """_strip_relations_section must be a no-op when content has no ## Relations section."""
    content = "## Biographie\n\nCelaena est une assassin.\n\n## Anecdotes\n\nElle aime la musique."
    result = _strip_relations_section(content)
    assert result == content


# --- STU-311: _insufficient_data flag and short-content warning ---

def test_make_stub_page_sets_insufficient_data_flag():
    """make_stub_page with insufficient_data=True must set _insufficient_data, not _failed."""
    entity = {"canonical_name": "Brullo", "importance": "secondaire", "type": "PERSON"}
    page = make_stub_page(entity, insufficient_data=True)
    assert page.get("_insufficient_data") is True
    assert "_failed" not in page


def test_make_stub_page_default_sets_no_flags():
    """make_stub_page() with no flags must set neither _failed nor _insufficient_data."""
    entity = {"canonical_name": "Brullo", "importance": "secondaire", "type": "PERSON"}
    page = make_stub_page(entity)
    assert "_failed" not in page
    assert "_insufficient_data" not in page


def test_run_generation_for_entity_sets_insufficient_data_when_no_context(tmp_path):
    """When context_by_chapter is empty, _run_generation_for_entity must return _insufficient_data stub."""
    entity = {
        "canonical_name": "Brullo",
        "importance": "secondaire",
        "type": "PERSON",
        "context_by_chapter": {},
    }
    page = _run_generation_for_entity(
        entity=entity,
        book_title="Mon Livre",
        model="qwen2.5",
        timeout=120,
        sections=["infobox", "biography"],
        max_tokens=800,
        dry_run=False,
        debug_dir=tmp_path / "debug",
    )
    assert page.get("_insufficient_data") is True
    assert "_failed" not in page


def test_parse_response_warns_on_suspiciously_short_content(capsys):
    """parse_response must log a warning when content is non-empty but suspiciously short."""
    raw = json.dumps({
        "title": "Brullo",
        "importance": "secondaire",
        "entity_type": "PERSON",
        "infobox_fields": {},
        "content": "## Biographie\n\nPersonnage mineur.",
    })
    entity = {"canonical_name": "Brullo", "importance": "secondaire", "type": "PERSON"}
    page = parse_response(raw, entity)
    assert not page.get("_failed"), "Short but non-empty content must not be marked failed"
    captured = capsys.readouterr()
    assert "brullo" in captured.err.lower() or "court" in captured.err.lower() or "short" in captured.err.lower()


def test_print_generation_summary_reports_insufficient_data_separately(capsys):
    """_print_generation_summary must count and list _insufficient_data pages separately from _failed."""
    pages = [
        {"title": "Celaena", "content": "## Bio\n\nHero."},
        {"title": "Brullo", "content": "...", "_insufficient_data": True},
        {"title": "Arobynn", "content": "", "_failed": True},
    ]
    _print_generation_summary(pages)
    captured = capsys.readouterr()
    assert "Brullo" in captured.err
    assert "insufficient" in captured.err.lower() or "données" in captured.err.lower()


# --- STU-317: _check_forbidden_names detection ---

def test_check_forbidden_names_detects_in_content():
    page = {
        "content": "Celaena, aussi connue sous le nom d'Aelin Galathynius, est une assassine.",
        "infobox_fields": {},
    }
    hits = _check_forbidden_names(page, ["Aelin Galathynius", "Aelin"])
    assert "Aelin Galathynius" in hits


def test_check_forbidden_names_detects_in_infobox():
    page = {
        "content": "Texte propre sans spoiler.",
        "infobox_fields": {"alias": "Aelin"},
    }
    hits = _check_forbidden_names(page, ["Aelin Galathynius", "Aelin"])
    assert "Aelin" in hits


def test_check_forbidden_names_case_insensitive():
    page = {
        "content": "Son vrai nom est aelin galathynius.",
        "infobox_fields": {},
    }
    hits = _check_forbidden_names(page, ["Aelin Galathynius"])
    assert "Aelin Galathynius" in hits


def test_check_forbidden_names_returns_empty_when_clean():
    page = {
        "content": "Celaena Sardothien est une assassine.",
        "infobox_fields": {"nom": "Celaena Sardothien"},
    }
    hits = _check_forbidden_names(page, ["Aelin Galathynius", "Aelin"])
    assert hits == []


def test_check_forbidden_names_returns_empty_for_empty_list():
    page = {"content": "N'importe quel contenu.", "infobox_fields": {}}
    hits = _check_forbidden_names(page, [])
    assert hits == []


def test_build_prompt_includes_forbidden_names_block():
    entity = {
        "canonical_name": "Celaena Sardothien",
        "importance": "principal",
        "type": "PERSON",
        "context_by_chapter": {"ch01": ["Celaena entre dans la salle."]},
    }
    prompt = build_prompt(entity, "Throne of Glass", sections=["infobox", "biography"],
                          forbidden_names=["Aelin Galathynius", "Aelin"])
    assert "FORBIDDEN NAMES" in prompt
    assert "Aelin Galathynius" in prompt
    assert "Aelin" in prompt


def test_build_prompt_no_forbidden_names_block_when_empty():
    entity = {
        "canonical_name": "Celaena Sardothien",
        "importance": "principal",
        "type": "PERSON",
        "context_by_chapter": {"ch01": ["Celaena entre dans la salle."]},
    }
    prompt = build_prompt(entity, "Throne of Glass", sections=["infobox", "biography"],
                          forbidden_names=[])
    assert "FORBIDDEN NAMES" not in prompt


def test_build_prompt_no_forbidden_names_block_when_omitted():
    entity = {
        "canonical_name": "Celaena Sardothien",
        "importance": "principal",
        "type": "PERSON",
        "context_by_chapter": {"ch01": ["Celaena entre dans la salle."]},
    }
    prompt = build_prompt(entity, "Throne of Glass", sections=["infobox", "biography"])
    assert "FORBIDDEN NAMES" not in prompt


def test_run_generation_retries_on_forbidden_name(monkeypatch, tmp_path):
    entity = {
        "canonical_name": "Celaena Sardothien",
        "importance": "principal",
        "type": "PERSON",
        "context_by_chapter": {"ch01": ["Celaena entre dans la salle."]},
    }
    debug_dir = tmp_path / "debug"
    calls = []

    def fake_runner(**kwargs):
        calls.append(kwargs.get("forbidden_names"))
        if len(calls) == 1:
            return {
                "title": "Celaena Sardothien",
                "importance": "principal",
                "entity_type": "PERSON",
                "infobox_fields": {},
                "content": "Celaena, aussi connue sous le nom d'Aelin Galathynius, est une assassine.",
            }
        return {
            "title": "Celaena Sardothien",
            "importance": "principal",
            "entity_type": "PERSON",
            "infobox_fields": {},
            "content": "Celaena Sardothien est une assassine.",
        }

    monkeypatch.setattr("scripts.generate_wiki_pages._run_wiki_page_item", fake_runner)

    page = _run_generation_for_entity(
        entity=entity,
        book_title="Throne of Glass",
        model="qwen2.5",
        timeout=120,
        sections=["infobox", "biography"],
        max_tokens=800,
        dry_run=False,
        debug_dir=debug_dir,
        forbidden_names=["Aelin Galathynius", "Aelin"],
    )

    assert len(calls) == 2
    assert "Aelin" not in page.get("content", "")
    assert page["title"] == "Celaena Sardothien"


def test_run_generation_returns_stub_after_failed_retry(monkeypatch, tmp_path):
    entity = {
        "canonical_name": "Celaena Sardothien",
        "importance": "principal",
        "type": "PERSON",
        "context_by_chapter": {"ch01": ["Celaena entre dans la salle."]},
    }
    debug_dir = tmp_path / "debug"

    def fake_runner(**kwargs):
        return {
            "title": "Celaena Sardothien",
            "importance": "principal",
            "entity_type": "PERSON",
            "infobox_fields": {},
            "content": "Celaena, aussi connue sous le nom d'Aelin Galathynius.",
        }

    monkeypatch.setattr("scripts.generate_wiki_pages._run_wiki_page_item", fake_runner)

    page = _run_generation_for_entity(
        entity=entity,
        book_title="Throne of Glass",
        model="qwen2.5",
        timeout=120,
        sections=["infobox", "biography"],
        max_tokens=800,
        dry_run=False,
        debug_dir=debug_dir,
        forbidden_names=["Aelin Galathynius"],
    )

    assert page.get("_failed") is True
    assert page.get("_spoiler_rejected") is True


def test_run_generation_no_retry_when_clean(monkeypatch, tmp_path):
    entity = {
        "canonical_name": "Celaena Sardothien",
        "importance": "principal",
        "type": "PERSON",
        "context_by_chapter": {"ch01": ["Celaena entre dans la salle."]},
    }
    debug_dir = tmp_path / "debug"
    calls = []

    def fake_runner(**kwargs):
        calls.append(1)
        return {
            "title": "Celaena Sardothien",
            "importance": "principal",
            "entity_type": "PERSON",
            "infobox_fields": {},
            "content": "Celaena Sardothien est une assassine.",
        }

    monkeypatch.setattr("scripts.generate_wiki_pages._run_wiki_page_item", fake_runner)

    page = _run_generation_for_entity(
        entity=entity,
        book_title="Throne of Glass",
        model="qwen2.5",
        timeout=120,
        sections=["infobox", "biography"],
        max_tokens=800,
        dry_run=False,
        debug_dir=debug_dir,
        forbidden_names=["Aelin Galathynius"],
    )

    assert len(calls) == 1
    assert page["title"] == "Celaena Sardothien"
    assert not page.get("_failed")


def test_run_generation_no_retry_when_no_forbidden_names(monkeypatch, tmp_path):
    entity = {
        "canonical_name": "Celaena Sardothien",
        "importance": "principal",
        "type": "PERSON",
        "context_by_chapter": {"ch01": ["Celaena entre dans la salle."]},
    }
    debug_dir = tmp_path / "debug"
    calls = []

    def fake_runner(**kwargs):
        calls.append(1)
        return {
            "title": "Celaena Sardothien",
            "importance": "principal",
            "entity_type": "PERSON",
            "infobox_fields": {},
            "content": "Celaena aussi connue sous le nom d'Aelin Galathynius.",
        }

    monkeypatch.setattr("scripts.generate_wiki_pages._run_wiki_page_item", fake_runner)

    page = _run_generation_for_entity(
        entity=entity,
        book_title="Throne of Glass",
        model="qwen2.5",
        timeout=120,
        sections=["infobox", "biography"],
        max_tokens=800,
        dry_run=False,
        debug_dir=debug_dir,
    )

    assert len(calls) == 1
    assert not page.get("_failed")


def test_wiki_page_item_input_carries_validator_context():
    """language / forbidden_names / file_path must reach the wiki-page-item
    pipeline input — the wiki-page-validator stage reads them from
    additional_context and its checks are no-ops without them."""
    from scripts.generate_wiki_pages import _wiki_page_item_input

    entity = {"canonical_name": "Celaena Sardothien", "importance": "principal",
              "type": "PERSON", "context_by_chapter": {"ch01": ["..."]}}
    item = _wiki_page_item_input(
        entity=entity,
        book_title="Throne of Glass",
        sections=["infobox", "biography"],
        max_tokens=800,
        forbidden_names=["Aelin"],
        language="fr",
        file_path="library/x/books/01.epub",
    )
    assert item["title"] == "Celaena Sardothien"
    assert item["language"] == "fr"
    assert item["forbidden_names"] == ["Aelin"]
    assert item["file_path"] == "library/x/books/01.epub"


def test_wiki_page_item_input_defaults():
    from scripts.generate_wiki_pages import _wiki_page_item_input

    item = _wiki_page_item_input(
        entity={"canonical_name": "X", "importance": "figurant", "type": "PERSON"},
        book_title="B",
        sections=["infobox"],
        max_tokens=200,
    )
    assert item["language"] == "fr"
    assert item["forbidden_names"] == []
    assert item["file_path"] == ""


def test_wiki_page_item_input_grounding_config():
    from scripts.generate_wiki_pages import _wiki_page_item_input

    entity = {"canonical_name": "Nox Owen", "importance": "principal",
              "type": "PERSON", "context_by_chapter": {"ch01": ["..."]}}
    item = _wiki_page_item_input(
        entity=entity, book_title="B", sections=["infobox"], max_tokens=200,
        grounding={"llm": True, "llm_model": "qwen2.5", "llm_timeout": 60},
    )
    assert item["grounding_llm"] is True
    assert item["grounding_llm_model"] == "qwen2.5"
    assert item["grounding_llm_timeout"] == 60


def test_wiki_page_item_input_grounding_off_by_default():
    from scripts.generate_wiki_pages import _wiki_page_item_input

    item = _wiki_page_item_input(
        entity={"canonical_name": "X", "importance": "figurant", "type": "PERSON"},
        book_title="B", sections=["infobox"], max_tokens=200,
    )
    assert "grounding_llm" not in item


def _entity_with_chapter(pov, pov_character):
    return {
        "canonical_name": "Chaol",
        "type": "PERSON",
        "importance": "principal",
        "aliases": [],
        "chapter_summary_context": [
            {"chapter_key": "c1", "summary_bullets": ["Something happened."],
             "temporal_context": "present", "pov": pov, "pov_character": pov_character},
        ],
    }


def test_prompt_includes_pov_note_for_limited_pov():
    prompt = build_prompt(_entity_with_chapter("third_limited", "Chaol"), "Book", ["main"])
    assert "Chaol's perspective" in prompt


def test_prompt_no_pov_note_for_omniscient():
    prompt = build_prompt(_entity_with_chapter("omniscient", None), "Book", ["main"])
    assert "perspective —" not in prompt  # no per-chapter POV note emitted
