import json
import pytest
from unittest.mock import patch, MagicMock
from scripts.classify_relationships import call_ollama, classify_pair


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
