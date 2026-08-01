"""STU-488/753: per-tome entity status (the `status` infobox slot).

Since STU-753 the classifier searches the book itself instead of receiving a
pre-selected snippet pack: one agentic call per PERSON entity, fanned out by
the engine's map stage, instead of one call over the whole roster.
"""
import io
import json
import re
from pathlib import Path

import yaml

from scripts.entity_status import contexts_by_entity, resolve_verdicts
from scripts.wiki_preparation import load_status_verdicts
from wiki_creator.entity_status import (
    DEFAULT_STATUS,
    STATUS_VALUES,
    build_name_index,
    death_label,
    entity_rows,
    parse_status_verdict,
    status_label,
)
from wiki_creator.registry import EntityRecord, Mention, Registry

STATUS_PROMPT = (
    Path(__file__).resolve().parents[1]
    / ".studio"
    / "agents"
    / "entity-status.agent.yaml"
)


def test_status_enum_is_the_fandom_vocabulary():
    assert STATUS_VALUES == ("alive", "deceased", "missing", "unknown", "undead")
    assert DEFAULT_STATUS == "unknown"


def _prompt_status_mentions() -> set[str]:
    """Status tokens the prompt names as the values it may return.

    Mechanical, never a hand-kept list — a second copy of the enum is the drift
    STU-548 closed on the relationship prompt, and it would rot the same way.
    """
    prompt = yaml.safe_load(STATUS_PROMPT.read_text(encoding="utf-8"))["system_prompt"]
    listed = re.search(r"exactly one of:\s*(.+)", prompt)
    assert listed, "prompt no longer states an `exactly one of:` status roster"
    return {token.strip() for token in listed.group(1).split(",")}


def test_prompt_names_only_declared_status_values():
    """The prompt is a second consumer of the status enum after
    `parse_status_verdict`, which drops any status outside `STATUS_VALUES`."""
    mentions = _prompt_status_mentions()
    assert mentions, "extracted no status tokens from the prompt — the instruction grammar moved"
    undeclared = mentions - set(STATUS_VALUES)
    assert undeclared == set(), f"prompt names statuses absent from STATUS_VALUES: {sorted(undeclared)}"


def test_prompt_declares_the_search_tool():
    agent = yaml.safe_load(STATUS_PROMPT.read_text(encoding="utf-8"))
    assert agent["tools"] == ["book-search-search_book"]


def test_entity_rows_carries_name_and_sorted_aliases():
    entities = [{"canonical_name": "Brom", "aliases": ["z-alias", "a-alias"]}]
    [row] = entity_rows(entities)
    assert row == {"name": "Brom", "aliases": ["a-alias", "z-alias"]}


def test_entity_rows_drops_blank_aliases():
    entities = [{"canonical_name": "Brom", "aliases": ["", None, "Storyteller"]}]
    [row] = entity_rows(entities)
    assert row["aliases"] == ["Storyteller"]


# --- parse_status_verdict --------------------------------------------------

BOOK_TEXT = (
    "Eragon rode north with Brom.\n"
    "Brom's chest rose one last time, and then was still.\n"
    "Eragon rode on alone."
)
BROM_QUOTE = "Brom's chest rose one last time, and then was still."


def _verdict(**overrides):
    entry = {"status": "deceased", "quote": BROM_QUOTE}
    entry.update(overrides)
    return entry


def _parse(payload, name="Brom", aliases=(), book_text=BOOK_TEXT):
    return parse_status_verdict(payload, name, list(aliases), book_text, _index())


def test_a_verified_deceased_verdict_is_accepted():
    assert _parse(_verdict())["status"] == "deceased"


def test_a_json_string_payload_is_parsed():
    assert _parse(json.dumps(_verdict()))["status"] == "deceased"


def test_a_quote_not_verbatim_in_the_book_is_rejected():
    # The model has read this novel. Without the check, a verdict from its
    # memory of the plot and one from this run's text are indistinguishable.
    assert _parse(_verdict(quote="Brom died at Farthen Dur.")) is None


def test_a_quote_real_but_about_someone_else_is_rejected():
    # The quote is real book text, but it never names Eragon — the free-search
    # analogue of "the snippets shown for that entity" (STU-753).
    assert _parse(_verdict(status="alive", quote="Brom's chest rose one last time, and then was still."), name="Eragon") is None


