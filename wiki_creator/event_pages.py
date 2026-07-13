"""Event pages projection (SP3, STU-481): a view over the Event Layer
(events.json, SP0) that turns each high-salience event into one dedicated
"Event" wiki page — anchored prose + a deterministic infobox
{participants, lieu, chapitre, issue}. Deterministic, zero LLM — the writer
LLM call itself lives in scripts/generate_event_pages.py. Mirrors the
synopsis.py pure-module pattern.
"""
from __future__ import annotations

EVENT_ENTITY_TYPE = "EVENT"
EVENT_IMPORTANCE = "principal"

# An event of salience >= this threshold earns its own page. Tuned on TOG
# book 1 (~9 pages at 0.6); overridable via book YAML generation.event_pages.
DEFAULT_SALIENCE_THRESHOLD = 0.6
# Hard cap on the number of event pages, applied after threshold+participant
# filtering, keeping the most salient. 0 or negative disables the cap.
DEFAULT_MAX_PAGES = 20
DEFAULT_MAX_TOKENS = 900


def select_events(
    events: list[dict],
    threshold: float = DEFAULT_SALIENCE_THRESHOLD,
    max_pages: int = DEFAULT_MAX_PAGES,
    require_participants: bool = True,
) -> list[dict]:
    """Events that earn a dedicated page: salience >= ``threshold`` and (when
    ``require_participants``) at least one participant — a standalone event
    page needs actors. Ordered by salience (desc) then chapter, capped to the
    ``max_pages`` most salient (``max_pages <= 0`` keeps all).
    """
    selected = [
        e
        for e in events or []
        if float(e.get("salience", 0.0)) >= threshold
        and (not require_participants or e.get("participants"))
    ]
    selected.sort(
        key=lambda e: (
            -float(e.get("salience", 0.0)),
            int(e.get("chapter", 0)),
            str(e.get("description", "")).casefold(),
        )
    )
    if max_pages > 0:
        selected = selected[:max_pages]
    return selected


def event_title(event: dict) -> str:
    """Deterministic page title for an event: its description, stripped of
    trailing punctuation. Grounded, so no LLM naming hallucination."""
    return str(event.get("description", "")).strip().rstrip(".!—- ").strip()


def event_infobox_fields(event: dict) -> dict:
    """Deterministic infobox {participants, lieu, chapitre, issue} built from
    the event itself. Empty fields are omitted (page-infobox convention)."""
    fields: dict[str, str] = {}
    participants = [str(p) for p in event.get("participants") or [] if p]
    if participants:
        fields["participants"] = ", ".join(participants)
    places = [str(p) for p in event.get("places") or [] if p]
    if places:
        fields["lieu"] = ", ".join(places)
    chapter = event.get("chapter")
    if chapter:
        fields["chapitre"] = str(chapter)
    outcome = str(event.get("outcome") or "").strip()
    description = str(event.get("description", "")).strip()
    if outcome and outcome != description:
        fields["issue"] = outcome
    return fields


def _facts_block(event: dict) -> str:
    """Grounding lines for one event — the ONLY facts the writer may use."""
    lines: list[str] = []
    description = str(event.get("description", "")).strip()
    if description:
        lines.append(f"Événement : {description}")
    participants = [str(p) for p in event.get("participants") or [] if p]
    if participants:
        lines.append("Personnages : " + ", ".join(participants))
    places = [str(p) for p in event.get("places") or [] if p]
    if places:
        lines.append("Lieux : " + ", ".join(places))
    outcome = str(event.get("outcome") or "").strip()
    if outcome and outcome != description:
        lines.append("Issue : " + outcome)
    for bullet in event.get("source_bullets") or []:
        text = str(bullet).strip()
        if text and text != description:
            lines.append(f"Source : {text}")
    return "\n".join(f"  {line}" for line in lines) if lines else "  (no facts available)"


def build_event_prompt(
    event: dict,
    title: str,
    book_title: str,
    forbidden_names: list[str] | None = None,
) -> str:
    """Anchored writer prompt for one event page.

    Same JSON output contract as the wiki-page-item pages, so the existing
    parse/validation machinery applies unchanged. The listed facts are the
    ONLY authorized source of truth — spoiler safety is inherited from the
    Event Layer, which is bounded to the current book. Title and infobox are
    built deterministically by the caller; the writer only authors prose.
    """
    facts_block = _facts_block(event)

    forbidden_names_rule = ""
    if forbidden_names:
        names_list = "\n".join(f"- {n}" for n in forbidden_names)
        forbidden_names_rule = (
            f"\n\nFORBIDDEN NAMES (spoilers from later books — NEVER use these):\n"
            f"{names_list}\n"
            f"Any output containing a forbidden name will be rejected."
        )

    return f"""This is a fictional world. The facts listed below are the ONLY authoritative source of truth. Ignore any prior knowledge you have of this book, series, or author.

You are writing a single "Event" page of a wiki for a fictional novel called "{book_title}" — a page dedicated to one narrative event, "{title}", in the style of a Fandom event page.
Output ONLY a valid JSON object. No markdown fences. No explanation. No preamble.

---

FACTS ABOUT THIS EVENT — these are the ONLY facts you may use:
{facts_block}

---

WRITING RULES (follow strictly):

Tone and register:
- Write in encyclopedic French. Neutral, precise, factual.
- Flowing prose in paragraphs — no bullet lists, no headings other than the single "## Déroulement" heading.
- Use specific, concrete language anchored in the listed facts.

Content constraints:
- Recount only this event: what happens, who is involved, where, and how it resolves.
- Every factual claim in your output must be directly supported by one of the FACTS listed above. If you cannot point to a supporting fact, do not write the claim.
- Do NOT invent scenes, motives, outcomes, relationships, or characters that are not in the facts.
- Scope is strictly this book: no sequels, no series-level information, no real-world publication or author information.
- When referring to characters or places, use their names EXACTLY as written in the facts — do not paraphrase, alter, or approximate names.
- Never mention chapters or chapter numbers in your output.
- Do NOT include a ## Références section — it is added automatically.

Structure:
- The "content" field must contain a single "## Déroulement" heading followed by 1 to 3 paragraphs.
- Keep infobox_fields empty: the infobox is added automatically.{forbidden_names_rule}

---

REMINDER: Write ALL content in French. Source facts may be in English — your output must always be in French regardless.

Output this JSON object:
{{
  "title": "{title}",
  "importance": "{EVENT_IMPORTANCE}",
  "entity_type": "{EVENT_ENTITY_TYPE}",
  "infobox_fields": {{}},
  "content": "<Markdown string with \\\\n for newlines>"
}}

Output ONLY the JSON. Nothing before, nothing after."""
