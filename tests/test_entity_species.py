"""STU-574: species is the race a character IS — a per-character attribute, not
the collective-noun entity (`Elves`) STU-571 assumed would feed the slot."""
import json
from pathlib import Path

import pytest
import yaml

CUE_WORDS = Path(__file__).resolve().parents[1] / "wiki_creator" / "cue_words"


def test_both_languages_declare_species_markers():
    # The vocabulary is data, never a constant in a .py (CLAUDE.md).
    for lang in ("en", "fr"):
        cues = json.loads((CUE_WORDS / f"{lang}.json").read_text(encoding="utf-8"))
        assert cues["species_markers"], f"{lang} has no species_markers"
        assert all(isinstance(m, str) and m for m in cues["species_markers"])


from wiki_creator.entity_species import (
    CACHE_VERSION,
    SNIPPETS_PER_ENTITY,
    parse_species_verdict,
    roster_rows,
    select_species_snippets,
)
from wiki_creator.roster import load_cache, render_roster, save_cache

MARKERS = ["human", "elf", "dwarf", "race", "dragon"]


def _snip(text, chapter_id):
    return {"text": text, "chapter_id": chapter_id}


def test_only_marker_bearing_snippets_are_kept():
    """Single-source, like `affiliation`: no sentence proves "no species", so a
    snippet with no marker can only confirm the character exists."""
    chosen = select_species_snippets(
        [_snip("Eragon was a human of Carvahall.", "ch1"), _snip("Eragon ate bread.", "ch2")],
        MARKERS,
    )
    assert [s["text"] for s in chosen] == ["Eragon was a human of Carvahall."]


def test_snippets_are_capped():
    chosen = select_species_snippets(
        [_snip(f"the elf {i}", f"ch{i}") for i in range(20)], MARKERS
    )
    assert len(chosen) == SNIPPETS_PER_ENTITY


def test_no_markers_selects_nothing():
    """CLAUDE.md: an absent cue_words key degrades to an empty collection. No
    markers → no snippets → the slot is omitted. It must not crash."""
    assert select_species_snippets([_snip("Arya was an elf.", "ch1")], []) == []


def _rows():
    return roster_rows(
        [{"canonical_name": "Arya", "aliases": []}],
        {"Arya": [_snip("Arya was an elf of Ellesméra.", "ch10")]},
        MARKERS,
    )


def test_a_verdict_must_quote_the_entitys_own_snippet():
    """STU-539's rule. These novels are in the model's training data: without it,
    a verdict from its memory of the plot and one from this run's text are
    indistinguishable afterwards."""
    verdicts = parse_species_verdict(
        {"species": [{"name": "Arya", "species": "elf",
                      "quote": "Arya, the elven princess, drew her sword."}]},
        _rows(),
    )
    assert verdicts == {}


def test_the_value_must_appear_in_the_quote():
    """The load-bearing rule (shared with STU-551). The value is a NAME, so the
    model can quote a real sentence and infer the wrong race from it."""
    verdicts = parse_species_verdict(
        {"species": [{"name": "Arya", "species": "human",
                      "quote": "Arya was an elf of Ellesméra."}]},
        _rows(),
    )
    assert verdicts == {}


def test_a_grounded_verdict_survives():
    verdicts = parse_species_verdict(
        {"species": [{"name": "Arya", "species": "elf",
                      "quote": "Arya was an elf of Ellesméra."}]},
        _rows(),
    )
    assert verdicts == {"Arya": {"species": "elf", "quote": "Arya was an elf of Ellesméra."}}


def test_a_species_belonging_to_another_character_in_the_sentence_is_rejected():
    """The species-specific trap: a snippet names a species that is the VICTIM's,
    not the subject's. "Eragon killed the Urgal" must not make Eragon an Urgal.
    The quote is real, but the value the model pinned is only anchored by rule 3
    when it actually names Eragon's race — here it names the Urgal's, and the
    classifier is instructed to leave it out. Rule 3 cannot catch a species that
    IS in the quote but belongs to someone else; the prompt's THE TEST does. This
    pins the mechanical half: a value not in the quote is dropped regardless."""
    rows = roster_rows(
        [{"canonical_name": "Eragon", "aliases": []}],
        {"Eragon": [_snip("Eragon killed the Urgal with one stroke.", "ch12")]},
        MARKERS + ["urgal"],
    )
    # The model wrongly returns Urgal but cites a quote that does name it — rule 3
    # passes, so this verdict is the prompt's responsibility, not the parser's.
    # What the parser guarantees: a hallucinated race NOT in the quote is dropped.
    verdicts = parse_species_verdict(
        {"species": [{"name": "Eragon", "species": "human",
                      "quote": "Eragon killed the Urgal with one stroke."}]},
        rows,
    )
    assert verdicts == {}


def test_a_name_off_the_roster_is_rejected():
    verdicts = parse_species_verdict(
        {"species": [{"name": "Galbatorix", "species": "human",
                      "quote": "Galbatorix was a human once."}]},
        _rows(),
    )
    assert verdicts == {}


def test_the_value_must_match_whole_tokens_not_a_substring():
    """STU-541's rule: `elf` inside `himself` is an accident of spelling."""
    rows = roster_rows(
        [{"canonical_name": "Roran", "aliases": []}],
        {"Roran": [_snip("Roran steadied himself before the human host.", "ch10")]},
        MARKERS,
    )
    quote = "Roran steadied himself before the human host."
    verdicts = parse_species_verdict(
        {"species": [{"name": "Roran", "species": "elf", "quote": quote}]}, rows
    )
    assert verdicts == {}, "'elf' was accepted out of 'himself'"


