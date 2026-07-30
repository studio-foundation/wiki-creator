import json

from wiki_creator.ground_truth import (
    alias_lookup,
    lint_corpus,
    load_entries,
    resolve_gt_dir,
)

BOOK_TEXT = (
    "Alice followed the White Rabbit down the hole. The Mouse swam by. "
    "The Dormouse slept at the tea party. It was not a breeze."
)


def _write_gt(tmp_path, name, payload):
    (tmp_path / f"{name}.json").write_text(json.dumps(payload))


def test_load_entries_flat_and_nested(tmp_path):
    _write_gt(tmp_path, "alice", {
        "entity": "Alice",
        "canonical_aliases_book1": ["Alice"],
        "known_facts_book1": ["Alice followed the White Rabbit"],
        "forbidden_book1": {"sequel_only": ["Looking-Glass world"]},
    })
    _write_gt(tmp_path, "mice", {
        "_note": "shorter-binding first",
        "mouse": {
            "canonical_aliases_book1": ["the Mouse"],
            "known_facts_book1": ["The Mouse swam by"],
        },
        "dormouse": {
            "canonical_aliases_book1": ["Dormouse"],
            "known_facts_book1": ["The Dormouse slept"],
        },
    })
    entries, by_entity = load_entries(tmp_path)
    assert [e.entity for e in entries] == ["Alice", "the Mouse", "Dormouse"]
    assert entries[0].forbidden == [("Looking-Glass world", "sequel_only")]
    assert "_note" not in by_entity
    assert by_entity["the Mouse"]["known_facts_book1"] == ["The Mouse swam by"]
    assert alias_lookup(entries)["dormouse"] == "Dormouse"


def test_resolve_gt_dir_prefers_tome_subdir(tmp_path):
    series = tmp_path / "series"
    flat = series / "books" / "ground-truth"
    tome = flat / "03-ozma_of_oz"
    tome.mkdir(parents=True)
    (flat / "x.json").write_text("{}")
    (tome / "y.json").write_text("{}")
    assert resolve_gt_dir(series, "03-ozma_of_oz") == tome
    assert resolve_gt_dir(series, "01-other") == flat
    assert resolve_gt_dir(tmp_path / "nope", "01-x") is None


def _entries(tmp_path, payload):
    _write_gt(tmp_path, "gt", payload)
    return load_entries(tmp_path)[0]


def test_lint_flags_missing_aliases_and_facts(tmp_path):
    entries = _entries(tmp_path, {"ghost": {"hallucination_signals": []}})
    findings = lint_corpus(entries, BOOK_TEXT)
    msgs = [m for level, m in findings if level == "FAIL"]
    assert any("no canonical_aliases_book1" in m for m in msgs)
    assert any("no known_facts_book1" in m for m in msgs)


def test_lint_dead_alias_warns_when_another_is_live(tmp_path):
    entries = _entries(tmp_path, {
        "hatter": {
            "canonical_aliases_book1": ["Dormouse", "Mad Dormouse"],
            "known_facts_book1": ["slept"],
        }
    })
    findings = lint_corpus(entries, BOOK_TEXT)
    assert ("WARN", "Dormouse: alias 'Mad Dormouse' absent from the book text") in findings
    assert not any(level == "FAIL" and "absent" in m for level, m in findings)


def test_lint_dead_alias_fails_when_no_alias_is_live(tmp_path):
    entries = _entries(tmp_path, {
        "hatter": {
            "canonical_aliases_book1": ["Mad Hatter"],
            "known_facts_book1": ["tea"],
        }
    })
    findings = lint_corpus(entries, BOOK_TEXT)
    assert ("FAIL", "Mad Hatter: alias 'Mad Hatter' absent from the book text") in findings


def test_lint_forbidden_and_signals(tmp_path):
    entries = _entries(tmp_path, {
        "alice": {
            "canonical_aliases_book1": ["Alice"],
            "known_facts_book1": ["fell"],
            "forbidden_book1": {"not_in_book": ["Aren", "the White Rabbit down"]},
            "hallucination_signals": ["Dinah, kittens", "Alice", "tea party"],
        }
    })
    findings = lint_corpus(entries, BOOK_TEXT)
    fails = [m for level, m in findings if level == "FAIL"]
    assert any("forbidden 'Aren' too short" in m for m in fails)
    assert any("forbidden 'the White Rabbit down' OCCURS" in m for m in fails)
    assert any("contains a comma" in m for m in fails)
    assert any("signal 'Alice' is just the entity name" in m for m in fails)
    assert any("signal 'tea party' OCCURS" in m for m in fails)


def test_lint_alias_collision_warns_across_entities(tmp_path):
    entries = _entries(tmp_path, {
        "mouse": {"canonical_aliases_book1": ["Mouse"], "known_facts_book1": ["swam"]},
        "dormouse": {"canonical_aliases_book1": ["Dormouse"], "known_facts_book1": ["slept"]},
    })
    findings = lint_corpus(entries, BOOK_TEXT)
    assert any(level == "WARN" and "alias collision" in m for level, m in findings)
