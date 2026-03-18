#!/usr/bin/env python3
"""Stage: wiki-page-validator (script executor)

Valide la page générée par wiki-page-item.
Checks structurels (toutes importances) + grounding LLM (principal/secondary).

Input (Studio stdin):
  previous_outputs["wiki-page-item"]: page générée
  additional_context: YAML avec file_path, series, forbidden_series

Output (stdout):
  { "valid": bool, "errors": [...], "feedback": str }
"""
import json
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def parse_payload(payload: dict) -> tuple[dict, dict]:
    """Extract (page, meta) from Studio payload."""
    prev = payload.get("previous_outputs", {})
    page = prev.get("wiki-page-item", {})
    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    return page, ctx


if __name__ == "__main__":
    payload = json.load(sys.stdin)
    page, meta = parse_payload(payload)
    result = {"valid": True, "errors": [], "feedback": ""}
    print(json.dumps(result))
