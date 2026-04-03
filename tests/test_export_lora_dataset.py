"""Tests for scripts/export_lora_dataset.py."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# Import the script as a module
_script_path = Path(__file__).resolve().parent.parent / "scripts" / "export_lora_dataset.py"
_spec = importlib.util.spec_from_file_location("export_lora_dataset", _script_path)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["export_lora_dataset"] = _mod
_spec.loader.exec_module(_mod)

infer_importance = _mod.infer_importance
validate_output = _mod.validate_output
process_fandom_entry = _mod.process_fandom_entry
build_fandom_instruction = _mod.build_fandom_instruction
main_with_args = _mod.main_with_args
MIN_CONTENT_LENGTH = _mod.MIN_CONTENT_LENGTH


class TestInferImportance:
    def test_principal(self):
        assert infer_importance("x" * 2001) == "principal"

    def test_secondary(self):
        assert infer_importance("x" * 501) == "secondary"

    def test_figurant(self):
        assert infer_importance("x" * 100) == "figurant"

    def test_boundaries(self):
        assert infer_importance("x" * 2000) == "secondary"
        assert infer_importance("x" * 500) == "figurant"


class TestValidateOutput:
    def _make(self, **overrides):
        base = {
            "title": "Hero",
            "content": "A" * 60 + "\n\n## Section\n\nMore text here.",
            "entity_type": "PERSON",
            "importance": "secondary",
        }
        base.update(overrides)
        return base

    def test_valid(self):
        assert validate_output(self._make()) is True

    def test_empty_title(self):
        assert validate_output(self._make(title="")) is False

    def test_empty_content(self):
        assert validate_output(self._make(content="")) is False

    def test_short_content(self):
        assert validate_output(self._make(content="Short")) is False

    def test_invalid_entity_type(self):
        assert validate_output(self._make(entity_type="ANIMAL")) is False

    def test_invalid_importance(self):
        assert validate_output(self._make(importance="major")) is False

    def test_non_figurant_needs_header(self):
        content = "A" * 60 + "\n\nNo headers here just plain text."
        assert validate_output(self._make(content=content, importance="secondary")) is False

    def test_figurant_no_header_ok(self):
        content = "A" * 60 + "\n\nNo headers here just plain text."
        assert validate_output(self._make(content=content, importance="figurant")) is True


class TestProcessFandomEntry:
    def test_valid_entry(self):
        entry = {
            "page_title": "Celaena",
            "entity_type": "PERSON",
            "infobox_fields": {"name": "Celaena", "status": "Alive"},
            "content": "'''Celaena''' is an assassin.\n\n## Biography\n\n" + "Story. " * 100,
        }
        result = process_fandom_entry(entry, {})
        assert result is not None
        assert result["instruction"]
        assert result["input"] == ""
        out = json.loads(result["output"])
        assert out["title"] == "Celaena"
        assert out["infobox_fields"]["nom"] == "Celaena"  # normalized

    def test_rejected_short(self):
        entry = {
            "page_title": "Stub",
            "entity_type": "PERSON",
            "infobox_fields": {},
            "content": "Short.",
        }
        assert process_fandom_entry(entry, {}) is None

    def test_known_entity_importance(self):
        entry = {
            "page_title": "Hero",
            "entity_type": "PERSON",
            "infobox_fields": {},
            "content": "'''Hero''' is great.\n\n## Bio\n\n" + "Text. " * 20,
        }
        known = {"Hero": {"importance": "secondary", "type": "PERSON"}}
        result = process_fandom_entry(entry, known)
        assert result is not None
        out = json.loads(result["output"])
        assert out["importance"] == "secondary"


class TestEndToEnd:
    def test_export_with_fixture_data(self, tmp_path):
        fandom_path = tmp_path / "fandom.jsonl"
        entries = [
            {
                "page_title": "Hero",
                "entity_type": "PERSON",
                "infobox_fields": {"name": "Hero", "status": "Alive"},
                "content": "'''Hero''' is the main character.\n\n## Biography\n\nHero did many things in the story. " * 30,
            },
            {
                "page_title": "Village",
                "entity_type": "PLACE",
                "infobox_fields": {"name": "Village"},
                "content": "'''Village''' is a small town.\n\n## Description\n\nA quiet place in the mountains with old stone houses.",
            },
            {
                "page_title": "Stub",
                "entity_type": "PERSON",
                "infobox_fields": {},
                "content": "Short.",
            },
        ]
        with open(fandom_path, "w") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")

        output_dir = tmp_path / "output"
        main_with_args(fandom_jsonl=fandom_path, batch_dir=None, wiki_pages=None, gold_jsonl=None, output_dir=output_dir)

        assert (output_dir / "train.jsonl").exists()
        assert (output_dir / "eval.jsonl").exists()
        assert (output_dir / "export_report.json").exists()

        with open(output_dir / "export_report.json") as f:
            report = json.load(f)
        assert report["fandom_total"] == 3
        assert report["fandom_rejected"] == 1
        assert report["fandom_accepted"] == 2

        with open(output_dir / "eval.jsonl") as f:
            eval_lines = [json.loads(l) for l in f]
        assert len(eval_lines) == 1
        assert json.loads(eval_lines[0]["output"])["title"] == "Hero"

        with open(output_dir / "train.jsonl") as f:
            train_lines = [json.loads(l) for l in f]
        assert len(train_lines) == 1
        assert json.loads(train_lines[0]["output"])["title"] == "Village"
