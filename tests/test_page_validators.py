import json
import os
import subprocess
import sys
from pathlib import Path

from wiki_creator.page_templates import load_base_template, resolve_template
from wiki_creator.page_validators import duplicate_page_titles, undeclared_entity_types

REPO_ROOT = Path(__file__).resolve().parent.parent
DECLARED = set(load_base_template().get("entity_types") or {})


def _page(title, entity_type="PERSON"):
    return {"title": title, "entity_type": entity_type}


def _run_validator(script, output):
    proc = subprocess.run(
        [sys.executable, f"scripts/{script}"],
        input=json.dumps(output),
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_declared_types_pass():
    pages = [_page("Celaena", "PERSON"), _page("Adarlan", "PLACE"), _page("Synopsis", "SYNOPSIS")]
    assert undeclared_entity_types(pages, DECLARED) == []


def test_every_type_shipped_by_the_pipeline_is_declared():
    """The types real stages emit must exist in base.yaml — the drift this
    validator closes (the contract claimed PERSON|PLACE|ORG after EVENT shipped)."""
    assert {"PERSON", "PLACE", "ORG", "EVENT", "OTHER", "SYNOPSIS"} <= DECLARED


def test_templateless_types_resolve_to_no_slots():
    """OTHER/SYNOPSIS carry empty groups, so they resolve to zero slots exactly
    as an undeclared type did before they were added."""
    for etype in ("OTHER", "SYNOPSIS"):
        for tier in ("figurant", "secondary", "principal"):
            assert resolve_template(etype, tier).slots == ()


def test_declaring_a_type_lets_a_book_override_reach_it():
    """Declaring the key stops resolve_template from early-returning: a
    generation.template override now applies instead of being dropped."""
    book_config = {"generation": {"template": {"OTHER": {"add": [
        {"token": "biography", "group": "section", "provenance": "llm-prose",
         "obligation": "OPT", "tiers": ["principal"]},
    ]}}}}
    slots = resolve_template("OTHER", "principal", book_config).slots
    assert [s.token for s in slots] == ["biography"]


def test_undeclared_type_is_an_error():
    errors = undeclared_entity_types([_page("Cadre", "FACTION")], DECLARED)
    assert len(errors) == 1
    assert "'FACTION'" in errors[0] and "Cadre" in errors[0]


def test_unique_titles_pass():
    assert duplicate_page_titles([_page("Celaena"), _page("Chaol")]) == []


def test_collision_after_filename_rendering_is_an_error():
    """`page_filename` maps both spaces and slashes to `_`, so distinct titles
    can still land on one wiki title."""
    errors = duplicate_page_titles([_page("Rifthold Castle"), _page("Rifthold/Castle")])
    assert len(errors) == 1
    assert "Rifthold_Castle" in errors[0]


def test_entity_type_script_rejects_undeclared_type():
    result = _run_validator(
        "validate_entity_type_declared.py", {"pages": [_page("Cadre", "FACTION")]}
    )
    assert result["valid"] is False
    assert "FACTION" in result["errors"][0]


def test_entity_type_script_accepts_declared_types():
    result = _run_validator("validate_entity_type_declared.py", {"pages": [_page("Celaena")]})
    assert result == {"valid": True, "errors": []}


def test_unique_title_script_rejects_collision():
    result = _run_validator(
        "validate_unique_page_title.py", {"pages": [_page("Rifthold Castle"), _page("Rifthold/Castle")]}
    )
    assert result["valid"] is False
    assert "Rifthold_Castle" in result["errors"][0]


def test_unique_title_script_accepts_distinct_titles():
    result = _run_validator(
        "validate_unique_page_title.py", {"pages": [_page("Celaena"), _page("Chaol")]}
    )
    assert result == {"valid": True, "errors": []}
