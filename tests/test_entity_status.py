"""STU-488: per-tome entity status (the `status` / `death` infobox slots)."""
import json

from wiki_creator.entity_status import (
    DEFAULT_STATUS,
    SNIPPETS_PER_ENTITY,
    STATUS_VALUES,
    load_cached_status,
    parse_status_verdict,
    render_roster,
    roster_rows,
    save_status_cache,
    select_status_snippets,
)

MARKERS = ["died", "killed", "dead"]


def _snippet(text, chapter):
    return {"text": text, "chapter_id": f"chapter_{chapter}"}


def test_status_enum_is_the_fandom_vocabulary():
    assert STATUS_VALUES == ("alive", "deceased", "missing", "unknown", "undead")
    assert DEFAULT_STATUS == "unknown"


def test_marker_bearing_snippets_come_before_plain_ones():
    snippets = [
        _snippet("Brom rode north with Eragon.", 5),
        _snippet("Brom died at dawn.", 2),
    ]
    chosen = select_status_snippets(snippets, MARKERS)
    assert chosen[0]["text"] == "Brom died at dawn."


def test_plain_snippets_fill_up_latest_first():
    # No marker anywhere: this is the `alive` evidence path — the character acts
    # late in the book, so the latest snippets are the ones that show it.
    snippets = [_snippet(f"Eragon walks in chapter {n}.", n) for n in (1, 40, 12)]
    chosen = select_status_snippets(snippets, MARKERS)
    assert [s["chapter_id"] for s in chosen] == ["chapter_40", "chapter_12", "chapter_1"]


def test_marker_snippets_are_also_latest_first():
    # Status is the state at the END of the tome, so the latest death evidence wins.
    snippets = [_snippet("He was killed early.", 2), _snippet("He was killed later.", 30)]
    chosen = select_status_snippets(snippets, MARKERS)
    assert chosen[0]["text"] == "He was killed later."


def test_selection_caps_at_five():
    snippets = [_snippet(f"Eragon walks {n}.", n) for n in range(20)]
    assert len(select_status_snippets(snippets, MARKERS)) == SNIPPETS_PER_ENTITY


def test_marker_snippets_do_not_starve_the_cap():
    # 3 markers + 2 plain fills exactly 5 — the alive-evidence path stays open
    # even when some markers are present.
    marked = [_snippet(f"Someone died {n}.", n) for n in (1, 2, 3)]
    plain = [_snippet(f"Eragon walks {n}.", n) for n in (10, 11, 12)]
    chosen = select_status_snippets(marked + plain, MARKERS)
    assert len(chosen) == 5
    assert sum(1 for s in chosen if "died" in s["text"]) == 3


def test_empty_markers_still_selects_latest():
    # cue_words with no `status_markers` key degrades to an empty list: no marker
    # selection, no crash, latest snippets only.
    snippets = [_snippet("Brom died at dawn.", 2), _snippet("Eragon walks.", 9)]
    chosen = select_status_snippets(snippets, [])
    assert chosen[0]["chapter_id"] == "chapter_9"


def test_snippet_text_is_truncated_but_the_chapter_survives():
    long_text = "Brom died. " + "x" * 500
    [chosen] = select_status_snippets([_snippet(long_text, 7)], MARKERS)
    assert len(chosen["text"]) == 300
    assert chosen["chapter_id"] == "chapter_7"


def test_markers_match_whole_words_only():
    # "killed" must not fire on "skilled": if it did, the chapter-1 snippet would
    # count as marker-bearing and outrank the chapter-9 one.
    snippets = [_snippet("Eragon is a skilled rider.", 1), _snippet("Eragon rides.", 9)]
    chosen = select_status_snippets(snippets, ["killed"])
    assert chosen[0]["chapter_id"] == "chapter_9"


def test_roster_rows_carry_name_aliases_and_snippets():
    entities = [{"canonical_name": "Brom", "aliases": ["the storyteller"]}]
    contexts = {"Brom": [_snippet("Brom died at dawn.", 2)]}
    [row] = roster_rows(entities, contexts, MARKERS)
    assert row["name"] == "Brom"
    assert row["aliases"] == ["the storyteller"]
    assert row["snippets"][0]["text"] == "Brom died at dawn."


def test_roster_row_for_an_entity_with_no_context_is_empty_not_missing():
    entities = [{"canonical_name": "Ghost", "aliases": []}]
    [row] = roster_rows(entities, {}, MARKERS)
    assert row["snippets"] == []


BROM_QUOTE = "Brom's chest rose one last time, and then was still."


def _rows():
    return [
        {
            "name": "Brom",
            "aliases": ["the storyteller"],
            "snippets": [{"text": BROM_QUOTE, "chapter_id": "chapter_38"}],
        },
        {
            "name": "Eragon",
            "aliases": [],
            "snippets": [{"text": "Eragon rode on alone.", "chapter_id": "chapter_59"}],
        },
    ]


def _verdict(**overrides):
    entry = {"name": "Brom", "status": "deceased", "quote": BROM_QUOTE}
    entry.update(overrides)
    return {"status": [entry]}


def test_render_roster_shows_names_aliases_and_snippet_text():
    rendered = render_roster(_rows())
    assert "## Brom (also called: the storyteller)" in rendered
    assert f"- {BROM_QUOTE}" in rendered
    assert "## Eragon" in rendered


