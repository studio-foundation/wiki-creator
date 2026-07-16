"""STU-488: per-tome entity status (the `status` / `death` infobox slots)."""
from wiki_creator.entity_status import (
    DEFAULT_STATUS,
    SNIPPETS_PER_ENTITY,
    STATUS_VALUES,
    roster_rows,
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
