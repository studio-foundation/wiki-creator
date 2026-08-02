"""STU-753: full-text search over a book's parsed chapters."""
import json

from wiki_creator.book_search import full_text, load_chapters, search_chapters


def test_finds_a_literal_phrase():
    chapters = {"c1": "Brom rode north with Eragon."}
    [hit] = search_chapters(chapters, "Eragon")
    assert hit["chapter_id"] == "c1"
    assert "Eragon" in hit["text"]


def test_case_insensitive():
    chapters = {"c1": "BROM rode north."}
    assert search_chapters(chapters, "brom")


def test_no_match_returns_empty():
    assert search_chapters({"c1": "Eragon rode on."}, "Durza") == []


def test_empty_query_returns_empty():
    assert search_chapters({"c1": "Eragon rode on."}, "") == []
    assert search_chapters({"c1": "Eragon rode on."}, "   ") == []


def test_latest_chapter_first():
    chapters = {"c1": "Brom appears.", "c40": "Brom appears again.", "c12": "Brom appears too."}
    hits = search_chapters(chapters, "Brom")
    assert [h["chapter_id"] for h in hits] == ["c40", "c12", "c1"]


def test_one_hit_per_chapter_even_with_many_occurrences():
    chapters = {"c1": "Brom. Brom. Brom. Brom."}
    assert len(search_chapters(chapters, "Brom")) == 1


def test_caps_at_max_results():
    chapters = {f"c{n}": "Brom appears." for n in range(20)}
    assert len(search_chapters(chapters, "Brom", max_results=3)) == 3


def test_curly_quote_source_matches_straight_query():
    chapters = {"c1": "‘Brom’s dead,’ said Eragon."}
    assert search_chapters(chapters, "Brom's dead")


def test_snippet_offsets_are_correct_in_the_original_text():
    # A regression guard on the offset-preserving fold: `search_chapters` must
    # slice the ORIGINAL text at the match position, not a normalized copy
    # whose collapsed whitespace would shift every offset.
    chapters = {"c1": "Long lead-in text.\n\n\nBrom died at dawn.\n\n\nLong trailing text."}
    [hit] = search_chapters(chapters, "Brom died", context_chars=20)
    assert "Brom died" in hit["text"]


def test_snippet_is_a_window_around_the_match():
    chapters = {"c1": "x" * 500 + "Brom died at dawn." + "y" * 500}
    [hit] = search_chapters(chapters, "Brom died", context_chars=50)
    assert len(hit["text"]) < 200
    assert "Brom died" in hit["text"]


def test_load_chapters_reads_the_artifact(tmp_path):
    (tmp_path / "chapters.json").write_text(
        json.dumps({"chapters": {"c1": "Brom rode north."}}), encoding="utf-8"
    )
    assert load_chapters(tmp_path) == {"c1": "Brom rode north."}


def test_load_chapters_is_a_miss_not_a_crash(tmp_path):
    assert load_chapters(tmp_path) == {}
    (tmp_path / "chapters.json").write_text("{not json", encoding="utf-8")
    assert load_chapters(tmp_path) == {}


def test_full_text_joins_every_chapter():
    assert full_text({"c1": "Brom rode.", "c2": "Eragon walked."}) == "Brom rode.\nEragon walked."


def test_full_text_of_no_chapters_is_empty():
    assert full_text({}) == ""


def test_load_chapters_prefers_the_coref_resolved_variant(tmp_path):
    (tmp_path / "chapters.json").write_text(
        json.dumps({"chapters": {"c1": "He rode north."}}), encoding="utf-8"
    )
    (tmp_path / "chapters_resolved.json").write_text(
        json.dumps({"chapters": {"c1": "Brom rode north."}}), encoding="utf-8"
    )
    assert load_chapters(tmp_path) == {"c1": "Brom rode north."}


def test_load_chapters_falls_back_when_resolved_variant_is_malformed(tmp_path):
    (tmp_path / "chapters.json").write_text(
        json.dumps({"chapters": {"c1": "Brom rode north."}}), encoding="utf-8"
    )
    (tmp_path / "chapters_resolved.json").write_text("{not json", encoding="utf-8")
    assert load_chapters(tmp_path) == {"c1": "Brom rode north."}
