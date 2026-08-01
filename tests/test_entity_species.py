"""STU-574/753: species is the race a character IS — a per-character attribute.

Since STU-753 the classifier searches the book itself instead of receiving a
pre-selected snippet pack: one agentic call per PERSON entity, fanned out by
the engine's map stage, instead of one call over the whole roster.
"""
import io
import json
from pathlib import Path

import pytest
import yaml

from scripts.entity_species import resolve_verdicts
from scripts.wiki_preparation import build_entity_bundle, load_species_verdicts
from scripts.generate_wiki_pages import _extracted_fact_value
from wiki_creator.entity_species import entity_rows, parse_species_verdict
from wiki_creator.registry import EntityRecord, Mention, Registry

AGENT_YAML = Path(__file__).resolve().parents[1] / ".studio" / "agents" / "entity-species.agent.yaml"


def test_prompt_declares_the_search_tool():
    agent = yaml.safe_load(AGENT_YAML.read_text(encoding="utf-8"))
    assert agent["tools"] == ["book-search-search_book"]


def test_entity_rows_carries_name_and_sorted_aliases():
    entities = [{"canonical_name": "Arya", "aliases": ["z-alias", "Islanzadí's daughter"]}]
    [row] = entity_rows(entities)
    assert row == {"name": "Arya", "aliases": ["Islanzadí's daughter", "z-alias"]}


# --- parse_species_verdict ---------------------------------------------------

BOOK_TEXT = "Arya was an elf of Ellesméra. Eragon killed the Urgal with one stroke."


def _parse(payload, name="Arya", aliases=(), book_text=BOOK_TEXT):
    return parse_species_verdict(payload, name, list(aliases), book_text)


def test_a_verdict_must_quote_book_text():
    verdict = _parse({"species": "elf", "quote": "Arya, the elven princess, drew her sword."})
    assert verdict is None


def test_the_value_must_appear_in_the_quote():
    verdict = _parse({"species": "human", "quote": "Arya was an elf of Ellesméra."})
    assert verdict is None


def test_a_grounded_verdict_survives():
    verdict = _parse({"species": "elf", "quote": "Arya was an elf of Ellesméra."})
    assert verdict == {"species": "elf", "quote": "Arya was an elf of Ellesméra."}


def test_a_quote_naming_an_alias_is_accepted():
    text = "Islanzadí's daughter was an elf of Ellesméra."
    verdict = _parse(
        {"species": "elf", "quote": "Islanzadí's daughter was an elf of Ellesméra."},
        aliases=["Islanzadí's daughter"], book_text=text,
    )
    assert verdict["species"] == "elf"


def test_a_species_belonging_to_another_character_in_the_sentence_is_rejected():
    """The species-specific trap: "Eragon killed the Urgal" names a species
    that is the VICTIM's, not Eragon's. The quote is real and does name Eragon,
    but the species claimed ("human") is never IN the quote — rule 3 catches
    it regardless of who the sentence is about."""
    verdict = _parse(
        {"species": "human", "quote": "Eragon killed the Urgal with one stroke."}, name="Eragon"
    )
    assert verdict is None


def test_a_quote_real_but_about_someone_else_is_rejected():
    verdict = _parse({"species": "elf", "quote": "Arya was an elf of Ellesméra."}, name="Eragon")
    assert verdict is None


def test_the_value_must_match_whole_tokens_not_a_substring():
    """STU-541's rule: `elf` inside `himself` is an accident of spelling."""
    text = "Roran steadied himself before the human host."
    quote = "Roran steadied himself before the human host."
    verdict = _parse({"species": "elf", "quote": quote}, name="Roran", book_text=text)
    assert verdict is None, "'elf' was accepted out of 'himself'"


def test_typographic_quotes_match_a_straight_quoted_reply():
    text = "“I am an elf,” Arya said."
    verdict = _parse({"species": "elf", "quote": '"I am an elf," Arya said.'}, book_text=text)
    assert verdict["species"] == "elf"


@pytest.mark.parametrize("payload", ["not json", None, {}, {"species": "a string"}, 42])
def test_unparseable_payloads_verdict_nothing(payload):
    assert _parse(payload) is None


def test_an_empty_species_is_rejected():
    assert _parse({"species": "", "quote": "Arya was an elf of Ellesméra."}) is None


# --- resolve_verdicts (post-script fold over the map fan-out) --------------


def _rows():
    return entity_rows([{"canonical_name": "Arya", "aliases": []}, {"canonical_name": "Roran", "aliases": []}])


def test_a_missing_map_output_omits_the_slot_for_everyone():
    assert resolve_verdicts(_rows(), None, BOOK_TEXT) == {}


def test_resolve_folds_per_item_results_by_index():
    map_output = {"results": [
        {"index": 0, "status": "success", "output": {"species": "elf", "quote": "Arya was an elf of Ellesméra."}},
        {"index": 1, "status": "success", "output": {"species": "", "quote": ""}},
    ]}
    verdicts = resolve_verdicts(_rows(), map_output, BOOK_TEXT)
    assert verdicts == {"Arya": {"species": "elf", "quote": "Arya was an elf of Ellesméra."}}


