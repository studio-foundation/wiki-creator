"""Sanity checks for Studio pipeline YAML files."""

from pathlib import Path

import yaml


PIPELINES_DIR = Path(__file__).resolve().parents[1] / ".studio" / "pipelines"
CONTRACTS_DIR = Path(__file__).resolve().parents[1] / ".studio" / "contracts"
AGENTS_DIR = Path(__file__).resolve().parents[1] / ".studio" / "agents"


def _load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_script_stages_use_script_paths_only() -> None:
    """`script` must be a file path, not a command with inline flags."""
    for pipeline_path in PIPELINES_DIR.glob("*.pipeline.yaml"):
        doc = _load_yaml(pipeline_path)
        for stage in doc.get("stages", []):
            if stage.get("executor") != "script":
                continue
            script = stage.get("script", "")
            assert script.endswith(".py"), (
                f"{pipeline_path.name}:{stage.get('name')} script must end with .py, got {script!r}"
            )
            assert " " not in script.strip(), (
                f"{pipeline_path.name}:{stage.get('name')} script must be path only, got {script!r}"
            )


def test_chapter_summary_stage_has_explicit_extended_timeout() -> None:
    """LLM-backed chapter summaries need a longer timeout than Studio's 30s default."""
    target_pipelines = {
        "wiki-preparation.pipeline.yaml",
        "wiki-generation.pipeline.yaml",
    }

    for pipeline_name in target_pipelines:
        doc = _load_yaml(PIPELINES_DIR / pipeline_name)
        chapter_stage = next(
            stage for stage in doc.get("stages", [])
            if stage.get("name") == "chapter-summary"
        )
        assert chapter_stage.get("timeout_ms") == 600000, (
            f"{pipeline_name}:chapter-summary must set timeout_ms=600000"
        )


def test_chapter_summary_item_contract_exists_with_required_fields() -> None:
    contract_path = CONTRACTS_DIR / "chapter-summary-item.contract.yaml"
    assert contract_path.exists(), "chapter-summary-item contract is missing"

    doc = _load_yaml(contract_path)
    required_fields = doc.get("schema", {}).get("required_fields", [])
    assert required_fields == ["chapter_id", "chapter_title", "summary_bullets"]


def test_chapter_summary_item_pipeline_uses_ralph_and_contract() -> None:
    pipeline_path = PIPELINES_DIR / "chapter-summary-item.pipeline.yaml"
    agent_path = AGENTS_DIR / "chapter-summary.agent.yaml"

    assert pipeline_path.exists(), "chapter-summary-item pipeline is missing"
    assert agent_path.exists(), "chapter-summary agent is missing"

    doc = _load_yaml(pipeline_path)
    llm_stage = next(
        stage for stage in doc.get("stages", [])
        if stage.get("contract") == "chapter-summary-item"
    )
    assert llm_stage.get("agent") == "chapter-summary"
    assert isinstance(llm_stage.get("ralph"), dict), "chapter-summary-item stage must configure ralph"


def test_wiki_page_item_contract_exists_with_required_fields() -> None:
    contract_path = CONTRACTS_DIR / "wiki-page-item.contract.yaml"
    assert contract_path.exists(), "wiki-page-item contract is missing"

    doc = _load_yaml(contract_path)
    required_fields = doc.get("schema", {}).get("required_fields", [])
    assert required_fields == ["title", "importance", "entity_type", "infobox_fields", "content"]


def test_wiki_page_item_pipeline_uses_ralph_and_contract() -> None:
    pipeline_path = PIPELINES_DIR / "wiki-page-item.pipeline.yaml"
    agent_path = AGENTS_DIR / "wiki-page-item.agent.yaml"

    assert pipeline_path.exists(), "wiki-page-item pipeline is missing"
    assert agent_path.exists(), "wiki-page-item agent is missing"

    doc = _load_yaml(pipeline_path)
    llm_stage = next(
        stage for stage in doc.get("stages", [])
        if stage.get("contract") == "wiki-page-item"
    )
    assert llm_stage.get("agent") == "wiki-page-item"
    assert isinstance(llm_stage.get("ralph"), dict), "wiki-page-item stage must configure ralph"


def test_wiki_resolution_pipeline_inserts_alias_resolution_between_resolve_and_merge() -> None:
    pipeline_path = PIPELINES_DIR / "wiki-resolution.pipeline.yaml"
    doc = _load_yaml(pipeline_path)
    stage_names = [stage.get("name") for stage in doc.get("stages", [])]

    assert "alias-resolution" in stage_names
    assert stage_names.index("resolve-clusters") < stage_names.index("alias-resolution")
    assert stage_names.index("alias-resolution") < stage_names.index("merge-entities")

    alias_stage = next(
        stage for stage in doc.get("stages", [])
        if stage.get("name") == "alias-resolution"
    )
    assert alias_stage.get("script") == "scripts/alias_resolution.py"


def test_alias_resolution_contract_exists_with_required_fields() -> None:
    contract_path = CONTRACTS_DIR / "alias-resolution.contract.yaml"
    assert contract_path.exists(), "alias-resolution contract is missing"

    doc = _load_yaml(contract_path)
    required_fields = doc.get("schema", {}).get("required_fields", [])
    assert required_fields == ["entities", "narrator"]
