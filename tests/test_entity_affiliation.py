"""STU-551/753: affiliation is the faction a character belongs to at the end
of the tome.

Since STU-753 the classifier searches the book itself instead of receiving a
pre-selected snippet pack: one agentic call per PERSON entity, fanned out by
the engine's map stage, instead of one call over the whole roster.
"""
import io
import json
from pathlib import Path

import pytest
import yaml

from scripts.entity_affiliation import resolve_verdicts
from scripts.wiki_preparation import build_entity_bundle, load_affiliation_verdicts
from scripts.generate_wiki_pages import _extracted_fact_value
from wiki_creator.entity_affiliation import entity_rows, parse_affiliation_verdict
from wiki_creator.registry import EntityRecord, Mention, Registry

AGENT_YAML = Path(__file__).resolve().parents[1] / ".studio" / "agents" / "entity-affiliation.agent.yaml"


def test_prompt_declares_the_search_tool():
    agent = yaml.safe_load(AGENT_YAML.read_text(encoding="utf-8"))
    assert agent["tools"] == ["book-search-search_book"]


def test_entity_rows_carries_name_and_sorted_aliases():
    entities = [{"canonical_name": "Eragon", "aliases": ["z-alias", "Shadeslayer"]}]
    [row] = entity_rows(entities)
    assert row == {"name": "Eragon", "aliases": ["Shadeslayer", "z-alias"]}


# --- parse_affiliation_verdict ----------------------------------------------

BOOK_TEXT = "Eragon joined the Varden. Eragon rode north."


def _parse(payload, name="Eragon", aliases=(), book_text=BOOK_TEXT):
    return parse_affiliation_verdict(payload, name, list(aliases), book_text)


def test_a_verdict_must_quote_book_text():
    """STU-539's rule. These novels are in the model's training data: without it,
    a verdict from its memory of the plot and one from this run's text are
    indistinguishable afterwards."""
    verdict = _parse({"affiliation": "Varden", "quote": "Eragon was crowned king of the Varden."})
    assert verdict is None


def test_a_quote_real_but_about_someone_else_is_rejected():
    text = "Brom joined the Varden long ago."
    verdict = _parse({"affiliation": "Varden", "quote": "Brom joined the Varden long ago."}, book_text=text)
    assert verdict is None


def test_a_quote_naming_an_alias_is_accepted():
    text = "Shadeslayer joined the Varden that night."
    verdict = _parse(
        {"affiliation": "Varden", "quote": "Shadeslayer joined the Varden that night."},
        aliases=["Shadeslayer"], book_text=text,
    )
    assert verdict["affiliation"] == "Varden"


def test_the_value_must_appear_in_the_quote():
    """THE LOAD-BEARING RULE (STU-551). `status` returns an enum member, so
    verifying the quote verifies the verdict. `affiliation` returns a NAME, so
    the model can quote a real sentence and infer the wrong faction from it."""
    verdict = _parse({"affiliation": "Empire", "quote": "Eragon joined the Varden."})
    assert verdict is None


def test_a_grounded_verdict_survives():
    verdict = _parse({"affiliation": "Varden", "quote": "Eragon joined the Varden."})
    assert verdict == {"affiliation": "Varden", "quote": "Eragon joined the Varden."}


def test_typographic_quotes_match_a_straight_quoted_reply():
    text = "“I joined the Varden,” said Eragon."
    verdict = _parse(
        {"affiliation": "Varden", "quote": '"I joined the Varden," said Eragon.'}, book_text=text
    )
    assert verdict["affiliation"] == "Varden"


@pytest.mark.parametrize("payload", ["not json", None, {}, {"affiliation": "a string"}, 42])
def test_unparseable_payloads_verdict_nothing(payload):
    assert _parse(payload) is None


def test_an_empty_affiliation_is_rejected():
    assert _parse({"affiliation": "", "quote": "Eragon joined the Varden."}) is None


def test_the_value_must_match_whole_tokens_not_a_substring():
    """STU-541's rule: `beaver` inside `Beavers` is an accident of spelling. A
    raw substring test accepts `Order` off "he ordered the villagers", inventing
    a faction out of a verb."""
    text = "Roran betrayed nothing as he ordered the villagers to march."
    quote = "Roran betrayed nothing as he ordered the villagers to march."
    for invented in ("Order", "a", "der"):
        verdict = _parse({"affiliation": invented, "quote": quote}, name="Roran", book_text=text)
        assert verdict is None, f"{invented!r} was accepted out of 'ordered'"


def test_a_multi_word_faction_must_appear_contiguously():
    text = "Angela joined Du Vrangr Gata that spring."
    quote = "Angela joined Du Vrangr Gata that spring."
    assert _parse(
        {"affiliation": "Du Vrangr Gata", "quote": quote}, name="Angela", book_text=text
    )["affiliation"] == "Du Vrangr Gata"
    assert _parse(
        {"affiliation": "Du Gata", "quote": quote}, name="Angela", book_text=text
    ) is None


# --- resolve_verdicts (post-script fold over the map fan-out) --------------


def _rows():
    return entity_rows([{"canonical_name": "Eragon", "aliases": []}, {"canonical_name": "Murtagh", "aliases": []}])


def test_a_missing_map_output_omits_the_slot_for_everyone():
    """A false affiliation puts a character in the wrong army on a page nobody
    will reread; an absent one says nothing."""
    assert resolve_verdicts(_rows(), None, BOOK_TEXT) == {}