def test_render_roster_never_shows_the_chapter():
    # The chapter is derived by code from the quoted snippet. Showing it would
    # invite the model to report one instead of quoting.
    assert "chapter_38" not in render_roster(_rows())


def test_a_verified_deceased_verdict_carries_the_quoted_snippets_chapter():
    verdicts = parse_status_verdict(_verdict(), _rows())
    assert verdicts["Brom"]["status"] == "deceased"
    assert verdicts["Brom"]["chapter"] == 38


def test_a_json_string_payload_is_parsed():
    verdicts = parse_status_verdict(json.dumps(_verdict()), _rows())
    assert verdicts["Brom"]["status"] == "deceased"


def test_a_quote_not_verbatim_in_that_entitys_snippets_is_rejected():
    # The model has read this novel. Without the check, a verdict from its memory
    # of the plot and one from this run's text are indistinguishable afterwards.
    verdicts = parse_status_verdict(_verdict(quote="Brom died at Farthen Dur."), _rows())
    assert verdicts == {}


def test_a_quote_from_another_entitys_snippets_is_rejected():
    # "Eragon watched Brom die" is in BOTH characters' contexts and kills one.
    # A verdict must be grounded in the snippets shown for its OWN entity.
    verdicts = parse_status_verdict(
        _verdict(name="Eragon", quote=BROM_QUOTE), _rows()
    )
    assert verdicts == {}


def test_quote_matching_ignores_whitespace_and_case():
    verdicts = parse_status_verdict(
        _verdict(quote="  BROM'S CHEST ROSE   one last time,\nand then was still. "), _rows()
    )
    assert verdicts["Brom"]["status"] == "deceased"


def test_a_name_off_the_roster_is_rejected():
    verdicts = parse_status_verdict(_verdict(name="Durza"), _rows())
    assert verdicts == {}


def test_a_status_outside_the_enum_is_rejected():
    verdicts = parse_status_verdict(_verdict(status="martyred"), _rows())
    assert verdicts == {}


def test_an_explicit_unknown_verdict_is_dropped_not_stored():
    # `unknown` is the absence of a verdict, not a verdict. Storing it would make
    # the cache claim the model ruled on an entity it did not.
    verdicts = parse_status_verdict(_verdict(status="unknown", quote=BROM_QUOTE), _rows())
    assert verdicts == {}


def test_an_empty_quote_is_rejected():
    verdicts = parse_status_verdict(_verdict(quote=""), _rows())
    assert verdicts == {}


def test_alive_needs_a_quote_too():
    verdicts = parse_status_verdict(
        {"status": [{"name": "Eragon", "status": "alive", "quote": "Eragon rode on alone."}]},
        _rows(),
    )
    assert verdicts["Eragon"]["status"] == "alive"


def test_only_deceased_carries_a_death_chapter():
    # The slot's label is "Died". `missing` and `undead` have no death chapter.
    verdicts = parse_status_verdict(
        {"status": [{"name": "Eragon", "status": "alive", "quote": "Eragon rode on alone."}]},
        _rows(),
    )
    assert verdicts["Eragon"]["chapter"] is None


def test_a_deceased_verdict_quoted_from_an_unnumbered_chapter_keeps_its_status():
    rows = [{"name": "Brom", "aliases": [], "snippets": [{"text": BROM_QUOTE, "chapter_id": "Prologue"}]}]
    verdicts = parse_status_verdict(_verdict(), rows)
    assert verdicts["Brom"]["status"] == "deceased"
    assert verdicts["Brom"]["chapter"] is None


def test_unparseable_payloads_verdict_nothing():
    for payload in ["not json", None, [], {"merge": []}, {"status": "deceased"}, 42]:
        assert parse_status_verdict(payload, _rows()) == {}


def test_a_malformed_entry_does_not_sink_its_neighbours():
    payload = {
        "status": [
            "garbage",
            {"name": "Brom", "status": "deceased", "quote": BROM_QUOTE},
        ]
    }
    assert parse_status_verdict(payload, _rows())["Brom"]["status"] == "deceased"


def test_cache_round_trips(tmp_path):
    rows, verdicts = _rows(), {"Brom": {"status": "deceased", "quote": BROM_QUOTE, "chapter": 38}}
    path = tmp_path / "entity_status.json"
    save_status_cache(path, rows, verdicts)
    assert load_cached_status(path, rows) == verdicts


def test_a_changed_roster_misses_the_cache(tmp_path):
    # WIKI_MAX_CHAPTERS and every upstream extraction fix change the roster. A
    # verdict returned for a different roster must not be replayed onto it —
    # STU-539's premise was measured false against a 5-chapter extraction.
    path = tmp_path / "entity_status.json"
    save_status_cache(path, _rows(), {"Brom": {"status": "deceased", "quote": BROM_QUOTE, "chapter": 38}})
    other = _rows()
    other[0]["snippets"] = [{"text": "Brom rode north.", "chapter_id": "chapter_2"}]
    assert load_cached_status(path, other) is None


def test_a_missing_or_corrupt_cache_is_a_miss_not_a_crash(tmp_path):
    assert load_cached_status(tmp_path / "nope.json", _rows()) is None
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json", encoding="utf-8")
    assert load_cached_status(corrupt, _rows()) is None
