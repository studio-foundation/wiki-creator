"""Tests for scripts/generate_wiki_pages.py."""

import json

import pytest

from scripts.generate_wiki_pages import (
    GenerationConfig,
    _check_forbidden_names,
    _contains_template_placeholder,
    _force_correct_identity,
    _is_page_complete,
    _narrative_events,
    _nom_matches_identity,
    _print_generation_summary,
    _rejection_is_identity_only,
    _run_generation_for_entity,
    _strip_relations_section,
    build_prompt,
    generate_pages,
    generation_profile,
    load_batch_files,
    make_stub_page,
    parse_response,
)
from wiki_creator.studio_io import extract_stage_output_from_run_payload


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


def test_parse_response_forces_identity_fields_from_batch_entity():
    # STU-319: the LLM sometimes "corrects"/frenchifies the echoed identity
    # fields (Philippa -> Philippe), and may reclassify type/importance. The
    # batch entity is the source of truth for identity, so parse_response must
    # override whatever the LLM returned.
    entity = {
        "canonical_name": "Philippa",
        "importance": "secondary",
        "type": "PERSON",
    }
    raw = (
        '{"title":"Philippe","importance":"principal","entity_type":"ORGANIZATION",'
        '"infobox_fields":{},"content":"## Biographie\\n\\nTexte."}'
    )
    page = parse_response(raw, entity)
    assert page["title"] == "Philippa"
    assert page["importance"] == "secondary"
    assert page["entity_type"] == "PERSON"


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


def test_build_prompt_includes_place_events_block_and_rule():
    """STU-480 (SP2): PLACE pages get a grounding block + writing rule for
    events.json entries where the place is in `places`."""
    entity = {
        "canonical_name": "Rifthold",
        "importance": "principal",
        "type": "PLACE",
        "aliases": [],
        "context_by_chapter": {},
        "entity_events": [
            {
                "event_id": "e_ch12_0",
                "chapter": 12,
                "description": "Celaena affronte Cain lors de l'épreuve finale du tournoi",
                "participants": ["Celaena Sardothien", "Cain"],
                "places": ["Rifthold"],
                "outcome": "Celaena gagne malgré l'empoisonnement au bloodbane",
            },
        ],
    }
    prompt = build_prompt(
        entity,
        "Mon Livre",
        sections=["infobox", "biography", "events", "references"],
    )

    assert "## Events at this place" in prompt
    assert "épreuve finale du tournoi" in prompt
    assert "personnages : Celaena Sardothien, Cain" in prompt
    assert 'Include a "## Événements" section grounded ONLY in the "Events at this place" block above' in prompt
    assert 'Do NOT include a "## Événements" section' not in prompt


def test_build_prompt_place_without_events_omits_block_and_forbids_section():
    entity = {
        "canonical_name": "Oakwald",
        "importance": "secondary",
        "type": "PLACE",
        "aliases": [],
        "context_by_chapter": {},
    }
    prompt = build_prompt(
        entity,
        "Mon Livre",
        sections=["infobox", "biography", "events", "references"],
    )

    assert "## Events at this place" not in prompt
    assert 'Do NOT include a "## Événements" section: no narrative events are available for this place.' in prompt


def test_build_prompt_ignores_entity_events_for_non_place_types():
    """entity_events is populated for PERSON too (SP0 feeds SP1 later) — the
    SP2 block/rule must stay scoped to PLACE."""
    entity = {
        "canonical_name": "Celaena Sardothien",
        "importance": "principal",
        "type": "PERSON",
        "aliases": [],
        "context_by_chapter": {},
        "entity_events": [
            {"chapter": 12, "description": "duel final", "participants": ["Celaena Sardothien"]},
        ],
    }
    prompt = build_prompt(
        entity,
        "Mon Livre",
        sections=["infobox", "biography", "references"],
    )

    assert "## Events at this place" not in prompt
    assert "Événements" not in prompt


def _celaena_with_arc():
    return {
        "canonical_name": "Celaena Sardothien",
        "importance": "principal",
        "type": "PERSON",
        "aliases": [],
        "context_by_chapter": {},
        "entity_events": [
            {"chapter": 3, "description": "Celaena arrive au château de verre", "participants": ["Celaena Sardothien"], "salience": 0.4},
            {"chapter": 12, "description": "Celaena affronte Cain lors de l'épreuve finale", "participants": ["Celaena Sardothien", "Cain"], "outcome": "Celaena vainc Cain", "salience": 0.9},
            {"chapter": 13, "description": "Celaena est couronnée Champion du Roi", "participants": ["Celaena Sardothien"], "outcome": "Celaena est couronnée", "salience": 0.85},
        ],
    }


