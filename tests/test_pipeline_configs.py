"""Sanity checks for Studio pipeline YAML files."""

from pathlib import Path

import yaml


PIPELINES_DIR = Path(__file__).resolve().parents[1] / ".studio" / "pipelines"


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
