"""Series arc projection (STU-708): the grounded view that feeds one writer-LLM
call for the series hub's overarching-arc paragraph — the slot STU-707 renders.

Deterministic, zero LLM: the call itself lives in scripts/generate_series_arc.py.
Mirrors synopsis.py (SP4/STU-482) one level up — a book synopsis projects one
tome's Event Layer, this projects the whole series.

Grounding is deliberately NOT synopsis-on-synopsis: each tome contributes its
synopsis *and* its highest-salience events, so the arc is anchored in the events
the pipeline extracted from the text rather than in a summary of a summary, where
every drift compounds tome after tome.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from wiki_creator.md2wiki import convert
from wiki_creator.page_templates import language_name
from wiki_creator.register import DEFAULT_REGISTER
from wiki_creator.synopsis import event_lines

# Identity the wiki-page-item machinery (parse_response, the stub path) binds the
# generation to. The arc is a paragraph injected into the hub, never a page of its
# own, so it reuses the generation-only SYNOPSIS pseudo-type rather than declaring
# a page type nothing exports.
ARC_TITLE = "Arc"
ARC_ENTITY_TYPE = "SYNOPSIS"
ARC_IMPORTANCE = "principal"

# The synopsis carries the plot; the events are what keeps the arc anchored in
# extracted text. A handful per tome is enough for a paragraph and keeps a
# six-tome series inside one prompt. The salience cut mirrors the EVENT-page
# threshold (generate_event_pages default).
DEFAULT_MAX_EVENTS_PER_TOME = 6
DEFAULT_MIN_SALIENCE = 0.6
DEFAULT_MAX_TOKENS = 900

CACHE_VERSION = 1
CACHE_FILENAME = "series_arc.json"


@dataclass
class TomeGrounding:
    """One tome's contribution to the arc prompt, in reading order."""

    tome_number: str
    title: str
    synopsis: str = ""
    events: list[dict] = field(default_factory=list)


def select_tome_events(
    events: list[dict],
    max_events: int = DEFAULT_MAX_EVENTS_PER_TOME,
    min_salience: float = DEFAULT_MIN_SALIENCE,
) -> list[dict]:
    """The tome's ``max_events`` most salient events above ``min_salience``,
    returned in chapter order so the block reads chronologically."""
    eligible = [
        event
        for event in events or []
        if float(event.get("salience", 0.0)) >= min_salience
    ]
    strongest = sorted(
        eligible,
        key=lambda e: (
            -float(e.get("salience", 0.0)),
            str(e.get("description", "")).casefold(),
        ),
    )
    if max_events > 0:
        strongest = strongest[:max_events]
    return sorted(
        strongest,
        key=lambda e: (int(e.get("chapter", 0)), str(e.get("description", "")).casefold()),
    )


def grounding_block(tomes: list[TomeGrounding]) -> str:
    """The tome-by-tome grounding the writer may use, reading order. A tome with
    neither synopsis nor events still appears — its title is part of the shape of
    the series, and omitting it silently would let the writer bridge a gap it
    cannot see."""
    blocks: list[str] = []
    for tome in tomes:
        lines = [f"## Book {tome.tome_number} — {tome.title}"]
        synopsis = (tome.synopsis or "").strip()
        lines.append(f"Synopsis:\n{synopsis}" if synopsis else "Synopsis: (none available)")
        events = event_lines(tome.events)
        if events:
            lines.append("Key events:\n" + "\n".join(f"  {line}" for line in events))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) if blocks else "(no tome material available)"


def build_arc_prompt(
    tomes: list[TomeGrounding],
    main_characters: list[str],
    series_title: str,
    *,
    lang: str,
    register: str = DEFAULT_REGISTER,
) -> str:
    """Anchored writer prompt for the series hub's overarching-arc paragraph.

    Same JSON output contract as the wiki-page-item pages, so the existing
    parse/validation machinery applies unchanged. Unlike a tome page there is no
    forbidden-name list: the series wiki covers every tome, so nothing later is a
    spoiler from within it.
    """
    lang_name = language_name(lang)
    characters = ", ".join(main_characters) or "(none identified)"

    return f"""This is a fictional world. The material listed below is the ONLY authoritative source of truth. Ignore any prior knowledge you have of this series, its books, or its author.

You are writing the opening paragraph of the front page of a wiki for a fictional book series called "{series_title}" — the overarching arc of the series as a whole, the answer to "what is this series about".
Output ONLY a valid JSON object. No markdown fences. No explanation. No preamble.

---

MAIN CHARACTERS OF THE SERIES: {characters}

THE SERIES, TOME BY TOME, IN READING ORDER — these are the ONLY facts you may use:

{grounding_block(tomes)}

---

WRITING RULES (follow strictly):

Tone and register:
- Write in encyclopedic {lang_name}. {register}
- Flowing prose in paragraphs — no bullet lists, no headings, no title.

Content constraints:
- Describe the arc that spans the whole series: what drives it from the first tome to the last.
- Prefer what carries across tomes over what happens inside one of them — a tome-by-tome recap is what the individual synopses already are.
- Every factual claim in your output must be directly supported by the material above. If you cannot point to a supporting synopsis or event, do not write the claim.
- Do NOT invent scenes, motives, outcomes, relationships, or characters.
- Scope is strictly this series: no other works, no real-world publication or author information.
- When referring to characters or places, use their names EXACTLY as written above — do not paraphrase, alter, or approximate names.
- Context labels like [Chapter N] are internal references — never mention chapters or chapter numbers in your output.

Structure:
- The "content" field must contain 1 to 3 paragraphs of prose, and nothing else.
- Keep infobox_fields empty: this is not a page.

---

REMINDER: Write ALL content in {lang_name}. Source material may be in another language — your output must always be in {lang_name} regardless.

Output this JSON object:
{{
  "title": "{ARC_TITLE}",
  "importance": "{ARC_IMPORTANCE}",
  "entity_type": "{ARC_ENTITY_TYPE}",
  "infobox_fields": {{}},
  "content": "<Markdown string with \\\\n for newlines>"
}}

Output ONLY the JSON. Nothing before, nothing after."""


_HEADING_RE = re.compile(r"(?m)^\s*#{1,6}.*$")


def clean_arc(content: str) -> str:
    """The arc as the hub injects it: wikitext prose, no heading. The prompt
    forbids a heading and a title, but a writer that adds one anyway would put it
    above the hub's own ``= Series =`` title."""
    text = _HEADING_RE.sub("", content or "").strip()
    return convert(text).strip()


def arc_cache_key(prompt: str, fingerprint: str) -> str:
    """The inputs that produced an arc: the rendered prompt (every tome synopsis,
    event and character it grounds on) plus the agent-prompt fingerprint. A cache
    keyed on the series alone would replay an arc written for a different set of
    tomes, or under a different prompt (STU-560)."""
    return hashlib.sha256(f"{prompt}\x00{fingerprint}".encode("utf-8")).hexdigest()


def load_cached_arc(path: Path | str, key: str) -> str | None:
    try:
        cached = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(cached, dict) or cached.get("version") != CACHE_VERSION:
        return None
    if cached.get("key") != key:
        return None
    arc = cached.get("arc")
    return arc if isinstance(arc, str) and arc else None


def save_arc_cache(path: Path | str, key: str, arc: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"version": CACHE_VERSION, "key": key, "arc": arc},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
