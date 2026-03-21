"""Tests for run_wiki.py orchestrator configuration."""

BOOK_PATH = "library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml"


def test_required_files_wiki_resolution_includes_chapter_summaries() -> None:
    from run_wiki import required_files
    files = required_files(BOOK_PATH)
    assert any("chapter_summaries.json" in f for f in files["wiki-resolution"]), (
        "required_files['wiki-resolution'] must include chapter_summaries.json"
    )


def test_clean_files_wiki_extraction_includes_chapter_summaries() -> None:
    from run_wiki import clean_files
    files = clean_files(BOOK_PATH)
    assert any("chapter_summaries.json" in f for f in files["wiki-extraction"]), (
        "clean_files['wiki-extraction'] must include chapter_summaries.json "
        "so --clean --restart wiki-extraction deletes it"
    )


def test_clean_files_wiki_resolution_excludes_chapter_summaries() -> None:
    from run_wiki import clean_files
    files = clean_files(BOOK_PATH)
    assert not any("chapter_summaries.json" in f for f in files.get("wiki-resolution", [])), (
        "clean_files['wiki-resolution'] must NOT include chapter_summaries.json "
        "so --clean --restart wiki-resolution preserves it"
    )


def test_pre_steps_wiki_resolution_runs_chapter_summary() -> None:
    from run_wiki import PRE_STEPS
    assert "wiki-resolution" in PRE_STEPS, "PRE_STEPS must have wiki-resolution entry"
    cmd = PRE_STEPS["wiki-resolution"]
    assert "chapter_summary.py" in " ".join(cmd), (
        "PRE_STEPS['wiki-resolution'] must invoke chapter_summary.py"
    )
