"""Pipeline wiring after run_wiki.py's retirement (STU-457).

Studio orchestrates everything: the four top-level pipelines are call stages of
wiki-full, and every former run_wiki.py pre-step is a stage of the pipeline it
used to precede. These tests pin the wiring — the STU-512 lesson: without them,
a stage can be unwired with the suite green.
"""
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = ROOT / ".studio" / "contracts"
PIPELINES_DIR = ROOT / ".studio" / "pipelines"


def _pipeline(name: str) -> dict:
    return yaml.safe_load((PIPELINES_DIR / f"{name}.pipeline.yaml").read_text(encoding="utf-8"))


def _stage_names(pipeline: dict) -> list[str]:
    return [s.get("name") or s.get("call") or s.get("map") for s in pipeline["stages"]]


def _scripts(pipeline: dict) -> list[str]:
    return [s.get("script", "") for s in pipeline["stages"]]


def _expected_output_files(contract_name: str) -> list[str]:
    doc = yaml.safe_load(
        (CONTRACTS_DIR / f"{contract_name}.contract.yaml").read_text(encoding="utf-8")
    )
    return (doc.get("expected_outputs") or {}).get("files") or []


# STU-600: every output run_wiki.py's required_files() used to assert is declared
# as expected_outputs.files on the Studio contract of the stage that writes it,
# checked inside the RALPH loop. This map is the guard against a silent removal —
# the STU-591 trap: dropping a declaration must break a test, not vanish the only
# check that the file exists. (batch_ stands for the wiki_inputs/<slug>/batch_*.json
# files the wiki-preparation stage emits; chapter_summaries.json moved to the
# chapter-summary stage contract when the pre-step became a stage, STU-457.)
MOVED_OUTPUT_DECLARATIONS = [
    ("epub-parse", "epub_data.json"),
    ("entity-extraction", "extraction_config.json"),
    ("split-clusters", "splits.json"),
    ("chapter-summary", "chapter_summaries.json"),
    ("entity-classification", "entities_classified.json"),
    ("write-registry", "registry.json"),
    ("wiki-preparation", "relationships_classified.json"),
    ("wiki-preparation", "batch_"),
    ("wiki-page", "wiki_pages.json"),
]


@pytest.mark.parametrize("contract_name,filename", MOVED_OUTPUT_DECLARATIONS)
def test_pipeline_outputs_declared_in_contracts(contract_name, filename) -> None:
    files = _expected_output_files(contract_name)
    assert any(filename in f for f in files), (
        f"{contract_name}.contract.yaml must declare an expected_outputs.files entry "
        f"matching {filename!r} (moved from run_wiki.py required_files(), STU-600)"
    )


def test_extraction_config_declared_on_entity_extraction_stage() -> None:
    from wiki_creator.ner import EXTRACTION_CONFIG_FILE
    files = _expected_output_files("entity-extraction")
    assert any(EXTRACTION_CONFIG_FILE in f for f in files), (
        "an extraction that declares no config cannot be invalidated by a config "
        "change (STU-560); the declaration lives on entity-extraction (STU-600)"
    )


def test_wiki_full_chains_the_four_pipelines_in_order() -> None:
    """The four-pipeline sequence run_wiki.py used to hand-chain is Studio's now
    (STU-599 call stages). Order is the data-flow order: each pipeline reads the
    previous one's artifacts from disk (STU-455)."""
    stages = _pipeline("wiki-full")["stages"]
    assert [s["call"] for s in stages] == [
        "wiki-extraction",
        "wiki-resolution",
        "wiki-preparation",
        "pages-export",
    ]


def test_wiki_resolution_summarizes_chapters_first() -> None:
    """chapter summarization runs first in wiki-resolution. Since STU-621 it is a
    pre/call/post split (pre builds the fan-out items, the native call runs the
    engine map, post collects), so the pre stage leads and the post precedes the
    stages that read chapter_summaries.json downstream."""
    scripts = _scripts(_pipeline("wiki-resolution"))
    assert "chapter_summary_pre.py" in scripts[0]
    pre_idx = next(i for i, s in enumerate(scripts) if "chapter_summary_pre.py" in s)
    post_idx = next(i for i, s in enumerate(scripts) if "chapter_summary.py" in s)
    resolve_idx = next(i for i, s in enumerate(scripts) if "resolve_clusters.py" in s)
    assert pre_idx < post_idx < resolve_idx


