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


def test_validate_requires_decision_in_absorbed_slot():
    # A case-variant alias of the canonical name has the SAME slug as the
    # entity_id (entity_slug("perrington") == entity_slug("Perrington") ==
    # "perrington"). No MergeDecision names it in the absorbed-alias slot
    # (inputs[1]) — the only decision present is a decoy whose inputs[0]
    # happens to equal that slug. The whole-tuple check would wrongly treat
    # this as justified; only checking inputs[1] correctly rejects it.
    entity_id = "perrington"
    decoy_id = _decision_id("extraction_grouping", (entity_id, "duke_perrington"), "test:decoy")
    decoy = MergeDecision(
        decision_id=decoy_id,
        strategy="extraction_grouping",
        inputs=(entity_id, "duke_perrington"),
        evidence="test:decoy",
        confidence="medium",
    )
    record = EntityRecord(
        entity_id=entity_id,
        canonical_name="Perrington",
        entity_type="PERSON",
        aliases=["Perrington", "perrington"],
        decisions=[decoy_id],
    )
    registry = Registry(entities=[record], decisions={decoy_id: decoy})
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


import copy


def _run16_artifacts() -> tuple[dict, dict, dict]:
    """The Run 16 / STU-430 snippet as pipeline artifacts (Crown Prince and
    Perrington are distinct; 'Duke Perrington' is an extraction surface variant).
    Mirrors tests/test_alias_resolution.py:1248."""
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
            "mentions_by_chapter": {
                "ch02": [
                    "The Crown Prince, of course, sat with Perrington "
                    "on their own two logs, far from her.",
                ]
            },
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


def test_from_artifacts_run16_reconstruction():
    splits, alias_output, persons_full = _run16_artifacts()
    registry = Registry.from_artifacts(splits, alias_output, persons_full)

    assert sorted(r.entity_id for r in registry.entities) == ["crown_prince", "perrington"]
    perrington = registry.lookup("Perrington")
    assert perrington.canonical_name == "Perrington"
    assert perrington.entity_type == "PERSON"
    assert "Duke Perrington" in perrington.aliases
    # invariant 3 holds by construction
    assert perrington.canonical_name in perrington.aliases
    # the whole thing is save()-able (all invariants hold)
    registry.validate()


def test_from_artifacts_entity_ids_deterministic_between_runs():
    """Invariant 4: same artifacts ⇒ byte-identical registry."""
    splits, alias_output, persons_full = _run16_artifacts()
    first = Registry.from_artifacts(
        copy.deepcopy(splits), copy.deepcopy(alias_output), copy.deepcopy(persons_full)
    )
    second = Registry.from_artifacts(
        copy.deepcopy(splits), copy.deepcopy(alias_output), copy.deepcopy(persons_full)
    )
    assert first.to_dict() == second.to_dict()


def test_from_artifacts_unclustered_alias_gets_extraction_grouping():
    splits, alias_output, persons_full = _run16_artifacts()
    registry = Registry.from_artifacts(splits, alias_output, persons_full)
    perrington = registry.lookup("Perrington")
    strategies = {registry.decisions[d].strategy for d in perrington.decisions}
    assert strategies == {"extraction_grouping"}


def test_from_artifacts_clustered_alias_gets_cluster_jw():
    splits, alias_output, persons_full = _run16_artifacts()
    splits["PERSON"].append(
        {
            "canonical_candidate": "Perrington",
            "type": "PERSON",
            "all_mentions": ["Perrington", "Duke Perrington"],
            "entity_ids": ["e_perrington", "e_duke"],
            "entity_count": 2,
        }
    )
    registry = Registry.from_artifacts(splits, alias_output, persons_full)
    perrington = registry.lookup("Perrington")
    strategies = {registry.decisions[d].strategy for d in perrington.decisions}
    assert strategies == {"cluster_jw"}


