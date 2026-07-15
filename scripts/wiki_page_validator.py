#!/usr/bin/env python3
"""Stage: wiki-page-validator (script executor)

Validates the page produced by wiki-page-item.
Structural checks (all importances): language, EPUB IDs, infobox keys,
series anchoring, forbidden names/series, identity coherence (grounding v1).
Grounding checks:
  - deterministic (all importances): proper nouns absent from the source
    excerpts (wiki_creator/grounding.py)
  - optional LLM (principal/secondary, opt-in via grounding_llm):
    claim-by-claim verification via Ollama — same JSON contract as
    .studio/agents/wiki-page-validator.agent.yaml; silent skip if Ollama
    is unavailable.

Every error carries a stable neutral `code` (language-independent) plus a
localized `message` (base.yaml `validator.errors`, follows output_language).
generate_wiki_pages matches identity recovery on the codes, never the prose.

Input (Studio stdin):
  previous_outputs["wiki-page-item"]: generated page
  additional_context: YAML with title (canonical_name), language, file_path,
  series, forbidden_series, forbidden_names, prompt (source excerpts),
  grounding_llm (bool), grounding_llm_model

Output (stdout):
  { "valid": bool, "errors": [...], "error_codes": [...], "feedback": str }
"""
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

from wiki_creator.grounding import find_ungrounded_names
from wiki_creator.lang import load_lang_config
from wiki_creator.llm import ollama
from wiki_creator.page_templates import language_name, slot_label, validator_message
from wiki_creator.registry import normalize_name as _normalize_name


@dataclass(frozen=True)
class ValidationError:
    """A validator failure: a stable neutral ``code`` for cross-component
    matching, plus a localized reader-facing ``message``."""
    code: str
    message: str


def _err(code: str, lang: str, **params) -> ValidationError:
    return ValidationError(code, f"❌ {validator_message(code, lang, **params)}")


def check_language_fr(page: dict, lang: str = "fr") -> list[ValidationError]:
    """Detect English contamination in a page that must be French.

    Marker vocabulary comes from cue_words/en.json (language_id_markers) —
    never hardcoded here. Degrades to no-op if the key is absent.
    """
    markers = load_lang_config("en").get("language_id_markers", [])
    content = page.get("content", "").lower()
    hits = [m for m in markers if m in content]
    if hits:
        return [_err("language_contamination", lang, markers=", ".join(hits[:3]))]
    return []


def check_epub_ids(page: dict, lang: str = "fr") -> list[ValidationError]:
    content = page.get("content", "")
    if ".xhtml" in content:
        return [_err("epub_id", lang)]
    return []


def check_infobox_keys(page: dict, lang: str = "fr") -> list[ValidationError]:
    ib = page.get("infobox_fields", {})
    bad = [k for k in ib if k.startswith("- ")]
    if bad:
        return [_err("infobox_key_prefix", lang, key=bad[0])]
    return []


def check_series_anchor(page: dict, meta: dict, lang: str = "fr") -> list[ValidationError]:
    series = meta.get("series", "")
    if not series:
        return []
    first_para = (page.get("content", "") + "\n").split("\n")[0]
    if series.lower() not in first_para.lower():
        return [_err("series_anchor_missing", lang, series=series)]
    return []


def check_forbidden_series(page: dict, meta: dict, lang: str = "fr") -> list[ValidationError]:
    forbidden = meta.get("forbidden_series", [])
    if not forbidden:
        return []
    haystack = page.get("content", "") + str(page.get("infobox_fields", {}))
    hits = [kw for kw in forbidden if kw.lower() in haystack.lower()]
    if hits:
        return [_err("forbidden_series", lang, hit=hits[0])]
    return []


def check_forbidden_names(page: dict, meta: dict, lang: str = "fr") -> list[ValidationError]:
    forbidden = meta.get("forbidden_names", [])
    if not forbidden:
        return []
    haystack = page.get("content", "") + str(page.get("infobox_fields", {}))
    hits = [name for name in forbidden if name.lower() in haystack.lower()]
    if hits:
        return [_err("forbidden_name", lang, name=hits[0])]
    return []


_IDENTITY_INFOBOX_KEYS = {"nom", "name", "titre", "title", "nom complet", "full name"}


def check_identity_match(page: dict, meta: dict, lang: str = "fr") -> list[ValidationError]:
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
        errors.append(_err("identity_title_mismatch", lang, page_title=page_title, expected=expected))

    for key, value in (page.get("infobox_fields") or {}).items():
        if _normalize_name(str(key)) in _IDENTITY_INFOBOX_KEYS and not matches(str(value)):
            errors.append(_err("identity_infobox_mismatch", lang, key=key, value=value, expected=expected))
    return errors


