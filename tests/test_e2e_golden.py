"""Golden regression run — chained resolution stages on the smoke novella.

The unit suite tests every stage in isolation with synthetic inputs; nothing
exercises the *contract between stages*, so a renamed field or reshaped output
can pass 1000+ tests and only surface during a real (long, costly) run. This
module closes that gap: it chains every deterministic stage of the
wiki-extraction/wiki-resolution pipelines — no spaCy model, no LLM, no network —
and compares each stage's actual output against committed golden files.

    seed (frozen entity-extraction output, tests/fixtures/e2e/golden/seed/)
    → entity-clustering → split-clusters → resolve-clusters
    → relationship-extraction → alias-resolution → entity-classification
    → build-character-graph → write-registry

Stages are launched exactly like Studio launches them (subprocess, JSON on
stdin/stdout, YAML additional_context), with `previous_outputs` accumulated in
pipeline order — so lookup-priority quirks (e.g. relationship-extraction
reading resolve-clusters, alias-resolution preferring it when present) behave
as they do in a real run.

To update goldens after an intentional behavior change:

    UPDATE_GOLDENS=1 python -m pytest tests/test_e2e_golden.py -q

then review the golden diff like any other code change. To rebuild the seed
after editing the novella: python tests/fixtures/e2e/golden/gen_seed.py
"""
import difflib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from _markers import requires_en_sm
from test_e2e_smoke import _build_smoke_epub, _run_stage

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = Path(__file__).parent / "fixtures" / "e2e" / "golden"
SEED_DIR = GOLDEN_DIR / "seed"
STAGE_GOLDEN_DIR = GOLDEN_DIR / "stages"
UPDATE_GOLDENS = os.environ.get("UPDATE_GOLDENS") == "1"

SEED_FULL_FILES = (
    "persons_full.json",
    "places_full.json",
    "orgs_full.json",
    "events_full.json",
)

# (stage_name, script) in real pipeline order (STU-276: relationship-extraction
# before alias-resolution).
CHAIN = [
    ("entity-clustering", "entity_clustering.py"),
    ("split-clusters", "split_clusters.py"),
    ("resolve-clusters", "resolve_clusters.py"),
    ("relationship-extraction", "relationship_extraction.py"),
    ("alias-resolution", "alias_resolution.py"),
    ("entity-classification", "entity_classification.py"),
    ("build-character-graph", "build_character_graph.py"),
    ("write-registry", "write_registry.py"),
]

STAGE_NAMES = [name for name, _ in CHAIN]


def _normalize(obj, tmp_root: str):
    """Strip run-specific absolute paths so goldens are machine-independent."""
    if isinstance(obj, dict):
        return {k: _normalize(v, tmp_root) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalize(v, tmp_root) for v in obj]
    if isinstance(obj, str):
        return obj.replace(tmp_root, "<RUN_DIR>")
    return obj