def test_from_artifacts_recorded_merge_keeps_method_and_evidence():
    splits, alias_output, persons_full = _run16_artifacts()
    alias_output["entities"][1]["aliases"] = ["Duke", "Duke Perrington", "Perrington"]
    alias_output["entities"][1]["alias_resolution"] = {
        "merged_from": ["Duke"],
        "evidence": [
            {"method": "pure_title", "confidence": "high", "snippet": "Duke Perrington scowled."}
        ],
        "confidence": "high",
        "method": "pure_title",
    }
    registry = Registry.from_artifacts(splits, alias_output, persons_full)
    perrington = registry.lookup("Perrington")
    by_alias_slug = {
        registry.decisions[d].inputs[1]: registry.decisions[d] for d in perrington.decisions
    }
    duke = by_alias_slug["duke"]
    assert duke.strategy == "pure_title"
    assert duke.confidence == "high"
    assert "Duke Perrington scowled." in duke.evidence
    # the plain surface variant still gets a synthesized decision
    assert by_alias_slug["duke_perrington"].strategy == "extraction_grouping"


def test_from_artifacts_rebuilds_mentions_with_longest_surface_match():
    splits, alias_output, persons_full = _run16_artifacts()
    registry = Registry.from_artifacts(splits, alias_output, persons_full)
    crown = registry.lookup("Crown Prince")
    assert len(crown.mentions) == 1
    mention = crown.mentions[0]
    assert mention.surface == "Crown Prince"
    assert mention.chapter_id == "ch02"
    assert mention.source == "ner"
    assert mention.start is None and mention.raw_label is None
    assert "sat with Perrington" in mention.context


def test_from_artifacts_canonical_added_to_aliases_when_missing():
    splits, alias_output, persons_full = _run16_artifacts()
    alias_output["entities"][0]["aliases"] = []  # artifact anomaly
    registry = Registry.from_artifacts(splits, alias_output, persons_full)
    crown = registry.lookup("Crown Prince")
    assert crown.aliases == ["Crown Prince"]


def test_from_artifacts_slug_collision_gets_deterministic_suffix():
    splits, alias_output, persons_full = _run16_artifacts()
    alias_output["entities"].append(
        {
            "canonical_name": "Crown-Prince",  # different name, same slug
            "type": "PERSON",
            "aliases": ["Crown-Prince"],
            "source_ids": [],
            "relevant": True,
        }
    )
    registry = Registry.from_artifacts(splits, alias_output, persons_full)
    ids = sorted(r.entity_id for r in registry.entities)
    assert ids == ["crown_prince", "crown_prince_2", "perrington"]


def test_from_artifacts_merges_duplicate_canonicals():
    splits, alias_output, persons_full = _run16_artifacts()
    alias_output["entities"].append(
        {
            "canonical_name": "Perrington",
            "type": "PERSON",
            "aliases": ["Perrington", "the duke"],
            "source_ids": [],
            "relevant": True,
        }
    )
    registry = Registry.from_artifacts(splits, alias_output, persons_full)
    assert sorted(r.entity_id for r in registry.entities) == ["crown_prince", "perrington"]
    perrington = registry.lookup("Perrington")
    assert "the duke" in perrington.aliases
    assert registry.warnings  # the resolution is traced
    registry.validate()


def test_from_artifacts_alias_collision_canonical_wins():
    splits, alias_output, persons_full = _run16_artifacts()
    # 'Crown Prince' also (wrongly) listed as alias of Perrington in the artifacts
    alias_output["entities"][1]["aliases"] = ["Crown Prince", "Duke Perrington", "Perrington"]
    registry = Registry.from_artifacts(splits, alias_output, persons_full)
    crown = registry.lookup("Crown Prince")
    perrington = [r for r in registry.entities if r.entity_id == "perrington"][0]
    assert crown.entity_id == "crown_prince"  # canonical owner keeps it
    assert "Crown Prince" not in perrington.aliases
    assert any("Crown Prince" in w for w in registry.warnings)
    registry.validate()


def test_from_artifacts_tolerates_missing_optional_inputs():
    _, alias_output, _ = _run16_artifacts()
    registry = Registry.from_artifacts(None, alias_output, None)
    assert len(registry.entities) == 2
    assert all(r.mentions == [] for r in registry.entities)
    registry.validate()


