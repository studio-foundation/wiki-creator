"""Subprocess tests for scripts/write_registry.py (STU-441, write-registry stage)."""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "write_registry.py"


def _book_tree(tmp_path: Path) -> tuple[Path, Path]:
    """Minimal library layout: returns (epub_path, processing_dir)."""
    books = tmp_path / "library" / "author" / "series" / "books"
    books.mkdir(parents=True)
    epub = books / "01-book.epub"
    epub.write_bytes(b"")
    processing = tmp_path / "library" / "author" / "series" / "processing_output" / "01-book"
    processing.mkdir(parents=True)
    return epub, processing


def _artifacts() -> tuple[dict, dict, dict]:
    splits = {
        "singles_resolved": [],
        "by_type": {},
        "stats": {},
    }
    alias_output = {
        "entities": [
            {
                "canonical_name": "Crown Prince",
                "type": "PERSON",
                "total_mentions": 1,
                "chapters_present": 1,
                "importance": "principal",
                "aliases": ["Crown Prince"],
                "source_ids": ["e_crown_prince"],
                "relevant": True,
            },
            {
                "canonical_name": "Perrington",
                "type": "PERSON",
                "total_mentions": 2,
                "chapters_present": 1,
                "importance": "principal",
                "aliases": ["Duke Perrington", "Perrington"],
                "source_ids": ["e_perrington"],
                "relevant": True,
            },
        ],
        "relationships": [],
        "narrator": None,
        "stats": {"merges_applied": 0},
    }
    persons_full = {
        "e_crown_prince": {
            "type": "PERSON",
            "raw_mentions": ["Crown Prince"],
            "first_seen": "ch02",
            "mention_count": 1,
            "mentions_by_chapter": {"ch02": ["The Crown Prince sat with Perrington."]},
        },
        "e_perrington": {
            "type": "PERSON",
            "raw_mentions": ["Perrington", "Duke Perrington"],
            "first_seen": "ch02",
            "mention_count": 2,
            "mentions_by_chapter": {"ch02": ["Perrington scowled at the competitors."]},
        },
    }
    return splits, alias_output, persons_full


def _run(payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )


def test_write_registry_writes_registry_json(tmp_path):
    epub, processing = _book_tree(tmp_path)
    splits, alias_output, persons_full = _artifacts()
    (processing / "splits.json").write_text(json.dumps(splits), encoding="utf-8")
    (processing / "persons_full.json").write_text(json.dumps(persons_full), encoding="utf-8")

    result = _run(
        {
            "additional_context": f"file_path: {epub}\n",
            "previous_outputs": {"entity-classification": alias_output},
        }
    )
    assert result.returncode == 0, result.stderr

    out = json.loads(result.stdout)
    assert out["registry"]["entities"] == 2
    assert out["registry"]["decisions"] >= 1

    saved = json.loads((processing / "registry.json").read_text(encoding="utf-8"))
    assert saved["version"] == 1
    assert {e["entity_id"] for e in saved["entities"]} == {"crown_prince", "perrington"}
    # mentions were rebuilt from persons_full.json
    perrington = [e for e in saved["entities"] if e["entity_id"] == "perrington"][0]
    assert perrington["mentions"][0]["chapter_id"] == "ch02"


def test_write_registry_falls_back_to_entities_classified(tmp_path):
    epub, processing = _book_tree(tmp_path)
    splits, alias_output, _ = _artifacts()
    (processing / "splits.json").write_text(json.dumps(splits), encoding="utf-8")
    (processing / "entities_classified.json").write_text(
        json.dumps(alias_output), encoding="utf-8"
    )

    result = _run({"additional_context": f"file_path: {epub}\n", "previous_outputs": {}})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["registry"]["entities"] == 2
    assert (processing / "registry.json").exists()