def test_wiki_resolution_wires_chapter_summary_as_pre_call_post() -> None:
    """The STU-621 shape: a native `call: chapter-summaries` runs the engine map
    only when the pre stage says so (llm mode, chapters pending), and
    on_failure: continue keeps the run alive (extractive fallback in post)."""
    stages = _pipeline("wiki-resolution")["stages"]
    call = next(s for s in stages if s.get("call") == "chapter-summaries-verdict")
    assert call["pipeline"] == "chapter-summaries"
    assert call["on_failure"] == "continue"
    assert "needs_verdict" in call["condition"]


def test_wiki_preparation_runs_classify_before_events() -> None:
    """events depend on relationships_classified.json, so classify_relationships.py
    must run before build_event_layer.py; discovery types the graph the classifier
    reads, so it comes before classify (STU-556)."""
    scripts = _scripts(_pipeline("wiki-preparation"))
    discover_idx = next(i for i, s in enumerate(scripts) if "discover_relationships.py" in s)
    classify_idx = next(i for i, s in enumerate(scripts) if "classify_relationships.py" in s)
    graph_idx = next(i for i, s in enumerate(scripts) if "build_character_graph.py" in s)
    events_idx = next(i for i, s in enumerate(scripts) if "build_event_layer.py" in s)
    prep_idx = next(i for i, s in enumerate(scripts) if "wiki_preparation.py" in s)
    assert discover_idx < classify_idx < graph_idx < events_idx < prep_idx


def test_wiki_preparation_wires_the_entity_trio_as_pre_call_post() -> None:
    """The STU-457 shape: pre decides cache hit/miss, the call runs the LLM only
    on a miss (condition), post applies with the stage's safe default — so a
    failed verdict merges nothing and the run proceeds (on_failure: continue)."""
    stages = _pipeline("wiki-preparation")["stages"]
    by_call = {s.get("call"): s for s in stages if s.get("call")}
    for verdict, item_pipeline in [
        ("entity-status-verdict", "entity-status-item"),
        ("entity-affiliation-verdict", "entity-affiliation-item"),
        ("entity-species-verdict", "entity-species-item"),
    ]:
        call = by_call[verdict]
        assert call["pipeline"] == item_pipeline
        assert call["on_failure"] == "continue"
        assert "needs_verdict" in call["condition"]


def test_wiki_preparation_wires_discover_and_classify_as_pre_call_post() -> None:
    """STU-621: the relation fan-outs are native `call` stages, not subprocess
    fan-outs — condition-gated on the pre stage, on_failure: continue."""
    stages = _pipeline("wiki-preparation")["stages"]
    by_call = {s.get("call"): s for s in stages if s.get("call")}
    for verdict, item_pipeline in [
        ("discover-relationships-verdict", "discover-relationships"),
        ("classify-relationships-verdict", "classify-relationships"),
    ]:
        call = by_call[verdict]
        assert call["pipeline"] == item_pipeline
        assert call["on_failure"] == "continue"
        assert "needs_verdict" in call["condition"]


def test_pages_export_wires_the_page_fan_outs_as_native_calls() -> None:
    """STU-621: synopsis / event pages route through the `wiki-pages` map, and
    generate-wiki-pages is the two-pass plan/call/probe/call split — every page
    fan-out is a native `call`, no per-page subprocess."""
    stages = _pipeline("pages-export")["stages"]
    by_call = {s.get("call"): s for s in stages if s.get("call")}
    for verdict in ("book-synopsis-verdict", "event-pages-verdict", "wiki-pages-verdict"):
        assert by_call[verdict]["pipeline"] == "wiki-pages"
        assert by_call[verdict]["on_failure"] == "continue"
        assert "needs_verdict" in by_call[verdict]["condition"]
    # The attempt-2 retry call fires only when the probe found forbidden-name hits.
    retry = by_call["wiki-pages-retry-verdict"]
    assert retry["pipeline"] == "wiki-pages"
    assert "needs_retry" in retry["condition"]


def test_pages_export_generates_before_assembling() -> None:
    """The four generation pre-steps are stages now; assembly reads their
    artifacts, so every generator must precede assemble_wiki_pages.py, and the
    synopsis (SP4) follows the entity pages it links."""
    scripts = _scripts(_pipeline("pages-export"))
    pages_idx = next(i for i, s in enumerate(scripts) if "generate_wiki_pages.py" in s)
    synopsis_idx = next(i for i, s in enumerate(scripts) if "generate_book_synopsis.py" in s)
    events_idx = next(i for i, s in enumerate(scripts) if "generate_event_pages.py" in s)
    stance_idx = next(i for i, s in enumerate(scripts) if "consolidate_editorial_stance.py" in s)
    assemble_idx = next(i for i, s in enumerate(scripts) if "assemble_wiki_pages.py" in s)
    assert pages_idx < synopsis_idx < events_idx < stance_idx < assemble_idx
