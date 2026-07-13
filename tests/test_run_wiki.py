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
    cmds = PRE_STEPS["wiki-resolution"]
    assert any("chapter_summary.py" in " ".join(cmd) for cmd in cmds), (
        "PRE_STEPS['wiki-resolution'] must invoke chapter_summary.py"
    )


def test_pre_steps_wiki_preparation_runs_classify_before_events() -> None:
    """events depend on relationships_classified.json, so classify_relationships.py
    must run before build_event_layer.py."""
    from run_wiki import PRE_STEPS
    assert "wiki-preparation" in PRE_STEPS, "PRE_STEPS must have wiki-preparation entry"
    cmds = PRE_STEPS["wiki-preparation"]
    joined = [" ".join(cmd) for cmd in cmds]
    classify_idx = next(i for i, c in enumerate(joined) if "classify_relationships.py" in c)
    events_idx = next(i for i, c in enumerate(joined) if "build_event_layer.py" in c)
    assert classify_idx < events_idx, (
        "classify_relationships.py must run before build_event_layer.py in PRE_STEPS['wiki-preparation']"
    )


def test_pre_steps_wiki_generation_runs_pages_before_synopsis() -> None:
    """The synopsis (SP4) is generated in the same pre-step batch as the entity
    pages, after generate_wiki_pages.py."""
    from run_wiki import PRE_STEPS
    cmds = PRE_STEPS["wiki-generation"]
    joined = [" ".join(cmd) for cmd in cmds]
    pages_idx = next(i for i, c in enumerate(joined) if "generate_wiki_pages.py" in c)
    synopsis_idx = next(i for i, c in enumerate(joined) if "generate_book_synopsis.py" in c)
    assert pages_idx < synopsis_idx, (
        "generate_wiki_pages.py must run before generate_book_synopsis.py in PRE_STEPS['wiki-generation']"
    )
