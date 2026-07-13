#!/usr/bin/env python3
"""Stage: wiki-page-validator (script executor)

Valide la page générée par wiki-page-item.
Checks structurels (toutes importances) : langue, IDs EPUB, clés infobox,
ancrage série, noms/séries interdits, cohérence identitaire (grounding v1).
Checks de grounding :
  - déterministe (toutes importances) : noms propres absents des extraits
    source (wiki_creator/grounding.py)
  - LLM optionnel (principal/secondary, opt-in via grounding_llm) :
    vérification claim-par-claim via Ollama — même contrat JSON que
    .studio/agents/wiki-page-validator.agent.yaml ; skip silencieux si
    Ollama indisponible.

Input (Studio stdin):
  previous_outputs["wiki-page-item"]: page générée
  additional_context: YAML avec title (canonical_name), language, file_path,
  series, forbidden_series, forbidden_names, prompt (extraits source),
  grounding_llm (bool), grounding_llm_model

Output (stdout):
  { "valid": bool, "errors": [...], "feedback": str }
"""
import json
import os
import re
import sys
from pathlib import Path

import yaml

from wiki_creator.grounding import find_ungrounded_names
from wiki_creator.lang import load_lang_config
from wiki_creator.llm import ollama
from wiki_creator.registry import normalize_name as _normalize_name


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


def check_ungrounded_names(page: dict, meta: dict) -> list[str]:
    """Grounding déterministe — noms propres inventés.

    Le prompt de génération (meta['prompt']) contient tout ce que le writer
    avait le droit de savoir. Un nom propre de la page absent de ce prompt
    est une invention (contamination cross-livre, personnage halluciné).
    """
    source = meta.get("prompt", "")
    if not source:
        return []
    # The expected title is legitimate even if phrased differently.
    source = f"{source}\n{meta.get('title', '')}"
    names = find_ungrounded_names(
        page.get("content", ""),
        page.get("infobox_fields") or {},
        source,
        language=meta.get("language", "fr"),
    )
    return [f"❌ Nom non ancré dans les extraits source : {n}" for n in names]


_GROUNDING_IMPORTANCES = {"principal", "secondary", "secondaire"}
_MAX_REPORTED_CLAIMS = 5

# Same contract as .studio/agents/wiki-page-validator.agent.yaml (the agent
# variant of this check) — keep the two in sync.
_GROUNDING_PROMPT_TEMPLATE = """Respond with ONLY a valid JSON object. No markdown fences, no explanation.

Tu es un validateur de pages wiki pour un roman.

Les extraits source ci-dessous sont la seule vérité autorisée :
---
{source}
---

Page wiki à vérifier :
---
{page_content}
---

Pour chaque affirmation factuelle de la page (rôles, relations, événements,
morts, titres), vérifie qu'elle est directement ancrée dans les extraits.
N'utilise aucune connaissance externe sur le livre ou l'auteur.
Les noms propres seuls ne sont pas des affirmations — ignore-les.

Retourne exactement :
{{"grounded": true, "ungrounded_claims": []}}
ou
{{"grounded": false, "ungrounded_claims": ["description courte", ...]}}
(au maximum {max_claims} claims)
"""


def _parse_grounding_response(raw: str) -> list[str]:
    """Extract ungrounded_claims from the model output; [] on any mismatch."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    if data.get("grounded") is True:
        return []
    claims = data.get("ungrounded_claims", [])
    if not isinstance(claims, list):
        return []
    return [str(c) for c in claims[:_MAX_REPORTED_CLAIMS] if str(c).strip()]


def check_grounding_llm(page: dict, meta: dict) -> list[str]:
    """Grounding LLM — vérification claim-par-claim via Ollama (opt-in).

    Attrape les faits inventés sur des noms légitimes (ex : mort d'un
    personnage qui survit dans le livre), hors de portée de la couche
    déterministe. Dégradation gracieuse : sans Ollama, le check est sauté
    avec un avertissement stderr — jamais d'échec de stage.
    """
    if not meta.get("grounding_llm"):
        return []
    if page.get("importance") not in _GROUNDING_IMPORTANCES:
        return []
    source = meta.get("prompt", "")
    content = page.get("content", "")
    if not source or not content:
        return []

    url = os.environ.get("OLLAMA_URL", ollama.DEFAULT_URL)
    if not ollama.is_available(url):
        print(
            f"[wiki-page-validator] Ollama not available at {url} — "
            "LLM grounding check skipped.",
            file=sys.stderr,
        )
        return []

    prompt = _GROUNDING_PROMPT_TEMPLATE.format(
        source=source,
        page_content=content,
        max_claims=_MAX_REPORTED_CLAIMS,
    )
    raw = ollama.generate(
        prompt,
        model=meta.get("grounding_llm_model", "mistral:7b-instruct"),
        url=url,
        timeout=int(meta.get("grounding_llm_timeout", 120)),
        num_predict=512,
    )
    if raw is None:
        print("[wiki-page-validator] LLM grounding call failed", file=sys.stderr)
        return []

    claims = _parse_grounding_response(raw)
    return [f"❌ Affirmation non ancrée dans les extraits source : {c}" for c in claims]


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
    errors += check_ungrounded_names(page, meta)
    errors += check_grounding_llm(page, meta)
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
