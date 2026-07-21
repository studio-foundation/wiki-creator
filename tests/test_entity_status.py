"""STU-488: per-tome entity status (the `status` infobox slot)."""
import json
import re
from pathlib import Path

import yaml

from scripts.entity_status import contexts_by_entity, resolve_status
from scripts.wiki_preparation import load_status_verdicts
from wiki_creator.entity_status import (
    CACHE_VERSION,
    DEFAULT_STATUS,
    SNIPPETS_PER_ENTITY,
    STATUS_VALUES,
    build_name_index,
    death_label,
    load_cached_status,
    parse_status_verdict,
    render_roster,
    roster_rows,
    save_status_cache,
    select_status_snippets,
)
from wiki_creator.registry import EntityRecord, Mention, Registry

MARKERS = ["died", "killed", "dead"]

STATUS_PROMPT = (
    Path(__file__).resolve().parents[1]
    / ".studio"
    / "agents"
    / "entity-status.agent.yaml"
)


def _snippet(text, chapter):
    return {"text": text, "chapter_id": f"chapter_{chapter}"}


def test_status_enum_is_the_fandom_vocabulary():
    assert STATUS_VALUES == ("alive", "deceased", "missing", "unknown", "undead")
    assert DEFAULT_STATUS == "unknown"


def _prompt_status_mentions() -> set[str]:
    """Status tokens the prompt names as the values it may return.

    Mechanical, never a hand-kept list — a second copy of the enum is the drift
    STU-548 closed on the relationship prompt, and it would rot the same way. The
    tokens are read out of the prompt's own instruction grammar: the `exactly one
    of:` roster (the returnable statuses; `unknown` is deliberately absent — it is
    the non-answer `parse_status_verdict` renders for a name it never lists).
    """
    prompt = yaml.safe_load(STATUS_PROMPT.read_text(encoding="utf-8"))["system_prompt"]
    listed = re.search(r"exactly one of:\s*(.+)", prompt)
    assert listed, "prompt no longer states an `exactly one of:` status roster"
    return {token.strip() for token in listed.group(1).split(",")}


def test_prompt_names_only_declared_status_values():
    """The prompt is a second consumer of the status enum after `parse_status_verdict`,
    which drops any status outside `STATUS_VALUES`.

    STU-548's shape: rename a member (`deceased` → `dead`) in `STATUS_VALUES` and the
    prompt keeps ordering `deceased`; the parser then discards every death verdict and
    the whole roster renders `unknown`, silently, with the suite green. `rg` skips
    `.studio/` and no test read the prompt, so nothing caught it. This fails the moment
    the prompt names a status absent from the enum.
    """
    mentions = _prompt_status_mentions()
    assert mentions, "extracted no status tokens from the prompt — the instruction grammar moved"
    undeclared = mentions - set(STATUS_VALUES)
    assert undeclared == set(), f"prompt names statuses absent from STATUS_VALUES: {sorted(undeclared)}"


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
    verdicts = parse_status_verdict(_verdict(), _rows(), _index())
    assert verdicts["Brom"]["status"] == "deceased"


def test_a_json_string_payload_is_parsed():
    verdicts = parse_status_verdict(json.dumps(_verdict()), _rows(), _index())
    assert verdicts["Brom"]["status"] == "deceased"


def test_a_quote_not_verbatim_in_that_entitys_snippets_is_rejected():
    # The model has read this novel. Without the check, a verdict from its memory
    # of the plot and one from this run's text are indistinguishable afterwards.
    verdicts = parse_status_verdict(_verdict(quote="Brom died at Farthen Dur."), _rows(), _index())
    assert verdicts == {}


def test_a_quote_from_another_entitys_snippets_is_rejected():
    # "Eragon watched Brom die" is in BOTH characters' contexts and kills one.
    # A verdict must be grounded in the snippets shown for its OWN entity.
    verdicts = parse_status_verdict(
        _verdict(name="Eragon", quote=BROM_QUOTE), _rows(), _index()
    )
    assert verdicts == {}