def test_from_artifacts_triple_slug_collision_never_yields_duplicate_ids():
    """Regression (STU-441 review finding 1): 'Crown Prince', 'Crown-Prince' and
    'Crown Prince 2' would previously collide — the second entity took the
    suffixed id 'crown_prince_2', and the third entity's *base* slug also
    computed to 'crown_prince_2', producing a duplicate id and crashing
    validate()."""
    splits, alias_output, persons_full = _run16_artifacts()
    alias_output["entities"] = [
        {
            "canonical_name": "Crown Prince",
            "type": "PERSON",
            "aliases": ["Crown Prince"],
            "source_ids": [],
            "relevant": True,
        },
        {
            "canonical_name": "Crown-Prince",  # slugs to crown_prince -> crown_prince_2
            "type": "PERSON",
            "aliases": ["Crown-Prince"],
            "source_ids": [],
            "relevant": True,
        },
        {
            "canonical_name": "Crown Prince 2",  # base slug collides with the above suffix
            "type": "PERSON",
            "aliases": ["Crown Prince 2"],
            "source_ids": [],
            "relevant": True,
        },
    ]
    registry = Registry.from_artifacts(splits, alias_output, persons_full)
    ids = [r.entity_id for r in registry.entities]
    assert len(ids) == len(set(ids)), f"duplicate entity_ids produced: {ids}"
    registry.validate()  # must not raise


def test_from_artifacts_alias_order_deterministic_for_casefold_equal_aliases():
    """Regression (STU-441 review finding 2): when two aliases are casefold-equal
    but differ in case (e.g. 'Duke' vs 'duke'), the alias list — and therefore
    the per-entity decisions order built by iterating it — must not depend on
    set iteration/hash-seed order.

    A same-process comparison is a tautology (both calls share the same hash
    seed), so this drives two separate subprocesses with distinct fixed
    PYTHONHASHSEED values and asserts their to_dict() outputs are
    byte-identical. That is what actually distinguishes the old (hash-seed
    dependent) behavior from the fixed, deterministic one.
    """
    import json
    import os
    import pathlib
    import subprocess
    import sys

    splits, alias_output, persons_full = _run16_artifacts()
    alias_output["entities"][1]["aliases"] = ["duke", "Duke", "Perrington", "Duke Perrington"]

    # Lightweight in-process sanity check: both case variants survive as
    # distinct aliases.
    registry = Registry.from_artifacts(
        copy.deepcopy(splits), copy.deepcopy(alias_output), copy.deepcopy(persons_full)
    )
    perrington = registry.lookup("Perrington")
    assert "Duke" in perrington.aliases
    assert "duke" in perrington.aliases

    repo_root = pathlib.Path(__file__).resolve().parents[1]
    driver = (
        "import json, sys\n"
        "from wiki_creator.registry import Registry\n"
        "payload = json.loads(sys.stdin.read())\n"
        "registry = Registry.from_artifacts(\n"
        "    payload['splits'], payload['alias_output'], payload['persons_full']\n"
        ")\n"
        "print(json.dumps(registry.to_dict(), sort_keys=False))\n"
    )
    stdin_payload = json.dumps(
        {"splits": splits, "alias_output": alias_output, "persons_full": persons_full}
    )

    outputs = []
    for seed in ("0", "1"):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        env["PYTHONPATH"] = str(repo_root)
        result = subprocess.run(
            [sys.executable, "-c", driver],
            input=stdin_payload,
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            env=env,
            check=True,
        )
        outputs.append(result.stdout)

    assert outputs[0] == outputs[1], "to_dict() output differs across PYTHONHASHSEED values"


def test_from_artifacts_prunes_orphan_decisions_after_alias_collision():
    """Regression (STU-441 review finding 3): when _resolve_alias_collisions
    drops an alias from the losing record, the now-unreferenced MergeDecision
    must be pruned from the registry, not just from that record's own
    .decisions list — otherwise audit_log()/to_dict()["decisions"] keeps
    listing decisions no entity carries."""
    splits, alias_output, persons_full = _run16_artifacts()
    # 'Crown Prince' is (wrongly) also listed as an alias of Perrington: the
    # collision resolver drops it from Perrington, so Perrington's synthesized
    # decision for that alias must disappear from the registry entirely.
    alias_output["entities"][1]["aliases"] = ["Crown Prince", "Duke Perrington", "Perrington"]
    registry = Registry.from_artifacts(splits, alias_output, persons_full)

    referenced = {d_id for r in registry.entities for d_id in r.decisions}
    audit_ids = {d.decision_id for d in registry.audit_log()}
    assert audit_ids == referenced, f"orphan decisions: {audit_ids - referenced}"

    perrington = [r for r in registry.entities if r.entity_id == "perrington"][0]
    dropped_slug = entity_slug("Crown Prince")
    assert not any(
        registry.decisions[d].inputs == (perrington.entity_id, dropped_slug)
        for d in registry.decisions
    )
    registry.validate()