def test_a_quote_naming_an_alias_is_accepted():
    text = "The old Rider they called Storyteller fell silent forever."
    assert _parse(
        _verdict(quote="The old Rider they called Storyteller fell silent forever."),
        name="Brom", aliases=["Storyteller"], book_text=text,
    )["status"] == "deceased"


def test_quote_matching_ignores_whitespace_and_case():
    assert _parse(_verdict(quote="  BROM'S CHEST ROSE   one last time,\nand then was still. "))["status"] == "deceased"


def test_curly_apostrophe_folds_to_straight():
    text = "Brom’s hand went still."
    assert _parse(_verdict(quote="Brom's hand went still."), book_text=text)["status"] == "deceased"


def test_ellipsis_folds_to_three_dots():
    text = "Brom fell silent… then died."
    assert _parse(_verdict(quote="Brom fell silent... then died."), book_text=text)["status"] == "deceased"


def test_em_dash_folds_to_hyphen():
    text = "Brom—dying—spoke once more."
    assert _parse(_verdict(quote="Brom-dying-spoke once more."), book_text=text)["status"] == "deceased"


def test_folding_does_not_relax_the_check_for_invented_text():
    text = "Brom’s hand went still."
    assert _parse(_verdict(quote="Brom's heart stopped beating."), book_text=text) is None


def test_a_status_outside_the_enum_is_rejected():
    assert _parse(_verdict(status="martyred")) is None


def test_an_explicit_unknown_verdict_is_dropped_not_stored():
    assert _parse(_verdict(status="unknown", quote=BROM_QUOTE)) is None


def test_an_empty_quote_is_rejected():
    assert _parse(_verdict(quote="")) is None


def test_alive_needs_a_quote_too():
    text = "Eragon rode on alone, still very much alive."
    verdict = _parse({"status": "alive", "quote": "Eragon rode on alone, still very much alive."}, name="Eragon", book_text=text)
    assert verdict["status"] == "alive"


def test_unparseable_payloads_verdict_nothing():
    for payload in ["not json", None, [], {"merge": []}, 42, {"quote": BROM_QUOTE}]:
        assert _parse(payload) is None


# --- contexts_by_entity ------------------------------------------------------


def _registry():
    return Registry(entities=[
        EntityRecord(
            entity_id="brom",
            canonical_name="Brom",
            entity_type="PERSON",
            aliases=["the storyteller"],
            mentions=[
                Mention(surface="Brom", chapter_id="chapter_38", context=BROM_QUOTE),
                Mention(surface="Brom", chapter_id="chapter_2", context=None),
                Mention(surface="Brom", chapter_id="chapter_2", context="   "),
            ],
        ),
        EntityRecord(
            entity_id="tronjheim",
            canonical_name="Tronjheim",
            entity_type="PLACE",
            mentions=[Mention(surface="Tronjheim", chapter_id="chapter_40", context="The city stood.")],
        ),
    ])


def test_contexts_marks_persons_with_a_real_mention():
    assert "Brom" in contexts_by_entity(_registry())


def test_non_person_entities_have_no_context():
    # `status` is declared on PERSON only; no other type has the slot.
    assert "Tronjheim" not in contexts_by_entity(_registry())


# --- resolve_verdicts (post-script fold over the map fan-out) --------------


def _rows():
    return entity_rows([{"canonical_name": "Brom", "aliases": []}, {"canonical_name": "Eragon", "aliases": []}])


def _map_output(*items):
    return {"results": [{"index": i, "status": "success", "output": out} for i, out in enumerate(items)]}


def test_a_missing_map_output_leaves_the_roster_unknown():
    assert resolve_verdicts(_rows(), None, BOOK_TEXT, _index()) == {}


def test_resolve_folds_per_item_results_by_index():
    verdicts = resolve_verdicts(
        _rows(),
        _map_output({"status": "deceased", "quote": BROM_QUOTE}, {"status": "unknown"}),
        BOOK_TEXT,
        _index(),
    )
    assert verdicts == {"Brom": {"status": "deceased", "quote": BROM_QUOTE}}


def test_resolve_skips_a_failed_item_but_keeps_the_rest():
    map_output = {
        "results": [
            {"index": 0, "status": "failed"},
            {"index": 1, "status": "success", "output": {
                "status": "alive", "quote": "Eragon rode on alone.",
            }},
        ]
    }
    text = "Brom died.\nEragon rode on alone."
    verdicts = resolve_verdicts(_rows(), map_output, text, _index())
    assert "Brom" not in verdicts
    assert verdicts["Eragon"]["status"] == "alive"


