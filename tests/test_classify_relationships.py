import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from scripts.classify_relationships import call_ollama, classify_pair, _load_done_keys, _save


def test_call_ollama_returns_response_string():
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"response": "hello"}).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = call_ollama("prompt", model="qwen2.5", timeout=10)
    assert result == "hello"


def test_call_ollama_returns_none_on_error():
    with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
        result = call_ollama("prompt", model="qwen2.5", timeout=10)
    assert result is None


def test_classify_pair_dry_run_returns_pair_unchanged():
    pair = {"entity_a": "Celaena", "entity_b": "Dorian", "cooccurrence_count": 5, "sample_contexts": []}
    result = classify_pair(pair, model="qwen2.5", novel_summary=None, dry_run=True)
    assert result == pair
    assert "relationship_type" not in result


def test_load_done_keys_returns_empty_when_file_missing():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        result, pairs = _load_done_keys(tmp_path / "nonexistent.json")
        assert result == set()
        assert pairs == []


def test_load_done_keys_returns_existing_pairs():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        output = tmp_path / "out.json"
        data = {
            "relationships": [
                {"entity_a": "A", "entity_b": "B", "relationship_type": "ami"},
            ]
        }
        output.write_text(json.dumps(data))
        keys, pairs = _load_done_keys(output)
        assert ("A", "B") in keys
        assert len(pairs) == 1


def test_save_writes_valid_json():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        output = tmp_path / "out.json"
        base = {"entities": [], "stats": {}, "narrator": None}
        pairs = [{"entity_a": "A", "entity_b": "B"}]
        _save(output, base, pairs)
        written = json.loads(output.read_text())
        assert written["relationships"] == pairs
        assert written["entities"] == []