def check_ungrounded_names(page: dict, meta: dict, lang: str = "fr") -> list[ValidationError]:
    """Deterministic grounding — invented proper nouns.

    The generation prompt (meta['prompt']) contains everything the writer was
    allowed to know. A page proper noun absent from that prompt is an invention
    (cross-book contamination, hallucinated character).
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
    return [_err("ungrounded_name", lang, name=n) for n in names]


_GROUNDING_IMPORTANCES = {"principal", "secondary"}
_MAX_REPORTED_CLAIMS = 5

# Prompt scaffolding stays English (STU-510/STU-517); only the language-anchoring
# directive follows output_language. The .studio/agents/wiki-page-validator.agent.yaml
# variant of this check keeps the same JSON contract (grounded / ungrounded_claims).
_GROUNDING_PROMPT_TEMPLATE = """Respond with ONLY a valid JSON object. No markdown fences, no explanation.

You are a wiki-page validator for a novel.

The source excerpts below are the only allowed truth:
---
{source}
---

Wiki page to verify:
---
{page_content}
---

For every factual claim in the page (roles, relationships, events, deaths,
titles), check that it is directly grounded in the excerpts.
Use no external knowledge about the book or the author.
Bare proper nouns are not claims — ignore them.
Write each claim description in {claim_language}.

Return exactly:
{{"grounded": true, "ungrounded_claims": []}}
or
{{"grounded": false, "ungrounded_claims": ["short description", ...]}}
(at most {max_claims} claims)
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


def check_grounding_llm(page: dict, meta: dict, lang: str = "fr") -> list[ValidationError]:
    """LLM grounding — claim-by-claim verification via Ollama (opt-in).

    Catches invented facts about legitimate names (e.g. the death of a
    character who survives in the book), beyond the deterministic layer's
    reach. Graceful degradation: without Ollama the check is skipped with a
    stderr warning — never a stage failure.
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
        claim_language=language_name(lang),
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
    return [_err("ungrounded_claim", lang, claim=c) for c in claims]


def check_references_book_title(
    page: dict, allowed_book_titles: list[str], lang: str = "fr"
) -> list[ValidationError]:
    content = page.get("content", "")
    heading = re.escape(slot_label("references", lang))
    match = re.search(rf"##\s*{heading}(.*?)(?=\n##|\Z)", content, re.IGNORECASE | re.DOTALL)
    if not match:
        return []
    block = match.group(1)
    titles = re.findall(r"\*([^*\n]+)\*|_([^_\n]+)_", block)
    found = [t[0] or t[1] for t in titles]
    allowed_lower = [a.lower() for a in allowed_book_titles]
    errors = []
    for title in found:
        if title.lower() not in allowed_lower:
            errors.append(_err("unauthorized_reference_title", lang, title=title))
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
    lang = meta.get("language", "fr")
    errors: list[ValidationError] = []
    # The FR-contamination check only applies to French books; the book
    # language comes from the item input (default 'fr', historical corpus).
    if lang == "fr":
        errors += check_language_fr(page, lang)
    errors += check_epub_ids(page, lang)
    errors += check_identity_match(page, meta, lang)
    errors += check_infobox_keys(page, lang)
    errors += check_series_anchor(page, meta, lang)
    errors += check_forbidden_series(page, meta, lang)
    errors += check_forbidden_names(page, meta, lang)
    errors += check_ungrounded_names(page, meta, lang)
    errors += check_grounding_llm(page, meta, lang)
    allowed_book_titles = _load_allowed_book_titles(meta)
    if allowed_book_titles:
        errors += check_references_book_title(page, allowed_book_titles, lang)
    messages = [e.message for e in errors]
    return {
        "valid": len(errors) == 0,
        "errors": messages,
        "error_codes": [e.code for e in errors],
        "feedback": build_feedback(messages, lang) if errors else "",
    }


def build_feedback(errors: list[str], lang: str = "fr") -> str:
    """Retry feedback for the writer. Scaffolding stays English (STU-510); only
    the write-in-language directive follows ``lang`` (STU-514). The error lines it
    interpolates are already localized to ``lang`` (STU-517)."""
    lines = "\n".join(f"- {e}" for e in errors)
    lang_name = language_name(lang)
    return (
        "The previous page contained the following errors. "
        "Regenerate it, fixing all of them:\n"
        f"{lines}\n\n"
        f"Reminders: write entirely in {lang_name}, ground every statement in the "
        "provided excerpts, and mention no series other than the book's."
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