def test_live_and_resume_paths_agree_on_entity_type(tmp_path):
    """Option B (STU-441): the registry reads the entity-classification set on
    both the live path (stage output in memory) and the resume path
    (entities_classified.json on disk). Both must yield the same entity_type for
    every entity, so a book's registry doesn't drift between run modes.

    The disk file carries classification-refined types (here 'Perrington' demoted
    to OTHER); the in-memory stage output is the same payload — the produced
    registry.json must be identical.
    """
    epub, processing = _book_tree(tmp_path)
    splits, classified, persons_full = _artifacts()
    # Simulate entity-classification having refined a type.
    classified["entities"][1]["type"] = "OTHER"
    (processing / "splits.json").write_text(json.dumps(splits), encoding="utf-8")
    (processing / "persons_full.json").write_text(json.dumps(persons_full), encoding="utf-8")
    (processing / "entities_classified.json").write_text(
        json.dumps(classified), encoding="utf-8"
    )

    # Live path: stage output present in previous_outputs.
    live = _run(
        {
            "additional_context": f"file_path: {epub}\n",
            "previous_outputs": {"entity-classification": classified},
        }
    )
    assert live.returncode == 0, live.stderr
    live_registry = json.loads((processing / "registry.json").read_text(encoding="utf-8"))

    # Resume path: no stage output, falls back to entities_classified.json on disk.
    resume = _run(
        {"additional_context": f"file_path: {epub}\n", "previous_outputs": {}}
    )
    assert resume.returncode == 0, resume.stderr
    resume_registry = json.loads((processing / "registry.json").read_text(encoding="utf-8"))

    live_types = {e["entity_id"]: e["entity_type"] for e in live_registry["entities"]}
    resume_types = {e["entity_id"]: e["entity_type"] for e in resume_registry["entities"]}
    assert live_types == resume_types
    assert live_types["perrington"] == "OTHER"  # refined type is reflected
    # Whole artifact is identical across run modes.
    assert live_registry == resume_registry


def test_write_registry_stamps_book_id_provenance(tmp_path):
    """STU-484: every mention/record carries book_id derived from the book slug."""
    epub, processing = _book_tree(tmp_path)
    splits, alias_output, persons_full = _artifacts()
    (processing / "splits.json").write_text(json.dumps(splits), encoding="utf-8")
    (processing / "persons_full.json").write_text(json.dumps(persons_full), encoding="utf-8")

    result = _run(
        {
            "additional_context": f"file_path: {epub}\n",
            "previous_outputs": {"entity-classification": alias_output},
        }
    )
    assert result.returncode == 0, result.stderr

    saved = json.loads((processing / "registry.json").read_text(encoding="utf-8"))
    for entity in saved["entities"]:
        assert entity["books"] == ["01-book"]
        assert entity["first_book"] == "01-book"
        for mention in entity["mentions"]:
            assert mention["book_id"] == "01-book"


def test_write_registry_fails_without_file_path():
    result = _run({"additional_context": "", "previous_outputs": {}})
    assert result.returncode == 1
    assert "file_path" in json.loads(result.stdout)["error"]


def _second_book_tree(tmp_path: Path) -> tuple[Path, Path]:
    """Second tome in the same series as _book_tree."""
    books = tmp_path / "library" / "author" / "series" / "books"
    books.mkdir(parents=True, exist_ok=True)
    epub = books / "02-book.epub"
    epub.write_bytes(b"")
    processing = tmp_path / "library" / "author" / "series" / "processing_output" / "02-book"
    processing.mkdir(parents=True)
    return epub, processing