def test_quote_matching_ignores_whitespace_and_case():
    verdicts = parse_status_verdict(
        _verdict(quote="  BROM'S CHEST ROSE   one last time,\nand then was still. "), _rows(), _index()
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
    verdicts = parse_status_verdict(verdict, rows, _index())
    assert verdicts["Brom"]["status"] == "deceased"


def test_curly_apostrophe_folds_to_straight():
    rows = [
        {"name": "Brom", "aliases": [], "snippets": [{"text": "Brom’s hand went still.", "chapter_id": "c1"}]}
    ]
    verdicts = parse_status_verdict(_verdict(quote="Brom's hand went still."), rows, _index())
    assert verdicts["Brom"]["status"] == "deceased"


def test_ellipsis_folds_to_three_dots():
    rows = [
        {
            "name": "Brom",
            "aliases": [],
            "snippets": [{"text": "Brom fell silent… then died.", "chapter_id": "c1"}],
        }
    ]
    verdicts = parse_status_verdict(_verdict(quote="Brom fell silent... then died."), rows, _index())
    assert verdicts["Brom"]["status"] == "deceased"


def test_em_dash_folds_to_hyphen():
    rows = [
        {
            "name": "Brom",
            "aliases": [],
            "snippets": [{"text": "Brom—dying—spoke once more.", "chapter_id": "c1"}],
        }
    ]
    verdicts = parse_status_verdict(_verdict(quote="Brom-dying-spoke once more."), rows, _index())
    assert verdicts["Brom"]["status"] == "deceased"


def test_folding_does_not_relax_the_check_for_invented_text():
    # Folding only equates two spellings of the SAME sentence. A sentence the
    # model invented must still be rejected, even one that also carries a
    # typographic apostrophe.
    rows = [
        {"name": "Brom", "aliases": [], "snippets": [{"text": "Brom’s hand went still.", "chapter_id": "c1"}]}
    ]
    verdicts = parse_status_verdict(_verdict(quote="Brom's heart stopped beating."), rows, _index())
    assert verdicts == {}


def test_a_name_off_the_roster_is_rejected():
    verdicts = parse_status_verdict(_verdict(name="Durza"), _rows(), _index())
    assert verdicts == {}


def test_a_status_outside_the_enum_is_rejected():
    verdicts = parse_status_verdict(_verdict(status="martyred"), _rows(), _index())
    assert verdicts == {}


def test_an_explicit_unknown_verdict_is_dropped_not_stored():
    # `unknown` is the absence of a verdict, not a verdict. Storing it would make
    # the cache claim the model ruled on an entity it did not.
    verdicts = parse_status_verdict(_verdict(status="unknown", quote=BROM_QUOTE), _rows(), _index())
    assert verdicts == {}


def test_an_empty_quote_is_rejected():
    verdicts = parse_status_verdict(_verdict(quote=""), _rows(), _index())
    assert verdicts == {}


def test_alive_needs_a_quote_too():
    verdicts = parse_status_verdict(
        {"status": [{"name": "Eragon", "status": "alive", "quote": "Eragon rode on alone."}]},
        _rows(),
        _index(),
    )
    assert verdicts["Eragon"]["status"] == "alive"


def test_unparseable_payloads_verdict_nothing():
    for payload in ["not json", None, [], {"merge": []}, {"status": "deceased"}, 42]:
        assert parse_status_verdict(payload, _rows(), _index()) == {}


def test_a_malformed_entry_does_not_sink_its_neighbours():
    payload = {
        "status": [
            "garbage",
            {"name": "Brom", "status": "deceased", "quote": BROM_QUOTE},
        ]
    }
    assert parse_status_verdict(payload, _rows(), _index())["Brom"]["status"] == "deceased"


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


def test_a_missing_verdict_leaves_the_roster_unknown(tmp_path):
    # The call stage was skipped or failed (on_failure: continue): every
    # character renders `unknown`, the slot's declared fallback, and nothing is
    # cached — a false `deceased` kills a living character on a page nobody
    # will reread.
    cache = tmp_path / "s.json"
    assert resolve_status(_rows(), None, cache, _index()) == {}
    assert not cache.exists()


def test_a_successful_verdict_is_cached_and_replayed(tmp_path):
    cache = tmp_path / "s.json"
    stage_output = {"status": [{"name": "Brom", "status": "deceased", "quote": BROM_QUOTE}]}

    first = resolve_status(_rows(), stage_output, cache, _index())
    assert first["Brom"]["status"] == "deceased"

    # Cache hit: the verdict is served without consulting the (absent) call output.
    second = resolve_status(_rows(), None, cache, _index())
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


def test_person_declares_the_death_slot_as_optional():
    # OPT, so `validate_template`'s MIN-needs-a-fallback rule does not apply and
    # an absent circumstance renders no row (STU-552).
    person = load_base_template()["entity_types"]["PERSON"]
    slots = {s["token"]: s for s in person["infobox"]}
    assert slots["death"]["provenance"] == "extracted-fact"
    assert slots["death"]["obligation"] == "OPT"
    assert "{{{death|}}}" in person["export"]["infobox_source"]


def test_the_stage_is_wired_before_wiki_preparation():
    # STU-512's lesson: without this, the whole feature is deletable with the
    # suite green. Since STU-457 the stage lives in the wiki-preparation
    # pipeline YAML (pre / call / post), no longer in run_wiki.py's PRE_STEPS.
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


def test_death_label_renders_both_fields():
    assert death_label("Durza", "Farthen Dûr", "fr") == "Tué par Durza à Farthen Dûr"
    assert death_label("Durza", "Farthen Dûr", "en") == "Killed by Durza at Farthen Dûr"


def test_death_label_renders_the_agent_alone():
    assert death_label("Durza", None, "fr") == "Tué par Durza"


def test_death_label_renders_the_place_alone():
    # A death with no killer — illness, drowning. "Mort à X" stays true whatever
    # the cause, which is why there is no cause enum.
    assert death_label(None, "Terím", "fr") == "Mort à Terím"


def test_death_label_is_none_without_a_field():
    assert death_label(None, None, "fr") is None
    assert death_label("", "  ", "fr") is None


def test_death_label_falls_back_to_fr_for_an_unknown_lang():
    # chrome_label's own fallback chain; the slot must not vanish for a book
    # whose output_language has no chrome entry.
    assert death_label("Durza", None, "de") == "Tué par Durza"


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


def _gated_rows(quote):
    return [{"name": "Brom", "aliases": [], "snippets": [{"text": quote, "chapter_id": "ch37"}]}]


def _gated_verdict(entry, quote):
    return parse_status_verdict({"status": [entry]}, _gated_rows(quote), _index())


def test_agent_and_place_survive_all_three_gates():
    quote = "Durza's blade took Brom in the side at Farthen Dûr"
    verdicts = _gated_verdict(
        {"name": "Brom", "status": "deceased", "quote": quote, "agent": "Durza", "place": "Farthen Dûr"},
        quote,
    )
    assert verdicts["Brom"] == {
        "status": "deceased",
        "quote": quote,
        "agent": "Durza",
        "place": "Farthen Dûr",
    }


def test_a_name_absent_from_the_quote_is_dropped():
    # Gate 3. The slot asserts a link between two facts; sourcing the halves
    # from two snippets is the model inferring that link.
    quote = "Durza's blade took Brom in the side"
    verdicts = _gated_verdict(
        {"name": "Brom", "status": "deceased", "quote": quote, "agent": "Durza", "place": "Farthen Dûr"},
        quote,
    )
    assert verdicts["Brom"]["agent"] == "Durza"
    assert "place" not in verdicts["Brom"]


def test_a_name_from_a_neighbouring_snippet_is_dropped():
    # Gate 3 again, but the place is real evidence — just not evidence of the
    # death. It must be checked against the quote alone, not the snippet pool.
    quote = "Durza's blade took Brom in the side"
    rows = [
        {
            "name": "Brom",
            "aliases": [],
            "snippets": [
                {"text": quote, "chapter_id": "ch37"},
                {"text": "They rode hard for Farthen Dûr", "chapter_id": "ch36"},
            ],
        }
    ]
    verdicts = parse_status_verdict(
        {"status": [{"name": "Brom", "status": "deceased", "quote": quote, "place": "Farthen Dûr"}]},
        rows,
        _index(),
    )
    assert "place" not in verdicts["Brom"]
    assert verdicts["Brom"]["status"] == "deceased"
    assert verdicts["Brom"]["quote"] == quote


def test_a_name_off_the_roster_is_dropped():
    quote = "Galbatorix's blade took Brom in the side"
    verdicts = _gated_verdict(
        {"name": "Brom", "status": "deceased", "quote": quote, "agent": "Galbatorix"},
        quote,
    )
    assert "agent" not in verdicts["Brom"]


def test_the_roster_is_type_scoped():
    # A PERSON returned as a place is not a place.
    quote = "Brom died with Durza"
    verdicts = _gated_verdict({"name": "Brom", "status": "deceased", "quote": quote, "place": "Durza"}, quote)
    assert "place" not in verdicts["Brom"]


def test_an_alias_renders_the_canonical_name():
    quote = "Captain Westfall struck Brom down"
    verdicts = _gated_verdict(
        {"name": "Brom", "status": "deceased", "quote": quote, "agent": "Captain Westfall"},
        quote,
    )
    assert verdicts["Brom"]["agent"] == "Chaol Westfall"


def test_only_a_deceased_verdict_carries_a_circumstance():
    quote = "Durza hunted Brom through Farthen Dûr"
    verdicts = _gated_verdict(
        {"name": "Brom", "status": "missing", "quote": quote, "agent": "Durza", "place": "Farthen Dûr"},
        quote,
    )
    assert verdicts["Brom"] == {"status": "missing", "quote": quote}


def test_a_dropped_field_never_drops_the_verdict():
    # The asymmetry: a wrong agent costs the circumstance, never the status.
    quote = "Brom is dead"
    verdicts = _gated_verdict(
        {"name": "Brom", "status": "deceased", "quote": quote, "agent": "Galbatorix", "place": "Urû'baen"},
        quote,
    )
    assert verdicts["Brom"] == {"status": "deceased", "quote": quote}


def test_the_name_index_folds_typography_and_case():
    index = build_name_index([{"entity_type": "PLACE", "canonical_name": "Farthen Dûr", "aliases": []}])
    assert index["PLACE"]["farthen dûr"] == "Farthen Dûr"


def test_the_name_index_ignores_types_that_are_not_person_or_place():
    index = build_name_index([{"entity_type": "ORG", "canonical_name": "Varden", "aliases": []}])
    assert index == {"PERSON": {}, "PLACE": {}}


def test_an_agent_that_is_only_a_substring_of_a_quote_word_is_dropped():
    # A spaCy-mistyped common noun ("Son") can sit on the PERSON roster; it must
    # not ground on a word it merely sits inside of, like "per-son".
    quote = "Brom's chest rose one last time, and then was still, a person no more"
    verdicts = _gated_verdict(
        {"name": "Brom", "status": "deceased", "quote": quote, "agent": "Son"},
        quote,
    )
    assert "agent" not in verdicts["Brom"]


def test_a_multiword_agent_still_grounds_after_the_boundary_fix():
    # Guards against the token-boundary fix breaking a real multi-word match.
    quote = "Durza's blade took Brom in the side at Farthen Dûr"
    verdicts = _gated_verdict(
        {"name": "Brom", "status": "deceased", "quote": quote, "place": "Farthen Dûr"},
        quote,
    )
    assert verdicts["Brom"]["place"] == "Farthen Dûr"


def test_an_agent_equal_to_the_dead_character_is_dropped():
    # The subject's own name is the one name guaranteed to clear the quote gate
    # (the snippets are selected because they mention the subject) — it must
    # never render as its own killer.
    quote = "Brom is dead"
    verdicts = _gated_verdict(
        {"name": "Brom", "status": "deceased", "quote": quote, "agent": "Brom"},
        quote,
    )
    assert verdicts["Brom"] == {"status": "deceased", "quote": quote}


def test_a_cache_from_an_older_question_is_not_replayed(tmp_path):
    # STU-552 changed what we ask, not the roster we ask it about. Without the
    # version, a pre-STU-552 cache validates and renders no circumstance forever.
    rows = _gated_rows("Brom is dead")
    path = tmp_path / "entity_status.json"
    path.write_text(
        json.dumps({"version": 1, "roster": rows, "verdicts": {"Brom": {"status": "deceased"}}}),
        encoding="utf-8",
    )
    assert load_cached_status(path, rows) is None


def test_a_cache_without_a_version_is_not_replayed(tmp_path):
    rows = _gated_rows("Brom is dead")
    path = tmp_path / "entity_status.json"
    path.write_text(json.dumps({"roster": rows, "verdicts": {}}), encoding="utf-8")
    assert load_cached_status(path, rows) is None


def test_a_saved_cache_round_trips(tmp_path):
    rows = _gated_rows("Durza's blade took Brom at Farthen Dûr")
    verdicts = {"Brom": {"status": "deceased", "quote": "x", "agent": "Durza"}}
    path = tmp_path / "entity_status.json"
    save_status_cache(path, rows, verdicts)
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == CACHE_VERSION
    assert load_cached_status(path, rows) == verdicts


def test_the_binder_renders_the_circumstance():
    entity = {"death_agent": "Durza", "death_place": "Farthen Dûr"}
    assert _extracted_fact_value(entity, "death", "fr") == "Tué par Durza à Farthen Dûr"


def test_the_binder_omits_the_slot_without_a_circumstance():
    # OPT: `_bind_batch_fields`'s `if value:` drops the token entirely, so a
    # living character gets no Décès row.
    assert _extracted_fact_value({}, "death", "fr") is None
    assert _extracted_fact_value({"status": "alive"}, "death", "fr") is None


def test_wiki_preparation_stamps_the_circumstance_onto_the_batch_entity():
    # The hop the suite cannot see otherwise: unstamp these and every page
    # renders no Décès row with every other test still green.
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
