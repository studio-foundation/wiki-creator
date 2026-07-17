"""STU-488: per-tome entity status (the `status` infobox slot)."""
import json
import subprocess
from unittest.mock import patch

import run_wiki
from scripts.entity_status import contexts_by_entity, resolve_status
from scripts.wiki_preparation import load_status_verdicts
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
from wiki_creator.registry import EntityRecord, Mention, Registry

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
    # The classifier is never shown the chapter. Showing it would invite the
    # model to report one instead of quoting.
    assert "chapter_38" not in render_roster(_rows())


def test_a_verified_deceased_verdict_is_accepted():
    verdicts = parse_status_verdict(_verdict(), _rows())
    assert verdicts["Brom"]["status"] == "deceased"


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


def test_the_eragon_regression_brom_quote_survives_curly_source_quotes():
    # STU-488 real run: the EPUB snippet carries curly quotes and an em dash;
    # the model echoed the same sentence back in straight ASCII. This is the
    # exact snippet/reply pair that scored 0/62 verdicts before the fix.
    rows = [
        {
            "name": "Brom",
            "aliases": [],
            "snippets": [
                {
                    "text": (
                        "Saphira … I like the name—fitting for a dragon.” "
                        "“Brom's dead,” said Eragon abruptly. “The Ra'zac killed him.”"
                    ),
                    "chapter_id": "chapter_32",
                }
            ],
        }
    ]
    verdict = _verdict(
        quote="\"Brom's dead,\" said Eragon abruptly. \"The Ra'zac killed him.\""
    )
    verdicts = parse_status_verdict(verdict, rows)
    assert verdicts["Brom"]["status"] == "deceased"


def test_curly_apostrophe_folds_to_straight():
    rows = [
        {"name": "Brom", "aliases": [], "snippets": [{"text": "Brom’s hand went still.", "chapter_id": "c1"}]}
    ]
    verdicts = parse_status_verdict(_verdict(quote="Brom's hand went still."), rows)
    assert verdicts["Brom"]["status"] == "deceased"


def test_ellipsis_folds_to_three_dots():
    rows = [
        {
            "name": "Brom",
            "aliases": [],
            "snippets": [{"text": "Brom fell silent… then died.", "chapter_id": "c1"}],
        }
    ]
    verdicts = parse_status_verdict(_verdict(quote="Brom fell silent... then died."), rows)
    assert verdicts["Brom"]["status"] == "deceased"


def test_em_dash_folds_to_hyphen():
    rows = [
        {
            "name": "Brom",
            "aliases": [],
            "snippets": [{"text": "Brom—dying—spoke once more.", "chapter_id": "c1"}],
        }
    ]
    verdicts = parse_status_verdict(_verdict(quote="Brom-dying-spoke once more."), rows)
    assert verdicts["Brom"]["status"] == "deceased"


def test_non_breaking_space_folds_to_a_plain_space():
    rows = [
        {"name": "Brom", "aliases": [], "snippets": [{"text": "Brom died at dawn.", "chapter_id": "c1"}]}
    ]
    verdicts = parse_status_verdict(_verdict(quote="Brom died at dawn."), rows)
    assert verdicts["Brom"]["status"] == "deceased"


def test_folding_does_not_relax_the_check_for_invented_text():
    # Folding only equates two spellings of the SAME sentence. A sentence the
    # model invented must still be rejected, even one that also carries a
    # typographic apostrophe.
    rows = [
        {"name": "Brom", "aliases": [], "snippets": [{"text": "Brom’s hand went still.", "chapter_id": "c1"}]}
    ]
    verdicts = parse_status_verdict(_verdict(quote="Brom's heart stopped beating."), rows)
    assert verdicts == {}


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


def test_a_deceased_verdict_quoted_from_an_unnumbered_chapter_keeps_its_status():
    rows = [{"name": "Brom", "aliases": [], "snippets": [{"text": BROM_QUOTE, "chapter_id": "Prologue"}]}]
    verdicts = parse_status_verdict(_verdict(), rows)
    assert verdicts["Brom"]["status"] == "deceased"


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
    rows, verdicts = _rows(), {"Brom": {"status": "deceased", "quote": BROM_QUOTE}}
    path = tmp_path / "entity_status.json"
    save_status_cache(path, rows, verdicts)
    assert load_cached_status(path, rows) == verdicts


def test_a_changed_roster_misses_the_cache(tmp_path):
    # WIKI_MAX_CHAPTERS and every upstream extraction fix change the roster. A
    # verdict returned for a different roster must not be replayed onto it —
    # STU-539's premise was measured false against a 5-chapter extraction.
    path = tmp_path / "entity_status.json"
    save_status_cache(path, _rows(), {"Brom": {"status": "deceased", "quote": BROM_QUOTE}})
    other = _rows()
    other[0]["snippets"] = [{"text": "Brom rode north.", "chapter_id": "chapter_2"}]
    assert load_cached_status(path, other) is None


def test_a_missing_or_corrupt_cache_is_a_miss_not_a_crash(tmp_path):
    assert load_cached_status(tmp_path / "nope.json", _rows()) is None
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json", encoding="utf-8")
    assert load_cached_status(corrupt, _rows()) is None


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


def test_contexts_come_from_person_mentions_with_their_chapter():
    contexts = contexts_by_entity(_registry())
    assert contexts["Brom"] == [{"text": BROM_QUOTE, "chapter_id": "chapter_38"}]


def test_non_person_entities_have_no_context():
    # `status` is declared on PERSON only; no other type has the slot.
    assert "Tronjheim" not in contexts_by_entity(_registry())