def _run_book(epub: Path, processing: Path, alias_output: dict, persons_full: dict) -> dict:
    splits, _, _ = _artifacts()
    (processing / "splits.json").write_text(json.dumps(splits), encoding="utf-8")
    (processing / "persons_full.json").write_text(json.dumps(persons_full), encoding="utf-8")
    result = _run(
        {
            "additional_context": f"file_path: {epub}\n",
            "previous_outputs": {"entity-classification": alias_output},
        }
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_write_registry_accumulates_series_registry(tmp_path):
    """STU-485: tome 1 then tome 2 → series registry at library/<author>/<series>/
    registry.json with stable ids, unioned provenance, and a per-tome delta."""
    epub1, processing1 = _book_tree(tmp_path)
    _, alias_output, persons_full = _artifacts()
    out1 = _run_book(epub1, processing1, alias_output, persons_full)
    assert out1["series_registry"]["added"] == 2
    assert out1["series_registry"]["matched"] == 0

    series_path = tmp_path / "library" / "author" / "series" / "registry.json"
    assert Path(out1["series_registry"]["path"]) == series_path
    assert series_path.exists()

    # Tome 2: Perrington returns (new alias), Kaltain is new.
    epub2, processing2 = _second_book_tree(tmp_path)
    alias_output2 = {
        "entities": [
            {
                "canonical_name": "Perrington",
                "type": "PERSON",
                "aliases": ["Perrington", "His Grace"],
                "source_ids": ["e_perrington"],
                "relevant": True,
            },
            {
                "canonical_name": "Kaltain",
                "type": "PERSON",
                "aliases": ["Kaltain"],
                "source_ids": ["e_kaltain"],
                "relevant": True,
            },
        ],
        "narrator": None,
        "stats": {"merges_applied": 0},
    }
    persons_full2 = {
        "e_perrington": {
            "type": "PERSON",
            "raw_mentions": ["Perrington", "His Grace"],
            "first_seen": "ch01",
            "mention_count": 1,
            "mentions_by_chapter": {"ch01": ["Perrington returned to the keep."]},
        },
        "e_kaltain": {
            "type": "PERSON",
            "raw_mentions": ["Kaltain"],
            "first_seen": "ch03",
            "mention_count": 1,
            "mentions_by_chapter": {"ch03": ["Kaltain smiled coldly."]},
        },
    }
    out2 = _run_book(epub2, processing2, alias_output2, persons_full2)
    assert out2["series_registry"]["matched"] == 1
    assert out2["series_registry"]["added"] == 1

    series = json.loads(series_path.read_text(encoding="utf-8"))
    by_id = {e["entity_id"]: e for e in series["entities"]}
    # Stable id across tomes, provenance and aliases unioned.
    assert set(by_id) == {"crown_prince", "perrington", "kaltain"}
    assert by_id["perrington"]["books"] == ["01-book", "02-book"]
    assert by_id["perrington"]["first_book"] == "01-book"
    assert "His Grace" in by_id["perrington"]["aliases"]
    assert {m["book_id"] for m in by_id["perrington"]["mentions"]} == {"01-book", "02-book"}
    assert by_id["kaltain"]["books"] == ["02-book"]
    # Accumulation decision traced.
    accumulated = [d for d in series["decisions"] if d["strategy"] == "series_accumulation"]
    assert [d["inputs"] for d in accumulated] == [["perrington", "his_grace"]]

    # Per-tome delta written next to the book registry.
    delta = json.loads((processing2 / "registry_delta.json").read_text(encoding="utf-8"))
    assert delta["book_ids"] == ["02-book"]
    assert delta["matched"] == [
        {"book_entity_id": "perrington", "series_entity_id": "perrington"}
    ]
    assert [e["series_entity_id"] for e in delta["added"]] == ["kaltain"]


def _tome_entities(entity_type: str) -> dict:
    return {
        "entities": [
            {
                "canonical_name": "Terrasen",
                "type": entity_type,
                "aliases": ["Terrasen"],
                "source_ids": ["e_terrasen"],
                "relevant": True,
            }
        ],
        "relationships": [],
        "narrator": None,
        "stats": {"merges_applied": 0},
    }


def _tome_full(entity_type: str) -> dict:
    return {
        "e_terrasen": {
            "type": entity_type,
            "raw_mentions": ["Terrasen"],
            "first_seen": "ch01",
            "mention_count": 1,
            "mentions_by_chapter": {"ch01": ["Terrasen lay to the north."]},
        }
    }


def _accumulate_two_tomes(tmp_path: Path, canon: str | None) -> dict:
    """Tome 1 says PLACE, tome 2 says PERSON; returns the series record."""
    series_dir = tmp_path / "library" / "author" / "series"
    epub1, processing1 = _book_tree(tmp_path)
    if canon is not None:
        (series_dir / "canon.yaml").write_text(canon, encoding="utf-8")
    _run_book(epub1, processing1, _tome_entities("PLACE"), _tome_full("PLACE"))

    epub2, processing2 = _second_book_tree(tmp_path)
    _run_book(epub2, processing2, _tome_entities("PERSON"), _tome_full("PERSON"))

    series = json.loads((series_dir / "registry.json").read_text(encoding="utf-8"))
    return {e["entity_id"]: e for e in series["entities"]}["terrasen"]


_CANON_OVERRIDE = """canon:
  primary_source: epub
  sources:
    - id: epub_01
      type: epub
      path: books/01-book.epub
    - id: epub_02
      type: epub
      path: books/02-book.epub
  cross_tome:
    later_tome_overrides: true
"""


def test_write_registry_cross_tome_override_follows_canon(tmp_path):
    """STU-512 wiring: canon.cross_tome.later_tome_overrides reaches accumulate.

    Unwire later_tome_overrides in main() and this test fails.
    """
    assert _accumulate_two_tomes(tmp_path, _CANON_OVERRIDE)["entity_type"] == "PERSON"


def test_write_registry_cross_tome_keeps_earlier_tome_without_canon(tmp_path):
    """No canon.yaml → historical rule: the earlier tome's type wins."""
    assert _accumulate_two_tomes(tmp_path, None)["entity_type"] == "PLACE"


def test_write_registry_skips_accumulation_on_corrupt_series_registry(tmp_path):
    """An unreadable series registry must not be clobbered."""
    epub, processing = _book_tree(tmp_path)
    _, alias_output, persons_full = _artifacts()
    series_path = tmp_path / "library" / "author" / "series" / "registry.json"
    series_path.write_text("{not json", encoding="utf-8")

    out = _run_book(epub, processing, alias_output, persons_full)
    assert out["series_registry"] is None
    assert out["registry"]["entities"] == 2  # book registry still written
    assert series_path.read_text(encoding="utf-8") == "{not json"
    assert not (processing / "registry_delta.json").exists()
