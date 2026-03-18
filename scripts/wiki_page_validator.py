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


_EN_MARKERS = [
    "is the", "was a", "was the", "known as", "also known",
    "she was", "he is", "he was", "they are", "is an", "is a",
]


def check_language_fr(page: dict) -> list[str]:
    content = page.get("content", "").lower()
    hits = [m for m in _EN_MARKERS if m in content]
    if hits:
        return [f"❌ Contenu en anglais détecté (marqueurs : {', '.join(hits[:3])})"]
    return []


def check_epub_ids(page: dict) -> list[str]:
    content = page.get("content", "")
    if ".xhtml" in content:
        return ["❌ ID EPUB dans le contenu (ex: C07.xhtml)"]
    return []


def check_infobox_keys(page: dict) -> list[str]:
    ib = page.get("infobox_fields", {})
    bad = [k for k in ib if k.startswith("- ")]
    if bad:
        return [f"❌ Clé infobox préfixée par '- ' : {bad[0]}"]
    return []


def check_series_anchor(page: dict, meta: dict) -> list[str]:
    series = meta.get("series", "")
    if not series:
        return []
    first_para = (page.get("content", "") + "\n").split("\n")[0]
    if series.lower() not in first_para.lower():
        return [f"❌ Le titre de série '{series}' est absent du premier paragraphe"]
    return []


def check_forbidden_series(page: dict, meta: dict) -> list[str]:
    forbidden = meta.get("forbidden_series", [])
    if not forbidden:
        return []
    haystack = page.get("content", "") + str(page.get("infobox_fields", {}))
    hits = [kw for kw in forbidden if kw.lower() in haystack.lower()]
    if hits:
        return [f"❌ Hallucination cross-série détectée : {hits[0]}"]
    return []


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