def test_resolve_skips_a_missing_index():
    verdicts = resolve_verdicts(_rows(), {"results": []}, BOOK_TEXT, _index())
    assert verdicts == {}


# --- rendering (unchanged by STU-753) --------------------------------------

from scripts.generate_wiki_pages import _extracted_fact_value
from wiki_creator.page_templates import (
    load_base_template,
    load_lang_template,
    render_infobox_source,
    shipped_languages,
)


def test_every_enum_value_has_a_label_in_every_shipped_pack():
    for code in shipped_languages():
        chrome = load_lang_template(code)["chrome"]
        for status in STATUS_VALUES:
            assert chrome[f"status_{status}"]


def test_status_label_is_localized():
    assert status_label("deceased", "en") == "Deceased"
    assert status_label("deceased", "fr") == "Décédé"


def test_an_absent_status_renders_the_declared_fallback():
    assert status_label(None, "en") == status_label("unknown", "en")
    assert status_label("", "en") == status_label("unknown", "en")


def test_the_binder_renders_status_from_the_batch_entity():
    entity = {"status": "deceased"}
    assert _extracted_fact_value(entity, "status", lang="fr") == "Décédé"


def test_the_binder_renders_unknown_for_an_unstamped_entity():
    assert _extracted_fact_value({}, "status", lang="en") == status_label("unknown", "en")


def test_titles_still_binds():
    assert _extracted_fact_value({"titles": ["Roi"]}, "titles", lang="fr") == "Roi"


def test_person_declares_the_status_slot():
    person = load_base_template()["entity_types"]["PERSON"]
    slots = {s["token"]: s for s in person["infobox"]}
    assert slots["status"]["provenance"] == "extracted-fact"


def test_person_declares_the_death_slot_as_optional():
    person = load_base_template()["entity_types"]["PERSON"]
    slots = {s["token"]: s for s in person["infobox"]}
    assert slots["death"]["provenance"] == "extracted-fact"
    assert slots["death"]["obligation"] == "OPT"
    assert "{{{death|}}}" in render_infobox_source("PERSON", "fr")


def test_the_stage_is_wired_before_wiki_preparation():
    pipeline = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / ".studio" / "pipelines" / "wiki-preparation.pipeline.yaml")
        .read_text(encoding="utf-8")
    )
    scripts = [s.get("script", "") for s in pipeline["stages"] if isinstance(s, dict)]
    status_idx = next(i for i, s in enumerate(scripts) if "entity_status.py" in s)
    prep_idx = next(i for i, s in enumerate(scripts) if "wiki_preparation.py" in s)
    assert status_idx < prep_idx
    calls = [s.get("call") for s in pipeline["stages"] if isinstance(s, dict)]
    assert "entity-status-verdict" in calls


def test_load_status_verdicts_reads_the_artifact(tmp_path):
    (tmp_path / "entity_status.json").write_text(
        json.dumps({"version": 3, "verdicts": {"Brom": {"status": "deceased", "quote": BROM_QUOTE}}}),
        encoding="utf-8",
    )
    verdicts = load_status_verdicts(tmp_path)
    assert verdicts["Brom"]["status"] == "deceased"


def test_a_missing_or_corrupt_status_artifact_leaves_every_entity_unknown(tmp_path):
    assert load_status_verdicts(tmp_path) == {}
    (tmp_path / "entity_status.json").write_text("{not json", encoding="utf-8")
    assert load_status_verdicts(tmp_path) == {}


def test_death_label_renders_both_fields():
    assert death_label("Durza", "Farthen Dûr", "fr") == "Tué par Durza à Farthen Dûr"
    assert death_label("Durza", "Farthen Dûr", "en") == "Killed by Durza at Farthen Dûr"


def test_death_label_renders_the_agent_alone():
    assert death_label("Durza", None, "fr") == "Tué par Durza"


def test_death_label_renders_the_place_alone():
    assert death_label(None, "Terím", "fr") == "Mort à Terím"


def test_death_label_is_none_without_a_field():
    assert death_label(None, None, "fr") is None
    assert death_label("", "  ", "fr") is None


def test_death_label_falls_back_to_english_for_an_unknown_lang():
    assert death_label("Durza", None, "de") == "Killed by Durza"


# --- agent/place grounding (unchanged mechanics — the quote is still the
# grounding surface; only where the quote itself came from changed) --------


