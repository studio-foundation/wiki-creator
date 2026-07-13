import pytest
from dataclasses import dataclass, field
from typing import Literal
from wiki_creator import studio_io
from wiki_creator.studio_io import ArtifactSchemaError, to_dict, from_dict


@dataclass
class Leaf:
    name: str
    score: float
    tag: Literal["a", "b"] = "a"
    note: str | None = None
    items: list[str] = field(default_factory=list)


@dataclass
class Nest:
    leaf: Leaf
    leaves: list[Leaf] = field(default_factory=list)


def test_roundtrip_dataclass():
    n = Nest(leaf=Leaf(name="x", score=1.0), leaves=[Leaf(name="y", score=2.0, tag="b")])
    assert from_dict(Nest, to_dict(n)) == n


def test_roundtrip_list_container():
    data = [Leaf(name="x", score=1.0), Leaf(name="y", score=2.0)]
    assert from_dict(list[Leaf], to_dict(data)) == data


def test_roundtrip_dict_container():
    data = {"a": Leaf(name="x", score=1.0)}
    assert from_dict(dict[str, Leaf], to_dict(data)) == data


def test_missing_required_raises():
    with pytest.raises(ArtifactSchemaError, match="score"):
        from_dict(Leaf, {"name": "x"})


def test_unknown_key_raises():
    with pytest.raises(ArtifactSchemaError, match="drifted"):
        from_dict(Leaf, {"name": "x", "score": 1.0, "drifted": 9})


def test_type_mismatch_raises():
    with pytest.raises(ArtifactSchemaError, match="score"):
        from_dict(Leaf, {"name": "x", "score": "not-a-number"})


def test_literal_violation_raises():
    with pytest.raises(ArtifactSchemaError, match="tag"):
        from_dict(Leaf, {"name": "x", "score": 1.0, "tag": "z"})


def test_optional_none_ok():
    assert from_dict(Leaf, {"name": "x", "score": 1.0, "note": None}).note is None


def test_optional_type_mismatch_raises():
    with pytest.raises(ArtifactSchemaError, match="note"):
        from_dict(Leaf, {"name": "x", "score": 1.0, "note": 123})


def test_int_accepted_for_float():
    assert from_dict(Leaf, {"name": "x", "score": 1}).score == 1.0


def test_save_load_roundtrip(tmp_path):
    p = tmp_path / "a.json"
    n = Nest(leaf=Leaf(name="x", score=1.0))
    studio_io.save_artifact(p, n, Nest)
    assert studio_io.load_artifact(p, Nest) == n


def test_save_rejects_offschema(tmp_path):
    # obj whose serialized form violates schema cannot be written
    bad = Leaf(name="x", score=1.0, tag="a")
    object.__setattr__(bad, "tag", "z")
    with pytest.raises(ArtifactSchemaError):
        studio_io.save_artifact(tmp_path / "b.json", bad, Leaf)
