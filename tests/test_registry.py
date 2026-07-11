"""Tests for wiki_creator/registry.py — EntityRegistry pas 1 (STU-441)."""
import pytest

from wiki_creator.registry import (
    EntityRecord,
    MergeDecision,
    Mention,
    entity_slug,
)


def test_entity_slug_is_deterministic_lowercase_ascii():
    assert entity_slug("Chaol Westfall") == "chaol_westfall"
    assert entity_slug("Chaol Westfall") == entity_slug("Chaol Westfall")
    # accents fold to ascii, punctuation collapses to single underscore
    assert entity_slug("Céfiro—Dorn!") == "cefiro_dorn"
    # leading/trailing separators stripped
    assert entity_slug("  The Guard  ") == "the_guard"
    # degenerate input still yields a usable id
    assert entity_slug("") == "unnamed"
    assert entity_slug("!!!") == "unnamed"


def test_mention_defaults_reflect_reconstruction_gaps():
    m = Mention(surface="Perrington", chapter_id="ch02")
    assert m.source == "ner"
    assert m.start is None and m.end is None
    assert m.raw_label is None and m.context is None


def test_merge_decision_is_frozen():
    d = MergeDecision(
        decision_id="d_abc",
        strategy="pure_title",
        inputs=("perrington", "duke_perrington"),
        evidence="snippet",
        confidence="high",
    )
    assert d.reversible is True
    with pytest.raises(AttributeError):
        d.strategy = "manual"  # type: ignore[misc]


def test_entity_record_defaults():
    r = EntityRecord(entity_id="perrington", canonical_name="Perrington", entity_type="PERSON")
    assert r.aliases == [] and r.mentions == [] and r.decisions == []


from wiki_creator.registry import Registry, _decision_id


def _record_with_decision(
    entity_id: str,
    canonical: str,
    aliases: list[str],
    strategy: str = "extraction_grouping",
) -> tuple[EntityRecord, dict[str, MergeDecision]]:
    """Build a valid EntityRecord + the decisions justifying its non-canonical aliases."""
    decisions: dict[str, MergeDecision] = {}
    decision_ids: list[str] = []
    for alias in aliases:
        if alias == canonical:
            continue
        d_id = _decision_id(strategy, (entity_id, entity_slug(alias)), f"test:{alias}")
        decisions[d_id] = MergeDecision(
            decision_id=d_id,
            strategy=strategy,
            inputs=(entity_id, entity_slug(alias)),
            evidence=f"test:{alias}",
            confidence="medium",
        )
        decision_ids.append(d_id)
    record = EntityRecord(
        entity_id=entity_id,
        canonical_name=canonical,
        entity_type="PERSON",
        aliases=list(aliases),
        decisions=decision_ids,
    )
    return record, decisions


def _valid_registry() -> Registry:
    r1, d1 = _record_with_decision("chaol_westfall", "Chaol Westfall", ["Captain Westfall", "Chaol Westfall"])
    r2, d2 = _record_with_decision("perrington", "Perrington", ["Duke Perrington", "Perrington"])
    return Registry(entities=[r1, r2], decisions={**d1, **d2})


def test_lookup_matches_aliases_case_insensitively():
    registry = _valid_registry()
    assert registry.lookup("captain westfall").entity_id == "chaol_westfall"
    assert registry.lookup("PERRINGTON").entity_id == "perrington"
    assert registry.lookup("Nehemia") is None


def test_alias_table_maps_every_alias_to_its_entity_id():
    table = _valid_registry().alias_table()
    assert table["Captain Westfall"] == "chaol_westfall"
    assert table["Duke Perrington"] == "perrington"
    assert table["Perrington"] == "perrington"


def test_audit_log_is_sorted_and_complete():
    registry = _valid_registry()
    log = registry.audit_log()
    assert [d.decision_id for d in log] == sorted(d.decision_id for d in log)
    assert len(log) == 2


def test_validate_accepts_valid_registry():
    _valid_registry().validate()  # must not raise


def test_validate_rejects_alias_owned_by_two_entities():
    registry = _valid_registry()
    r_extra, d_extra = _record_with_decision("westfall_2", "Westfall Two", ["Captain Westfall", "Westfall Two"])
    registry.entities.append(r_extra)
    registry.decisions.update(d_extra)
    with pytest.raises(ValueError, match="invariant 1"):
        registry.validate()


def test_validate_rejects_alias_without_merge_decision():
    registry = _valid_registry()
    registry.entities[0].aliases.append("Mystery Name")
    with pytest.raises(ValueError, match="invariant 2"):
        registry.validate()


def test_validate_rejects_canonical_missing_from_aliases():
    registry = _valid_registry()
    registry.entities[1].aliases.remove("Perrington")
    with pytest.raises(ValueError, match="invariant 3"):
        registry.validate()


def test_validate_rejects_unknown_decision_id():
    registry = _valid_registry()
    registry.entities[0].decisions.append("d_does_not_exist")
    with pytest.raises(ValueError, match="unknown decision_id"):
        registry.validate()


def test_validate_rejects_duplicate_entity_ids():
    registry = _valid_registry()
    dup, d_dup = _record_with_decision("perrington", "Perrington Bis", ["Perrington Bis"])
    registry.entities.append(dup)
    registry.decisions.update(d_dup)
    with pytest.raises(ValueError, match="duplicate entity_id"):
        registry.validate()


def test_round_trip_save_load_preserves_everything(tmp_path):
    registry = _valid_registry()
    registry.entities[0].mentions.append(
        Mention(surface="Chaol", chapter_id="ch01", context="Chaol stood guard.")
    )
    registry.warnings.append("test warning")
    path = tmp_path / "registry.json"

    registry.save(path)
    loaded = Registry.load(path)

    assert loaded.to_dict() == registry.to_dict()
    assert loaded.entities[0].mentions[0] == registry.entities[0].mentions[0]
    assert loaded.decisions == registry.decisions
    assert loaded.warnings == ["test warning"]


def test_saved_json_shape(tmp_path):
    import json as jsonlib

    path = tmp_path / "registry.json"
    _valid_registry().save(path)
    raw = jsonlib.loads(path.read_text(encoding="utf-8"))
    assert raw["version"] == 1
    assert {e["entity_id"] for e in raw["entities"]} == {"chaol_westfall", "perrington"}
    # decisions are stored once, top-level, referenced by id from records
    top_ids = {d["decision_id"] for d in raw["decisions"]}
    for entity in raw["entities"]:
        assert set(entity["decisions"]) <= top_ids


def test_save_enforces_invariants(tmp_path):
    registry = _valid_registry()
    registry.entities[0].aliases.append("Unjustified Alias")
    with pytest.raises(ValueError, match="invariant 2"):
        registry.save(tmp_path / "registry.json")
    assert not (tmp_path / "registry.json").exists()


def test_load_rejects_corrupted_registry(tmp_path):
    import json as jsonlib

    registry = _valid_registry()
    path = tmp_path / "registry.json"
    registry.save(path)
    raw = jsonlib.loads(path.read_text(encoding="utf-8"))
    raw["entities"][0]["aliases"].append("Injected Alias")
    path.write_text(jsonlib.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="invariant 2"):
        Registry.load(path)
