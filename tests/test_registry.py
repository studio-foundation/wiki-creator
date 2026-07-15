"""Tests for wiki_creator/registry.py — EntityRegistry pas 1 (STU-441)."""
import pytest

from wiki_creator.registry import (
    EntityRecord,
    MergeDecision,
    Mention,
    entity_slug,
    normalize_name,
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


def _with_mention_spans(persons_full: dict) -> tuple[dict, str]:
    """Add STU-489 mention_spans_by_chapter to the Run 16 artifacts, with
    offsets indexing into a chapter text. Returns (persons_full, ch02_text)."""
    ch02 = (
        "The Crown Prince, of course, sat with Perrington "
        "on their own two logs, far from her. "
        "Perrington scowled at the competitors. "
        "Later, Duke Perrington left the hall."
    )
    def _span(surface: str, occurrence: int = 0) -> dict:
        pos = -1
        for _ in range(occurrence + 1):
            pos = ch02.index(surface, pos + 1)
        return {"surface": surface, "start": pos, "end": pos + len(surface)}

    full = copy.deepcopy(persons_full)
    full["e_crown_prince"]["mention_spans_by_chapter"] = {
        "ch02": [_span("Crown Prince")]
    }
    full["e_perrington"]["mention_spans_by_chapter"] = {
        "ch02": [
            _span("Perrington", 0),
            _span("Perrington", 1),
            _span("Duke Perrington"),
        ]
    }
    return full, ch02


def test_from_artifacts_populates_offsets_from_mention_spans():
    """STU-489: with mention_spans_by_chapter persisted, every rebuilt Mention
    carries non-None offsets and the real per-occurrence surface."""
    splits, alias_output, persons_full = _run16_artifacts()
    persons_full, ch02 = _with_mention_spans(persons_full)
    registry = Registry.from_artifacts(splits, alias_output, persons_full)

    perrington = registry.lookup("Perrington")
    assert len(perrington.mentions) == 3  # one per occurrence, not per context
    assert [m.surface for m in perrington.mentions] == [
        "Perrington", "Perrington", "Duke Perrington",
    ]
    for mention in perrington.mentions:
        assert mention.start is not None and mention.end is not None
        assert ch02[mention.start:mention.end] == mention.surface
    # The preserved context pairs with the first occurrence of the chapter.
    assert perrington.mentions[0].context == "Perrington scowled at the competitors."
    assert perrington.mentions[1].context is None


def test_mention_window_extracts_centered_context():
    """STU-489 acceptance: a window centered on the mention is extractible."""
    splits, alias_output, persons_full = _run16_artifacts()
    persons_full, ch02 = _with_mention_spans(persons_full)
    registry = Registry.from_artifacts(splits, alias_output, persons_full)

    mention = registry.lookup("Crown Prince").mentions[0]
    window = mention.window(ch02, radius=20)
    assert "Crown Prince" in window
    assert window == ch02[max(0, mention.start - 20) : mention.end + 20]
    # Small radius stays anchored on the mention, not the chapter head.
    assert mention.window(ch02, radius=0) == "Crown Prince"


def test_mention_window_none_without_offsets():
    m = Mention(surface="Perrington", chapter_id="ch02")
    assert m.window("any chapter text") is None


def test_offsets_round_trip_save_load(tmp_path):
    splits, alias_output, persons_full = _run16_artifacts()
    persons_full, _ = _with_mention_spans(persons_full)
    registry = Registry.from_artifacts(splits, alias_output, persons_full)

    path = tmp_path / "registry.json"
    registry.save(path)
    loaded = Registry.load(path)

    assert loaded.to_dict() == registry.to_dict()
    expected = [
        (s["start"], s["end"])
        for s in persons_full["e_perrington"]["mention_spans_by_chapter"]["ch02"]
    ]
    reloaded = loaded.lookup("Perrington").mentions
    assert [(m.start, m.end) for m in reloaded] == expected
    assert all(isinstance(m.start, int) and isinstance(m.end, int) for m in reloaded)


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


def _homonym_artifacts():
    """Two entities named 'Adarlan' — a PERSON and a PLACE (the STU-473 shape)."""
    splits = {"PERSON": [], "PLACE": [], "ORG": [], "EVENT": [], "OTHER": []}
    alias_output = {
        "entities": [
            {"canonical_name": "Adarlan", "type": "PERSON", "aliases": ["Adarlan"],
             "source_ids": [], "relevant": True},
            {"canonical_name": "Adarlan", "type": "PLACE", "aliases": ["Adarlan"],
             "source_ids": [], "relevant": True},
        ],
    }
    return splits, alias_output


def test_different_type_homonyms_are_not_merged_by_default():
    from wiki_creator.registry import Registry

    splits, alias_output = _homonym_artifacts()
    registry = Registry.from_artifacts(splits, alias_output)
    kinds = sorted((r.canonical_name, r.entity_type) for r in registry.entities)
    assert kinds == [("Adarlan", "PERSON"), ("Adarlan", "PLACE")]
    # entity_ids stay unique, and the coexistence is validated + traced
    assert len({r.entity_id for r in registry.entities}) == 2
    registry.validate()
    assert any("name collision" in w for w in registry.warnings)


def test_validate_accepts_same_name_different_type():
    from wiki_creator.registry import Registry

    splits, alias_output = _homonym_artifacts()
    Registry.from_artifacts(splits, alias_output).validate()  # must not raise


def test_collision_policy_merge_restores_legacy_fold():
    from wiki_creator.naming import NamingPolicy
    from wiki_creator.registry import Registry

    splits, alias_output = _homonym_artifacts()
    registry = Registry.from_artifacts(
        splits, alias_output, policy=NamingPolicy(collision_policy="merge")
    )
    assert len(registry.entities) == 1  # PERSON + PLACE folded into one
    registry.validate()


def test_collision_policy_fail_raises_on_cross_type_homonym():
    from wiki_creator.naming import NamingPolicy
    from wiki_creator.registry import Registry

    splits, alias_output = _homonym_artifacts()
    with pytest.raises(ValueError, match="name collision"):
        Registry.from_artifacts(splits, alias_output, policy=NamingPolicy(collision_policy="fail"))


def test_same_type_duplicate_canonicals_still_merge():
    from wiki_creator.registry import Registry

    splits, alias_output = _homonym_artifacts()
    alias_output["entities"][1]["type"] = "PERSON"  # now both PERSON
    registry = Registry.from_artifacts(splits, alias_output)
    assert len(registry.entities) == 1
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


# --- STU-443 (pas 4): downstream single-source-of-truth identity binding ---

def test_bind_identity_rewrites_canonical_and_aliases():
    registry = _valid_registry()
    # A batch entity that reached us via a non-canonical surface with a partial
    # alias set: bind_identity replaces both from the authoritative record.
    entity = {"canonical_name": "Captain Westfall", "aliases": ["Chaol"], "type": "PERSON"}
    assert registry.bind_identity(entity) is True
    assert entity["canonical_name"] == "Chaol Westfall"
    # aliases carry the *other* surfaces only — never the canonical_name itself.
    assert entity["aliases"] == ["Captain Westfall"]
    assert "Chaol Westfall" not in entity["aliases"]


def test_bind_identity_unknown_entity_leaves_fields_untouched():
    registry = _valid_registry()
    entity = {"canonical_name": "Nehemia", "aliases": ["Princess"]}
    assert registry.bind_identity(entity) is False
    assert entity["canonical_name"] == "Nehemia"
    assert entity["aliases"] == ["Princess"]


def test_bind_identity_exposes_books_and_first_book():
    # STU-486: bind_identity also exposes the record's book provenance so
    # generation can render per-tome categories / an appearance line.
    r1, d1 = _record_with_decision("chaol_westfall", "Chaol Westfall", ["Captain Westfall", "Chaol Westfall"])
    r1.books = ["01-throne-of-glass", "02-crown-of-midnight"]
    r1.first_book = "01-throne-of-glass"
    registry = Registry(entities=[r1], decisions=d1)
    entity = {"canonical_name": "Chaol Westfall", "aliases": []}
    assert registry.bind_identity(entity) is True
    assert entity["books"] == ["01-throne-of-glass", "02-crown-of-midnight"]
    assert entity["first_book"] == "01-throne-of-glass"


def test_bind_identity_unknown_provenance_defaults_to_empty():
    r1, d1 = _record_with_decision("perrington", "Perrington", ["Duke Perrington", "Perrington"])
    registry = Registry(entities=[r1], decisions=d1)
    entity = {"canonical_name": "Perrington", "aliases": []}
    assert registry.bind_identity(entity) is True
    assert entity["books"] == []
    assert entity["first_book"] is None


def test_load_from_processing_absent_returns_none(tmp_path):
    assert Registry.load_from_processing(tmp_path) is None


def test_load_from_processing_roundtrips(tmp_path):
    _valid_registry().save(tmp_path / "registry.json")
    loaded = Registry.load_from_processing(tmp_path)
    assert loaded is not None
    assert loaded.lookup("Duke Perrington").canonical_name == "Perrington"


def test_load_from_processing_corrupt_returns_none(tmp_path):
    (tmp_path / "registry.json").write_text("{ not json", encoding="utf-8")
    assert Registry.load_from_processing(tmp_path) is None


# --- normalize_name (STU-450: single canonical name normalization) ---


def test_normalize_name_casefolds_strips_accents_and_trims():
    assert normalize_name("  Néhémia D'EYLLWE  ") == "nehemia d'eyllwe"


def test_normalize_name_casefold_more_aggressive_than_lower():
    # casefold folds ß -> ss, where str.lower() would not
    assert normalize_name("Straße") == "strasse"


def test_normalize_name_preserves_internal_whitespace():
    # not a slug: internal spacing/apostrophes/hyphens are kept
    assert normalize_name("Celaena  Sardothien") == "celaena  sardothien"


def test_normalize_name_handles_none_and_non_str():
    assert normalize_name(None) == ""
    assert normalize_name(123) == "123"


def test_normalize_name_matches_legacy_grounding_and_validator_semantics():
    # freezes the behavior the 3 former call sites now share
    assert normalize_name("Martín") == "martin"
    assert normalize_name("BARCELONE") == "barcelone"
    assert normalize_name("  Vidal  ") == "vidal"


# --- from_artifacts: embedding_disambiguation strategy round-trip (STU-468) ---


def test_from_artifacts_preserves_embedding_disambiguation_strategy():
    """method: 'embedding_disambiguation' (recorded by the new alias-resolution
    strategy) must survive from_artifacts() verbatim as MergeDecision.strategy —
    same wiring already proven for 'pure_title' in
    test_from_artifacts_recorded_merge_keeps_method_and_evidence."""
    splits, alias_output, persons_full = _run16_artifacts()
    alias_output["entities"][1]["aliases"] = ["Duke", "Duke Perrington", "Perrington"]
    alias_output["entities"][1]["alias_resolution"] = {
        "merged_from": ["Duke"],
        "evidence": [
            {
                "method": "embedding_disambiguation",
                "confidence": "high",
                "snippet": "context cosine=0.910 (embedding disambiguation)",
            }
        ],
        "confidence": "high",
        "method": "embedding_disambiguation",
    }
    registry = Registry.from_artifacts(splits, alias_output, persons_full)
    perrington = registry.lookup("Perrington")
    by_alias_slug = {
        registry.decisions[d].inputs[1]: registry.decisions[d] for d in perrington.decisions
    }
    duke = by_alias_slug["duke"]
    assert duke.strategy == "embedding_disambiguation"
    assert duke.confidence == "high"
    assert "context cosine=0.910 (embedding disambiguation)" in duke.evidence
# --- Provenance par livre (STU-484: book_id / books / first_book) ---


def test_mention_book_id_defaults_to_none():
    assert Mention(surface="Perrington", chapter_id="ch02").book_id is None


def test_entity_record_provenance_defaults_empty():
    r = EntityRecord(entity_id="perrington", canonical_name="Perrington", entity_type="PERSON")
    assert r.books == [] and r.first_book is None


def test_from_artifacts_without_book_id_leaves_provenance_empty():
    splits, alias_output, persons_full = _run16_artifacts()
    registry = Registry.from_artifacts(splits, alias_output, persons_full)
    for record in registry.entities:
        assert record.books == []
        assert record.first_book is None
        assert all(m.book_id is None for m in record.mentions)


def test_from_artifacts_stamps_book_id_on_mentions_and_records():
    splits, alias_output, persons_full = _run16_artifacts()
    registry = Registry.from_artifacts(splits, alias_output, persons_full, book_id="01-book")
    assert registry.entities  # sanity
    for record in registry.entities:
        assert record.books == ["01-book"]
        assert record.first_book == "01-book"
        assert record.mentions  # each Run 16 entity has at least one mention
        assert all(m.book_id == "01-book" for m in record.mentions)


def test_provenance_round_trips_through_save_load(tmp_path):
    splits, alias_output, persons_full = _run16_artifacts()
    registry = Registry.from_artifacts(splits, alias_output, persons_full, book_id="01-book")
    path = tmp_path / "registry.json"
    registry.save(path)

    raw = __import__("json").loads(path.read_text(encoding="utf-8"))
    perrington = [e for e in raw["entities"] if e["entity_id"] == "perrington"][0]
    assert perrington["books"] == ["01-book"]
    assert perrington["first_book"] == "01-book"
    assert perrington["mentions"][0]["book_id"] == "01-book"

    loaded = Registry.load(path)
    assert loaded.to_dict() == registry.to_dict()
    loaded_perrington = loaded.lookup("Perrington")
    assert loaded_perrington.books == ["01-book"]
    assert loaded_perrington.first_book == "01-book"
    assert all(m.book_id == "01-book" for m in loaded_perrington.mentions)


def test_from_dict_tolerates_missing_provenance_keys():
    """Registries written before STU-484 carry no books/first_book/book_id."""
    legacy = {
        "version": 1,
        "entities": [
            {
                "entity_id": "perrington",
                "canonical_name": "Perrington",
                "entity_type": "PERSON",
                "aliases": ["Perrington"],
                "mentions": [{"surface": "Perrington", "chapter_id": "ch02"}],
                "decisions": [],
            }
        ],
        "decisions": [],
        "warnings": [],
    }
    registry = Registry.from_dict(legacy)
    record = registry.entities[0]
    assert record.books == [] and record.first_book is None
    assert record.mentions[0].book_id is None

# --- Series accumulation (STU-485) -------------------------------------------


def _book_registry(book_id: str, entities: list[dict]) -> Registry:
    """Build a valid single-book registry from {canonical, aliases, type?, chapters?}."""
    records: list[EntityRecord] = []
    decisions: dict[str, MergeDecision] = {}
    for spec in entities:
        canonical = spec["canonical"]
        aliases = sorted(set(spec.get("aliases", [])) | {canonical}, key=lambda a: (a.casefold(), a))
        record, record_decisions = _record_with_decision(
            entity_slug(canonical), canonical, aliases
        )
        record.entity_type = spec.get("type", "PERSON")
        record.mentions = [
            Mention(surface=canonical, chapter_id=ch, book_id=book_id)
            for ch in spec.get("chapters", ["ch01"])
        ]
        record.books = [book_id]
        record.first_book = book_id
        records.append(record)
        decisions.update(record_decisions)
    return Registry(entities=records, decisions=decisions)


def test_accumulate_inheritance_book1_to_book2():
    """The STU-485 acceptance scenario: Eragon/Saphira from tome 1 are reused
    in tome 2 (same entity_id), tome 2's new entities are added, accumulation
    decisions are traced and auditable."""
    series = Registry()
    book1 = _book_registry("01-eragon", [
        {"canonical": "Eragon", "aliases": ["Eragon Shadeslayer"]},
        {"canonical": "Saphira", "chapters": ["ch02"]},
    ])
    delta1 = series.accumulate(book1)
    series.validate()
    assert [e["series_entity_id"] for e in delta1["added"]] == ["eragon", "saphira"]
    assert delta1["matched"] == []

    book2 = _book_registry("02-eldest", [
        {"canonical": "Eragon", "aliases": ["Argetlam"], "chapters": ["ch01", "ch05"]},
        {"canonical": "Saphira", "chapters": ["ch03"]},
        {"canonical": "Roran", "chapters": ["ch01"]},
    ])
    delta2 = series.accumulate(book2)
    series.validate()

    # Stable ids: tome-1 entities reused, not duplicated.
    assert {e["series_entity_id"] for e in delta2["matched"]} == {"eragon", "saphira"}
    assert [e["series_entity_id"] for e in delta2["added"]] == ["roran"]
    assert {r.entity_id for r in series.entities} == {"eragon", "saphira", "roran"}

    # Aliases and provenance unioned.
    eragon = series.lookup("Eragon")
    assert eragon.entity_id == "eragon"
    assert "Argetlam" in eragon.aliases and "Eragon Shadeslayer" in eragon.aliases
    assert eragon.books == ["01-eragon", "02-eldest"]
    assert eragon.first_book == "01-eragon"
    assert {m.book_id for m in eragon.mentions} == {"01-eragon", "02-eldest"}

    # Accumulation decisions traced and auditable.
    assert delta2["aliases_added"] == {"eragon": ["Argetlam"]}
    accumulated = [
        d for d in series.audit_log() if d.strategy == "series_accumulation"
    ]
    assert len(accumulated) == 1
    assert accumulated[0].inputs == ("eragon", "argetlam")
    assert "02-eldest" in accumulated[0].evidence
    assert accumulated[0].decision_id in eragon.decisions


def test_accumulate_matches_on_alias_overlap_and_normalization():
    """A tome-2 canonical that was only an alias in tome 1 still matches, and
    matching is accent/case tolerant (normalize_name, STU-450)."""
    series = Registry()
    series.accumulate(_book_registry("01-book", [
        {"canonical": "Celaena Sardothien", "aliases": ["Adarlan's Assassin"]},
    ]))
    delta = series.accumulate(_book_registry("02-book", [
        {"canonical": "Adarlan's Assassín", "aliases": ["Lillian Gordaina"]},
    ]))
    series.validate()
    assert delta["added"] == []
    assert delta["matched"][0]["series_entity_id"] == "celaena_sardothien"
    record = series.lookup("Lillian Gordaina")
    assert record.entity_id == "celaena_sardothien"
    assert record.canonical_name == "Celaena Sardothien"  # series canonical wins


def test_accumulate_is_idempotent_per_book():
    series = Registry()
    book1 = _book_registry("01-book", [
        {"canonical": "Eragon", "aliases": ["Eragon Shadeslayer"]},
    ])
    series.accumulate(book1)
    once = series.to_dict()

    delta = series.accumulate(book1)  # re-run of the same tome
    series.validate()
    assert series.to_dict() == once
    assert delta["added"] == [] and delta["decisions_added"] == []
    assert delta["aliases_added"] == {}


def test_accumulate_rerun_replaces_book_mentions():
    """Re-resolving a tome replaces its mention contribution instead of stacking it."""
    series = Registry()
    series.accumulate(_book_registry("01-book", [
        {"canonical": "Eragon", "chapters": ["ch01", "ch02"]},
    ]))
    series.accumulate(_book_registry("02-book", [
        {"canonical": "Eragon", "chapters": ["ch09"]},
    ]))
    # Tome 2 re-run finds one fewer mention.
    series.accumulate(_book_registry("02-book", [
        {"canonical": "Eragon", "chapters": ["ch08"]},
    ]))
    series.validate()
    eragon = series.lookup("Eragon")
    book2_chapters = [m.chapter_id for m in eragon.mentions if m.book_id == "02-book"]
    assert book2_chapters == ["ch08"]
    book1_chapters = [m.chapter_id for m in eragon.mentions if m.book_id == "01-book"]
    assert book1_chapters == ["ch01", "ch02"]


def test_accumulate_new_entity_id_collision_gets_suffix():
    """A new tome-2 entity whose slug collides with an unrelated series entity
    gets a deterministic suffix; its decisions are re-emitted on the new id."""
    series = Registry()
    series.accumulate(_book_registry("01-book", [
        {"canonical": "The Guard", "aliases": []},
    ]))
    # Different entity, same slug, no alias overlap.
    book2 = _book_registry("02-book", [
        {"canonical": "Thé Guard!!", "aliases": ["Palace Guard"]},
    ])
    # Force distinct identity: rename so normalization cannot match tome 1.
    book2.entities[0].canonical_name = "Guard Captain"
    book2.entities[0].aliases = ["Guard Captain", "Palace Guard"]
    book2.entities[0].entity_id = "the_guard"
    delta = series.accumulate(book2)
    series.validate()
    assert delta["added"] == [
        {"book_entity_id": "the_guard", "series_entity_id": "the_guard_2"}
    ]
    renamed = series.lookup("Guard Captain")
    assert renamed.entity_id == "the_guard_2"
    # Its alias decision was re-emitted against the new id.
    for d_id in renamed.decisions:
        assert series.decisions[d_id].inputs[0] == "the_guard_2"


def test_accumulate_alias_owned_elsewhere_stays_with_owner():
    """Invariant 1 across tomes: an alias already owned by another series
    entity is not stolen; the conflict is warned and auditable."""
    series = Registry()
    series.accumulate(_book_registry("01-book", [
        {"canonical": "Murtagh", "aliases": ["The Red Rider"]},
        {"canonical": "Galbatorix"},
    ]))
    delta = series.accumulate(_book_registry("02-book", [
        {"canonical": "Galbatorix", "aliases": ["The Red Rider"]},
    ]))
    series.validate()
    assert series.lookup("The Red Rider").entity_id == "murtagh"
    assert "The Red Rider" not in series.lookup("Galbatorix").aliases
    assert any("already belongs to 'murtagh'" in w for w in delta["warnings"])
    assert any("already belongs to 'murtagh'" in w for w in series.warnings)


def test_accumulate_keeps_series_entity_type_and_warns():
    series = Registry()
    series.accumulate(_book_registry("01-book", [
        {"canonical": "Terrasen", "type": "PLACE"},
    ]))
    delta = series.accumulate(_book_registry("02-book", [
        {"canonical": "Terrasen", "type": "PERSON"},
    ]))
    series.validate()
    assert series.lookup("Terrasen").entity_type == "PLACE"
    assert any("kept entity_type 'PLACE'" in w for w in delta["warnings"])


def test_accumulate_later_tome_overrides_entity_type_and_warns():
    """cross_tome.later_tome_overrides (STU-512): tome N wins, still auditable."""
    series = Registry()
    series.accumulate(_book_registry("01-book", [
        {"canonical": "Terrasen", "type": "PLACE"},
    ]))
    delta = series.accumulate(
        _book_registry("02-book", [{"canonical": "Terrasen", "type": "PERSON"}]),
        later_tome_overrides=True,
    )
    series.validate()
    assert series.lookup("Terrasen").entity_type == "PERSON"
    assert any("overridden to 'PERSON'" in w for w in delta["warnings"])


def test_accumulate_series_round_trips_through_save_load(tmp_path):
    series = Registry()
    series.accumulate(_book_registry("01-book", [
        {"canonical": "Eragon", "aliases": ["Eragon Shadeslayer"]},
    ]))
    series.accumulate(_book_registry("02-book", [
        {"canonical": "Eragon", "aliases": ["Argetlam"]},
        {"canonical": "Roran"},
    ]))
    path = tmp_path / "registry.json"
    series.save(path)
    loaded = Registry.load(path)
    assert loaded.to_dict() == series.to_dict()


def test_seed_table_maps_normalized_aliases_to_records():
    series = Registry()
    series.accumulate(_book_registry("01-book", [
        {"canonical": "Celaena Sardothien", "aliases": ["Adarlan's Assassin"]},
    ]))
    table = series.seed_table()
    assert table[normalize_name("ADARLAN'S ASSASSÍN")].entity_id == "celaena_sardothien"
    assert table[normalize_name("celaena sardothien")].entity_id == "celaena_sardothien"
    assert normalize_name("Nehemia") not in table
