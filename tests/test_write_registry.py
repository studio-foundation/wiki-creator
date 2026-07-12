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
        "PERSON": [],
        "PLACE": [],
        "ORG": [],
        "EVENT": [],
        "OTHER": [],
        "stats": {},
    }
    alias_output = {
        "entities": [
            {
                "canonical_name": "Crown Prince",
                "type": "PERSON",
                "aliases": ["Crown Prince"],
                "source_ids": ["e_crown_prince"],
                "relevant": True,
            },
            {
                "canonical_name": "Perrington",
                "type": "PERSON",
                "aliases": ["Duke Perrington", "Perrington"],
                "source_ids": ["e_perrington"],
                "relevant": True,
            },
        ],
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
            "previous_outputs": {"alias-resolution": alias_output},
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


def test_write_registry_fails_without_file_path():
    result = _run({"additional_context": "", "previous_outputs": {}})
    assert result.returncode == 1
    assert "file_path" in json.loads(result.stdout)["error"]