def _index():
    return build_name_index(
        [
            {"entity_type": "PERSON", "canonical_name": "Durza", "aliases": []},
            {"entity_type": "PERSON", "canonical_name": "Brom", "aliases": []},
            {"entity_type": "PERSON", "canonical_name": "Chaol Westfall", "aliases": ["Captain Westfall"]},
            # A spaCy-mistyped common noun kept on the PERSON roster (STU-537):
            # "Son" sits inside "per-son" with no relation to it.
            {"entity_type": "PERSON", "canonical_name": "Son", "aliases": []},
            {"entity_type": "PLACE", "canonical_name": "Farthen Dûr", "aliases": []},
        ]
    )


def _gated_verdict(entry, quote):
    return parse_status_verdict(entry, "Brom", [], quote, _index())


def test_agent_and_place_survive_all_three_gates():
    quote = "Durza's blade took Brom in the side at Farthen Dûr"
    verdict = _gated_verdict(
        {"status": "deceased", "quote": quote, "agent": "Durza", "place": "Farthen Dûr"}, quote
    )
    assert verdict == {"status": "deceased", "quote": quote, "agent": "Durza", "place": "Farthen Dûr"}


def test_a_name_absent_from_the_quote_is_dropped():
    quote = "Durza's blade took Brom in the side"
    verdict = _gated_verdict(
        {"status": "deceased", "quote": quote, "agent": "Durza", "place": "Farthen Dûr"}, quote
    )
    assert verdict["agent"] == "Durza"
    assert "place" not in verdict


def test_a_name_off_the_roster_is_dropped():
    quote = "Galbatorix's blade took Brom in the side"
    verdict = _gated_verdict({"status": "deceased", "quote": quote, "agent": "Galbatorix"}, quote)
    assert "agent" not in verdict


def test_the_roster_is_type_scoped():
    quote = "Brom died with Durza"
    verdict = _gated_verdict({"status": "deceased", "quote": quote, "place": "Durza"}, quote)
    assert "place" not in verdict


def test_an_alias_renders_the_canonical_name():
    quote = "Captain Westfall struck Brom down"
    verdict = _gated_verdict({"status": "deceased", "quote": quote, "agent": "Captain Westfall"}, quote)
    assert verdict["agent"] == "Chaol Westfall"


def test_only_a_deceased_verdict_carries_a_circumstance():
    quote = "Durza hunted Brom through Farthen Dûr"
    verdict = _gated_verdict(
        {"status": "missing", "quote": quote, "agent": "Durza", "place": "Farthen Dûr"}, quote
    )
    assert verdict == {"status": "missing", "quote": quote}


def test_a_dropped_field_never_drops_the_verdict():
    quote = "Brom is dead"
    verdict = _gated_verdict(
        {"status": "deceased", "quote": quote, "agent": "Galbatorix", "place": "Urû'baen"}, quote
    )
    assert verdict == {"status": "deceased", "quote": quote}


def test_the_name_index_folds_typography_and_case():
    index = build_name_index([{"entity_type": "PLACE", "canonical_name": "Farthen Dûr", "aliases": []}])
    assert index["PLACE"]["farthen dûr"] == "Farthen Dûr"


def test_the_name_index_ignores_types_that_are_not_person_or_place():
    index = build_name_index([{"entity_type": "ORG", "canonical_name": "Varden", "aliases": []}])
    assert index == {"PERSON": {}, "PLACE": {}}


def test_an_agent_that_is_only_a_substring_of_a_quote_word_is_dropped():
    quote = "Brom's chest rose one last time, and then was still, a person no more"
    verdict = _gated_verdict({"status": "deceased", "quote": quote, "agent": "Son"}, quote)
    assert "agent" not in verdict


def test_a_multiword_agent_still_grounds_after_the_boundary_fix():
    quote = "Durza's blade took Brom in the side at Farthen Dûr"
    verdict = _gated_verdict({"status": "deceased", "quote": quote, "place": "Farthen Dûr"}, quote)
    assert verdict["place"] == "Farthen Dûr"


def test_an_agent_equal_to_the_dead_character_is_dropped():
    quote = "Brom is dead"
    verdict = _gated_verdict({"status": "deceased", "quote": quote, "agent": "Brom"}, quote)
    assert verdict == {"status": "deceased", "quote": quote}