def test_resolve_folds_per_item_results_by_index():
    map_output = {"results": [
        {"index": 0, "status": "success", "output": {"affiliation": "Varden", "quote": "Eragon joined the Varden."}},
        {"index": 1, "status": "success", "output": {"affiliation": "", "quote": ""}},
    ]}
    verdicts = resolve_verdicts(_rows(), map_output, BOOK_TEXT)
    assert verdicts == {"Eragon": {"affiliation": "Varden", "quote": "Eragon joined the Varden."}}


def test_resolve_skips_a_failed_item():
    map_output = {"results": [{"index": 0, "status": "failed"}]}
    assert resolve_verdicts(_rows(), map_output, BOOK_TEXT) == {}


# --- consumers (unaffected by STU-753's retrieval change) ------------------


def test_the_binder_renders_affiliation_from_the_batch_entity():
    assert _extracted_fact_value({"affiliation": "Varden"}, "affiliation", lang="fr") == "Varden"


def test_an_unstamped_entity_renders_no_affiliation():
    assert _extracted_fact_value({}, "affiliation", lang="fr") is None
    assert _extracted_fact_value({"affiliation": ""}, "affiliation", lang="fr") is None


def test_preparation_stamps_affiliation_onto_the_batch_entity():
    bundle = build_entity_bundle(
        entity={"canonical_name": "Eragon", "type": "PERSON", "importance": "principal"},
        relationships=[],
        persons={}, places={}, orgs={}, events={},
        entities_by_name={},
        affiliation_verdicts={"Eragon": {"affiliation": "Varden", "quote": "x"}},
    )
    assert bundle["affiliation"] == "Varden"


def test_preparation_stamps_nothing_for_an_undecided_character():
    bundle = build_entity_bundle(
        entity={"canonical_name": "Murtagh", "type": "PERSON", "importance": "secondary"},
        relationships=[],
        persons={}, places={}, orgs={}, events={},
        entities_by_name={},
        affiliation_verdicts={},
    )
    assert bundle["affiliation"] is None


def test_load_affiliation_verdicts_degrades_on_an_absent_artifact(tmp_path):
    assert load_affiliation_verdicts(tmp_path) == {}


def test_person_declares_the_affiliation_slot():
    from wiki_creator.page_templates import load_base_template
    person = load_base_template()["entity_types"]["PERSON"]
    slots = {s["token"]: s for s in person["infobox"]}
    assert slots["affiliation"]["provenance"] == "extracted-fact"
    assert slots["affiliation"]["obligation"] == "OPT"


def test_an_undecided_affiliation_clears_the_writers_guess():
    import scripts.generate_wiki_pages as gwp

    entity = {"canonical_name": "Eragon", "type": "PERSON", "importance": "principal"}
    page = {"infobox_fields": {"affiliation": "Les Varden"}}
    gwp._bind_batch_fields(page, entity, {})
    assert "affiliation" not in page["infobox_fields"]


def test_a_decided_affiliation_overwrites_the_writers_guess():
    import scripts.generate_wiki_pages as gwp

    entity = {
        "canonical_name": "Brom", "type": "PERSON", "importance": "principal",
        "affiliation": "Varden",
    }
    page = {"infobox_fields": {"affiliation": "Les Ombres"}}
    gwp._bind_batch_fields(page, entity, {})
    assert page["infobox_fields"]["affiliation"] == "Varden"


# --- pre stage (gating + item shape) ---------------------------------------


def _pre_setup(tmp_path):
    books_dir = tmp_path / "author" / "series" / "books"
    books_dir.mkdir(parents=True)
    epub = books_dir / "01-a-book.epub"
    epub.write_bytes(b"not a real epub - only the path is used")
    processing = tmp_path / "author" / "series" / "processing_output" / "01-a-book"
    processing.mkdir(parents=True)
    return epub, processing


def _run_pre(monkeypatch, epub):
    import scripts.entity_affiliation_pre as pre

    payload = {"additional_context": yaml.safe_dump(
        {"title": "Test", "language": "en", "file_path": str(epub)}
    )}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    pre.main()
    return json.loads(out.getvalue())


def test_pre_skips_with_no_registry(tmp_path, monkeypatch):
    epub, processing = _pre_setup(tmp_path)
    stale = processing / "entity_affiliation.json"
    stale.write_text("{}", encoding="utf-8")
    result = _run_pre(monkeypatch, epub)
    assert result["needs_verdict"] is False
    assert not stale.exists()


def test_pre_emits_one_item_per_person_with_context(tmp_path, monkeypatch):
    epub, processing = _pre_setup(tmp_path)
    registry = Registry(entities=[
        EntityRecord(
            entity_id="eragon", canonical_name="Eragon", entity_type="PERSON",
            aliases=["Eragon"],
            mentions=[Mention(surface="Eragon", chapter_id="c1", context="Eragon joined the Varden.")],
        ),
        EntityRecord(
            entity_id="ghost", canonical_name="Ghost", entity_type="PERSON",
            aliases=["Ghost"], mentions=[],
        ),
    ])
    (processing / "registry.json").write_text(json.dumps(registry.to_dict()), encoding="utf-8")
    (processing / "chapters.json").write_text(
        json.dumps({"chapters": {"c1": "Eragon joined the Varden."}}), encoding="utf-8"
    )
    result = _run_pre(monkeypatch, epub)
    assert result["needs_verdict"] is True
    names = {e["name"] for e in result["entities"]}
    assert names == {"Eragon"}
    assert result["prompt_fingerprint"]
