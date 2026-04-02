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
import re
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


def check_forbidden_names(page: dict, meta: dict) -> list[str]:
    forbidden = meta.get("forbidden_names", [])
    if not forbidden:
        return []
    haystack = page.get("content", "") + str(page.get("infobox_fields", {}))
    hits = [name for name in forbidden if name.lower() in haystack.lower()]
    if hits:
        return [f"❌ Spoiler détecté (nom interdit) : {hits[0]}"]
    return []


def check_references_book_title(page: dict, allowed_book_titles: list[str]) -> list[str]:
    content = page.get("content", "")
    match = re.search(r"##\s*Références(.*?)(?=\n##|\Z)", content, re.IGNORECASE | re.DOTALL)
    if not match:
        return []
    block = match.group(1)
    titles = re.findall(r"\*([^*\n]+)\*|_([^_\n]+)_", block)
    found = [t[0] or t[1] for t in titles]
    allowed_lower = [a.lower() for a in allowed_book_titles]
    errors = []
    for title in found:
        if title.lower() not in allowed_lower:
            errors.append(f"❌ Titre non autorisé dans Références : '{title}'")
    return errors


def _load_allowed_book_titles(meta: dict) -> list[str]:
    file_path = meta.get("file_path", "")
    if not file_path:
        return []
    try:
        from wiki_creator.paths import book_paths_from_epub
        paths = book_paths_from_epub(file_path)
        epub_data = paths.processing / "epub_data.json"
        with open(epub_data, encoding="utf-8") as f:
            data = json.load(f)
        title = data.get("title", "")
        return [title] if title else []
    except Exception as exc:
        print(f"[wiki-page-validator] could not load book title for references check: {exc}", file=sys.stderr)
        return []


def validate_page(page: dict, meta: dict) -> dict:
    errors: list[str] = []
    errors += check_language_fr(page)
    errors += check_epub_ids(page)
    errors += check_infobox_keys(page)
    errors += check_series_anchor(page, meta)
    errors += check_forbidden_series(page, meta)
    errors += check_forbidden_names(page, meta)
    allowed_book_titles = _load_allowed_book_titles(meta)
    if allowed_book_titles:
        errors += check_references_book_title(page, allowed_book_titles)
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "feedback": build_feedback(errors) if errors else "",
    }


def build_feedback(errors: list[str]) -> str:
    lines = "\n".join(f"- {e}" for e in errors)
    return (
        "La page précédente contient les erreurs suivantes. "
        "Régénère-la en les corrigeant toutes :\n"
        f"{lines}\n\n"
        "Rappels : écris entièrement en français, appuie chaque affirmation "
        "sur les extraits fournis, ne mentionne aucune série sauf celle du livre."
    )


def parse_payload(payload: dict) -> tuple[dict, dict]:
    """Extract (page, meta) from Studio payload."""
    prev = payload.get("previous_outputs", {})
    page = prev.get("wiki-page-item", {})
    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    return page, ctx


if __name__ == "__main__":
    payload = json.load(sys.stdin)
    page, meta = parse_payload(payload)
    result = validate_page(page, meta)
    print(json.dumps(result))