def test_the_binder_renders_the_circumstance():
    entity = {"death_agent": "Durza", "death_place": "Farthen Dûr"}
    assert _extracted_fact_value(entity, "death", lang="fr") == "Tué par Durza à Farthen Dûr"


def test_the_binder_omits_the_slot_without_a_circumstance():
    assert _extracted_fact_value({}, "death", lang="fr") is None
    assert _extracted_fact_value({"status": "alive"}, "death", lang="fr") is None


def test_wiki_preparation_stamps_the_circumstance_onto_the_batch_entity():
    from scripts.wiki_preparation import build_entity_bundle

    entity = {"canonical_name": "Brom", "type": "PERSON", "importance": "principal"}
    verdicts = {"Brom": {"status": "deceased", "quote": "x", "agent": "Durza", "place": "Farthen Dûr"}}
    bundle = build_entity_bundle(
        entity, [], {}, {}, {}, {}, {"Brom": entity},
        status_verdicts=verdicts,
    )
    assert bundle["death_agent"] == "Durza"
    assert bundle["death_place"] == "Farthen Dûr"


def test_wiki_preparation_stamps_none_for_a_character_with_no_circumstance():
    from scripts.wiki_preparation import build_entity_bundle

    entity = {"canonical_name": "Eragon", "type": "PERSON", "importance": "principal"}
    bundle = build_entity_bundle(
        entity, [], {}, {}, {}, {}, {"Eragon": entity},
        status_verdicts={},
    )
    assert bundle["death_agent"] is None
    assert bundle["death_place"] is None


# --- pre stage (gating + item shape) ---------------------------------------


def _pre_setup(tmp_path):
    books_dir = tmp_path / "author" / "series" / "books"
    books_dir.mkdir(parents=True)
    epub = books_dir / "01-a-book.epub"
    epub.write_bytes(b"not a real epub - only the path is used")
    processing = tmp_path / "author" / "series" / "processing_output" / "01-a-book"
    processing.mkdir(parents=True)
    return epub, processing


def _run_pre(monkeypatch, epub, extra_ctx=None):
    import scripts.entity_status_pre as pre

    payload = {"additional_context": yaml.safe_dump(
        {"title": "Test", "language": "en", "file_path": str(epub), **(extra_ctx or {})}
    )}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    pre.main()
    return json.loads(out.getvalue())


def test_pre_skips_with_no_registry(tmp_path, monkeypatch):
    epub, processing = _pre_setup(tmp_path)
    stale = processing / "entity_status.json"
    stale.write_text("{}", encoding="utf-8")
    result = _run_pre(monkeypatch, epub)
    assert result["needs_verdict"] is False
    assert not stale.exists()


def test_pre_emits_one_item_per_person_with_context(tmp_path, monkeypatch):
    epub, processing = _pre_setup(tmp_path)
    registry = Registry(entities=[
        EntityRecord(
            entity_id="brom", canonical_name="Brom", entity_type="PERSON",
            aliases=["Brom"],
            mentions=[Mention(surface="Brom", chapter_id="c1", context=BROM_QUOTE)],
        ),
        EntityRecord(
            entity_id="ghost", canonical_name="Ghost", entity_type="PERSON",
            aliases=["Ghost"], mentions=[],
        ),
    ])
    (processing / "registry.json").write_text(
        json.dumps(registry.to_dict()), encoding="utf-8"
    )
    (processing / "chapters.json").write_text(
        json.dumps({"chapters": {"c1": BROM_QUOTE}}), encoding="utf-8"
    )
    result = _run_pre(monkeypatch, epub)
    assert result["needs_verdict"] is True
    names = {e["name"] for e in result["entities"]}
    assert names == {"Brom"}  # Ghost has no context
    assert result["entities"][0]["book_dir"].endswith("processing_output/01-a-book")
    assert result["prompt_fingerprint"]


def test_pre_skips_without_chapters_json(tmp_path, monkeypatch):
    epub, processing = _pre_setup(tmp_path)
    registry = Registry(entities=[
        EntityRecord(
            entity_id="brom", canonical_name="Brom", entity_type="PERSON",
            aliases=[], mentions=[Mention(surface="Brom", chapter_id="c1", context=BROM_QUOTE)],
        )
    ])
    (processing / "registry.json").write_text(json.dumps(registry.to_dict()), encoding="utf-8")
    result = _run_pre(monkeypatch, epub)
    assert result["needs_verdict"] is False