# --- consumers (unaffected by STU-753's retrieval change) ------------------


def test_the_binder_renders_species_from_the_batch_entity():
    assert _extracted_fact_value({"species": "elf"}, "species", lang="fr") == "elf"


def test_an_unstamped_entity_renders_no_species():
    assert _extracted_fact_value({}, "species", lang="fr") is None
    assert _extracted_fact_value({"species": ""}, "species", lang="fr") is None


def test_preparation_stamps_species_onto_the_batch_entity():
    bundle = build_entity_bundle(
        entity={"canonical_name": "Arya", "type": "PERSON", "importance": "principal"},
        relationships=[],
        persons={}, places={}, orgs={}, events={},
        entities_by_name={},
        species_verdicts={"Arya": {"species": "elf", "quote": "x"}},
    )
    assert bundle["species"] == "elf"


def test_preparation_stamps_nothing_for_an_undecided_character():
    bundle = build_entity_bundle(
        entity={"canonical_name": "Roran", "type": "PERSON", "importance": "secondary"},
        relationships=[],
        persons={}, places={}, orgs={}, events={},
        entities_by_name={},
        species_verdicts={},
    )
    assert bundle["species"] is None


def test_load_species_verdicts_degrades_on_an_absent_artifact(tmp_path):
    assert load_species_verdicts(tmp_path) == {}


def test_person_declares_the_species_slot():
    from wiki_creator.page_templates import load_base_template
    person = load_base_template()["entity_types"]["PERSON"]
    slots = {s["token"]: s for s in person["infobox"]}
    assert slots["species"]["provenance"] == "extracted-fact"
    assert slots["species"]["obligation"] == "OPT"
    assert slots["species"]["genre_gated"] is True


def test_an_undecided_species_clears_the_writers_guess():
    import scripts.generate_wiki_pages as gwp

    entity = {"canonical_name": "Roran", "type": "PERSON", "importance": "principal"}
    page = {"infobox_fields": {"species": "Humain"}}
    gwp._bind_batch_fields(page, entity, {})
    assert "species" not in page["infobox_fields"]


def test_a_decided_species_overwrites_the_writers_guess():
    import scripts.generate_wiki_pages as gwp

    entity = {
        "canonical_name": "Arya", "type": "PERSON", "importance": "principal",
        "species": "elf",
    }
    page = {"infobox_fields": {"species": "Humaine"}}
    gwp._bind_batch_fields(page, entity, {})
    assert page["infobox_fields"]["species"] == "elf"


# --- pre stage (genre gate + item shape) ------------------------------------


def _pre_setup(tmp_path):
    books_dir = tmp_path / "author" / "series" / "books"
    books_dir.mkdir(parents=True)
    epub = books_dir / "01-a-book.epub"
    epub.write_bytes(b"not a real epub - only the path is used")
    processing = tmp_path / "author" / "series" / "processing_output" / "01-a-book"
    processing.mkdir(parents=True)
    return epub, processing


def _run_pre(monkeypatch, epub, invented_names=True):
    import scripts.entity_species_pre as pre

    payload = {"additional_context": yaml.safe_dump(
        {"title": "Test", "language": "en", "file_path": str(epub), "ner": {"invented_names": invented_names}}
    )}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    pre.main()
    return json.loads(out.getvalue())


def test_a_book_with_no_invented_species_skips_the_call_entirely(tmp_path, monkeypatch):
    """THE STU-574 GATE. The `species` slot is `genre_gated: true`: a real-world-cast
    book has no species to attribute. The gate is `ner.invented_names`, checked in
    the pre stage before any registry read, so a non-genre book emits
    `needs_verdict: false` and clears any stale artifact."""
    epub, processing = _pre_setup(tmp_path)
    stale = processing / "entity_species.json"
    stale.write_text("{}", encoding="utf-8")
    result = _run_pre(monkeypatch, epub, invented_names=False)
    assert result["needs_verdict"] is False
    assert not stale.exists()


def test_pre_skips_with_no_registry(tmp_path, monkeypatch):
    epub, processing = _pre_setup(tmp_path)
    result = _run_pre(monkeypatch, epub, invented_names=True)
    assert result["needs_verdict"] is False


def test_pre_emits_one_item_per_person_with_context(tmp_path, monkeypatch):
    epub, processing = _pre_setup(tmp_path)
    registry = Registry(entities=[
        EntityRecord(
            entity_id="arya", canonical_name="Arya", entity_type="PERSON",
            aliases=["Arya"],
            mentions=[Mention(surface="Arya", chapter_id="c1", context="Arya was an elf.")],
        ),
    ])
    (processing / "registry.json").write_text(json.dumps(registry.to_dict()), encoding="utf-8")
    (processing / "chapters.json").write_text(
        json.dumps({"chapters": {"c1": "Arya was an elf."}}), encoding="utf-8"
    )
    result = _run_pre(monkeypatch, epub, invented_names=True)
    assert result["needs_verdict"] is True
    assert {e["name"] for e in result["entities"]} == {"Arya"}
