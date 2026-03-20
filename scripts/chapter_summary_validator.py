#!/usr/bin/env python3
"""Stage: chapter-summary-validator (script executor)

Checks structurels sur un résumé de chapitre généré par chapter-summary-item.

Input (Studio stdin):
  previous_outputs["chapter-summary-item"]: résumé généré
  additional_context: YAML book metadata

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
    prev = payload.get("previous_outputs", {})
    summary = prev.get("chapter-summary-item", {})
    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    return summary, ctx


def check_temporal_context(summary: dict) -> list[str]:
    tc = summary.get("temporal_context")
    if not tc:
        return ["❌ temporal_context absent ou null"]
    return []


def check_bullets_not_empty(summary: dict) -> list[str]:
    bullets = summary.get("summary_bullets", [])
    if not bullets:
        return ["❌ summary_bullets vide"]
    return []


def validate_summary(summary: dict, meta: dict) -> dict:
    errors: list[str] = []
    errors += check_temporal_context(summary)
    errors += check_bullets_not_empty(summary)
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "feedback": build_feedback(errors) if errors else "",
    }


def build_feedback(errors: list[str]) -> str:
    lines = "\n".join(f"- {e}" for e in errors)
    return (
        "Le résumé précédent contient les erreurs suivantes. Régénère-le :\n"
        f"{lines}\n\n"
        "Rappels : renseigne temporal_context (present|flashback), "
        "génère au moins 3 bullets ancrés dans le texte du chapitre."
    )


if __name__ == "__main__":
    payload = json.load(sys.stdin)
    summary, meta = parse_payload(payload)
    result = validate_summary(summary, meta)
    print(json.dumps(result))
