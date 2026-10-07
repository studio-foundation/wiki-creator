"""STU-753: full-text search over a book's parsed chapters."""
import json

from wiki_creator.book_search import (
    estimate_tokens,
    full_text,
    load_chapters,
    quote_surface,
    search_chapters,
    select_passages,
)


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


def test_quote_surface_carries_both_chapter_variants(tmp_path):
    (tmp_path / "chapters.json").write_text(
        json.dumps({"chapters": {"c1": "He rode north."}}), encoding="utf-8"
    )
    (tmp_path / "chapters_resolved.json").write_text(
        json.dumps({"chapters": {"c1": "Brom rode north."}}), encoding="utf-8"
    )
    surface = quote_surface(tmp_path)
    assert "He rode north." in surface
    assert "Brom rode north." in surface


def test_quote_surface_without_coref_is_the_original_text(tmp_path):
    (tmp_path / "chapters.json").write_text(
        json.dumps({"chapters": {"c1": "He rode north."}}), encoding="utf-8"
    )
    assert "He rode north." in quote_surface(tmp_path)


# --- select_passages (STU-2018) ----------------------------------------------

STATUS_KEYWORDS = ["died", "dead", "buried"]


def _book(n_chapters: int, paragraph: str) -> dict[str, str]:
    return {f"c{n}": "\n\n".join([paragraph] * 5) for n in range(1, n_chapters + 1)}


def test_selector_never_exceeds_the_budget():
    chapters = _book(40, "Brom rode north and spoke at length of the old riders. " * 6)
    for budget in (0, 50, 500, 5000):
        picked = select_passages(chapters, {}, "Brom", [], STATUS_KEYWORDS, budget_tokens=budget)
        assert sum(estimate_tokens(p["text"]) for p in picked) <= budget
    assert picked


def test_selector_caps_a_long_paragraph_around_the_mention():
    text = "filler " * 400 + "Brom died there. " + "filler " * 400
    [passage] = select_passages({"c1": text}, {}, "Brom", [], STATUS_KEYWORDS)
    assert "Brom died" in passage["text"]
    assert len(passage["text"]) <= 800


def test_selector_covers_every_alias():
    chapters = {
        "c1": "The Storyteller sat by the fire.",
        "c2": "Old Brom sharpened his sword.",
        "c3": "Nobody else was there.",
    }
    picked = select_passages(chapters, {}, "Brom", ["Storyteller"], STATUS_KEYWORDS)
    assert [p["chapter"] for p in picked] == ["c1", "c2"]


def test_selector_matches_whole_words_only():
    assert select_passages({"c1": "Bromley went home."}, {}, "Brom", [], []) == []


def test_selector_includes_a_coref_only_passage_once():
    original = {"c1": "Brom rode north.\n\nThen he fell, and he was dead."}
    resolved = {"c1": "Brom rode north.\n\nThen Brom fell, and Brom was dead."}
    picked = select_passages(original, resolved, "Brom", [], STATUS_KEYWORDS)
    assert [p["text"] for p in picked] == ["Brom rode north.", "Then Brom fell, and Brom was dead."]


def test_selector_prefers_keyword_passages_under_a_tight_budget():
    chapters = {"c1": "Brom rode north.\n\nBrom talked.\n\nBrom was buried at dawn."}
    [picked] = select_passages(
        chapters, {}, "Brom", [], STATUS_KEYWORDS,
        budget_tokens=estimate_tokens("Brom was buried at dawn."),
    )
    assert picked["text"] == "Brom was buried at dawn."


def test_selector_spreads_across_chapters_latest_first():
    chapters = _book(10, "Brom rode north.")
    one = estimate_tokens("Brom rode north.")
    picked = select_passages(chapters, {}, "Brom", [], [], budget_tokens=3 * one)
    assert [p["chapter"] for p in picked] == ["c8", "c9", "c10"]


def test_selector_returns_book_order_and_is_deterministic():
    chapters = {
        "c1": "Brom was buried.\n\nBrom spoke.",
        "c2": "Brom spoke again.\n\nBrom died.",
    }
    first = select_passages(chapters, {}, "Brom", [], STATUS_KEYWORDS)
    assert first == select_passages(dict(chapters), {}, "Brom", [], list(STATUS_KEYWORDS))
    assert [p["text"] for p in first] == [
        "Brom was buried.", "Brom spoke.", "Brom spoke again.", "Brom died.",
    ]