def test_build_prompt_includes_narrative_role_block_and_rule_for_person():
    """STU-479 (SP1): PERSON pages generating the narrative_role section get a
    grounding block + writing rule for events.json entries where they participate."""
    prompt = build_prompt(
        _celaena_with_arc(),
        "Throne of Glass",
        sections=["narrative_role"],
    )

    assert "## Événements où Celaena Sardothien participe (ordre chronologique)" in prompt
    assert "épreuve finale" in prompt
    assert "est couronnée Champion du Roi" in prompt
    assert 'Write a "## Rôle dans le récit" section grounded ONLY in the' in prompt
    assert 'Do NOT include a "## Rôle dans le récit" section' not in prompt


def test_build_prompt_narrative_role_events_ordered_chronologically():
    """Salience selects which beats survive the cap; the prompt lists them by
    chapter so the arc reads in order (climax kept even though it sits late)."""
    prompt = build_prompt(_celaena_with_arc(), "Throne of Glass", sections=["narrative_role"])
    arrive = prompt.index("arrive au château")
    duel = prompt.index("épreuve finale")
    crown = prompt.index("couronnée Champion")
    assert arrive < duel < crown


def test_build_prompt_narrative_role_gated_to_its_own_section():
    """The arc block never leaks into other PERSON section prompts (biography)."""
    prompt = build_prompt(_celaena_with_arc(), "Throne of Glass", sections=["biography"])
    assert "## Événements où Celaena Sardothien participe" not in prompt
    assert "Rôle dans le récit" not in prompt


def test_build_prompt_person_without_events_omits_narrative_block():
    entity = {
        "canonical_name": "Perrington",
        "importance": "secondary",
        "type": "PERSON",
        "aliases": [],
        "context_by_chapter": {},
        "entity_events": [],
    }
    prompt = build_prompt(entity, "Throne of Glass", sections=["narrative_role"])
    assert "## Événements où" not in prompt
    assert 'Do NOT include a "## Rôle dans le récit" section' in prompt


def test_narrative_events_caps_by_salience_then_orders_by_chapter():
    events = [
        {"chapter": c, "description": f"beat {c}", "salience": s}
        for c, s in [(1, 0.1), (5, 0.9), (2, 0.2), (50, 0.95), (3, 0.15)]
    ]
    entity = {"type": "PERSON", "canonical_name": "X", "entity_events": events}
    import scripts.generate_wiki_pages as gwp

    picked = gwp._narrative_events({**entity})
    chapters = [e["chapter"] for e in picked]
    assert chapters == sorted(chapters)  # chronological


def test_narrative_events_empty_for_non_person():
    entity = {"type": "PLACE", "entity_events": [{"chapter": 1, "description": "x", "salience": 1.0}]}
    assert _narrative_events(entity) == []


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

    output = extract_stage_output_from_run_payload(run_payload, "wiki-page-item")

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

    def fake_runner(*, entity, book_title, model, timeout, sections, max_tokens,
                    forbidden_names=None, language="fr", file_path="", grounding=None, runner=None,
                    stance=None):
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


def _relationship(other: str, count: int, **extra) -> dict:
    return {
        "entity_a": "Celaena Sardothien",
        "entity_b": other,
        "cooccurrence_count": count,
        "relationship_type": "allié",
        "direction": "B→A",
        "evolution": None,
        **extra,
    }


def _entity_with_relationships(importance: str, relationships: list[dict]) -> dict:
    return {
        "canonical_name": "Celaena Sardothien",
        "importance": importance,
        "type": "PERSON",
        "aliases": [],
        "context_by_chapter": {},
        "relationships": relationships,
    }


def test_build_prompt_includes_relationship_evidence_and_key_moments():
    """STU-438: evidence and key_moments must reach the writer prompt."""
    entity = _entity_with_relationships("principal", [
        _relationship(
            "Elena", 61,
            evidence="Elena tendit la main à Celaena au bord du gouffre.",
            key_moments=["ch05: Elena sauve Celaena", "ch09: Elena révèle son passé", "ch12: adieux"],
        ),
    ])
    prompt = build_prompt(entity, "Throne of Glass", ["infobox", "biography", "relationships"])
    assert 'evidence: "Elena tendit la main à Celaena au bord du gouffre."' in prompt
    assert "key_moment: ch05: Elena sauve Celaena" in prompt
    assert "key_moment: ch09: Elena révèle son passé" in prompt
    # capped at 2 key moments per relation
    assert "ch12: adieux" not in prompt
    # anchoring rule emitted when at least one relation is enriched
    assert "Anchor each" in prompt


def test_build_prompt_filters_sentinel_key_moment():
    """The classifier's 'no moment found' sentinel must not leak into the prompt."""
    entity = _entity_with_relationships("principal", [
        _relationship(
            "Elena", 61,
            evidence="Elena parla à Celaena.",
            key_moments=["no specific moment identifiable in provided excerpts"],
        ),
    ])
    prompt = build_prompt(entity, "Throne of Glass", ["infobox", "biography", "relationships"])
    assert "no specific moment identifiable" not in prompt
    assert "key_moment:" not in prompt


