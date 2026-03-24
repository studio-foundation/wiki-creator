import json
import pytest
from pathlib import Path
from wiki_creator.character_graph import CharacterGraph, IndirectRelationship

FIXTURES = Path(__file__).parent / "fixtures" / "character_graph"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_from_json_raises_on_incompatible_format():
    with pytest.raises(ValueError, match="incompatible"):
        CharacterGraph.from_json({"nodes": [], "links": []})


def test_from_json_roundtrip_empty():
    g = CharacterGraph()
    data = g.to_json()
    g2 = CharacterGraph.from_json(data)
    assert g2.to_json() == data
