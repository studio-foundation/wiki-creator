"""Editorial-stance consolidation (STU-508): a single post-generation pass that
scans generated pages for register contradicting the book's declared
``editorial_stance.mode`` (STU-507) and reports the drift.

Advisory only (``non_binary_advisory``) — never fails a run. Inter-page tone
coherence is not contractable per page (INV-08), so this is a run-level report,
not a per-page validator.

Deterministic and zero-LLM: the marker vocabulary lives in
``cue_words/<lang>.json`` (``editorial_stance_markers``), never hardcoded here.
The Fable frugality constraint — one pass, not a verifier per page — holds by
construction. Absent vocabulary degrades to no findings.

Three independent axes:
- ``meta_narrative`` / ``reader_address`` markers speak of the text as text or
  address the reader — forbidden by the in-universe rule (everywhere in
  ``in_universe``; outside the exception sections in ``hybrid``; never flagged
  in ``out_of_universe``).
- ``author`` markers name the real-world author/publisher/edition — forbidden
  whenever ``stance.forbid_author_mentions``, regardless of mode or section.
- ``pipeline_metric`` (STU-579) flags a raw mention/cooccurrence count leaked
  into prose (a number next to a metric term, e.g. "503 mentions communes").
  Stance-independent: an internal pipeline metric is never reader-facing text
  in any mode or section, so it is always flagged.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from wiki_creator.editorial_stance import OUT_OF_UNIVERSE_SECTIONS, EditorialStance
from wiki_creator.lang import load_lang_config
from wiki_creator.page_templates import slot_label

_INUNIVERSE_CATEGORIES = ("meta_narrative", "reader_address")
_AUTHOR_CATEGORY = "author"
_PIPELINE_METRIC_CATEGORY = "pipeline_metric"

# Characters of context kept on each side of a matched marker in the quote.
QUOTE_RADIUS = 45

_HEADING_RE = re.compile(r"(?m)^#{2,6}\s*(.+?)\s*$")

# A raw integer, tolerating thousands separators and thin/no-break spaces
# ("1234", "1,234", "1.234", "1\u00a0234").
_NUMBER = "\\d[\\d.,\u00a0\u202f\u2009 ]*"


@dataclass(frozen=True)
class StanceFinding:
    page_title: str
    entity_type: str
    section: str  # heading the marker sits under ("" = lede, before first heading)
    category: str
    marker: str
    quote: str


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.casefold().replace("’", "'").strip()


def load_markers(lang: str) -> dict[str, list[str]]:
    """``editorial_stance_markers`` from cue_words, one bucket per category.
    Empty dict when the key is absent — the scan then finds nothing."""
    raw = load_lang_config(lang).get("editorial_stance_markers") or {}
    return {k: list(v) for k, v in raw.items() if isinstance(v, list)}


def _marker_regex(markers: list[str]) -> re.Pattern | None:
    parts = sorted({m.replace("’", "'") for m in markers if m and m.strip()}, key=len, reverse=True)
    if not parts:
        return None
    alt = "|".join(re.escape(p) for p in parts)
    return re.compile(rf"(?<!\w)(?:{alt})(?!\w)", re.IGNORECASE)


def _category_regexes(markers: dict[str, list[str]]) -> dict[str, re.Pattern]:
    out = {}
    for category, words in markers.items():
        rx = _marker_regex(words)
        if rx is not None:
            out[category] = rx
    return out


def load_pipeline_metric_terms(lang: str) -> list[str]:
    """``pipeline_metric_terms`` from cue_words — metric nouns ("cooccurrence",
    "mentions communes", …) that mark a leaked internal count when a raw number
    sits next to them. Empty when the key is absent (the metric scan then finds
    nothing), matching the graceful-degradation contract of ``load_markers``."""
    raw = load_lang_config(lang).get("pipeline_metric_terms") or []
    return [t for t in raw if isinstance(t, str)]


def _pipeline_metric_regex(terms: list[str]) -> re.Pattern | None:
    """Match a raw pipeline metric leaked into prose: a number adjacent to a
    metric term, in either order ("503 mentions communes", "cooccurrence
    count: 42"). Returns ``None`` when there is no vocabulary to match."""
    parts = sorted({t.replace("’", "'") for t in terms if t and t.strip()}, key=len, reverse=True)
    if not parts:
        return None
    alt = "|".join(re.escape(p) for p in parts)
    return re.compile(
        rf"(?<!\w)(?:{_NUMBER}\s*(?:{alt})|(?:{alt})[\s:=_-]*{_NUMBER})(?!\w)",
        re.IGNORECASE,
    )


def _allowed_oou_headings(stance: EditorialStance, lang: str) -> frozenset[str]:
    """Folded headings of the sections where out-of-universe register is
    sanctioned for this stance (hybrid exceptions, or all in out_of_universe)."""
    return frozenset(
        _fold(slot_label(token, lang))
        for token in OUT_OF_UNIVERSE_SECTIONS
        if stance.allows_section(token)
    )


def _sections(content: str) -> list[tuple[str, str]]:
    """Split into ``(heading_text, region_text)`` pairs; ``""`` heading is the
    lede before the first ``##``."""
    matches = list(_HEADING_RE.finditer(content))
    if not matches:
        return [("", content)]
    regions: list[tuple[str, str]] = []
    if matches[0].start() > 0:
        regions.append(("", content[: matches[0].start()]))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        regions.append((m.group(1), content[m.end() : end]))
    return regions


def _quote(region: str, match: re.Match) -> str:
    start = max(0, match.start() - QUOTE_RADIUS)
    end = min(len(region), match.end() + QUOTE_RADIUS)
    snippet = region[start:end].replace("\n", " ").strip()
    snippet = re.sub(r"\s+", " ", snippet)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(region) else ""
    return f"{prefix}{snippet}{suffix}"


def scan_page(
    page: dict,
    stance: EditorialStance,
    lang: str,
    *,
    regexes: dict[str, re.Pattern] | None = None,
    allowed_headings: frozenset[str] | None = None,
    metric_regex: re.Pattern | None = None,
) -> list[StanceFinding]:
    content = str(page.get("content") or "")
    if not content.strip():
        return []
    if regexes is None:
        regexes = _category_regexes(load_markers(lang))
    if allowed_headings is None:
        allowed_headings = _allowed_oou_headings(stance, lang)
    if metric_regex is None:
        metric_regex = _pipeline_metric_regex(load_pipeline_metric_terms(lang))

    title = str(page.get("title") or "")
    etype = str(page.get("entity_type") or "")
    findings: list[StanceFinding] = []

    for heading, region in _sections(content):
        oou_ok = _fold(heading) in allowed_headings
        for category, rx in regexes.items():
            if category == _AUTHOR_CATEGORY:
                if not stance.forbid_author_mentions:
                    continue
            elif stance.mode == "out_of_universe" or oou_ok:
                continue
            for m in rx.finditer(region):
                findings.append(
                    StanceFinding(title, etype, heading, category, m.group(0), _quote(region, m))
                )
        # STU-579: a raw mention/cooccurrence count in reader-facing prose is a
        # leaked pipeline metric. Stance-independent — never legitimate in any
        # mode or section, so it is scanned unconditionally (unlike meta/reader,
        # which out-of-universe and exception sections sanction).
        if metric_regex is not None:
            for m in metric_regex.finditer(region):
                findings.append(
                    StanceFinding(
                        title, etype, heading, _PIPELINE_METRIC_CATEGORY,
                        m.group(0), _quote(region, m),
                    )
                )
    return findings


def scan_pages(
    pages: list[dict], stance: EditorialStance, lang: str
) -> list[StanceFinding]:
    regexes = _category_regexes(load_markers(lang))
    allowed_headings = _allowed_oou_headings(stance, lang)
    metric_regex = _pipeline_metric_regex(load_pipeline_metric_terms(lang))
    findings: list[StanceFinding] = []
    for page in pages:
        findings.extend(
            scan_page(
                page, stance, lang,
                regexes=regexes,
                allowed_headings=allowed_headings,
                metric_regex=metric_regex,
            )
        )
    return findings


_CATEGORY_LABEL = {
    "meta_narrative": "speaks of the text as a text (novel/chapter/narration)",
    "reader_address": "addresses the reader",
    "author": "names the real-world author/edition",
    "pipeline_metric": "exposes a raw pipeline metric (mention/cooccurrence count)",
}


def build_report(
    findings: list[StanceFinding], stance: EditorialStance, *, pages_scanned: int
) -> dict:
    """Serializable advisory report — the JSON artifact and the source of the
    human-readable summary. ``status`` is always advisory; drift never fails."""
    by_page: dict[str, list[StanceFinding]] = {}
    for f in findings:
        by_page.setdefault(f.page_title, []).append(f)
    return {
        "status": "non_binary_advisory",
        "declared_mode": stance.mode,
        "pages_scanned": pages_scanned,
        "pages_with_drift": len(by_page),
        "drift_count": len(findings),
        "findings": [
            {
                "page": f.page_title,
                "entity_type": f.entity_type,
                "section": f.section,
                "category": f.category,
                "marker": f.marker,
                "quote": f.quote,
            }
            for f in findings
        ],
    }


def format_summary(report: dict) -> str:
    """Human-readable rendering of ``build_report`` output: page, deviation,
    short quote — not just a score (STU-508 acceptance criterion)."""
    mode = report["declared_mode"]
    scanned = report["pages_scanned"]
    drift = report["drift_count"]
    lines = [
        f"[editorial-consolidation] declared stance: {mode} — "
        f"scanned {scanned} page(s), {drift} deviation(s) across "
        f"{report['pages_with_drift']} page(s)",
    ]
    if not drift:
        lines.append("  No editorial-stance drift detected.")
        return "\n".join(lines)

    by_page: dict[str, list[dict]] = {}
    for f in report["findings"]:
        by_page.setdefault(f["page"], []).append(f)
    for page, items in by_page.items():
        lines.append(f"  - {page}")
        for f in items:
            where = f["section"] or "(lede)"
            label = _CATEGORY_LABEL.get(f["category"], f["category"])
            lines.append(f"      [{where}] {label} — \"{f['marker']}\": {f['quote']}")
    return "\n".join(lines)
