"""Book synopsis projection (SP4, STU-482): a view over the Event Layer
(events.json, SP0) that feeds one anchored writer-LLM prompt for a single
book-wide plot-summary page. Deterministic, zero LLM — the LLM call itself
lives in scripts/generate_book_synopsis.py. Mirrors the event_layer.py
pure-module pattern.
"""
from __future__ import annotations

SYNOPSIS_TITLE = "Synopsis"
SYNOPSIS_ENTITY_TYPE = "SYNOPSIS"
SYNOPSIS_IMPORTANCE = "principal"

# Chapters can carry many low-salience beats (corridor scenes, small talk);
# the synopsis only needs the strongest per chapter to stay within prompt
# budget while covering the whole book.
DEFAULT_MAX_EVENTS_PER_CHAPTER = 3
DEFAULT_MAX_TOKENS = 1500


def select_events(
    events: list[dict],
    max_per_chapter: int = DEFAULT_MAX_EVENTS_PER_CHAPTER,
) -> list[dict]:
    """All events ordered by chapter, capped to the ``max_per_chapter`` most
    salient beats of each chapter (``max_per_chapter <= 0`` keeps everything).
    Within a chapter the kept events stay in the Event Layer's stable order
    (description casefold) rather than salience order, so the prompt reads
    chronologically.
    """
    by_chapter: dict[int, list[dict]] = {}
    for event in events or []:
        by_chapter.setdefault(int(event.get("chapter", 0)), []).append(event)

    selected: list[dict] = []
    for chapter in sorted(by_chapter):
        chapter_events = by_chapter[chapter]
        if max_per_chapter > 0 and len(chapter_events) > max_per_chapter:
            chapter_events = sorted(
                chapter_events,
                key=lambda e: (
                    -float(e.get("salience", 0.0)),
                    str(e.get("description", "")).casefold(),
                ),
            )[:max_per_chapter]
        chapter_events = sorted(
            chapter_events, key=lambda e: str(e.get("description", "")).casefold()
        )
        selected.extend(chapter_events)
    return selected


# Salience is a continuous [0,1] score (event_layer._salience); the writer needs
# a discrete signal it can act on when deciding how much prose to spend. The 0.6
# cut mirrors the EVENT-page threshold (generate_event_pages default), 0.35 is a
# lone turning-point cue (event_layer._CUE_WEIGHT).
def salience_label(value: float) -> str:
    if value >= 0.6:
        return "high"
    if value >= 0.35:
        return "medium"
    return "low"


def event_lines(events: list[dict], include_salience: bool = False) -> list[str]:
    """One grounding line per event: ``[Chapter N] description (participants:
    … — places: …)``. The ``outcome`` is only appended when it adds information
    beyond the description. With ``include_salience``, each line also carries a
    salience tier (``importance: high|medium|low``) so the writer can weight
    prose proportionally. These are prompt-grounding labels only (never rendered
    output), so they stay in English regardless of the wiki's output language.
    """
    lines: list[str] = []
    for event in events or []:
        description = str(event.get("description", "")).strip()
        if not description:
            continue
        line = f"[Chapter {event.get('chapter', '?')}] {description}"
        details: list[str] = []
        participants = [str(p) for p in event.get("participants") or [] if p]
        if participants:
            details.append("participants: " + ", ".join(participants))
        places = [str(p) for p in event.get("places") or [] if p]
        if places:
            details.append("places: " + ", ".join(places))
        outcome = str(event.get("outcome") or "").strip()
        if outcome and outcome != description:
            details.append("outcome: " + outcome)
        if include_salience:
            details.append(
                "importance: " + salience_label(float(event.get("salience", 0.0)))
            )
        if details:
            line += " (" + " — ".join(details) + ")"
        lines.append(line)
    return lines


def build_synopsis_prompt(
    events: list[dict],
    book_title: str,
    forbidden_names: list[str] | None = None,
) -> str:
    """Anchored writer prompt for the book synopsis page.

    Same JSON output contract as the wiki-page-item pages so the existing
    parse/validation machinery (parse_response, wiki-page-validator) applies
    unchanged. The listed events are the ONLY authorized source of truth —
    spoiler safety is inherited from the Event Layer, which is bounded to the
    current book.
    """
    lines = event_lines(events)
    events_block = "\n".join(f"  {line}" for line in lines) if lines else "  (no events available)"

    forbidden_names_rule = ""
    if forbidden_names:
        names_list = "\n".join(f"- {n}" for n in forbidden_names)
        forbidden_names_rule = (
            f"\n\nFORBIDDEN NAMES (spoilers from later books — NEVER use these):\n"
            f"{names_list}\n"
            f"Any output containing a forbidden name will be rejected."
        )

    return f"""This is a fictional world. The events listed below are the ONLY authoritative source of truth. Ignore any prior knowledge you have of this book, series, or author.

You are writing the plot synopsis page of a wiki for a fictional novel called "{book_title}" — a single page summarizing the whole plot, separate from the entity pages.
Output ONLY a valid JSON object. No markdown fences. No explanation. No preamble.

---

EVENTS OF THE BOOK, IN NARRATIVE ORDER — these are the ONLY facts you may use:
{events_block}

---

WRITING RULES (follow strictly):

Tone and register:
- Write in encyclopedic French. Neutral, precise, factual.
- Flowing prose in paragraphs — no bullet lists, no headings other than the single "## Synopsis" heading.
- Use specific, concrete language anchored in the listed events.

Content constraints:
- Retrace the plot from beginning to end, following the order of the events above.
- Every factual claim in your output must be directly supported by one of the EVENTS listed above. If you cannot point to a supporting event, do not write the claim.
- Do NOT invent scenes, motives, outcomes, relationships, or characters that are not in the events.
- Scope is strictly this book: no sequels, no series-level information, no real-world publication or author information.
- When referring to characters or places, use their names EXACTLY as written in the events — do not paraphrase, alter, or approximate names.
- Context labels like [Chapitre N] are internal references — never mention chapters or chapter numbers in your output.
- Do NOT include a ## Références section — it is added automatically.

Structure:
- The "content" field must contain a single "## Synopsis" heading followed by 4 to 8 paragraphs.
- Keep infobox_fields empty: this page has no infobox.{forbidden_names_rule}

---

REMINDER: Write ALL content in French. Source events may be in English — your output must always be in French regardless.

Output this JSON object:
{{
  "title": "{SYNOPSIS_TITLE}",
  "importance": "{SYNOPSIS_IMPORTANCE}",
  "entity_type": "{SYNOPSIS_ENTITY_TYPE}",
  "infobox_fields": {{}},
  "content": "<Markdown string with \\\\n for newlines>"
}}

Output ONLY the JSON. Nothing before, nothing after."""