def test_build_prompt_sample_context_is_fallback_only():
    """sample_contexts appears only for relations without evidence, truncated."""
    long_context = "Chaol regarda Celaena traverser la salle. " * 10  # > 200 chars
    entity = _entity_with_relationships("principal", [
        _relationship(
            "Elena", 61,
            evidence="Elena parla à Celaena.",
            sample_contexts=["Elena et Celaena discutèrent longuement dans la crypte."],
        ),
        _relationship(
            "Chaol Westfall", 45,
            sample_contexts=[long_context],
        ),
    ])
    prompt = build_prompt(entity, "Throne of Glass", ["infobox", "biography", "relationships"])
    # relation with evidence: its raw sample context must NOT be duplicated
    assert "discutèrent longuement dans la crypte" not in prompt
    # relation without evidence: gets the fallback context, truncated
    assert 'context: "Chaol regarda Celaena traverser la salle.' in prompt
    assert long_context not in prompt


def test_build_prompt_omits_untyped_relations():
    """Untyped relations never reach the writer prompt — no metric-name fallback (STU-501)."""
    entity = _entity_with_relationships("principal", [
        _relationship("Chaol Westfall", 90, relationship_type="allié"),
        _relationship("Xavier", 80, relationship_type=None),
        _relationship("Brullo", 70, relationship_type="null"),
    ])
    prompt = build_prompt(entity, "Throne of Glass", ["infobox", "biography", "relationships"])
    assert "co-occurrence" not in prompt
    assert "related_entity: Xavier" not in prompt
    assert "related_entity: Brullo" not in prompt
    assert "related_entity: Chaol Westfall" in prompt


def test_build_prompt_relationship_enrichment_budget_by_importance():
    """principal enriches top 5, secondary top 3, figurant none."""
    rels = [
        _relationship(f"Perso {i}", 100 - i, evidence=f"Preuve numéro {i}.")
        for i in range(6)
    ]

    prompt = build_prompt(
        _entity_with_relationships("principal", rels),
        "Throne of Glass", ["infobox", "biography", "relationships"],
    )
    assert 'evidence: "Preuve numéro 4."' in prompt
    assert 'evidence: "Preuve numéro 5."' not in prompt

    prompt = build_prompt(
        _entity_with_relationships("secondary", rels),
        "Throne of Glass", ["infobox", "biography", "relationships"],
    )
    assert 'evidence: "Preuve numéro 2."' in prompt
    assert 'evidence: "Preuve numéro 3."' not in prompt

    prompt = build_prompt(
        _entity_with_relationships("figurant", rels),
        "Throne of Glass", ["infobox", "biography", "relationships"],
    )
    assert "evidence:" not in prompt
    assert "Anchor each" not in prompt


def test_build_prompt_without_evidence_fields_is_unchanged():
    """Regression guard: relations lacking the STU-438 fields keep the bare format."""
    entity = _entity_with_relationships("principal", [
        _relationship("Elena", 61),
    ])
    prompt = build_prompt(entity, "Throne of Glass", ["infobox", "biography", "relationships"])
    assert "related_entity: Elena" in prompt
    assert "evidence:" not in prompt
    assert "key_moment:" not in prompt
    assert "context:" not in prompt
    assert "Anchor each" not in prompt


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


