"""Tests for run_wiki.py orchestrator configuration."""
import json

import yaml

BOOK_PATH = "library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml"


def _extracted_book(tmp_path, ner: dict) -> str:
    """A book whose extraction ran under `ner`, laid out the way paths.py expects."""
    from wiki_creator.ner import EXTRACTION_CONFIG_FILE, extraction_fingerprint

    books_dir = tmp_path / "author" / "series" / "books"
    books_dir.mkdir(parents=True)
    epub = books_dir / "01-a-book.epub"
    epub.write_bytes(b"not a real epub - only the path is used")
    book_yaml = books_dir / "01-a-book.yaml"
    book_config = {"file_path": str(epub), "ner": ner}
    book_yaml.write_text(yaml.safe_dump(book_config), encoding="utf-8")

    processing = tmp_path / "author" / "series" / "processing_output" / "01-a-book"
    processing.mkdir(parents=True)
    (processing / EXTRACTION_CONFIG_FILE).write_text(
        json.dumps(extraction_fingerprint(book_config)), encoding="utf-8"
    )
    return str(book_yaml)


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


def test_series_mode_runs_each_tome_in_order(monkeypatch) -> None:
    """--series discovers tomes in reading order and runs each through run_book."""
    import run_wiki

    books = ["library/a/s/books/01_one.yaml", "library/a/s/books/02_two.yaml"]
    monkeypatch.setattr(run_wiki, "discover_series_books", lambda d: [__import__("pathlib").Path(b) for b in books])
    calls: list[str] = []
    monkeypatch.setattr(run_wiki, "run_book", lambda book, **kw: calls.append(book))
    monkeypatch.setattr("sys.argv", ["run_wiki.py", "--series", "library/a/s"])

    run_wiki.main()

    assert calls == books, "series mode must run each tome in reading order"


def test_required_files_wiki_extraction_includes_extraction_config() -> None:
    from run_wiki import required_files
    from wiki_creator.ner import EXTRACTION_CONFIG_FILE
    files = required_files(BOOK_PATH)
    assert any(EXTRACTION_CONFIG_FILE in f for f in files["wiki-extraction"]), (
        "an extraction that declares no config cannot be invalidated by a config change (STU-560)"
    )


def test_extraction_config_unchanged_when_book_still_asks_for_it(tmp_path) -> None:
    from run_wiki import extraction_config_changed
    book = _extracted_book(tmp_path, {"invented_names": True, "threshold": 0.3})
    assert not extraction_config_changed(book)


def test_flipping_invented_names_invalidates_the_extraction(tmp_path) -> None:
    """The STU-560 test: flip `ner` on an extracted book, the cache must not stand."""
    from run_wiki import extraction_config_changed
    book = _extracted_book(tmp_path, {"invented_names": False})
    book_config = yaml.safe_load(open(book))
    book_config["ner"] = {"invented_names": True}
    open(book, "w").write(yaml.safe_dump(book_config))
    assert extraction_config_changed(book)


def test_extraction_predating_the_config_is_stale(tmp_path) -> None:
    """The three shipped caches: extracted before anything recorded a backend."""
    from run_wiki import extraction_config_changed
    from wiki_creator.ner import EXTRACTION_CONFIG_FILE
    from wiki_creator.paths import book_paths_from_yaml
    book = _extracted_book(tmp_path, {"invented_names": True})
    (book_paths_from_yaml(book).processing / EXTRACTION_CONFIG_FILE).unlink()
    assert extraction_config_changed(book)


def test_completed_extraction_reruns_when_the_config_changed(tmp_path, monkeypatch) -> None:
    """The skip is `status == completed` + files present; a `ner` flip must break it."""
    import run_wiki

    book = _extracted_book(tmp_path, {"invented_names": False})
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_wiki, "PIPELINES", ["wiki-extraction"])
    monkeypatch.setattr(run_wiki, "check_outputs", lambda pipeline, book_path: [])
    ran: list[str] = []
    monkeypatch.setattr(run_wiki, "run_pipeline", lambda pipeline, book_path, extra_args=None: ran.append(pipeline) or True)
    run_wiki.save_state(book, {"stages": {"wiki-extraction": {"status": "completed"}}})

    run_wiki.run_book(book, restart=None, retries=1, clean=False)
    assert ran == [], "an unchanged config must still skip"

    monkeypatch.setattr(run_wiki, "extraction_config_changed", lambda book_path: True)
    run_wiki.run_book(book, restart=None, retries=1, clean=False)
    assert ran == ["wiki-extraction"]


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