def _bare_decision(strategy, survivor, absorbed_slug, evidence="ev", confidence="medium"):
    d_id = _decision_id(strategy, (survivor, absorbed_slug), evidence)
    return MergeDecision(
        decision_id=d_id, strategy=strategy, inputs=(survivor, absorbed_slug),
        evidence=evidence, confidence=confidence,
    )


def test_merge_attach_records_decision_for_existing_alias():
    reg = _valid_registry()
    perrington = reg._by_id("perrington")
    # 'Duke Perrington' is already an alias; attach its justifying decision
    d = _bare_decision("title_apposition", "perrington", entity_slug("Duke Perrington"))
    returned = reg.merge("perrington", entity_slug("Duke Perrington"), d)
    assert returned == "perrington"
    assert d.decision_id in perrington.decisions
    assert reg.decisions[d.decision_id].strategy == "title_apposition"


def test_merge_fold_absorbs_entity_record():
    r1, d1 = _record_with_decision("perrington", "Perrington", ["Duke Perrington", "Perrington"])
    r2, d2 = _record_with_decision("the_duke", "The Duke", ["The Duke"])
    reg = Registry(entities=[r1, r2], decisions={**d1, **d2})
    fold = _bare_decision("role_symmetric", "perrington", entity_slug("The Duke"))
    r2.aliases.append("The Duke")  # ensure present
    reg.merge("perrington", "the_duke", fold)
    assert [r.entity_id for r in reg.entities] == ["perrington"]
    perrington = reg._by_id("perrington")
    assert "The Duke" in perrington.aliases
    assert fold.decision_id in perrington.decisions


def test_merge_unknown_survivor_raises():
    reg = _valid_registry()
    with pytest.raises(ValueError, match="unknown survivor"):
        reg.merge("nobody", "x", _bare_decision("manual", "nobody", "x"))


def test_merge_conflict_canonical_owner_wins():
    # perrington (canonical 'Perrington') and a second entity both claim 'Perrington'
    r1, d1 = _record_with_decision("perrington", "Perrington", ["Duke Perrington", "Perrington"])
    r2, d2 = _record_with_decision("guard", "Guard", ["Guard"])
    reg = Registry(entities=[r1, r2], decisions={**d1, **d2})
    # guard wrongly gains 'Perrington' as an alias, justified by a decision
    d = _bare_decision("extraction_grouping", "guard", entity_slug("Perrington"))
    r2.aliases.append("Perrington")
    reg.merge("guard", entity_slug("Perrington"), d)
    # canonical owner keeps it; guard loses it + the orphan decision; warning logged
    assert "Perrington" not in reg._by_id("guard").aliases
    assert reg._by_id("perrington") is not None
    assert d.decision_id not in reg._by_id("guard").decisions
    assert any("Perrington" in w for w in reg.warnings)
    reg.validate()


def test_merge_conflict_more_mentions_wins_when_no_canonical_owner():
    r1, d1 = _record_with_decision("a_one", "A One", ["A One", "Shadow"])
    r2, d2 = _record_with_decision("b_two", "B Two", ["B Two", "Shadow"])
    reg = Registry(entities=[r1, r2], decisions={**d1, **d2})
    reg._by_id("a_one").mentions.extend(
        [Mention(surface="Shadow", chapter_id="ch01"), Mention(surface="Shadow", chapter_id="ch02")]
    )
    reg._by_id("b_two").mentions.append(Mention(surface="Shadow", chapter_id="ch01"))
    # trigger resolution by (re-)attaching the contested alias on the lower-mention entity
    d = _bare_decision("extraction_grouping", "b_two", entity_slug("Shadow"))
    reg.merge("b_two", entity_slug("Shadow"), d)
    assert "Shadow" in reg._by_id("a_one").aliases      # more mentions wins
    assert "Shadow" not in reg._by_id("b_two").aliases
    reg.validate()
