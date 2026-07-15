import json

from wiki_creator.chapters import is_frontmatter_chapter
from wiki_creator.section_filter import (
    OPENING_CHARS,
    apply_frontmatter,
    load_cached_drops,
    parse_drop_verdict,
    render_section_list,
    save_drop_cache,
    section_rows,
)


def _chapter(chapter_id, title="", content="x" * 500):
    return {"id": chapter_id, "title": title, "content": content}


# --- section_rows ---


def test_rows_follow_spine_order_and_carry_char_counts():
    chapters = [_chapter("cop", "Copyright", "c" * 1730), _chapter("c01", "Chapter 1", "a" * 5704)]
    rows = section_rows(chapters)
    assert [(r["id"], r["chars"]) for r in rows] == [("cop", 1730), ("c01", 5704)]


def test_row_title_falls_back_to_id_when_absent():
    assert section_rows([_chapter("annotation", "")])[0]["title"] == "annotation"


def test_row_carries_an_opening_snippet():
    """The title alone cannot tell an in-world 'Argument' from a marketing synopsis."""
    chapters = [_chapter("fm2", "Argument", "Behold, the land of Alagaesia, vast and verdant. " * 40)]
    opening = section_rows(chapters)[0]["opening"]
    assert opening.startswith("Behold, the land of Alagaesia")
    assert len(opening) <= OPENING_CHARS


def test_opening_is_single_line_and_pipe_free():
    """The rendered row is pipe-delimited; the snippet must not forge a column."""
    chapters = [_chapter("c01", "Chapter 1", "First line\nsecond | third\tfourth")]
    assert section_rows(chapters)[0]["opening"] == "First line second / third fourth"


def test_render_lists_one_row_per_section():
    rendered = render_section_list([{"id": "cop", "title": "Copyright", "chars": 1730, "opening": "Copyright (c) 2023"}])
    assert rendered == "cop | Copyright | 1730 | Copyright (c) 2023"


# --- parse_drop_verdict ---


def test_parses_drop_ids_with_reasons():
    payload = {"drop": [{"id": "annotation", "reason": "back-cover blurb"}]}
    assert parse_drop_verdict(payload, {"annotation", "c01"}) == {"annotation": "back-cover blurb"}


def test_accepts_raw_json_string():
    payload = json.dumps({"drop": [{"id": "cop", "reason": "copyright page"}]})
    assert parse_drop_verdict(payload, {"cop"}) == {"cop": "copyright page"}


def test_unknown_ids_are_ignored():
    """A hallucinated id must not drop anything — it maps to no real chapter."""
    payload = {"drop": [{"id": "ghost", "reason": "invented"}, {"id": "cop", "reason": "copyright"}]}
    assert parse_drop_verdict(payload, {"cop"}) == {"cop": "copyright"}


def test_malformed_response_drops_nothing():
    """Bias toward keep: an unparseable verdict must never delete a chapter."""
    for payload in ["not json", "", None, {}, {"drop": "everything"}, {"drop": [{"no_id": 1}]}, []]:
        assert parse_drop_verdict(payload, {"cop", "c01"}) == {}


def test_reason_is_optional():
    assert parse_drop_verdict({"drop": [{"id": "cop"}]}, {"cop"}) == {"cop": ""}


# --- apply_frontmatter ---


def test_tags_only_listed_sections_and_reports_them():
    chapters = [_chapter("cop", "Copyright"), _chapter("c01", "Chapter 1")]
    dropped = apply_frontmatter(chapters, {"cop": "copyright page"})

    assert dropped == [{"id": "cop", "title": "Copyright", "reason": "copyright page"}]
    assert chapters[0]["frontmatter"] is True
    assert is_frontmatter_chapter(chapters[0]) is True
    assert is_frontmatter_chapter(chapters[1]) is False


def test_untagged_chapter_is_not_frontmatter():
    chapters = [_chapter("c01", "Chapter 1")]
    apply_frontmatter(chapters, {})
    assert is_frontmatter_chapter(chapters[0]) is False


def test_chapters_are_tagged_never_removed():
    """chapters.json must keep every section; the filter only annotates."""
    chapters = [_chapter("cop", "Copyright"), _chapter("c01", "Chapter 1")]
    apply_frontmatter(chapters, {"cop": "copyright page"})
    assert [c["id"] for c in chapters] == ["cop", "c01"]
    assert chapters[0]["content"] == "x" * 500


# --- cache ---


def test_cache_round_trips(tmp_path):
    path = tmp_path / "section_filter.json"
    rows = section_rows([_chapter("cop", "Copyright"), _chapter("c01", "Chapter 1")])
    save_drop_cache(path, rows, {"cop": "copyright page"})
    assert load_cached_drops(path, rows) == {"cop": "copyright page"}


def test_cache_misses_when_the_section_list_changed(tmp_path):
    """WIKI_MAX_CHAPTERS truncates the book — a verdict for another list must not apply."""
    path = tmp_path / "section_filter.json"
    full = section_rows([_chapter("cop", "Copyright"), _chapter("c01", "Chapter 1")])
    save_drop_cache(path, full, {"cop": "copyright page"})

    truncated = section_rows([_chapter("cop", "Copyright")])
    assert load_cached_drops(path, truncated) is None


def test_absent_cache_is_a_miss(tmp_path):
    rows = section_rows([_chapter("c01", "Chapter 1")])
    assert load_cached_drops(tmp_path / "nope.json", rows) is None


def test_unreadable_cache_is_a_miss_not_a_crash(tmp_path):
    path = tmp_path / "section_filter.json"
    path.write_text("{ truncated", encoding="utf-8")
    rows = section_rows([_chapter("c01", "Chapter 1")])
    assert load_cached_drops(path, rows) is None