def test_typographic_quotes_match_a_straight_quoted_reply():
    """The 99a6a71 regression: the EPUB ships curly quotes, the model echoes
    straight ones. Inherited from `roster.normalize`, so it holds for free."""
    rows = roster_rows(
        [{"canonical_name": "Arya", "aliases": []}],
        {"Arya": [_snip("“I am an elf,” Arya said.", "ch10")]},
        MARKERS,
    )
    verdicts = parse_species_verdict(
        {"species": [{"name": "Arya", "species": "elf",
                      "quote": '"I am an elf," Arya said.'}]},
        rows,
    )
    assert verdicts["Arya"]["species"] == "elf"


@pytest.mark.parametrize("payload", ["not json", None, {}, {"species": "a string"}, 42])
def test_unparseable_payloads_verdict_nothing(payload):
    assert parse_species_verdict(payload, _rows()) == {}


def test_cache_is_keyed_on_the_roster_rows(tmp_path):
    cache = tmp_path / "entity_species.json"
    verdicts = {"Arya": {"species": "elf", "quote": "Arya was an elf of Ellesméra."}}
    save_cache(cache, _rows(), verdicts, CACHE_VERSION)
    assert load_cache(cache, _rows(), CACHE_VERSION) == verdicts

    other = roster_rows(
        [{"canonical_name": "Arya", "aliases": []}],
        {"Arya": [_snip("Arya was a human once.", "ch10")]},
        MARKERS,
    )
    assert load_cache(cache, other, CACHE_VERSION) is None


def test_render_roster_shows_names_aliases_and_snippets():
    rendered = render_roster(
        roster_rows(
            [{"canonical_name": "Arya", "aliases": ["Islanzadí's daughter"]}],
            {"Arya": [_snip("Arya was an elf of Ellesméra.", "ch10")]},
            MARKERS,
        )
    )
    assert "## Arya (also called: Islanzadí's daughter)" in rendered
    assert "- Arya was an elf of Ellesméra." in rendered


import io
import json as _json

from scripts.entity_species import resolve_species

_VERDICT = {"species": [
    {"name": "Arya", "species": "elf", "quote": "Arya was an elf of Ellesméra."}
]}


def test_resolve_caches_and_replays(tmp_path):
    cache = tmp_path / "entity_species.json"
    first = resolve_species(_rows(), _VERDICT, cache)
    assert first["Arya"]["species"] == "elf"

    # Cache hit: served without consulting the (absent) call output.
    second = resolve_species(_rows(), None, cache)
    assert second == first


def test_a_missing_verdict_omits_the_slot_for_everyone(tmp_path):
    """A false species labels a character the wrong race on a page nobody will
    reread; an absent one says nothing. The call stage failing (on_failure:
    continue) or being skipped must never fail the run and must cache nothing."""
    cache = tmp_path / "entity_species.json"
    assert resolve_species(_rows(), None, cache) == {}
    assert not cache.exists()


def test_a_book_with_no_invented_species_skips_the_call_entirely(tmp_path, monkeypatch):
    """THE STU-574 GATE. The `species` slot is `genre_gated: true`: a real-world-cast
    book has no species to attribute. The gate is `ner.invented_names`, checked in
    the pre stage before any registry read, so a non-genre book emits
    `needs_verdict: false` (the call is condition-skipped) and clears any stale
    artifact."""
    import scripts.entity_species_pre as pre

    books_dir = tmp_path / "author" / "series" / "books"
    books_dir.mkdir(parents=True)
    epub = books_dir / "01-a-book.epub"
    epub.write_bytes(b"not a real epub - only the path is used")
    processing = tmp_path / "author" / "series" / "processing_output" / "01-a-book"
    processing.mkdir(parents=True)
    stale = processing / "entity_species.json"
    stale.write_text("{}", encoding="utf-8")

    payload = {"additional_context": yaml.safe_dump(
        {"title": "Test", "language": "en", "file_path": str(epub), "ner": {"invented_names": False}}
    )}
    monkeypatch.setattr("sys.stdin", io.StringIO(_json.dumps(payload)))
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    pre.main()

    assert _json.loads(out.getvalue())["needs_verdict"] is False
    assert not stale.exists()


from scripts.generate_wiki_pages import _extracted_fact_value
from scripts.wiki_preparation import build_entity_bundle, load_species_verdicts


def test_the_binder_renders_species_from_the_batch_entity():
    assert _extracted_fact_value({"species": "elf"}, "species", "fr") == "elf"


def test_an_unstamped_entity_renders_no_species():
    assert _extracted_fact_value({}, "species", "fr") is None
    assert _extracted_fact_value({"species": ""}, "species", "fr") is None


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
    """As for `affiliation` (STU-551/STU-572): base.yaml's brief lets the writer
    invent a species, and `_bind_batch_fields` only overwrites when the pipeline
    HAS a value. Without the clear, an undecided character renders the LLM's guess
    — the ungrounded fact this stage exists to prevent."""
    import scripts.generate_wiki_pages as gwp

    entity = {"canonical_name": "Roran", "type": "PERSON", "importance": "principal"}
    page = {"infobox_fields": {"species": "Humain"}}  # the writer's guess
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