@pytest.fixture(scope="module")
def chain_run(tmp_path_factory):
    """Run the full deterministic chain once; return normalized stage outputs."""
    tmp_path = tmp_path_factory.mktemp("golden")
    epub = _build_smoke_epub(tmp_path)
    processing = epub.parent.parent / "processing_output" / "smoke-novella"
    processing.mkdir(parents=True)

    ctx = yaml.safe_dump({
        "file_path": str(epub),
        "spacy_model": "en_core_web_sm",  # language inference only — model never loaded
        "book_slug": "smoke-novella",
        "min_mentions_absolute": 2,
    })

    parse_result = _run_stage("parse_epub.py", {"additional_context": ctx})

    # Materialize what entity-extraction would have written to disk: the
    # committed per-type registries, and chapters.json from the live parse
    # (same shape as save_chapters_json).
    for filename in SEED_FULL_FILES:
        shutil.copy(SEED_DIR / filename, processing / filename)
    (processing / "chapters.json").write_text(
        json.dumps(
            {"chapters": {ch["id"]: ch["content"] for ch in parse_result["chapters"]}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    seed = json.loads((SEED_DIR / "extraction_output.json").read_text(encoding="utf-8"))
    outputs: dict[str, dict] = {
        "epub-parse": parse_result,
        "entity-extraction": seed,
    }
    for stage_name, script in CHAIN:
        outputs[stage_name] = _run_stage(script, {
            "additional_context": ctx,
            "previous_outputs": outputs,
            "all_stage_outputs": outputs,
        })

    return {
        "outputs": _normalize(outputs, str(tmp_path)),
        "processing": processing,
        "tmp_root": str(tmp_path),
        "parse_result": parse_result,
        "epub": epub,
    }


def _assert_matches_golden(golden_path: Path, actual) -> None:
    if UPDATE_GOLDENS:
        golden_path.parent.mkdir(parents=True, exist_ok=True)
        golden_path.write_text(
            json.dumps(actual, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
    assert golden_path.exists(), (
        f"golden file missing: {golden_path}\n"
        f"Generate it with: UPDATE_GOLDENS=1 python -m pytest {Path(__file__).name} -q"
    )
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    if actual != golden:
        diff = "\n".join(difflib.unified_diff(
            json.dumps(golden, ensure_ascii=False, indent=1).splitlines(),
            json.dumps(actual, ensure_ascii=False, indent=1).splitlines(),
            fromfile=f"golden/{golden_path.name}",
            tofile="actual",
            lineterm="",
        ))
        pytest.fail(
            f"stage output drifted from golden {golden_path.name} — if the change "
            f"is intentional, rerun with UPDATE_GOLDENS=1 and review the diff:\n{diff}"
        )


@pytest.mark.parametrize("stage_name", STAGE_NAMES)
def test_stage_output_matches_golden(chain_run, stage_name):
    _assert_matches_golden(
        STAGE_GOLDEN_DIR / f"{stage_name}.json",
        chain_run["outputs"][stage_name],
    )


def test_registry_artifact_matches_golden(chain_run):
    registry_path = chain_run["processing"] / "registry.json"
    assert registry_path.exists(), "write-registry did not write registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    _assert_matches_golden(
        STAGE_GOLDEN_DIR / "artifact-registry.json",
        _normalize(registry, chain_run["tmp_root"]),
    )


def test_chain_writes_expected_disk_artifacts(chain_run):
    processing = chain_run["processing"]
    for artifact in ("splits.json", "relationships.json", "registry.json"):
        assert (processing / artifact).exists(), f"missing disk artifact: {artifact}"


# ---------------------------------------------------------------------------
# Semantic sanity checks — independent of golden files, so a wholesale golden
# regeneration cannot silently freeze a broken pipeline state.
# ---------------------------------------------------------------------------

def test_clustering_merges_title_variant(chain_run):
    """'Captain Elias Thorn' and 'Elias Thorn' must land in one PERSON cluster."""
    clusters = chain_run["outputs"]["entity-clustering"]["clusters"]
    thorn = [
        c for c in clusters
        if any("Thorn" in m for m in c["all_mentions"])
    ]
    assert len(thorn) == 1, f"expected one Thorn cluster, got {thorn}"
    assert len(thorn[0]["entity_ids"]) == 2


def test_resolution_preserves_all_entities(chain_run):
    """Every seed entity must survive to resolve-clusters (as entity or alias)."""
    seed = json.loads((SEED_DIR / "extraction_output.json").read_text(encoding="utf-8"))
    seed_mentions = {
        m
        for e in seed["entities_for_resolution"].values()
        for m in e["raw_mentions"]
    }
    merged = chain_run["outputs"]["resolve-clusters"]["entities"]
    covered = {a for e in merged for a in [e["canonical_name"], *e.get("aliases", [])]}
    missing = {m for m in seed_mentions if m not in covered}
    assert not missing, f"entities lost in resolution: {missing}"


def test_relationship_extraction_finds_protagonist_edge(chain_run):
    """Thorn and Vale co-occur in all four chapters — the graph must see it."""
    relationships = chain_run["outputs"]["relationship-extraction"]["relationships"]
    pairs = {(r["entity_a"], r["entity_b"]) for r in relationships}
    assert any(
        {"Thorn", "Vale"} <= {token for name in pair for token in name.split()}
        for pair in pairs
    ), f"no Thorn–Vale edge in {pairs}"


def test_classification_assigns_importance_tiers(chain_run):
    entities = chain_run["outputs"]["entity-classification"]["entities"]
    assert entities
    valid = {"principal", "secondary", "figurant", "ignored"}
    for entity in entities:
        assert entity.get("importance") in valid, entity
    protagonists = {
        e["canonical_name"] for e in entities
        if e["importance"] in {"principal", "secondary"}
    }
    # Both protagonists must survive classification as distinct entities —
    # 'Captain Elias Thorn' being swallowed into Mira Vale by role
    # canonicalization is the exact cross-stage bug this chain first caught.
    assert any("Vale" in name for name in protagonists), protagonists
    assert any("Thorn" in name for name in protagonists), protagonists


def test_classification_keeps_protagonist_relationship(chain_run):
    """The Thorn–Vale edge must survive alias rewriting and intra-entity filtering."""
    relationships = chain_run["outputs"]["entity-classification"]["relationships"]
    assert relationships, "protagonist relationship dropped during classification"


def test_registry_covers_classified_entities(chain_run):
    registry_out = chain_run["outputs"]["write-registry"]["registry"]
    classified = chain_run["outputs"]["entity-classification"]["entities"]
    assert registry_out["entities"] >= len(classified)


def test_registry_mentions_carry_offsets(chain_run):
    """STU-489: mentions rebuilt from extraction carry non-None offsets that
    slice the chapter text (chapters.json) back to the mention surface — so a
    context window centered on the mention is extractible downstream."""
    processing = chain_run["processing"]
    registry = json.loads((processing / "registry.json").read_text(encoding="utf-8"))
    chapters = json.loads((processing / "chapters.json").read_text(encoding="utf-8"))[
        "chapters"
    ]
    checked = 0
    for entity in registry["entities"]:
        for mention in entity["mentions"]:
            assert mention["start"] is not None and mention["end"] is not None, mention
            text = chapters[mention["chapter_id"]]
            assert text[mention["start"] : mention["end"]] == mention["surface"], mention
            checked += 1
    assert checked > 0, "no registry mentions to check offsets on"


# ---------------------------------------------------------------------------
# Seed honesty check — in CI (spaCy model installed) verify the committed seed
# still matches the shapes real entity-extraction produces, so the golden
# chain never drifts from what extraction actually feeds resolution.
# ---------------------------------------------------------------------------

@requires_en_sm
def test_seed_shape_matches_real_extraction(chain_run):
    extraction = _run_stage("entity_extraction.py", {
        "additional_context": yaml.safe_dump({
            "file_path": str(chain_run["epub"]),
            "spacy_model": "en_core_web_sm",
            "min_mentions_absolute": 2,
        }),
        "previous_outputs": {"epub-parse": chain_run["parse_result"]},
    })
    real = extraction["entities_for_resolution"]
    assert real, "real extraction returned no entities"
    seed = json.loads((SEED_DIR / "extraction_output.json").read_text(encoding="utf-8"))
    seed_entities = seed["entities_for_resolution"]

    seed_keys = {frozenset(e.keys()) for e in seed_entities.values()}
    real_keys = {frozenset(e.keys()) for e in real.values()}
    assert seed_keys == real_keys, (
        f"seed entity shape {seed_keys} != real extraction shape {real_keys} — "
        f"regenerate the seed (gen_seed.py) and goldens"
    )

    chapter_ids = {ch["id"] for ch in chain_run["parse_result"]["chapters"]}
    assert {e["first_seen"] for e in seed_entities.values()} <= chapter_ids

    # The full per-type files must carry the same entry shape as the seed copies.
    processing = chain_run["epub"].parent.parent / "processing_output" / "smoke-novella"
    real_persons = json.loads(
        (processing / "persons_full.json").read_text(encoding="utf-8")
    )["persons_full"]
    seed_persons = json.loads(
        (SEED_DIR / "persons_full.json").read_text(encoding="utf-8")
    )["persons_full"]
    real_shape = {frozenset(e.keys()) for e in real_persons.values()}
    seed_shape = {frozenset(e.keys()) for e in seed_persons.values()}
    assert seed_shape == real_shape
