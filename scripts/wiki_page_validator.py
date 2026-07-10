#!/usr/bin/env python3
"""Stage: wiki-page-validator (script executor)

Valide la page générée par wiki-page-item.
Checks structurels (toutes importances) : langue, IDs EPUB, clés infobox,
ancrage série, noms/séries interdits, cohérence identitaire (grounding v1).

Input (Studio stdin):
  previous_outputs["wiki-page-item"]: page générée
  additional_context: YAML avec title (canonical_name), language, file_path,
  series, forbidden_series, forbidden_names

Output (stdout):
  { "valid": bool, "errors": [...], "feedback": str }
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from wiki_creator.lang import load_lang_config


def check_language_fr(page: dict) -> list[str]:
    """Detect English contamination in a page that must be French.

    Marker vocabulary comes from cue_words/en.json (language_id_markers) —
    never hardcoded here. Degrades to no-op if the key is absent.
    """
    markers = load_lang_config("en").get("language_id_markers", [])
    content = page.get("content", "").lower()
    hits = [m for m in markers if m in content]
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


_IDENTITY_INFOBOX_KEYS = {"nom", "name", "titre", "title", "nom complet", "full name"}


def _normalize_name(value: str) -> str:
    """Lowercase and strip accents for tolerant name comparison."""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    return value.strip().lower()


def check_identity_match(page: dict, meta: dict) -> list[str]:
    """Grounding v1 — the page must describe the entity it was asked for.

    Catches identity confusions observed in real runs (page 'Verin' with
    infobox nom='Kaltain', title 'Philippa' rendered as 'Philippe'):
    - page title must match the requested canonical_name;
    - identity infobox fields (nom/name/titre) must reference it.
    A match is exact or by containment in either direction (accent- and
    case-insensitive), so 'Celaena' vs 'Celaena Sardothien' passes.
    """
    expected = meta.get("title", "")
    if not expected:
        return []
    expected_n = _normalize_name(expected)
    errors = []

    def matches(value: str) -> bool:
        value_n = _normalize_name(value)
        return bool(value_n) and (expected_n in value_n or value_n in expected_n)

    page_title = str(page.get("title", ""))
    if page_title and not matches(page_title):
        errors.append(
            f"❌ Titre de page '{page_title}' ≠ entité demandée '{expected}'"
        )

    for key, value in (page.get("infobox_fields") or {}).items():
        if _normalize_name(str(key)) in _IDENTITY_INFOBOX_KEYS and not matches(str(value)):
            errors.append(
                f"❌ Infobox '{key}: {value}' ne correspond pas à l'entité '{expected}'"
            )
    return errors


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
    # The FR-contamination check only applies to French books; the book
    # language comes from the item input (default 'fr', historical corpus).
    if meta.get("language", "fr") == "fr":
        errors += check_language_fr(page)
    errors += check_epub_ids(page)
    errors += check_identity_match(page, meta)
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
