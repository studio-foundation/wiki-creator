"""Golden non-regression test — the registry's identity projection must match the
committed Run 16 fixture, canonically (STU-442, spec §3.5 pas 2 / §4)."""
import json
from pathlib import Path

from wiki_creator.registry import Registry

FIXTURES = Path(__file__).parent / "fixtures" / "registry_run16"


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _build_registry() -> Registry:
    full = {}
    full.update(_load("persons_full.json"))
    full.update(_load("places_full.json"))
    return Registry.from_artifacts(_load("splits.json"), _load("alias_resolution.json"), full)


def test_run16_registry_is_valid_and_all_strategies_present():
    registry = _build_registry()
    registry.validate()  # every invariant holds → save()-able
    strategies = {d.strategy for d in registry.audit_log()}
    assert {
        "cluster_jw", "title_apposition", "pure_title", "role_symmetric",
        "llm_confirm", "extraction_grouping",
    } <= strategies


def test_run16_crown_prince_and_perrington_stay_separate():
    registry = _build_registry()
    assert registry.lookup("Crown Prince").entity_id != registry.lookup("Perrington").entity_id


def test_run16_identity_projection_matches_golden():
    projected = _build_registry().to_entities_classified()
    golden = _load("entities_classified.golden.json")
    assert projected == golden
