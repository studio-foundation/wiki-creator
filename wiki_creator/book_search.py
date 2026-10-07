"""Full-text search over a book's parsed chapters (STU-753), and the
deterministic evidence picker the entity trio's single-shot verdicts read
(`select_passages`, STU-2018).

The retrieval primitive an agentic point-query verdict searches with, instead
of receiving a pre-selected snippet pack. ``chapters.json`` (written by
``entity_extraction.save_chapters_json``) maps chapter id -> full chapter text;
this is the same artifact `relationship_extraction.py` already reads for
co-occurrence, so no new artifact is introduced.

A query is a literal, case-insensitive phrase — never a regex. The caller is
an LLM tool call: a regex engine let loose on model-shaped input is a
catastrophic-backtracking surface a substring search never opens.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from wiki_creator.chapters import chapter_number
from wiki_creator.roster import fold_typography

MAX_RESULTS = 8
CONTEXT_CHARS = 300

# The smallest window any configured provider runs with: the athena-* Ollama
# variants pin num_ctx 32768, and Studio cannot report a provider's window. A
# quarter of it leaves the system prompt, the reply and the chars/4 estimate's
# error (a non-English text tokenizes denser) well inside the window.
CONTEXT_WINDOW_TOKENS = 32768
PASSAGE_TOKEN_BUDGET = CONTEXT_WINDOW_TOKENS // 4
MAX_PASSAGE_CHARS = 800
# A resolved paragraph whose words are mostly an original mention paragraph's
# is that paragraph with its pronouns rewritten, not new evidence.
_DUPLICATE_OVERLAP = 0.5

_PARAGRAPH_RE = re.compile(r"\n\s*\n")
_WORD_RE = re.compile(r"\w+")


def load_chapters(processing_dir: Path | str) -> dict[str, str]:
    """This book's chapters as ``{chapter_id: text}``, or ``{}``.

    Prefers ``chapters_resolved.json`` (STU-763: coref-resolved text, pronouns
    replaced by canonical names) when present — a fact stated only through a
    pronoun then search-hits under the entity's own name. Falls back to
    ``chapters.json`` for a book that never ran coref.
    """
    for filename in ("chapters_resolved.json", "chapters.json"):
        chapters = _read_chapters(Path(processing_dir) / filename)
        if chapters is not None:
            return chapters
    return {}


def chapter_variants(processing_dir: Path | str) -> tuple[dict[str, str], dict[str, str]]:
    """The original chapters and the coref-resolved ones (``{}`` when absent)."""
    root = Path(processing_dir)
    return (
        _read_chapters(root / "chapters.json") or {},
        _read_chapters(root / "chapters_resolved.json") or {},
    )


def quote_surface(processing_dir: Path | str) -> str:
    """The text a verdict's quote may be verbatim in: the original chapters and
    the coref-resolved ones (STU-2008). Search runs on the resolved text, but a
    model quoting the book's real sentence must not fail the gate because coref
    rewrote its pronouns."""
    return "\n".join(
        full_text(_read_chapters(Path(processing_dir) / filename) or {})
        for filename in ("chapters.json", "chapters_resolved.json")
    )


def _read_chapters(path: Path) -> dict[str, str] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    chapters = data.get("chapters") if isinstance(data, dict) else None
    return chapters if isinstance(chapters, dict) else None


def full_text(chapters: dict[str, str]) -> str:
    """Every chapter's text joined — the grounding surface a free-search verdict's
    quote must appear in (there is no pre-selected snippet pack to check against)."""
    return "\n".join(str(t) for t in (chapters or {}).values())


def search_chapters(
    chapters: dict[str, str],
    query: str,
    *,
    max_results: int = MAX_RESULTS,
    context_chars: int = CONTEXT_CHARS,
) -> list[dict]:
    """Up to ``max_results`` passages containing ``query``, latest chapter first.

    One match per chapter — the first occurrence. A name mentioned 40 times in
    one chapter is one passage to read, not 40; a character's fate is decided
    from where it is stated, and the agent can search again, narrower, if the
    first passage does not settle it. Latest-first mirrors `roster.latest_first`:
    for the temporal questions (status, affiliation) the passage that matters is
    the one nearest the end of the book.
    """
    needle = fold_typography(query).strip()
    if not needle:
        return []
    hits = []
    for chapter_id, text in (chapters or {}).items():
        text = str(text or "")
        pos = fold_typography(text).find(needle)
        if pos == -1:
            continue
        start = max(0, pos - context_chars // 2)
        end = min(len(text), pos + len(needle) + context_chars // 2)
        hits.append({"chapter_id": chapter_id, "text": text[start:end].strip()})
    hits.sort(key=lambda h: chapter_number(h["chapter_id"]) or 0, reverse=True)
    return hits[:max_results]


def estimate_tokens(text: str) -> int:
    return -(-len(text) // 4)


def _surface_pattern(surfaces: list[str]) -> re.Pattern | None:
    parts = sorted(
        {r"\s+".join(map(re.escape, fold_typography(s).split())) for s in surfaces if str(s or "").strip()},
        key=len,
        reverse=True,
    )
    return re.compile(r"\b(?:" + "|".join(parts) + r")\b") if parts else None


def _passage(paragraph: str, pos: int) -> str:
    """The paragraph, or a ``MAX_PASSAGE_CHARS`` window centred on the mention."""
    if len(paragraph) <= MAX_PASSAGE_CHARS:
        return paragraph
    start = max(0, min(pos - MAX_PASSAGE_CHARS // 2, len(paragraph) - MAX_PASSAGE_CHARS))
    return paragraph[start:start + MAX_PASSAGE_CHARS].strip()


def _mentions(text: str, pattern: re.Pattern) -> list[tuple[int, str]]:
    found = []
    for index, paragraph in enumerate(p.strip() for p in _PARAGRAPH_RE.split(str(text or ""))):
        match = pattern.search(fold_typography(paragraph))
        if match:
            found.append((index, _passage(paragraph, match.start())))
    return found


def _words(text: str) -> set[str]:
    return set(_WORD_RE.findall(fold_typography(text)))


def select_passages(
    original: dict[str, str],
    resolved: dict[str, str],
    name: str,
    aliases: list[str],
    keywords: list[str],
    *,
    budget_tokens: int = PASSAGE_TOKEN_BUDGET,
) -> list[dict]:
    """The passages one verdict call reads about one character (STU-2018).

    Every paragraph naming ``name`` or an alias in the original chapters, plus
    each coref-resolved paragraph that names them where the original only had a
    pronoun (STU-763). Picked in rounds across chapters, latest chapter first in
    each round, paragraphs holding a slot ``keyword`` before the rest, until the
    next one would pass ``budget_tokens``. Returned in book order. Deterministic:
    the engine's per-item resume keys on this list.
    """
    pattern = _surface_pattern([name, *aliases])
    if pattern is None:
        return []
    keyword_re = _surface_pattern(keywords)

    candidates = []
    for order, chapter_id in enumerate(dict.fromkeys([*original, *resolved])):
        found = _mentions(original.get(chapter_id, ""), pattern)
        seen = [_words(text) for _, text in found]
        for index, text in _mentions(resolved.get(chapter_id, ""), pattern):
            words = _words(text)
            if not any(len(words & other) >= _DUPLICATE_OVERLAP * len(words) for other in seen):
                found.append((index, text))
        found.sort(key=lambda hit: hit[0])
        for tier in (True, False):
            tiered = [
                hit for hit in found
                if bool(keyword_re and keyword_re.search(fold_typography(hit[1]))) is tier
            ]
            for rank, (index, text) in enumerate(tiered):
                candidates.append(((not tier, rank, -order), (order, index), chapter_id, text))

    picked, used = [], 0
    for _, position, chapter_id, text in sorted(candidates):
        cost = estimate_tokens(text)
        if used + cost > budget_tokens:
            continue
        used += cost
        picked.append((position, chapter_id, text))
    return [{"chapter": chapter_id, "text": text} for _, chapter_id, text in sorted(picked)]


def with_passages(rows: list[dict], processing_dir: Path | str, keywords: list[str]) -> list[dict]:
    """Each fan-out row with the passages its single verdict call reads."""
    original, resolved = chapter_variants(processing_dir)
    return [
        {**row, "passages": select_passages(original, resolved, row["name"], row["aliases"], keywords)}
        for row in rows
    ]