def test_every_studio_failure_leaves_the_roster_unknown(tmp_path):
    # Missing CLI, timeout, non-zero exit, unparseable output, missing stage
    # output: each renders `unknown`, which is the slot's declared fallback.
    # A false `deceased` kills a living character on a page nobody will reread.
    for error in [
        FileNotFoundError(),
        subprocess.TimeoutExpired(cmd="studio", timeout=1),
    ]:
        with patch("scripts.entity_status.subprocess.run", side_effect=error):
            assert resolve_status(_rows(), "Eragon", tmp_path / "s.json") == {}

    class _Result:
        returncode = 1
        stdout = ""
        stderr = "boom"

    with patch("scripts.entity_status.subprocess.run", return_value=_Result()):
        assert resolve_status(_rows(), "Eragon", tmp_path / "s.json") == {}

    class _Garbage:
        returncode = 0
        stdout = "not json at all"
        stderr = ""

    with patch("scripts.entity_status.subprocess.run", return_value=_Garbage()):
        assert resolve_status(_rows(), "Eragon", tmp_path / "s.json") == {}


def test_a_failed_run_is_not_cached(tmp_path):
    # Caching a failure would make the next run replay it silently.
    cache = tmp_path / "s.json"
    with patch("scripts.entity_status.subprocess.run", side_effect=FileNotFoundError()):
        resolve_status(_rows(), "Eragon", cache)
    assert not cache.exists()


def test_a_stale_verdict_for_another_roster_does_not_survive_a_failed_retry(tmp_path):
    # A full run leaves an artifact for roster R1. A re-run with a changed
    # roster (WIKI_MAX_CHAPTERS, an extraction fix) R2 misses the cache and
    # then fails the `studio run` — `load_status_verdicts` is roster-blind, so
    # any artifact left on disk here would be replayed onto R2 by the consumer.
    cache = tmp_path / "s.json"
    save_status_cache(cache, _rows(), {"Brom": {"status": "deceased", "quote": BROM_QUOTE}})

    other_rows = _rows()
    other_rows[0]["snippets"] = [{"text": "Brom rode north.", "chapter_id": "chapter_2"}]

    with patch("scripts.entity_status.subprocess.run", side_effect=FileNotFoundError()):
        resolve_status(other_rows, "Eragon", cache)
    assert not cache.exists()


def test_a_successful_verdict_is_cached_and_replayed(tmp_path):
    cache = tmp_path / "s.json"
    stage_output = {"status": [{"name": "Brom", "status": "deceased", "quote": BROM_QUOTE}]}

    class _Ok:
        returncode = 0
        stdout = json.dumps({
            "id": "run-1",
            "stages": [
                {"stage_name": "entity-status-item", "status": "success", "output": stage_output},
            ],
        })
        stderr = ""

    with patch("scripts.entity_status.subprocess.run", return_value=_Ok()) as run:
        first = resolve_status(_rows(), "Eragon", cache)
    assert first["Brom"]["status"] == "deceased"

    with patch("scripts.entity_status.subprocess.run") as run:
        second = resolve_status(_rows(), "Eragon", cache)
    run.assert_not_called()
    assert second == first


from scripts.generate_wiki_pages import _extracted_fact_value
from wiki_creator.entity_status import status_label
from wiki_creator.page_templates import load_base_template


def test_every_enum_value_has_a_label_in_both_languages():
    # No French string literal may live in a .py — the labels are data.
    chrome = load_base_template()["chrome"]
    for status in STATUS_VALUES:
        entry = chrome[f"status_{status}"]
        assert entry["fr"] and entry["en"]


def test_status_label_is_localized():
    assert status_label("deceased", "en") == "Deceased"
    assert status_label("deceased", "fr") == "Décédé"


def test_an_absent_status_renders_the_declared_fallback():
    # base.yaml declares `fallback: unknown` on the slot; MIN means it renders.
    assert status_label(None, "en") == status_label("unknown", "en")
    assert status_label("", "en") == status_label("unknown", "en")


def test_the_binder_renders_status_from_the_batch_entity():
    entity = {"status": "deceased"}
    assert _extracted_fact_value(entity, "status", "fr") == "Décédé"


def test_the_binder_renders_unknown_for_an_unstamped_entity():
    # A book that never ran the stage, and a verdict that was rejected, render
    # the same thing.
    assert _extracted_fact_value({}, "status", "en") == status_label("unknown", "en")


def test_titles_still_binds():
    assert _extracted_fact_value({"titles": ["Roi"]}, "titles", "fr") == "Roi"


def test_person_declares_the_status_slot():
    person = load_base_template()["entity_types"]["PERSON"]
    slots = {s["token"]: s for s in person["infobox"]}
    assert slots["status"]["provenance"] == "extracted-fact"
    assert "death" not in slots
    assert "{{{death|}}}" not in person["export"]["infobox_source"]


def test_the_pre_step_is_registered_before_wiki_preparation():
    # STU-512's lesson: without this, the whole feature is deletable with the
    # suite green.
    commands = [" ".join(cmd) for cmd in run_wiki.PRE_STEPS["wiki-preparation"]]
    assert any("scripts/entity_status.py" in cmd for cmd in commands)


def test_load_status_verdicts_reads_the_artifact(tmp_path):
    (tmp_path / "entity_status.json").write_text(
        json.dumps({
            "roster": [],
            "verdicts": {"Brom": {"status": "deceased", "quote": BROM_QUOTE}},
        }),
        encoding="utf-8",
    )
    verdicts = load_status_verdicts(tmp_path)
    assert verdicts["Brom"]["status"] == "deceased"


def test_a_missing_or_corrupt_status_artifact_leaves_every_entity_unknown(tmp_path):
    assert load_status_verdicts(tmp_path) == {}
    (tmp_path / "entity_status.json").write_text("{not json", encoding="utf-8")
    assert load_status_verdicts(tmp_path) == {}