def _celaena_with_flashback() -> dict:
    return {
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


def test_build_prompt_backstory_block_and_rule_when_backstory_section():
    """STU-493: generating the backstory section surfaces the flashback context
    block plus a writing rule for the "Avant les événements du livre" section."""
    prompt = build_prompt(_celaena_with_flashback(), "Throne of Glass", ["backstory"])
    assert "## Backstory context" in prompt
    assert "Five years earlier" in prompt
    assert 'Write a "## Avant les événements du livre" section grounded ONLY in the' in prompt
    assert 'Do NOT include a "## Avant les événements du livre" section' not in prompt


def test_build_prompt_backstory_gated_to_its_own_section():
    """STU-493: flashback content never leaks into other PERSON section prompts —
    present and flashback bullets are not mixed in the biography prompt."""
    prompt = build_prompt(_celaena_with_flashback(), "Throne of Glass", ["biography"])
    assert "## Chapter summary context" in prompt
    assert "She arrived at the castle." in prompt
    assert "## Backstory context" not in prompt
    assert "Five years earlier" not in prompt
    assert "Avant les événements du livre" not in prompt


def test_build_prompt_backstory_section_omitted_when_no_flashbacks():
    entity = {
        "canonical_name": "Dorian",
        "type": "PERSON",
        "importance": "secondary",
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
    prompt = build_prompt(entity, "Throne of Glass", ["backstory"])
    assert "## Backstory context" not in prompt
    assert 'Do NOT include a "## Avant les événements du livre" section' in prompt


def test_has_backstory_detects_flashback_chapters():
    import scripts.generate_wiki_pages as gwp

    assert gwp._has_backstory(_celaena_with_flashback()) is True
    assert gwp._has_backstory({"chapter_summary_context": []}) is False
    assert gwp._has_backstory(
        {"chapter_summary_context": [{"chapter_key": "ch01", "temporal_context": "present"}]}
    ) is False


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


def test_build_prompt_localizes_titles_briefs_and_directive_in_english():
    """STU-510: lang='en' routes section titles, few-shot, briefs, and the
    write-in-<language> directive to English; French drops out entirely."""
    entity = {
        "canonical_name": "Celaena",
        "type": "PERSON",
        "importance": "principal",
        "aliases": [],
        "context_by_chapter": {"C01.xhtml": ["She fought."]},
    }
    en = build_prompt(entity, "Throne of Glass",
                      sections=["infobox", "biography", "personality", "references"], lang="en")
    assert "Write ALL content in English" in en
    assert "encyclopedic English" in en
    assert "## Biography" in en                      # few-shot heading, English
    assert "Who this character is" in en             # biography brief, English
    assert 'The ## References section must list' in en
    assert "Biographie" not in en                    # no French titles leak
    assert "français" not in en.lower()

    fr = build_prompt(entity, "Throne of Glass",
                      sections=["infobox", "biography", "personality", "references"])
    assert "Write ALL content in French" in fr
    assert "## Biographie" in fr                      # French default preserved
    assert "Qui est ce personnage" in fr


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
    entity = {"canonical_name": "Brullo", "importance": "secondary", "type": "PERSON"}
    page = make_stub_page(entity, insufficient_data=True)
    assert page.get("_insufficient_data") is True
    assert "_failed" not in page


def test_make_stub_page_default_sets_no_flags():
    """make_stub_page() with no flags must set neither _failed nor _insufficient_data."""
    entity = {"canonical_name": "Brullo", "importance": "secondary", "type": "PERSON"}
    page = make_stub_page(entity)
    assert "_failed" not in page
    assert "_insufficient_data" not in page


def test_run_generation_for_entity_sets_insufficient_data_when_no_context(tmp_path):
    """When context_by_chapter is empty, _run_generation_for_entity must return _insufficient_data stub."""
    entity = {
        "canonical_name": "Brullo",
        "importance": "secondary",
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
        "importance": "secondary",
        "entity_type": "PERSON",
        "infobox_fields": {},
        "content": "## Biographie\n\nPersonnage mineur.",
    })
    entity = {"canonical_name": "Brullo", "importance": "secondary", "type": "PERSON"}
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


# --- STU-318: identity repair helpers ---

def _verin_entity():
    return {
        "canonical_name": "Verin",
        "type": "PERSON",
        "aliases": ["Verin", "Lord Verin"],
    }


def test_nom_matches_identity_true_for_partial_canonical():
    entity = {"canonical_name": "Nehemia Ytger", "type": "PERSON", "aliases": []}
    assert _nom_matches_identity("Nehemia", entity) is True


def test_nom_matches_identity_true_for_known_alias():
    entity = {"canonical_name": "Chaol", "type": "PERSON",
              "aliases": ["Captain Westfall", "Chaol Westfall"]}
    assert _nom_matches_identity("Captain Westfall", entity) is True


def test_nom_matches_identity_false_for_swapped_name():
    assert _nom_matches_identity("Kaltain", _verin_entity()) is False


def test_nom_matches_identity_true_for_empty_nom():
    assert _nom_matches_identity("", _verin_entity()) is True


def test_force_correct_identity_rewrites_swapped_nom():
    page = {"infobox_fields": {"nom": "Kaltain", "rôle": "Dame de la cour"},
            "content": "## Biographie\n\nTexte."}
    changed = _force_correct_identity(page, _verin_entity())
    assert changed is True
    assert page["infobox_fields"]["nom"] == "Verin"
    assert page["_identity_corrected"] is True


def test_force_correct_identity_noop_when_clean():
    page = {"infobox_fields": {"nom": "Verin"}, "content": "x"}
    changed = _force_correct_identity(page, _verin_entity())
    assert changed is False
    assert "_identity_corrected" not in page


def test_force_correct_identity_strips_sibling_swapped_alias():
    page = {"infobox_fields": {"nom": "Verin", "alias": "Kaltain, Le Fléau"},
            "content": "x"}
    changed = _force_correct_identity(page, _verin_entity(),
                                      sibling_canonicals={"Kaltain Rompier"})
    assert changed is True
    assert page["infobox_fields"]["alias"] == "Le Fléau"


def test_force_correct_identity_keeps_own_alias_even_if_sibling_token_overlaps():
    entity = {"canonical_name": "Kaltain Rompier", "type": "PERSON",
              "aliases": ["Kaltain", "Kaltain Rompier"]}
    page = {"infobox_fields": {"nom": "Kaltain Rompier", "alias": "Kaltain"},
            "content": "x"}
    changed = _force_correct_identity(page, entity, sibling_canonicals={"Kaltain Rompier"})
    assert page["infobox_fields"]["alias"] == "Kaltain"
    assert changed is False


# --- STU-318: recovery + force-correct wiring ---

def _verin_entity_ctx():
    return {
        "canonical_name": "Verin",
        "importance": "secondary",
        "type": "PERSON",
        "aliases": ["Verin", "Lord Verin"],
        "context_by_chapter": {"ch01": ["Verin entre dans la cour."]},
    }


def test_force_correct_on_success_path_keeps_page(monkeypatch, tmp_path):
    def fake_runner(**kwargs):
        return {
            "title": "Verin",
            "importance": "secondary",
            "entity_type": "PERSON",
            "infobox_fields": {"nom": "Kaltain"},
            "content": "## Biographie\n\nVerin est un lord.",
        }

    monkeypatch.setattr("scripts.generate_wiki_pages._run_wiki_page_item", fake_runner)

    page = _run_generation_for_entity(
        entity=_verin_entity_ctx(),
        book_title="Throne of Glass",
        model="qwen2.5",
        timeout=120,
        sections=["infobox", "biography"],
        max_tokens=800,
        dry_run=False,
        debug_dir=tmp_path / "debug",
        sibling_canonicals={"Kaltain Rompier"},
    )

    assert page.get("_failed") is not True
    assert page["infobox_fields"]["nom"] == "Verin"
    assert page["_identity_corrected"] is True


def test_recovers_and_corrects_on_identity_only_rejection(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "scripts.generate_wiki_pages._run_wiki_page_item",
        lambda **_: {"error": "studio_run_failed", "run_metadata": {"run_id": "r1"}},
    )

    def fake_stage_output(run_id, stage_name):
        if stage_name == "wiki-page-validator":
            return {"valid": False,
                    "errors": ["❌ Infobox 'nom: Kaltain' ne correspond pas à l'entité 'Verin'"]}
        return {
            "title": "Verin",
            "importance": "secondary",
            "entity_type": "PERSON",
            "infobox_fields": {"nom": "Kaltain"},
            "content": "## Biographie\n\nVerin est un lord.",
        }

    monkeypatch.setattr("scripts.generate_wiki_pages.studio_io.load_studio_stage_output", fake_stage_output)

    page = _run_generation_for_entity(
        entity=_verin_entity_ctx(),
        book_title="Throne of Glass",
        model="qwen2.5",
        timeout=120,
        sections=["infobox", "biography"],
        max_tokens=800,
        dry_run=False,
        debug_dir=tmp_path / "debug",
        sibling_canonicals={"Kaltain Rompier"},
    )

    assert page.get("_failed") is not True
    assert page["infobox_fields"]["nom"] == "Verin"
    assert page["_identity_corrected"] is True


def test_does_not_recover_on_non_identity_rejection(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "scripts.generate_wiki_pages._run_wiki_page_item",
        lambda **_: {"error": "studio_run_failed", "run_metadata": {"run_id": "r1"}},
    )

    def fake_stage_output(run_id, stage_name):
        if stage_name == "wiki-page-validator":
            return {"valid": False,
                    "errors": ["❌ Nom non ancré dans les extraits source : Yrene"]}
        return {"title": "Verin", "importance": "secondary", "entity_type": "PERSON",
                "infobox_fields": {"nom": "Kaltain"}, "content": "x"}

    monkeypatch.setattr("scripts.generate_wiki_pages.studio_io.load_studio_stage_output", fake_stage_output)

    page = _run_generation_for_entity(
        entity=_verin_entity_ctx(),
        book_title="Throne of Glass",
        model="qwen2.5",
        timeout=120,
        sections=["infobox", "biography"],
        max_tokens=800,
        dry_run=False,
        debug_dir=tmp_path / "debug",
        sibling_canonicals={"Kaltain Rompier"},
    )

    assert page.get("_failed") is True


def test_does_not_recover_when_no_run_id(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "scripts.generate_wiki_pages._run_wiki_page_item",
        lambda **_: {"error": "studio_run_timeout", "run_metadata": {}},
    )
    page = _run_generation_for_entity(
        entity=_verin_entity_ctx(),
        book_title="Throne of Glass",
        model="qwen2.5",
        timeout=120,
        sections=["infobox", "biography"],
        max_tokens=800,
        dry_run=False,
        debug_dir=tmp_path / "debug",
    )
    assert page.get("_failed") is True


def test_non_person_success_page_not_touched(monkeypatch, tmp_path):
    entity = {"canonical_name": "Rifthold", "importance": "secondary", "type": "PLACE",
              "aliases": [], "context_by_chapter": {"ch01": ["Rifthold est une cité."]}}

    monkeypatch.setattr(
        "scripts.generate_wiki_pages._run_wiki_page_item",
        lambda **_: {"title": "Rifthold", "importance": "secondary", "entity_type": "PLACE",
                     "infobox_fields": {"nom": "Adarlan"}, "content": "## Description\n\nx"},
    )

    page = _run_generation_for_entity(
        entity=entity,
        book_title="Throne of Glass",
        model="qwen2.5",
        timeout=120,
        sections=["infobox"],
        max_tokens=800,
        dry_run=False,
        debug_dir=tmp_path / "debug",
        sibling_canonicals={"Adarlan"},
    )

    assert page["infobox_fields"]["nom"] == "Adarlan"
    assert "_identity_corrected" not in page


def test_rejection_is_identity_only(monkeypatch):
    monkeypatch.setattr(
        "scripts.generate_wiki_pages.studio_io.load_studio_stage_output",
        lambda run_id, stage: {"errors": ["❌ Infobox 'nom: X' ne correspond pas à l'entité 'Y'"]},
    )
    assert _rejection_is_identity_only("r1") is True


def test_rejection_is_identity_only_false_when_mixed(monkeypatch):
    monkeypatch.setattr(
        "scripts.generate_wiki_pages.studio_io.load_studio_stage_output",
        lambda run_id, stage: {"errors": [
            "❌ Infobox 'nom: X' ne correspond pas à l'entité 'Y'",
            "❌ Nom non ancré dans les extraits source : Z",
        ]},
    )
    assert _rejection_is_identity_only("r1") is False


# --- STU-443 (pas 4): identity safety nets are counted, not silent ---

import scripts.generate_wiki_pages as _gwp


def test_force_identity_trigger_is_counted(monkeypatch, tmp_path):
    _gwp._reset_safety_net_telemetry()
    monkeypatch.setattr(
        "scripts.generate_wiki_pages._run_wiki_page_item",
        lambda **_: {"title": "Verin", "importance": "secondary", "entity_type": "PERSON",
                     "infobox_fields": {"nom": "Kaltain"},
                     "content": "## Biographie\n\nVerin est un lord."},
    )
    _run_generation_for_entity(
        entity=_verin_entity_ctx(), book_title="TOG", model="q", timeout=1,
        sections=["infobox", "biography"], max_tokens=800, dry_run=False,
        debug_dir=tmp_path / "d", sibling_canonicals={"Kaltain Rompier"},
    )
    assert _gwp._SAFETY_NET_TRIGGERS["force_identity"] == 1
    assert _gwp._SAFETY_NET_TRIGGERS["identity_recovery"] == 0


def test_clean_page_records_no_trigger(monkeypatch, tmp_path):
    _gwp._reset_safety_net_telemetry()
    monkeypatch.setattr(
        "scripts.generate_wiki_pages._run_wiki_page_item",
        lambda **_: {"title": "Verin", "importance": "secondary", "entity_type": "PERSON",
                     "infobox_fields": {"nom": "Verin"},
                     "content": "## Biographie\n\nVerin est un lord."},
    )
    _run_generation_for_entity(
        entity=_verin_entity_ctx(), book_title="TOG", model="q", timeout=1,
        sections=["infobox", "biography"], max_tokens=800, dry_run=False,
        debug_dir=tmp_path / "d",
    )
    assert _gwp._SAFETY_NET_TRIGGERS == {"force_identity": 0, "identity_recovery": 0}


def test_identity_recovery_trigger_is_counted(monkeypatch, tmp_path):
    _gwp._reset_safety_net_telemetry()
    monkeypatch.setattr(
        "scripts.generate_wiki_pages._run_wiki_page_item",
        lambda **_: {"error": "studio_run_failed", "run_metadata": {"run_id": "r1"}},
    )

    def fake_stage_output(run_id, stage_name):
        if stage_name == "wiki-page-validator":
            return {"valid": False,
                    "errors": ["❌ Infobox 'nom: Kaltain' ne correspond pas à l'entité 'Verin'"]}
        return {"title": "Verin", "importance": "secondary", "entity_type": "PERSON",
                "infobox_fields": {"nom": "Kaltain"}, "content": "## Biographie\n\nVerin est un lord."}

    monkeypatch.setattr("scripts.generate_wiki_pages.studio_io.load_studio_stage_output", fake_stage_output)
    _run_generation_for_entity(
        entity=_verin_entity_ctx(), book_title="TOG", model="q", timeout=1,
        sections=["infobox", "biography"], max_tokens=800, dry_run=False,
        debug_dir=tmp_path / "d", sibling_canonicals={"Kaltain Rompier"},
    )
    assert _gwp._SAFETY_NET_TRIGGERS["identity_recovery"] == 1


def test_write_identity_telemetry_roundtrip(tmp_path):
    _gwp._reset_safety_net_telemetry()
    _gwp._record_safety_net("force_identity")
    _gwp._write_identity_telemetry(tmp_path)
    written = json.loads((tmp_path / "identity_telemetry.json").read_text())
    assert written == {"safety_net_triggers": {"force_identity": 1, "identity_recovery": 0}}


# --- STU-447: validated wiki_pages.json write boundary ---

from wiki_creator import studio_io
from wiki_creator.types import WikiPage


def test_save_writes_validated_wiki_pages_artifact(tmp_path):
    """Disk wiki_pages.json round-trips through the WikiPage schema, wrapper preserved."""
    output_file = str(tmp_path / "wiki_pages.json")
    pages = [
        {"title": "Celaena", "importance": "principal", "entity_type": "PERSON",
         "books": ["01-throne-of-glass"], "infobox_fields": {"nom": "Celaena"},
         "content": "## Biographie\n\nTexte."},
        # non-PERSON success path carries run_metadata (_execute_wiki_page_item)
        {"title": "Rifthold", "importance": "secondary", "entity_type": "PLACE",
         "infobox_fields": {}, "content": "## Géographie\n\nTexte.",
         "run_metadata": {"command": ["studio"], "run_id": "r1"}},
        # identity-corrected / spoiler-rejected / stub pages omit content/infobox_fields
        {"title": "Kaltain", "importance": "secondary", "entity_type": "PERSON",
         "_identity_corrected": True},
        {"title": "Arobynn", "importance": "principal", "entity_type": "PERSON",
         "_failed": True, "_spoiler_rejected": True},
    ]
    _gwp._save(pages, output_file)

    with open(output_file, encoding="utf-8") as f:
        raw = json.load(f)
    assert list(raw.keys()) == ["pages"]
    validated = studio_io.from_dict(list[WikiPage], raw["pages"])
    assert validated[0].title == "Celaena"
    assert validated[1].run_metadata == {"command": ["studio"], "run_id": "r1"}
    assert validated[2]._identity_corrected is True
    assert validated[3]._failed is True and validated[3]._spoiler_rejected is True


def test_save_rejects_unknown_page_key(tmp_path):
    """An unknown key on a page dict must be rejected before it reaches disk."""
    output_file = str(tmp_path / "wiki_pages.json")
    pages = [
        {"title": "Celaena", "importance": "principal", "entity_type": "PERSON",
         "infobox_fields": {}, "content": "## Bio", "surprise": "unexpected"},
    ]
    with pytest.raises(TypeError):
        _gwp._save(pages, output_file)


def test_stray_llm_key_is_dropped_and_does_not_crash_save(tmp_path):
    """A stray top-level key from the LLM must be dropped by parse_response so
    the page still validates through _save (regression: WikiPage(**p) would
    otherwise raise TypeError and brick the run on this + every rerun)."""
    raw = json.dumps({
        "title": "Victor Grandes", "importance": "secondary", "entity_type": "PERSON",
        "infobox_fields": {}, "content": "## Biographie\n\nTexte.",
        "reasoning": "chain-of-thought the model leaked", "sources": ["ch1"],
    })
    page = parse_response(raw, _entity())
    assert "reasoning" not in page and "sources" not in page

    output_file = str(tmp_path / "wiki_pages.json")
    _gwp._save([page], output_file)  # must not raise
    with open(output_file, encoding="utf-8") as f:
        raw_disk = json.load(f)
    validated = studio_io.from_dict(list[WikiPage], raw_disk["pages"])
    assert validated[0].title == "Victor Grandes"


# --- STU-449: generate_pages() public interface, runner-injected (no subprocess) ---


class _FakeRunner:
    """Fake StudioRunner: returns a canned page per entity, records calls, and
    never shells out. Proves generate_pages() is testable without a subprocess."""

    def __init__(self):
        self.run_calls = []

    def run_item(self, item_input, entity, timeout):
        self.run_calls.append(entity["canonical_name"])
        return {
            "title": entity["canonical_name"],
            "importance": entity.get("importance", ""),
            "entity_type": entity.get("type", ""),
            "infobox_fields": {},
            "content": f"## Description\n\n{entity['canonical_name']} est un lieu.",
            "run_metadata": {},
        }

    def load_stage_output(self, run_id, stage):  # pragma: no cover - unused here
        return None


def _place_batch():
    entity = {
        "canonical_name": "Rifthold",
        "importance": "secondary",
        "type": "PLACE",
        "context_by_chapter": {"C01": ["Rifthold, la capitale."]},
    }
    return [("batch_00.json", {"batch_id": "batch_00", "entities": [entity]})]


def _config(tmp_path) -> GenerationConfig:
    return GenerationConfig(
        book_title="Mon Livre",
        generation_cfg={},
        output_file=str(tmp_path / "wiki_pages.json"),
        debug_dir=tmp_path / "debug",
    )


def test_generate_pages_uses_runner_and_saves(tmp_path):
    runner = _FakeRunner()
    pages = generate_pages(_place_batch(), _config(tmp_path), runner)

    assert runner.run_calls == ["Rifthold"]
    assert [p["title"] for p in pages] == ["Rifthold"]
    assert "Rifthold est un lieu." in pages[0]["content"]

    saved = json.loads((tmp_path / "wiki_pages.json").read_text(encoding="utf-8"))
    assert [p["title"] for p in saved["pages"]] == ["Rifthold"]


def test_generate_pages_dry_run_skips_runner(tmp_path):
    runner = _FakeRunner()
    config = _config(tmp_path)
    config.dry_run = True
    pages = generate_pages(_place_batch(), config, runner)

    assert runner.run_calls == []
    assert [p["title"] for p in pages] == ["Rifthold"]


def test_generate_pages_resumes_completed_pages(tmp_path):
    output_file = tmp_path / "wiki_pages.json"
    output_file.write_text(
        json.dumps({"pages": [{"title": "Rifthold", "importance": "secondary",
                                "entity_type": "PLACE", "content": "## Description\n\nDéjà fait."}]}),
        encoding="utf-8",
    )
    runner = _FakeRunner()
    pages = generate_pages(_place_batch(), _config(tmp_path), runner)

    assert runner.run_calls == []  # already-done page not regenerated
    assert [p["title"] for p in pages] == ["Rifthold"]
    assert "Déjà fait." in pages[0]["content"]


# --- STU-497: small-dataset subset re-run (--entities / --force) ---


def _named_place_batch(name):
    entity = {
        "canonical_name": name,
        "importance": "secondary",
        "type": "PLACE",
        "context_by_chapter": {"C01": [f"{name}."]},
    }
    return [("batch_00.json", {"batch_id": "batch_00", "entities": [entity]})]


def _seed_pages(output_file, titles):
    output_file.write_text(
        json.dumps({"pages": [
            {"title": t, "importance": "secondary", "entity_type": "PLACE",
             "content": f"## Description\n\nPage originale de {t}."}
            for t in titles
        ]}),
        encoding="utf-8",
    )


def test_generate_pages_force_regenerates_only_target_preserves_others(tmp_path):
    output_file = tmp_path / "wiki_pages.json"
    _seed_pages(output_file, ["Rifthold", "Endovier", "Orynth"])
    runner = _FakeRunner()
    config = _config(tmp_path)
    config.force = True

    pages = generate_pages(_named_place_batch("Rifthold"), config, runner)

    assert runner.run_calls == ["Rifthold"]  # only the target regenerated

    by_title = {p["title"]: p for p in pages}
    assert set(by_title) == {"Rifthold", "Endovier", "Orynth"}
    # target replaced by the runner's fresh output
    assert "Rifthold est un lieu." in by_title["Rifthold"]["content"]
    # untargeted pages preserved verbatim from the seed
    assert by_title["Endovier"]["content"] == "## Description\n\nPage originale de Endovier."
    assert by_title["Orynth"]["content"] == "## Description\n\nPage originale de Orynth."

    saved = json.loads(output_file.read_text(encoding="utf-8"))
    assert {p["title"] for p in saved["pages"]} == {"Rifthold", "Endovier", "Orynth"}


def test_generate_pages_without_force_skips_already_done_target(tmp_path):
    output_file = tmp_path / "wiki_pages.json"
    _seed_pages(output_file, ["Rifthold", "Endovier"])
    runner = _FakeRunner()

    pages = generate_pages(_named_place_batch("Rifthold"), _config(tmp_path), runner)

    assert runner.run_calls == []  # already done, not regenerated without --force
    by_title = {p["title"]: p for p in pages}
    assert by_title["Rifthold"]["content"] == "## Description\n\nPage originale de Rifthold."


def test_load_batch_files_entity_filter_is_case_insensitive(tmp_path):
    d = tmp_path / "wiki_inputs"
    d.mkdir()
    (d / "batch_00.json").write_text(
        json.dumps({"batch_id": "b0", "entities": [
            {"canonical_name": "Celaena Sardothien", "importance": "principal"},
            {"canonical_name": "Dorian", "importance": "principal"},
        ]}),
        encoding="utf-8",
    )

    batches = load_batch_files(str(d), None, ["celaena sardothien"])

    names = [e["canonical_name"] for _, b in batches for e in b["entities"]]
    assert names == ["Celaena Sardothien"]


def test_load_batch_files_entity_and_importance_filters_are_anded(tmp_path):
    d = tmp_path / "wiki_inputs"
    d.mkdir()
    (d / "batch_00.json").write_text(
        json.dumps({"batch_id": "b0", "entities": [
            {"canonical_name": "Celaena Sardothien", "importance": "principal"},
            {"canonical_name": "Brullo", "importance": "figurant"},
        ]}),
        encoding="utf-8",
    )

    # name matches Brullo but importance filter excludes figurant → empty
    batches = load_batch_files(str(d), ["principal"], ["Brullo"])

    assert batches == []
