#!/usr/bin/env python3
"""
Standalone pre-processing script: generate wiki pages via Ollama.

Run this BEFORE the wiki-generation Studio pipeline.
Results are saved to <book processing dir>/wiki_pages.json and loaded
by assemble_wiki_pages.py inside the pipeline.

Usage:
    python scripts/generate_wiki_pages.py --book library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml
    python scripts/generate_wiki_pages.py --book library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml --model llama3:8b
    python scripts/generate_wiki_pages.py --book library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml --importance principal secondary
    python scripts/generate_wiki_pages.py --book library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml --dry-run

Subset re-run (regenerate a few pages without touching the rest):
    python scripts/generate_wiki_pages.py --book <book.yaml> --entities "Celaena Sardothien" --force
    python scripts/generate_wiki_pages.py --book <book.yaml> --importance principal --force
Existing pages for entities outside the filter are preserved verbatim. --force
regenerates the targeted entities even if already done; without it, already-done
pages are skipped. A filter that matches nothing exits without writing.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import shutil
import dataclasses
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
from wiki_creator.chapters import resolve_chapter_number
from wiki_creator.lang import load_lang_config
from wiki_creator.editorial_stance import GROUNDING_BLOCK, EditorialStance, editorial_stance
from wiki_creator.page_templates import (
    few_shot_example,
    language_name,
    length_guide,
    output_language,
    resolve_template,
    section_brief,
    slot_label,
    stub_content,
)
from wiki_creator.paths import book_paths_from_yaml
from wiki_creator.provenance import content_units, relation_units
from wiki_creator import studio_io
from wiki_creator.entity_links import link_first_mentions
from wiki_creator.entity_status import death_label, status_label
from wiki_creator.registry import Registry, normalize_name
from wiki_creator.spoiler_blocks import relationship_index_lines, per_relation_prose_enabled
from wiki_creator.relationship_types import usable_relationship_type
from wiki_creator.synopsis import event_lines
from wiki_creator.tome_labels import appearance_label
from wiki_creator.types import WikiPage

# STU-447: pages are persisted via WikiPage(**page); a stray top-level key from
# the LLM would make that raise TypeError and brick the run (the poisoned dict is
# reloaded unvalidated on rerun). parse_response drops unknown keys against this
# set so only WikiPage-shaped dicts ever reach _save.
_KNOWN_PAGE_KEYS = {f.name for f in dataclasses.fields(WikiPage)}

DEFAULT_NUM_PREDICT = 1024

_DEFAULT_SECTIONS_BY_IMPORTANCE = {
    "principal": ["infobox", "biography", "personality", "physical", "powers", "relationships", "trivia", "references"],
    "secondary": ["infobox", "biography", "relationships", "references"],
    "figurant": ["infobox", "biography"],
}
_INTERNAL_INFOBOX_KEYS = frozenset({
    "cooccurrence_count",
    "entity_type",
    "importance",
    "file_path",
    "type",
    "id",
    "canonical_name",
})

_MIN_CONTENT_CHARS_WARNING = 80  # warn when LLM output is suspiciously short but not empty

# Language-neutral: an angle-bracket token leaked from the prompt (`<if known>`).
_ANGLE_PLACEHOLDER = re.compile(r"<[^>\n]{1,80}>")


def _placeholder_patterns(lang: str) -> tuple[re.Pattern, ...]:
    """Prompt-placeholder detectors for a page in ``lang``: the neutral
    angle-bracket token plus the localized placeholder phrases from
    cue_words (`placeholder_markers`) — de-Frenchified in STU-517."""
    markers = load_lang_config(lang, allow_en_fallback=True).get("placeholder_markers", [])
    return (_ANGLE_PLACEHOLDER, *(
        re.compile(r"\b" + re.escape(m) + r"\b", re.IGNORECASE) for m in markers
    ))


def _assemble_section_blocks(blocks: list[str]) -> str:
    """Join non-empty section markdown blocks with a blank line."""
    return "\n\n".join(b.strip() for b in blocks if b and b.strip())


def _references_block(book_title: str, lang: str = "fr") -> str:
    """Deterministic References section — lists only the book title (no LLM)."""
    return f"## {slot_label('references', lang)}\n\n- {book_title}"


def _isolate_section(content: str, section: str, lang: str = "fr") -> str | None:
    """Return only the requested section's markdown block from a single-section
    generation, dropping any leaked foreign blocks (e.g. a ## Infobox echoed from
    the few-shot). If the model returned just the body with no heading, wrap it
    under the section's title. Returns None if nothing usable remains."""
    title = slot_label(section, lang)
    text = (content or "").strip()
    if not text:
        return None
    # Split into level-2 heading blocks: [pre, "## H1", body1, "## H2", body2, ...]
    parts = re.split(r"(?m)^(##\s+.+?)\s*$", text)
    headings = parts[1::2]
    bodies = parts[2::2]
    if not headings:
        # No headings at all → the model returned just the section body.
        return f"## {title}\n\n{text}"

    def _norm(s: str) -> str:
        return s.strip().lstrip("#").strip().lower()

    blocks = []
    for h, b in zip(headings, bodies):
        blocks.append((_norm(h), f"{h.strip()}\n\n{b.strip()}".strip()))
    # Prefer an exact title match; else, if exactly one non-infobox block, take it.
    for norm, block in blocks:
        if norm == title.lower():
            return block
    non_infobox = [blk for norm, blk in blocks if norm != slot_label("infobox", lang).lower()]
    if len(non_infobox) == 1:
        return non_infobox[0]
    return None


def _label_chapter_key(key: str, chapter_numbers: dict[str, int] | None = None) -> str:
    """Readable "Chapter N" label for a context section id, numbered by the
    chapter's *position* in the book — never by digits read out of the id
    itself (STU-580, same defect class as STU-550: `C25.xhtml` on a book with
    front matter before it, or `bookcontent2_0`, is not chapter 25/2).

    `chapter_numbers` is the bundle's `context_chapter_numbers` map (section id
    → position), produced by wiki_preparation. A key it doesn't cover — or an
    absent map, e.g. a pre-STU-580 batch — keeps its raw id rather than a label
    invented from its digits."""
    if not chapter_numbers:
        return key
    number = resolve_chapter_number(key, chapter_numbers)
    return f"Chapter {number}" if number is not None else key


# STU-438: how many top relations (already sorted by cooccurrence desc) get
# evidence/key_moments/context sub-lines in the prompt, per page importance.
_RELATIONSHIP_ENRICHMENT_BUDGET = {"principal": 5, "secondary": 3, "figurant": 0}
_MAX_KEY_MOMENTS_PER_RELATION = 2
_SAMPLE_CONTEXT_MAX_CHARS = 200
# Kept in sync with .studio/agents/relationship-classifier.agent.yaml: the
# classifier returns this exact string when no key moment could be identified.
_KEY_MOMENT_SENTINEL = "no specific moment identifiable in provided excerpts"

# SP2 (STU-480): "Lieu narratif" projection over the Event Layer (events.json,
# SP0) — events_for_entity() in wiki_preparation.py already filters events
# where the PLACE is in `places` into entity["entity_events"]; this just caps
# how many feed the prompt to bound its size.
_MAX_PLACE_EVENTS = 10


def _place_events_block(entity: dict) -> str:
    """Grounding block of events that occur at this PLACE, or "" when the
    entity isn't a PLACE or has no associated events (SP0 not run, or the
    place is purely descriptive)."""
    if entity.get("type") != "PLACE":
        return ""
    lines = event_lines((entity.get("entity_events") or [])[:_MAX_PLACE_EVENTS])
    if not lines:
        return ""
    return "## Events at this place\n" + "\n".join(f"  {line}" for line in lines)


# SP1 (STU-479): "Arc perso" projection over the Event Layer (events.json, SP0)
# — events_for_entity() in wiki_preparation.py filters events where the PERSON
# participates into entity["entity_events"]. The arc's climax beats (couronnement,
# duel) sit late in the book, so cap by salience (not chapter order, which would
# drop the ending) then re-sort chronologically for the prompt.
_MAX_PERSON_EVENTS = 18


def _narrative_events(entity: dict) -> list[dict]:
    """The character's most salient participant events, in chronological order.
    Empty for non-PERSON entities or when SP0 produced no events for them."""
    if entity.get("type") != "PERSON":
        return []
    events = entity.get("entity_events") or []
    top = sorted(
        events,
        key=lambda e: (-float(e.get("salience", 0.0)), int(e.get("chapter", 0))),
    )[:_MAX_PERSON_EVENTS]
    return sorted(top, key=lambda e: int(e.get("chapter", 0)))


def _has_backstory(entity: dict) -> bool:
    """True when the entity has any flashback-tagged chapter summary (STU-271),
    i.e. backstory content to surface under its own section (STU-493)."""
    return any(
        s.get("temporal_context") == "flashback"
        for s in entity.get("chapter_summary_context") or []
    )


def _narrative_role_block(entity: dict) -> str:
    """Grounding block of the character's arc through the plot, or "" when the
    entity isn't a PERSON or has no participant events. Prompt-grounding only
    (never rendered), so the header stays English like the other grounding
    labels, regardless of the wiki's output language."""
    lines = event_lines(_narrative_events(entity), include_salience=True)
    if not lines:
        return ""
    name = entity.get("canonical_name", "")
    header = f"## Events in which {name} participates (chronological order)"
    return header + "\n" + "\n".join(f"  {line}" for line in lines)


def _relationship_evidence_lines(rel: dict) -> list[str]:
    """Grounding sub-lines for one relation: verbatim evidence, key moments,
    and — only when evidence is absent — a truncated sample context fallback."""
    lines = []
    evidence = str(rel.get("evidence") or "").strip()
    if evidence:
        lines.append(f'    evidence: "{evidence}"')
    moments = [
        m for m in (str(m or "").strip() for m in rel.get("key_moments") or [])
        if m and m != _KEY_MOMENT_SENTINEL
    ]
    for moment in moments[:_MAX_KEY_MOMENTS_PER_RELATION]:
        lines.append(f"    key_moment: {moment}")
    if not evidence:
        contexts = [c for c in (str(c or "").strip() for c in rel.get("sample_contexts") or []) if c]
        if contexts:
            snippet = contexts[0]
            if len(snippet) > _SAMPLE_CONTEXT_MAX_CHARS:
                snippet = snippet[:_SAMPLE_CONTEXT_MAX_CHARS].rstrip() + "…"
            lines.append(f'    context: "{snippet}"')
    return lines


def build_relation_prompt(
    entity: dict,
    other: str,
    rel: dict,
    book_title: str,
    forbidden_names: list[str] | None = None,
    lang: str = "fr",
) -> str:
    """Prompt for a single ``### [[other]]`` progression subsection, in the wiki's
    output language.

    Grounds on this one relation's type / evolution / key_moments / evidence. The
    grounding fields are English and must be reformulated, never copied verbatim.
    """
    name = entity["canonical_name"]
    rtype = usable_relationship_type(rel.get("relationship_type")) or "relation"
    lang_name = language_name(lang)
    grounding_lines = []
    evolution = str(rel.get("evolution") or "").strip()
    if evolution:
        grounding_lines.append(f"    evolution: {evolution}")
    grounding_lines.extend(_relationship_evidence_lines(rel))
    grounding = "\n".join(grounding_lines) or "    (no extra grounding)"
    forbidden_rule = ""
    if forbidden_names:
        names_list = "\n".join(f"- {n}" for n in forbidden_names)
        forbidden_rule = (
            f"\n\nNEVER mention these characters (spoilers from other books):\n"
            f"{names_list}"
        )
    return f"""Write ONE wiki subsection in {lang_name} describing the progression of the relationship between {name} and {other} in "{book_title}".

Relationship type: {rtype}
Grounding elements (in English — REFORMULATE in {lang_name}, never copy verbatim):
{grounding}

Constraints:
- Write in {lang_name} only. The grounding elements are in English: translate and reformulate, do not copy any English phrase.
- A single short paragraph, grounded only in the elements above. Invent nothing.
- Start EXACTLY with the title: ### [[{other}]]
- Do not mention any character other than {name} and {other}.{forbidden_rule}"""


def build_prompt(
    entity: dict,
    book_title: str,
    sections: list[str],
    forbidden_names: list[str] | None = None,
    stance: EditorialStance | None = None,
    lang: str = "fr",
) -> str:
    stance = stance or EditorialStance()
    lang_name = language_name(lang)
    name = entity["canonical_name"]
    etype = entity["type"]
    importance = entity["importance"]
    aliases = entity.get("aliases", [])
    context = entity.get("context_by_chapter", {})
    context_chapter_numbers = entity.get("context_chapter_numbers", {})
    related_context = entity.get("related_context", [])
    chapter_summary_context = entity.get("chapter_summary_context", [])

    # --- Blocs de contexte ---
    context_lines = []
    for chapter, mentions in list(context.items())[:15]:
        label = _label_chapter_key(chapter, context_chapter_numbers)
        for mention in mentions[:3]:
            context_lines.append(f"  [{label}] {mention}")
    context_block = "\n".join(context_lines) if context_lines else "  (no excerpts available)"

    related_lines = []
    # STU-579: never inject the raw cooccurrence_count here. This block is
    # disambiguation-only, and a pipeline metric placed in front of the writer
    # ends up echoed verbatim in prose (STU-475's "503 mentions communes",
    # STU-501/528). The rows already arrive pre-sorted by cooccurrence
    # descending (wiki_preparation.build_related_context), so their ORDER
    # carries the prominence signal — the raw number was redundant as well as
    # leak-prone.
    for rel in related_context[:5]:
        related_name = rel.get("related_name", "").strip()
        if not related_name:
            continue
        related_type = rel.get("related_type") or "unknown"
        related_importance = rel.get("related_importance") or "unknown"
        related_lines.append(
            f"  - Name: {related_name} | Type: {related_type} | Importance: {related_importance}"
        )
        for snippet in rel.get("support_snippets", [])[:2]:
            related_lines.append(f"    - Snippet: {snippet}")
    related_block = "\n".join(related_lines) if related_lines else "  (no related entities available)"

    relationships = sorted(
        entity.get("relationships", []),
        key=lambda r: int(r.get("cooccurrence_count", 0) or 0),
        reverse=True,
    )
    enrichment_budget = _RELATIONSHIP_ENRICHMENT_BUDGET.get(importance, 0)
    rels_enriched = False
    rel_lines = []
    for r in relationships[:10]:
        a = (r.get("entity_a") or "").strip()
        b = (r.get("entity_b") or "").strip()
        other = b if a == name else a
        if not other:
            continue
        rtype = usable_relationship_type(r.get("relationship_type"))
        if not rtype:
            continue
        direction = r.get("direction") or ""
        evolution = r.get("evolution") or ""
        count = r.get("cooccurrence_count", 0)
        confidence = r.get("confidence") or "inferred"
        line = f"  - related_entity: {other} | relationship_type: {rtype} | confidence: {confidence} | cooccurrence_count: {count}"
        if direction:
            line += f" | direction: {direction}"
        if evolution:
            line += f"\n    evolution: {evolution}"
        if len(rel_lines) < enrichment_budget:
            evidence_lines = _relationship_evidence_lines(r)
            if evidence_lines:
                line += "\n" + "\n".join(evidence_lines)
                rels_enriched = True
        rel_lines.append(line)
    relationships_block = "\n".join(rel_lines) if rel_lines else ""

    # Indirect (inferred) relationships
    indirect_rels = entity.get("indirect_relationships", [])
    indirect_lines = []
    for r in indirect_rels[:5]:  # cap at 5 to avoid prompt bloat
        other = r.get("entity_b", "")
        via = " → ".join(r.get("via", []))
        path = " → ".join(r.get("path_edge_types", []))
        strength = r.get("strength", 0)
        if other and strength >= 0.1:
            indirect_lines.append(
                f"  - related_entity: {other} | via: {via} | path: {path} | inferred: true"
            )
    indirect_block = "\n".join(indirect_lines) if indirect_lines else ""

    present_lines = []
    backstory_lines = []
    for chapter in chapter_summary_context[:8]:
        chapter_key = chapter.get("chapter_key", "").strip()
        if not chapter_key:
            continue
        temporal = chapter.get("temporal_context", "unknown")
        entry_lines = [f"  - Chapter: {chapter_key}"]
        for bullet in chapter.get("summary_bullets", [])[:3]:
            entry_lines.append(f"    - {bullet}")
        pov = chapter.get("pov", "unknown")
        pov_char = chapter.get("pov_character")
        if pov_char:
            entry_lines.append(
                f"    - POV: narrated from {pov_char}'s perspective — statements about other "
                f"characters may reflect a subjective view, not objective fact."
            )
        elif pov in ("first_person", "third_limited"):
            entry_lines.append(
                "    - POV: subjective narration — some statements may reflect a character's "
                "perception rather than objective fact."
            )
        if temporal == "flashback":
            backstory_lines.extend(entry_lines)
        else:
            present_lines.extend(entry_lines)

    present_block = (
        "## Chapter summary context\n" + "\n".join(present_lines)
        if present_lines
        else "## Chapter summary context\n  (no chapter summaries available)"
    )
    backstory_block = (
        "## Backstory context (flashback chapters — events before the main narrative)\n"
        + "\n".join(backstory_lines)
        if backstory_lines
        else ""
    )
    # STU-493: flashback backstory is its own section — surface it (and only it)
    # when the backstory section is being generated, never mixed into biography.
    chapter_summary_block = present_block
    backstory_section = (
        f"\n\n{backstory_block}" if backstory_block and "backstory" in sections else ""
    )

    place_events_block = _place_events_block(entity)
    place_events_section = f"\n\n{place_events_block}" if place_events_block else ""

    # SP1: only surface the arc block when the narrative_role section is the one
    # being generated (PERSON is section-scoped — one section per prompt), so it
    # never leaks into the biography/personality prompts.
    narrative_role_block = (
        _narrative_role_block(entity) if "narrative_role" in sections else ""
    )
    narrative_role_section = f"\n\n{narrative_role_block}" if narrative_role_block else ""

    # --- Generation parameters ---
    alias_str = ", ".join(a for a in aliases if a != name) or "none"

    length_hint = length_guide(importance)

    sections_str = ", ".join(sections)

    # Section writing briefs, localized (base.yaml `briefs`), keyed by token.
    section_def_lines = "\n".join(
        f"  - {slot_label(token, lang)}: {brief}"
        for token in sections
        for brief in [section_brief(etype, token, lang)]
        if brief
    )

    # Few-shot example serialised, in the output language.
    few_shot_json = json.dumps(few_shot_example(lang), ensure_ascii=False, indent=2)

    indirect_section = ""
    if entity.get("importance") == "major" and len(indirect_rels) >= 2 and indirect_block:
        indirect_section = f"\nIndirect relationships (inferred — do NOT treat as confirmed direct interactions):\n{indirect_block}"

    forbidden_names_rule = ""
    if forbidden_names:
        names_list = "\n".join(f"- {n}" for n in forbidden_names)
        forbidden_names_rule = (
            f"\n\nFORBIDDEN NAMES (spoilers from later books — NEVER use these):\n"
            f"{names_list}\n"
            f"Use ONLY the entity's canonical name and listed aliases. "
            f"Any output containing a forbidden name will be rejected."
        )

    relations_title = slot_label("relationships", lang)
    has_typed_rels = bool(relationships_block)
    rels_in_sections = "relationships" in sections
    if rels_in_sections and has_typed_rels:
        relations_rule = (
            f'- For PERSON entities: ALWAYS include a "## {relations_title}" section when "relationships" is in the sections list AND typed relationships are provided above. Do not skip it.\n'
            f'- Each "## {relations_title}" entry must use this format: "**[[related_entity]]** — [relationship_type]. [evolution if available]"\n'
            '- NEVER print cooccurrence_count or any raw mention/cooccurrence count in the output. cooccurrence_count is an internal ranking metric only — it must not appear in reader-facing text.'
        )
        if rels_enriched:
            relations_rule += (
                f'\n- Anchor each "## {relations_title}" entry in the evidence quotes, key moments, and contexts provided above: '
                "cite or closely paraphrase these grounded facts instead of paraphrasing the abstract relationship_type. "
                "Do NOT invent moments that are not listed."
            )
    else:
        relations_rule = f"- Do NOT include a ## {relations_title} section in the content field. No relationships data is available for this entity."

    events_title = slot_label("events", lang)
    place_events_rule = ""
    if etype == "PLACE":
        if place_events_block:
            place_events_rule = (
                f'\n- Include a "## {events_title}" section grounded ONLY in the "Events at this place" block above: '
                "describe what actually happens here — the events themselves, not just the geography or architecture. "
                "Do NOT mention chapter numbers in the prose."
            )
        else:
            place_events_rule = (
                f'\n- Do NOT include a "## {events_title}" section: no narrative events are available for this place.'
            )

    references_rule = ""
    if "references" in sections:
        references_rule = (
            f'\n- The ## {slot_label("references", lang)} section must list ONLY "{book_title}". '
            "Do not add any other book, volume, or series title."
        )

    narrative_role_title = slot_label("narrative_role", lang)
    narrative_role_rule = ""
    if etype == "PERSON" and "narrative_role" in sections:
        if narrative_role_block:
            narrative_role_rule = (
                f'\n- Write a "## {narrative_role_title}" section grounded ONLY in the '
                "events block above: retrace the character's "
                "arc through the plot in chronological order, in flowing prose. Describe what "
                "the character does and what happens to them across these events — not a static "
                "portrait. Do NOT mention chapter numbers in the prose. Do NOT "
                "invent events, outcomes, or motives absent from the listed events."
                "\n- Name every other character explicitly, using their exact name as written "
                "in the events block. NEVER replace a named character with a vague periphrasis "
                "(e.g. \"the protagonist\", \"a young woman\", \"the main character\") — this is "
                "an encyclopedic article and each character has their own page, so there is no "
                "spoiler reason to withhold a name here. Introduce each character by name at "
                "their first mention; pronouns are fine afterwards."
                "\n- Weight the prose by each event's \"importance\" tier: an event marked "
                '"importance: high" earns a full, developed treatment; "medium" a sentence '
                'or two; "low" a brief mention or a subordinate clause — never a dedicated '
                "paragraph. Spend words in proportion to narrative importance, not evenly."
            )
        else:
            narrative_role_rule = (
                f'\n- Do NOT include a "## {narrative_role_title}" section: no narrative events are available for this character.'
            )

    backstory_title = slot_label("backstory", lang)
    backstory_rule = ""
    if etype == "PERSON" and "backstory" in sections:
        if backstory_block:
            backstory_rule = (
                f'\n- Write a "## {backstory_title}" section grounded ONLY in the '
                '"Backstory context" block above: recount what happened to the character before '
                "the book's present-day narrative, as revealed through flashbacks, in flowing prose. "
                "Do NOT repeat the present-day biography. Do NOT mention chapter numbers "
                "in the prose. Do NOT invent events absent from the backstory block."
            )
        else:
            backstory_rule = (
                f'\n- Do NOT include a "## {backstory_title}" section: no flashback backstory is available for this character.'
            )

    return f"""{GROUNDING_BLOCK}

{stance.prompt_block(sections, lang)}

You are writing a wiki page for a fictional novel called "{book_title}".
Output ONLY a valid JSON object. No markdown fences. No explanation. No preamble.

---

EXAMPLE OF THE EXPECTED OUTPUT FORMAT AND TONE:
{few_shot_json}

---

Entity to write:
  Name: {name}
  Type: {etype}
  Known aliases: {alias_str}

GROUNDING EXCERPTS — these are the ONLY facts you may use:
{context_block}

Related entities (disambiguation only — do not derive narrative from cooccurrence):
{related_block}

Typed relationships (use these directly for the ## Relations section):
{relationships_block if relationships_block else "  (no typed relationships available)"}{indirect_section}

Chapter summaries (orientation context — lower priority than excerpts):
{chapter_summary_block}{place_events_section}{narrative_role_section}{backstory_section}

---

WRITING RULES (follow strictly):

Tone and register:
- Write in encyclopedic {lang_name}. Neutral, precise, factual.
- Describe what the entity IS before describing what happens to it.
- When a chapter summary is tagged with a subjective POV, attribute contested claims to that viewpoint ("according to X", "from X's point of view") rather than stating them as fact.
- Use specific, concrete language. Avoid generic adjectives without textual evidence.
- If aliases exist, introduce them naturally in the biography ("also known as X", "born Y").
- Use ONLY aliases listed in "Known aliases" above. Do NOT infer or invent aliases from context.

Content constraints:
- Chapter summaries serve as orientation only. Direct excerpts take priority.
- Do NOT invent plot details, relationships, abilities, or physical traits not supported by excerpts.
- Do NOT turn cooccurrence between entities into narrative causality.
- Confidence markers: each relationship carries a "confidence" tag. State "explicit" relationships as fact (direct affirmation). Phrase "inferred" and "interpretation" relationships tentatively ("seems", "suggests", "could indicate") — never as established fact. Indirect relationships listed as "inferred: true" are interpretation: mention them only with such hedged phrasing, if at all.
- When referring to related entities or characters, use their name EXACTLY as written in the excerpts or relationships list — do not paraphrase, alter, or approximate names.{place_events_rule}{narrative_role_rule}{backstory_rule}
- If information is insufficient for a section, omit that section entirely.
- Do NOT write "information not available", "not mentioned in excerpts", or any similar phrase. Omit instead.
- Omit infobox fields entirely if their value is unknown.

Structure:
- Use exactly these sections in this order: {sections_str}.
- Target length: {length_hint}
- The "{slot_label("infobox", lang)}" section must use this format: one bullet per field, "- Key: Value".
{relations_rule}
- infobox_fields keys must be plain strings — no leading "- " or "* ". Correct: {{"nom": "X"}}, Wrong: {{"- nom": "X"}}.
- Context labels like [Chapter N] are internal references — never mention them in your output.{references_rule}
- infobox_fields must contain ONLY wiki-relevant fields (name, role, affiliation, etc.). Do NOT include internal data fields such as cooccurrence_count, entity_type, importance, or any metadata.

Section definitions for type {etype}:
{section_def_lines}{forbidden_names_rule}

---

REMINDER: Write ALL content in {lang_name}. Source excerpts may be in another language — your output must always be in {lang_name} regardless.

Output this JSON object:
{{
  "title": "{name}",
  "importance": "{importance}",
  "entity_type": "{etype}",
  "infobox_fields": {{}},
  "content": "<Markdown string with \\\\n for newlines>"
}}

Output ONLY the JSON. Nothing before, nothing after."""


def _strip_relations_section(content: str, title: str) -> str:
    """Remove the localized relationships section (``## <title>``) from Markdown.

    Post-processing guard: the LLM may produce a relationships section even when
    instructed not to. The heading is language-dependent (``Relations`` in fr,
    ``Relationships`` in en), so the pattern is built from the localized title —
    a hardcoded ``## Relations`` silently missed the English heading and let a
    hallucinated section survive on Alice (STU-628).
    """
    return re.sub(
        rf"(?m)^## {re.escape(title)}\s*\n(?:(?!^##\s).*\n?)*",
        "",
        content,
    ).rstrip("\n")


def _check_forbidden_names(page: dict, forbidden_names: list[str]) -> list[str]:
    """Return list of forbidden names found in page content or infobox fields."""
    if not forbidden_names:
        return []
    haystack = (page.get("content", "") + " " + str(page.get("infobox_fields", {}))).lower()
    return [name for name in forbidden_names if name.lower() in haystack]


def _nom_matches_identity(nom: str, entity: dict) -> bool:
    """True if nom matches (accent/case-insensitively) the entity's own
    canonical_name or any known alias. Empty nom counts as a match: there is
    nothing authored to be wrong."""
    nom_n = normalize_name(nom)
    if not nom_n:
        return True
    candidates = [entity.get("canonical_name", ""), *entity.get("aliases", [])]
    for cand in candidates:
        cand_n = normalize_name(cand)
        if cand_n and (nom_n in cand_n or cand_n in nom_n):
            return True
    return False


# STU-443 (pas 4): the identity safety nets are no longer silent — every
# trigger is counted per run so validation runs can observe when they fall
# silent and the net can be retired (STU-319 force-identity, STU-318 recovery).
# `force_identity` counts _force_correct_identity rewrites; `identity_recovery`
# counts _recover_identity_rejected_page recoveries.
_SAFETY_NET_TRIGGERS: dict[str, int] = {"force_identity": 0, "identity_recovery": 0}


def _reset_safety_net_telemetry() -> None:
    _SAFETY_NET_TRIGGERS.update(force_identity=0, identity_recovery=0)


def _record_safety_net(name: str) -> None:
    _SAFETY_NET_TRIGGERS[name] = _SAFETY_NET_TRIGGERS.get(name, 0) + 1


def _force_correct_identity(
    page: dict, entity: dict, sibling_canonicals: set[str] | None = None
) -> bool:
    """Repair infobox identity fields in place. PERSON-only (caller gates on
    type). Rewrites a swapped `nom` to canonical_name and drops any `alias`
    value that belongs to a *sibling* batch entity. Returns True if changed."""
    infobox = page.get("infobox_fields") or {}
    canonical = entity.get("canonical_name", "")
    changed = False

    nom = str(infobox.get("nom", "")).strip()
    if nom and not _nom_matches_identity(nom, entity):
        infobox["nom"] = canonical
        changed = True

    sib_norm = {n for n in (normalize_name(s) for s in (sibling_canonicals or set())) if n}
    if sib_norm and infobox.get("alias"):
        kept = []
        for value in str(infobox["alias"]).split(","):
            v_n = normalize_name(value)
            is_swap = bool(v_n) and not _nom_matches_identity(value, entity) and any(
                v_n == s or v_n in s or s in v_n for s in sib_norm
            )
            if is_swap:
                changed = True
            else:
                kept.append(value.strip())
        infobox["alias"] = ", ".join(k for k in kept if k)
        if not infobox["alias"]:
            infobox.pop("alias", None)

    if changed:
        page["infobox_fields"] = infobox
        page["_identity_corrected"] = True
    return changed


def _batch_bound_value(entity: dict, token: str, lang: str = "fr") -> str | None:
    """Value for a batch-bound infobox token, sourced from the batch entity.
    Returns None for tokens the batch cannot sensibly supply (skipped by the
    binder). `type` is intentionally unsupported: the coarse batch type is
    infobox noise; the specific type is an extracted-fact (slice C)."""
    if token == "nom":
        return entity.get("canonical_name") or None
    if token == "alias":
        aliases = [a for a in (entity.get("aliases") or []) if a]
        return ", ".join(aliases) if aliases else None
    if token == "apparition":
        # Provenance par livre (STU-486/STU-484): empty `books` (registry
        # absent or pre-multi-tome artifact) degrades to omitting the slot.
        return appearance_label(entity.get("books") or [], lang=lang) or None
    return None


def _extracted_fact_value(entity: dict, token: str, lang: str) -> str | None:
    """Value for an extracted-fact infobox token, sourced from facts the pipeline
    produced into the batch entity. None when the fact is absent (slot omitted).
    The specific `type` is a future slice."""
    if token == "titles":
        titles = [t for t in (entity.get("titles") or []) if t]
        return ", ".join(titles) if titles else None
    if token == "status":
        # MIN with a declared fallback: an unstamped entity renders `unknown`
        # rather than dropping the slot (STU-488).
        return status_label(entity.get("status"), lang)
    if token == "affiliation":
        # OPT with no declared fallback: an undecided character drops the slot
        # (STU-551). Plain text — no infobox slot carries a wikilink today.
        return (entity.get("affiliation") or "").strip() or None
    if token == "species":
        # OPT, genre-gated: a book with no invented species never ran the stage,
        # so the slot drops (STU-574). Plain text, like `affiliation`.
        return (entity.get("species") or "").strip() or None
    if token == "death":
        # OPT, unlike `status`: no grounded circumstance renders no row (STU-552).
        return death_label(entity.get("death_agent"), entity.get("death_place"), lang)
    return None


def _bind_batch_fields(page: dict, entity: dict, book_config: dict | None) -> None:
    """Overwrite pipeline-sourced infobox tokens with authoritative values, per
    the resolved template: `batch-bound` from the batch identity, `extracted-fact`
    from facts the pipeline produced. An `extracted-fact` slot the pipeline cannot
    fill is *cleared*, not left to the writer — the writer never owns a slot whose
    provenance promises a grounded fact (STU-572). `llm-prose` slots are left to
    the LLM. No-op when book_config is None."""
    if book_config is None:
        return
    page.setdefault("infobox_fields", {})
    resolved = resolve_template(entity.get("type"), entity.get("importance"), book_config)
    lang = output_language(book_config)
    for slot in resolved.infobox():
        if slot.provenance == "batch-bound":
            value = _batch_bound_value(entity, slot.token, lang)
            if value:
                page["infobox_fields"][slot.token] = value
        elif slot.provenance == "extracted-fact":
            # The pipeline owns this slot: both its value and its absence are
            # authoritative. A present value overwrites; an absent one clears
            # whatever the writer put there, rather than leaving an ungrounded
            # fact under a provenance that promises a grounded one (STU-572).
            # A slot the pipeline never computes (species, location, leaders)
            # is therefore always empty until it is computed.
            value = _extracted_fact_value(entity, slot.token, lang)
            if value:
                page["infobox_fields"][slot.token] = value
            else:
                page["infobox_fields"].pop(slot.token, None)


# The neutral error codes check_identity_match emits (scripts/wiki_page_validator.py).
# STU-517: matching on codes, not the validator's localized prose, so rewording an
# error can never silently break identity-only recovery.
_IDENTITY_ERROR_CODES = frozenset({"identity_title_mismatch", "identity_infobox_mismatch"})


def _rejection_is_identity_only(run_id: str, runner: StudioRunner | None = None) -> bool:
    """True iff the validator rejected the run and *every* error it reported is
    an identity error. Guards against smuggling a page past grounding/language
    validators when we recover it."""
    runner = runner or StudioRunner()
    vout = runner.load_stage_output(str(run_id), "wiki-page-validator")
    codes = (vout or {}).get("error_codes") or []
    return bool(codes) and all(code in _IDENTITY_ERROR_CODES for code in codes)


def _recover_identity_rejected_page(
    *, entity: dict, item_result: dict, sibling_canonicals: set[str] | None = None,
    runner: StudioRunner | None = None, lang: str = "fr",
) -> dict | None:
    """Recover a PERSON page from an identity-only rejected run and force-correct
    its identity fields. Returns the kept page, or None if not recoverable."""
    if entity.get("type") != "PERSON":
        return None
    runner = runner or StudioRunner()
    run_id = str((item_result.get("run_metadata") or {}).get("run_id") or "").strip()
    if not run_id or not _rejection_is_identity_only(run_id, runner):
        return None
    recovered = runner.load_stage_output(run_id, "wiki-page-item")
    if not isinstance(recovered, dict):
        return None
    page = parse_response(json.dumps(recovered, ensure_ascii=False), entity, lang=lang)
    if page.get("_failed"):
        return None
    _force_correct_identity(page, entity, sibling_canonicals)
    page["_identity_corrected"] = True
    return page


# STU-465: a technical generation failure and a genuine data famine are
# distinct conditions. Keep their stub content distinct so `_failed` pages are
# not mislabelled with an "insufficient data" message that masks a real failure.
def make_stub_page(
    entity: dict, failed: bool = False, insufficient_data: bool = False, lang: str = "fr"
) -> dict:
    page = {
        "title": entity["canonical_name"],
        "importance": entity["importance"],
        "entity_type": entity["type"],
        "books": list(entity.get("books") or []),
        "infobox_fields": {},
        "content": stub_content("failed" if failed else "insufficient", lang),
    }
    if failed:
        page["_failed"] = True
    if insufficient_data:
        page["_insufficient_data"] = True
    return page


def _save_generation_debug_artifact(debug_dir: Path, entity: dict, item_result: dict) -> None:
    debug_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{studio_io.slugify_filename(entity.get('canonical_name', 'untitled'))}.json"
    payload = {
        "entity_name": entity.get("canonical_name", ""),
        "error": item_result.get("error"),
        "raw_response": str(item_result.get("raw_response", "") or ""),
        "run_metadata": item_result.get("run_metadata"),
    }
    with open(debug_dir / filename, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _wiki_page_item_input(
    *,
    entity: dict,
    book_title: str,
    sections: list[str],
    max_tokens: int,
    forbidden_names: list[str] | None = None,
    language: str = "fr",
    file_path: str = "",
    grounding: dict | None = None,
    prompt_override: str | None = None,
    stance: EditorialStance | None = None,
) -> dict:
    # language / forbidden_names / file_path / grounding_* feed the
    # wiki-page-validator stage inside the wiki-page-item pipeline (its
    # checks read them from additional_context — without them those checks
    # are no-ops).
    item = {
        "title": entity.get("canonical_name", ""),
        "importance": entity.get("importance", ""),
        "entity_type": entity.get("type", ""),
        "max_tokens": max_tokens,
        "language": language,
        "forbidden_names": forbidden_names or [],
        "file_path": file_path,
        "prompt": prompt_override or build_prompt(
            entity, book_title, sections=sections,
            forbidden_names=forbidden_names, stance=stance, lang=language,
        ),
    }
    grounding = grounding or {}
    if grounding.get("llm"):
        item["grounding_llm"] = True
        if grounding.get("llm_model"):
            item["grounding_llm_model"] = grounding["llm_model"]
        if grounding.get("llm_timeout"):
            item["grounding_llm_timeout"] = grounding["llm_timeout"]
    return item


def _run_wiki_page_item(
    *,
    entity: dict,
    book_title: str,
    model: str,
    timeout: int,
    sections: list[str],
    max_tokens: int,
    forbidden_names: list[str] | None = None,
    language: str = "fr",
    file_path: str = "",
    grounding: dict | None = None,
    runner: StudioRunner | None = None,
    prompt_override: str | None = None,
    stance: EditorialStance | None = None,
) -> dict:
    item_input = _wiki_page_item_input(
        entity=entity,
        book_title=book_title,
        sections=sections,
        max_tokens=max_tokens,
        forbidden_names=forbidden_names,
        language=language,
        file_path=file_path,
        grounding=grounding,
        prompt_override=prompt_override,
        stance=stance,
    )
    return (runner or StudioRunner()).run_item(item_input, entity, timeout)


def _execute_wiki_page_item(item_input: dict, entity: dict, timeout: int) -> dict:
    """Run one wiki-page-item pipeline over a prebuilt item input and parse the
    resulting page. Shared by entity pages (via _run_wiki_page_item) and the
    book synopsis (scripts/generate_book_synopsis.py, SP4)."""
    timeout_seconds = max(timeout * 4, 120)

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".yaml", delete=False) as tmp:
        yaml.safe_dump(item_input, tmp, sort_keys=False, allow_unicode=True)
        input_path = tmp.name

    cmd = [
        "studio",
        "run",
        "wiki-page-item",
        "--input-file",
        input_path,
        "--json",
    ]
    try:
        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError:
        return {
            "error": "studio_cli_missing",
            "raw_response": "",
            "run_metadata": {"command": cmd},
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "error": "studio_run_timeout",
            "raw_response": (exc.stdout or "") + ("\n" + exc.stderr if exc.stderr else ""),
            "run_metadata": {"command": cmd, "timeout_seconds": timeout_seconds},
        }
    finally:
        try:
            Path(input_path).unlink(missing_ok=True)
        except OSError:
            pass

    combined_output = (result.stdout or "") + (("\n" + result.stderr) if result.stderr else "")
    run_payload = studio_io.extract_first_json_object(result.stdout or "")
    run_id = studio_io.extract_run_id(result.stdout or "")
    run_metadata = {
        "command": cmd,
        "returncode": result.returncode,
        "run_id": run_id or None,
        "status": (run_payload or {}).get("status"),
    }
    if result.returncode != 0:
        return {
            "error": "studio_run_failed",
            "raw_response": combined_output.strip(),
            "run_metadata": run_metadata,
        }

    if not run_id:
        return {
            "error": "studio_run_missing_id",
            "raw_response": combined_output.strip(),
            "run_metadata": run_metadata,
        }

    payload = studio_io.stage_output_from_stdout(result.stdout or "", "wiki-page-item")
    if payload is None:
        return {
            "error": "studio_run_output_missing",
            "raw_response": combined_output.strip(),
            "run_metadata": run_metadata,
        }

    page = parse_response(json.dumps(payload, ensure_ascii=False), entity, lang=item_input.get("language", "fr"))
    if page.get("_failed"):
        return {
            "error": "studio_invalid_output",
            "raw_response": combined_output.strip(),
            "run_metadata": {**run_metadata, "payload": payload},
        }
    return {
        **page,
        "run_metadata": run_metadata,
    }


class StudioRunner:
    """Every Studio touchpoint of the generation path behind one injectable
    interface: a fake makes generate_pages() testable without a subprocess, and
    the seam prepares the M4 fan-out (STU-449)."""

    def run_item(self, item_input: dict, entity: dict, timeout: int) -> dict:
        return _execute_wiki_page_item(item_input, entity, timeout)

    def load_stage_output(self, run_id: str, stage: str) -> dict | None:
        return studio_io.load_studio_stage_output(run_id, stage)


def _item_key(item_input: dict) -> str:
    return hashlib.sha256(
        json.dumps(item_input, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


class CollectingRunner:
    """Plan walk (STU-612): records every item the walk would dispatch and
    answers with a fake success, so the walk itself enumerates the calls —
    data gates, section order and the per-relation set included — with zero
    duplicated planning logic. Pages produced under it are discarded."""

    def __init__(self) -> None:
        self.items: dict[str, dict] = {}

    def run_item(self, item_input: dict, entity: dict, timeout: int) -> dict:
        self.items.setdefault(_item_key(item_input), dict(item_input))
        # Mirrors parse_response's identity stamping: the non-PERSON single-shot
        # path returns this dict as the page, and the walk's _commit validates it
        # as a WikiPage — without importance/entity_type the plan walk crashes on
        # the first non-PERSON entity.
        return {
            "title": entity.get("canonical_name", ""),
            "importance": entity.get("importance", ""),
            "entity_type": entity.get("type", ""),
            "books": list(entity.get("books") or []),
            "content": "planned",
            "infobox_fields": {},
            "run_metadata": {},
        }

    def load_stage_output(self, run_id: str, stage: str) -> dict | None:
        return None


class ReplayRunner:
    """Replay walk (STU-612): serves the engine map results keyed on the item
    input. A second request for the same item is the in-walk forbidden-name
    retry — recorded in `retry_items` and served from the second fan-out pass
    when one ran. Mirrors _execute_wiki_page_item's return contract, so the
    walk cannot tell replay from subprocess."""

    def __init__(self, first: dict[str, dict], second: dict[str, dict] | None = None) -> None:
        self.first = first
        self.second = second or {}
        self._seen: dict[str, int] = {}
        self.retry_items: dict[str, dict] = {}

    def run_item(self, item_input: dict, entity: dict, timeout: int) -> dict:
        key = _item_key(item_input)
        request = self._seen.get(key, 0)
        self._seen[key] = request + 1
        if request > 0:
            if key in self.second:
                return self._to_item_result(self.second[key], entity, item_input)
            self.retry_items.setdefault(key, dict(item_input))
        return self._to_item_result(self.first.get(key), entity, item_input)

    def load_stage_output(self, run_id: str, stage: str) -> dict | None:
        return studio_io.load_studio_stage_output(run_id, stage)

    @staticmethod
    def _to_item_result(map_result: dict | None, entity: dict, item_input: dict) -> dict:
        return page_from_map_result(map_result, entity, item_input.get("language", "fr"))


def page_from_map_result(map_result: dict | None, entity: dict, language: str = "fr") -> dict:
    """Reconstruct `_execute_wiki_page_item`'s return contract from one engine map
    result. Shared by the replay walk (entity pages) and the synopsis/event post
    stages, so all three parse a map result the same way (STU-621)."""
    if map_result is None:
        return {"error": "studio_map_item_missing", "raw_response": "", "run_metadata": {}}
    run_metadata = {
        "run_id": map_result.get("run_id"),
        "status": map_result.get("status"),
    }
    if map_result.get("status") != "success" or not isinstance(map_result.get("output"), dict):
        return {
            "error": "studio_map_item_failed",
            "raw_response": str(map_result.get("error") or ""),
            "run_metadata": run_metadata,
        }
    payload = map_result["output"]
    page = parse_response(json.dumps(payload, ensure_ascii=False), entity, lang=language)
    if page.get("_failed"):
        return {
            "error": "studio_invalid_output",
            "raw_response": json.dumps(payload, ensure_ascii=False),
            "run_metadata": {**run_metadata, "payload": payload},
        }
    return {**page, "run_metadata": run_metadata}


def wiki_pages_map_item(item_input: dict, attempt: int = 1) -> dict:
    """A `wiki-pages` map item from a prebuilt wiki-page-item input — the grounding
    defaults + `attempt` key `_run_pages_fanout` injects, extracted so the
    synopsis/event stages build identical items (STU-621)."""
    return {
        "grounding_llm": False,
        "grounding_llm_model": "",
        "grounding_llm_timeout": 0,
        **item_input,
        "attempt": attempt,
    }


def _run_pages_fanout(
    items: list[dict], fingerprint: str, attempt: int, timeout: int
) -> tuple[dict | None, str | None]:
    """One `studio run` fanning out over the planned items. Returns (map_output, error)."""
    payload = {
        "items": [wiki_pages_map_item(item, attempt) for item in items],
        "prompt_fingerprint": fingerprint,
    }
    timeout_seconds = max(600, len(items) * max(timeout, 60))
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".yaml", delete=False) as tmp:
        yaml.safe_dump(payload, tmp, sort_keys=False, allow_unicode=True)
        input_path = tmp.name
    cmd = ["studio", "run", "wiki-pages", "--input-file", input_path, "--json"]
    try:
        result = subprocess.run(
            cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=timeout_seconds
        )
    except FileNotFoundError:
        return None, "studio_cli_missing"
    except subprocess.TimeoutExpired:
        return None, "studio_run_timeout"
    finally:
        Path(input_path).unlink(missing_ok=True)
    if result.returncode != 0:
        return None, "studio_run_failed"
    map_output = studio_io.stage_output_from_stdout(result.stdout or "", "generate")
    if map_output is None:
        return None, "studio_run_output_missing"
    return map_output, None


def _fanout_results_by_key(keys: list[str], map_output: dict | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not isinstance(map_output, dict):
        return out
    for result in map_output.get("results") or []:
        if isinstance(result, dict) and isinstance(result.get("index"), int):
            i = result["index"]
            if 0 <= i < len(keys):
                out[keys[i]] = result
    return out


def generate_pages_fanout(batches: list[tuple[str, dict]], config: GenerationConfig) -> list[dict]:
    """generate_pages through the engine map stage: plan walk → fan-out →
    replay walk, with a second fan-out only for in-walk forbidden-name retries
    (their prompt is identical, so `attempt: 2` is what busts the item cache).
    Walks are deterministic and LLM-free; the fan-outs are the only Studio
    invocations."""
    fingerprint = _page_prompt_fingerprint(config)

    with tempfile.TemporaryDirectory(prefix="wiki-pages-plan-") as scratch:
        def _scratch_config(name: str) -> GenerationConfig:
            path = str(Path(scratch) / name)
            if Path(config.output_file).exists():
                shutil.copyfile(config.output_file, path)
            return dataclasses.replace(config, output_file=path)

        collector = CollectingRunner()
        generate_pages(batches, _scratch_config("plan.json"), runner=collector)
        keys = list(collector.items)
        items = list(collector.items.values())

        first: dict[str, dict] = {}
        if items:
            print(f"[generate-wiki-pages] fan-out: {len(items)} item call(s)", file=sys.stderr)
            map_output, error = _run_pages_fanout(items, fingerprint, attempt=1, timeout=config.timeout)
            if error:
                print(
                    f"[generate-wiki-pages] WARNING: {error} — every planned item renders "
                    "as failed; affected pages stub and retry next run",
                    file=sys.stderr,
                )
            first = _fanout_results_by_key(keys, map_output)
            resumed = (map_output or {}).get("resumed", 0)
            if resumed:
                print(f"[generate-wiki-pages] {resumed} item(s) served from resume cache", file=sys.stderr)

        probe = ReplayRunner(first)
        generate_pages(batches, _scratch_config("probe.json"), runner=probe)

        second: dict[str, dict] = {}
        if probe.retry_items:
            retry_keys = list(probe.retry_items)
            retry_items = list(probe.retry_items.values())
            print(
                f"[generate-wiki-pages] forbidden-name retry: {len(retry_items)} item call(s)",
                file=sys.stderr,
            )
            map_output, error = _run_pages_fanout(retry_items, fingerprint, attempt=2, timeout=config.timeout)
            if error:
                print(
                    f"[generate-wiki-pages] WARNING: {error} on the retry pass — "
                    "first-pass results stand, forbidden hits persist",
                    file=sys.stderr,
                )
            second = _fanout_results_by_key(retry_keys, map_output)

    return generate_pages(batches, config, runner=ReplayRunner(first, second))


# --- STU-621 native plan/call/probe/call/post split ---------------------------
#
# The walk is deterministic and LLM-free, so each stage re-runs it to reproduce
# the same items/keys; only the two `wiki-pages` map outputs flow between stages
# (through Studio context). The two nested `studio run` subprocesses of
# `generate_pages_fanout` become two native `call: wiki-pages` stages, so the
# whole build runs under one top-level engine (STU-615 lifted the depth cap).

VERDICT_STAGE = "wiki-pages-verdict"
RETRY_VERDICT_STAGE = "wiki-pages-retry-verdict"


def _map_output_from_payload(payload: dict, stage_name: str) -> dict | None:
    """A `wiki-pages` call's map output, from stage context (or None)."""
    verdict = payload.get("all_stage_outputs", {}).get(stage_name)
    if verdict is None:
        verdict = payload.get("previous_outputs", {}).get(stage_name)
    return verdict if isinstance(verdict, dict) else None


def _throwaway_walk(batches: list[tuple[str, dict]], config: GenerationConfig, runner) -> None:
    """Run a plan/probe walk against a scratch output file — the walk enumerates
    or replays items, its pages are discarded. The real output is copied in so
    resume / `--force` decisions match the final walk."""
    with tempfile.TemporaryDirectory(prefix="wiki-pages-walk-") as scratch:
        path = str(Path(scratch) / "walk.json")
        if Path(config.output_file).exists():
            shutil.copyfile(config.output_file, path)
        generate_pages(batches, dataclasses.replace(config, output_file=path), runner=runner)


def _plan_keys_and_items(batches: list[tuple[str, dict]], config: GenerationConfig) -> tuple[list[str], list[dict]]:
    """The plan walk: every item the generation would dispatch, in walk order."""
    collector = CollectingRunner()
    _throwaway_walk(batches, config, collector)
    return list(collector.items), list(collector.items.values())


def plan_generation(book_cfg: dict, book_paths) -> dict:
    """Plan stage: enumerate the attempt-1 fan-out items. `needs_verdict` is
    false when there is nothing to generate (the post stage then has no map to
    read and writes what `_prepare_generation` already wrote)."""
    config, batches = _prepare_generation(
        book_cfg, book_paths, model=os.environ.get("WIKI_MODEL", "qwen2.5"), timeout=120
    )
    if config is None:
        return {"items": [], "prompt_fingerprint": "", "needs_verdict": False}

    _keys, items = _plan_keys_and_items(batches, config)
    print(f"[generate-wiki-pages] plan: {len(items)} item call(s)", file=sys.stderr)
    return {
        "items": [wiki_pages_map_item(item, attempt=1) for item in items],
        "prompt_fingerprint": _page_prompt_fingerprint(config),
        "needs_verdict": bool(items),
    }


def probe_generation(book_cfg: dict, book_paths, first_map_output: dict | None) -> dict:
    """Probe stage: replay the attempt-1 results through the walk and collect the
    in-walk forbidden-name retries as attempt-2 items (their prompt is identical,
    so `attempt: 2` is what busts the item cache)."""
    config, batches = _prepare_generation(
        book_cfg, book_paths, model=os.environ.get("WIKI_MODEL", "qwen2.5"), timeout=120
    )
    if config is None:
        return {"items": [], "needs_retry": False}

    keys, _items = _plan_keys_and_items(batches, config)
    first = _fanout_results_by_key(keys, first_map_output)
    probe = ReplayRunner(first)
    _throwaway_walk(batches, config, probe)

    retry_items = list(probe.retry_items.values())
    if retry_items:
        print(f"[generate-wiki-pages] forbidden-name retry: {len(retry_items)} item call(s)", file=sys.stderr)
    return {
        "items": [wiki_pages_map_item(item, attempt=2) for item in retry_items],
        "needs_retry": bool(retry_items),
    }


def post_generation(
    book_cfg: dict, book_paths, first_map_output: dict | None, second_map_output: dict | None
) -> list[dict]:
    """Post stage: rebuild both passes' results and run the final replay walk,
    which commits the real `wiki_pages.json`."""
    config, batches = _prepare_generation(
        book_cfg, book_paths, model=os.environ.get("WIKI_MODEL", "qwen2.5"), timeout=120
    )
    if config is None:
        return []

    keys, _items = _plan_keys_and_items(batches, config)
    first = _fanout_results_by_key(keys, first_map_output)
    resumed = (first_map_output or {}).get("resumed", 0)
    if resumed:
        print(f"[generate-wiki-pages] {resumed} item(s) served from resume cache", file=sys.stderr)

    # Reproduce the attempt-2 keys the probe collected, so the second pass'
    # results map back onto the same items.
    probe = ReplayRunner(first)
    _throwaway_walk(batches, config, probe)
    retry_keys = list(probe.retry_items)
    second = _fanout_results_by_key(retry_keys, second_map_output)

    pages = generate_pages(batches, config, runner=ReplayRunner(first, second))
    _print_generation_summary(pages)
    _write_identity_telemetry(book_paths.processing)
    return pages


def _as_failure(result: object) -> dict:
    return result if isinstance(result, dict) else {"error": "studio_result_not_a_dict", "raw_response": repr(result)}


def _generate_one_section(
    *,
    entity: dict,
    section: str,
    book_title: str,
    model: str,
    timeout: int,
    max_tokens: int,
    forbidden_names: list[str] | None = None,
    language: str = "fr",
    file_path: str = "",
    grounding: dict | None = None,
    runner: StudioRunner | None = None,
    stance: EditorialStance | None = None,
) -> tuple[str | None, dict | None]:
    """Generate a single section via a scoped wiki-page-item call.

    Returns ``(content, failure)``: the section's content block, or None on
    error / persistent forbidden-name hit, paired with the failing item result
    so the caller can save its evidence (STU-533).
    """

    # SP1: the arc section is data-gated — skip the LLM call entirely when SP0
    # produced no participant events, rather than prompting it to hallucinate one.
    if section == "narrative_role" and not _narrative_events(entity):
        return None, None

    # STU-493: the backstory section is data-gated — skip the LLM call when the
    # character has no flashback-tagged chapter summaries.
    if section == "backstory" and not _has_backstory(entity):
        return None, None

    def _once() -> dict:
        return _run_wiki_page_item(
            entity=entity, book_title=book_title, model=model, timeout=timeout,
            sections=[section], max_tokens=max_tokens, forbidden_names=forbidden_names,
            language=language, file_path=file_path, grounding=grounding, runner=runner,
            stance=stance,
        )

    result = _once()
    if not isinstance(result, dict) or result.get("error"):
        return None, _as_failure(result)
    content = _isolate_section(result.get("content") or "", section, language) or ""
    if section == "relationships" and not entity.get("relationships"):
        content = _strip_relations_section(content, slot_label("relationships", language))
    if forbidden_names and _check_forbidden_names({"content": content, "infobox_fields": {}}, forbidden_names):
        result = _once()
        if not isinstance(result, dict) or result.get("error"):
            return None, _as_failure(result)
        content = _isolate_section(result.get("content") or "", section, language) or ""
        if section == "relationships" and not entity.get("relationships"):
            content = _strip_relations_section(content, slot_label("relationships", language))
        if _check_forbidden_names({"content": content, "infobox_fields": {}}, forbidden_names):
            return None, {"error": "forbidden_names_persist", "run_metadata": result.get("run_metadata")}
    content = content.strip()
    return (content or None), (None if content else {"error": "empty_section", "raw_response": result.get("content") or "", "run_metadata": result.get("run_metadata")})


def _generate_one_relation(
    *,
    entity: dict,
    other: str,
    rel: dict,
    book_title: str,
    model: str,
    timeout: int,
    max_tokens: int,
    forbidden_names: list[str] | None = None,
    language: str = "fr",
    file_path: str = "",
    grounding: dict | None = None,
    runner: StudioRunner | None = None,
) -> str | None:
    """Generate one ``### [[other]]`` French progression subsection. Returns the
    subsection markdown, or None on error / persistent forbidden-name hit."""
    prompt = build_relation_prompt(entity, other, rel, book_title, forbidden_names=forbidden_names, lang=language)

    def _once() -> dict:
        return _run_wiki_page_item(
            entity=entity, book_title=book_title, model=model, timeout=timeout,
            sections=["relationships"], max_tokens=max_tokens, forbidden_names=forbidden_names,
            language=language, file_path=file_path, grounding=grounding, runner=runner,
            prompt_override=prompt,
        )

    result = _once()
    if not isinstance(result, dict) or result.get("error"):
        return None
    content = (result.get("content") or "").strip()
    if forbidden_names and _check_forbidden_names({"content": content, "infobox_fields": {}}, forbidden_names):
        result = _once()
        if not isinstance(result, dict) or result.get("error"):
            return None
        content = (result.get("content") or "").strip()
        if _check_forbidden_names({"content": content, "infobox_fields": {}}, forbidden_names):
            return None
    return content or None


def _generate_relationships_subsections(
    *,
    entity: dict,
    book_title: str,
    model: str,
    timeout: int,
    max_tokens: int,
    forbidden_names: list[str] | None = None,
    language: str = "fr",
    file_path: str = "",
    grounding: dict | None = None,
    runner: StudioRunner | None = None,
) -> str | None:
    """The full ``## Relations`` block: one prose subsection per typed relationship
    (most-recent-reveal first). None when no subsection is produced."""
    own = {entity.get("canonical_name")} | set(entity.get("aliases") or [])
    typed = []
    for rel in entity.get("relationships") or []:
        if not usable_relationship_type(rel.get("relationship_type")):
            continue
        chapters = [n for n in (rel.get("chapters") or []) if isinstance(n, int)]
        other = rel["entity_b"] if rel.get("entity_a") in own else rel["entity_a"]
        typed.append((max(chapters) if chapters else -1, other, rel))
    typed.sort(key=lambda t: t[0], reverse=True)
    subs = []
    for _, other, rel in typed:
        block = _generate_one_relation(
            entity=entity, other=other, rel=rel, book_title=book_title, model=model,
            timeout=timeout, max_tokens=max_tokens, forbidden_names=forbidden_names,
            language=language, file_path=file_path, grounding=grounding, runner=runner,
        )
        if block:
            subs.append(block)
    if not subs:
        return None
    return "## Relations\n\n" + "\n\n".join(subs)


def _run_generation_for_entity(
    *,
    entity: dict,
    book_title: str,
    model: str,
    timeout: int,
    sections: list[str],
    max_tokens: int,
    dry_run: bool,
    debug_dir: Path,
    forbidden_names: list[str] | None = None,
    language: str = "fr",
    file_path: str = "",
    grounding: dict | None = None,
    sibling_canonicals: set[str] | None = None,
    book_config: dict | None = None,
    runner: StudioRunner | None = None,
) -> dict:
    if not entity.get("context_by_chapter", {}):
        return make_stub_page(entity, insufficient_data=True, lang=language)
    if dry_run:
        return make_stub_page(entity, lang=language)

    stance = editorial_stance(book_config or {})
    item_result = _run_wiki_page_item(
        entity=entity,
        book_title=book_title,
        model=model,
        timeout=timeout,
        sections=sections,
        max_tokens=max_tokens,
        forbidden_names=forbidden_names,
        stance=stance,
        language=language,
        file_path=file_path,
        grounding=grounding,
        runner=runner,
    )
    if isinstance(item_result, dict) and item_result.get("error"):
        recovered = _recover_identity_rejected_page(
            entity=entity,
            item_result=item_result,
            sibling_canonicals=sibling_canonicals,
            runner=runner,
            lang=language,
        )
        _save_generation_debug_artifact(debug_dir, entity, item_result)
        if recovered is not None:
            _record_safety_net("identity_recovery")
            recovered["content_units"] = content_units(sections, entity)
            recovered["relationship_index"] = relationship_index_lines(entity, language, book_config)
            _bind_batch_fields(recovered, entity, book_config)
            print(" ⚠ identity-corrected from rejected run", file=sys.stderr, end="", flush=True)
            return recovered
        return make_stub_page(entity, failed=True, lang=language)
    typed_rels = entity.get("relationships", [])
    if isinstance(item_result, dict) and "content" in item_result:
        if "relationships" not in sections or not typed_rels:
            item_result["content"] = _strip_relations_section(item_result["content"] or "", slot_label("relationships", language))

    # Forbidden names check + retry
    if forbidden_names and isinstance(item_result, dict) and "content" in item_result:
        hits = _check_forbidden_names(item_result, forbidden_names)
        if hits:
            print(f" ⚠ spoiler detected ({', '.join(hits)}), retrying…", file=sys.stderr, end="", flush=True)
            item_result = _run_wiki_page_item(
                entity=entity,
                book_title=book_title,
                model=model,
                timeout=timeout,
                sections=sections,
                max_tokens=max_tokens,
                forbidden_names=forbidden_names,
                stance=stance,
                language=language,
                file_path=file_path,
                grounding=grounding,
                runner=runner,
            )
            if isinstance(item_result, dict) and item_result.get("error"):
                _save_generation_debug_artifact(debug_dir, entity, item_result)
                return make_stub_page(entity, failed=True, lang=language)
            if isinstance(item_result, dict) and "content" in item_result:
                if "relationships" not in sections or not typed_rels:
                    item_result["content"] = _strip_relations_section(item_result["content"] or "", slot_label("relationships", language))
            hits = _check_forbidden_names(item_result, forbidden_names)
            if hits:
                print(f" ✗ spoiler persists ({', '.join(hits)})", file=sys.stderr, end="", flush=True)
                page = make_stub_page(entity, failed=True, lang=language)
                page["_spoiler_rejected"] = True
                return page

    if (
        entity.get("type") == "PERSON"
        and isinstance(item_result, dict)
        and "content" in item_result
        and _force_correct_identity(item_result, entity, sibling_canonicals)
    ):
        _record_safety_net("force_identity")
        print(" ⚠ name force-corrected", file=sys.stderr, end="", flush=True)

    if isinstance(item_result, dict) and "content" in item_result:
        item_result["content_units"] = content_units(sections, entity)
        item_result["relationship_index"] = relationship_index_lines(entity, language, book_config)
        _bind_batch_fields(item_result, entity, book_config)

    return item_result


def _run_generation_sectioned(
    *,
    entity: dict,
    book_title: str,
    model: str,
    timeout: int,
    sections: list[str],
    max_tokens: int,
    dry_run: bool,
    debug_dir: Path,
    forbidden_names: list[str] | None = None,
    language: str = "fr",
    file_path: str = "",
    grounding: dict | None = None,
    sibling_canonicals: set[str] | None = None,
    book_config: dict | None = None,
    runner: StudioRunner | None = None,
) -> dict:
    if not entity.get("context_by_chapter", {}):
        return make_stub_page(entity, insufficient_data=True, lang=language)
    if dry_run:
        return make_stub_page(entity, lang=language)

    stance = editorial_stance(book_config or {})
    content_sections = [s for s in sections if s not in ("infobox", "references")]
    per_relation = (
        entity.get("type") == "PERSON"
        and per_relation_prose_enabled(book_config or {})
        and bool(relation_units(entity))
    )
    blocks: list[str] = []
    emitted: list[str] = []
    for section in content_sections:
        if section == "relationships" and per_relation:
            block = _generate_relationships_subsections(
                entity=entity, book_title=book_title, model=model, timeout=timeout,
                max_tokens=max_tokens, forbidden_names=forbidden_names,
                language=language, file_path=file_path, grounding=grounding, runner=runner,
            )
            if block:
                blocks.append(block)
                # NOTE: 'relationships' deliberately NOT appended to `emitted`
                # so it is excluded from content_units — per-relation gating
                # (relation_units) replaces whole-section gating.
            continue
        block, failure = _generate_one_section(
            entity=entity, section=section, book_title=book_title, model=model,
            timeout=timeout, max_tokens=max_tokens, forbidden_names=forbidden_names,
            language=language, file_path=file_path, grounding=grounding, runner=runner,
            stance=stance,
        )
        if block:
            if section == "narrative_role" and sibling_canonicals:
                block = link_first_mentions(block, sibling_canonicals)
            blocks.append(block)
            emitted.append(section)
        elif section == "biography":
            _save_generation_debug_artifact(debug_dir, entity, failure or {"error": "biography_failed"})
            return make_stub_page(entity, failed=True, lang=language)
        # else: OPT section omitted

    if not blocks:
        return make_stub_page(entity, failed=True, lang=language)

    if "references" in sections:
        blocks.append(_references_block(book_title, language))

    page = {
        "title": entity["canonical_name"],
        "importance": entity["importance"],
        "entity_type": entity["type"],
        "books": list(entity.get("books") or []),
        "infobox_fields": {},
        "content": _assemble_section_blocks(blocks),
        "content_units": content_units(emitted, entity),
        "relationship_index": relationship_index_lines(entity, language, book_config),
    }
    if per_relation:
        page["relation_units"] = relation_units(entity)
        page["relationship_index"] = []
    if entity.get("type") == "PERSON" and _force_correct_identity(
        page, entity, sibling_canonicals
    ):
        _record_safety_net("force_identity")
    _bind_batch_fields(page, entity, book_config)
    return page


def _run_generation(
    *,
    entity: dict,
    book_title: str,
    model: str,
    timeout: int,
    sections: list[str],
    max_tokens: int,
    dry_run: bool,
    debug_dir: Path,
    forbidden_names: list[str] | None = None,
    language: str = "fr",
    file_path: str = "",
    grounding: dict | None = None,
    sibling_canonicals: set[str] | None = None,
    book_config: dict | None = None,
    runner: StudioRunner | None = None,
) -> dict:
    """Route generation by entity type.

    PERSON uses section-scoped prose (slice E): the few-shot trains stable
    section titles that `_isolate_section` can extract cleanly. PLACE/ORG/EVENT
    are article-shaped — the model titles the sections itself and returns several
    blocks per page.
    Sectioned isolation would then discard that valid content as a false
    `biography_failed` (STU-465), so non-PERSON types use single-shot generation
    which keeps the model's multi-section article as-is.
    """
    generator = (
        _run_generation_sectioned
        if entity.get("type") == "PERSON"
        else _run_generation_for_entity
    )
    return generator(
        entity=entity,
        book_title=book_title,
        model=model,
        timeout=timeout,
        sections=sections,
        max_tokens=max_tokens,
        dry_run=dry_run,
        debug_dir=debug_dir,
        forbidden_names=forbidden_names,
        language=language,
        file_path=file_path,
        grounding=grounding,
        sibling_canonicals=sibling_canonicals,
        book_config=book_config,
        runner=runner,
    )


def _clean_infobox_fields(fields: dict) -> dict:
    """Strip Markdown list prefixes from keys and remove internal artifact keys."""
    cleaned: dict[str, str] = {}
    for raw_key, value in fields.items():
        key = str(raw_key).lstrip("- *").strip()
        key = _normalize_infobox_key(key)
        if not key or key in _INTERNAL_INFOBOX_KEYS:
            continue
        cleaned[key] = value
    return cleaned


def _normalize_infobox_key(key: str) -> str:
    key = key.strip().lower()
    key = re.sub(r"\s+", "_", key)
    return key


def _extract_infobox_fields_from_content(content: str) -> dict[str, str]:
    lines = content.splitlines()
    start_idx = None
    for idx, line in enumerate(lines):
        if re.match(r"^##\s+infobox\s*$", line.strip(), flags=re.IGNORECASE):
            start_idx = idx + 1
            break

    if start_idx is None:
        return {}

    fields: dict[str, str] = {}
    for line in lines[start_idx:]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            break

        if stripped.startswith("- ") or stripped.startswith("* ") or stripped.startswith("+ "):
            stripped = stripped[2:].strip()

        if ":" not in stripped:
            continue

        raw_key, raw_value = stripped.split(":", 1)
        key = _normalize_infobox_key(raw_key)
        value = raw_value.strip()
        if key and value:
            fields[key] = value

    return fields


def parse_response(raw: str, entity: dict, lang: str = "fr") -> dict:
    raw = raw.strip()
    decoder = json.JSONDecoder()
    page = None
    for i, ch in enumerate(raw):
        if ch != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(raw[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            page = candidate
            break
    try:
        if page is None:
            raise json.JSONDecodeError("No JSON object found", raw, 0)
        # STU-319: the batch entity is the source of truth for identity. The
        # LLM only echoes these fields back and sometimes mangles them
        # (e.g. Philippa -> Philippe), which breaks the batch -> page mapping.
        # Force them from the entity rather than trusting the LLM's echo.
        page["title"] = entity["canonical_name"]
        page["importance"] = entity["importance"]
        page["entity_type"] = entity["type"]
        page["books"] = list(entity.get("books") or [])
        page.setdefault("infobox_fields", {})
        page.setdefault("content", "")
        if not _is_page_complete(page):
            print(f"    [WARN] Empty content for {entity['canonical_name']}, using failed stub", file=sys.stderr)
            return make_stub_page(entity, failed=True, lang=lang)
        if not page["infobox_fields"] and page["content"]:
            page["infobox_fields"] = _extract_infobox_fields_from_content(page["content"])
        page["infobox_fields"] = _clean_infobox_fields(page["infobox_fields"])
        if _contains_template_placeholder(page, lang):
            print(
                f"    [WARN] Placeholder/template leak for {entity['canonical_name']}, using failed stub",
                file=sys.stderr,
            )
            return make_stub_page(entity, failed=True, lang=lang)
        content_len = len(page["content"].strip())
        if content_len < _MIN_CONTENT_CHARS_WARNING:
            print(
                f"    [WARN] Very short content for {entity['canonical_name']} ({content_len} chars) — check the LLM output",
                file=sys.stderr,
            )
        return {k: v for k, v in page.items() if k in _KNOWN_PAGE_KEYS}
    except json.JSONDecodeError:
        print(f"    [WARN] JSON parse failed for {entity['canonical_name']}, using stub", file=sys.stderr)
        return make_stub_page(entity, lang=lang)


def load_batch_files(
    wiki_inputs_dir: str,
    importance_filter: list[str] | None,
    entity_filter: list[str] | None = None,
) -> list[tuple[str, dict]]:
    """Load all batch files from wiki_inputs_dir, optionally filtering by
    importance and/or canonical_name (case-insensitive). Both filters are ANDed."""
    if not os.path.isdir(wiki_inputs_dir):
        print(f"[ERROR] {wiki_inputs_dir}/ not found. Run wiki-preparation first.", file=sys.stderr)
        sys.exit(1)

    names = {n.strip().lower() for n in entity_filter} if entity_filter else None
    batch_files = sorted(f for f in os.listdir(wiki_inputs_dir) if f.endswith(".json"))
    result = []
    for fname in batch_files:
        path = os.path.join(wiki_inputs_dir, fname)
        with open(path, encoding="utf-8") as f:
            batch = json.load(f)
        entities = batch.get("entities", [])
        if importance_filter:
            entities = [e for e in entities if e.get("importance") in importance_filter]
        if names is not None:
            entities = [e for e in entities if e.get("canonical_name", "").strip().lower() in names]
        batch["entities"] = entities
        if entities:
            result.append((path, batch))
    return result


def load_book_title(epub_data_path: str) -> str:
    """Try to load book title from epub_data.json."""
    try:
        with open(epub_data_path, encoding="utf-8") as f:
            data = json.load(f)
            return data.get("title", "the novel")
    except Exception:
        return "the novel"


def load_book_config(book_yaml_path: str) -> dict:
    try:
        with open(book_yaml_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def generation_profile(config: dict, importance: str, entity_type: str | None = None) -> tuple[list[str], int]:
    profile = config.get(importance, {})

    resolved = resolve_template(entity_type, importance, {"generation": config})
    sections = resolved.section_tokens()
    if not sections:  # unknown/None type → keep the legacy default
        sections = _DEFAULT_SECTIONS_BY_IMPORTANCE.get(
            importance, _DEFAULT_SECTIONS_BY_IMPORTANCE["figurant"]
        )
    stance = editorial_stance({"generation": config})
    sections = [s for s in sections if stance.allows_section(s)]

    max_tokens = profile.get("max_tokens_per_page", DEFAULT_NUM_PREDICT)
    try:
        max_tokens = int(max_tokens)
    except (TypeError, ValueError):
        max_tokens = DEFAULT_NUM_PREDICT
    if max_tokens < 64:
        max_tokens = 64
    return sections, max_tokens


def _adjust_relationship_section(sections: list[str], entity: dict) -> list[str]:
    """Gate the relationships section on the entity's usable relations (STU-628).

    A relationships section with no data to ground it lets the writer fill the
    vacuum from training memory (Alice: 8 pages of invented Mad Hatter / Cheshire
    relations over 0 real relationship data). So drop it when the entity has no
    usable-typed relation (STU-501 filter); add it for a PERSON with 3+."""
    usable_rels = [
        r for r in (entity.get("relationships") or [])
        if usable_relationship_type(r.get("relationship_type"))
    ]
    if not usable_rels:
        return [s for s in sections if s != "relationships"]
    if (
        entity.get("type") == "PERSON"
        and len(usable_rels) >= 3
        and "relationships" not in sections
    ):
        return list(sections) + ["relationships"]
    return list(sections)


@dataclass
class GenerationConfig:
    """Run-constant inputs to generate_pages(). Per-entity values (sections,
    max_tokens, sibling_canonicals) are derived inside the loop."""
    book_title: str
    generation_cfg: dict
    output_file: str
    debug_dir: Path
    model: str = "qwen2.5"
    timeout: int = 120
    dry_run: bool = False
    forbidden_names: list[str] = field(default_factory=list)
    language: str = "fr"
    file_path: str = ""
    grounding: dict = field(default_factory=dict)
    book_config: dict | None = None
    identity_registry: Registry | None = None
    force: bool = False


_AGENTS_DIR = PROJECT_ROOT / ".studio" / "agents"


def _page_prompt_fingerprint(config: GenerationConfig) -> str:
    """Fingerprint the prompt + config every page in the artifact was generated under.

    The resume state is the output artifact itself, keyed per page title — so before
    STU-589 an edited page prompt or a changed generation profile (sections, lengths,
    editorial stance, language, model, spoiler/grounding config) replayed the stale
    pages silently. A page whose stored fingerprint no longer matches is regenerated
    rather than resumed (the per-entity context is the item input and re-keys itself).
    """
    return studio_io.prompt_fingerprint(
        agents=[
            _AGENTS_DIR / "wiki-page-item.agent.yaml",
            _AGENTS_DIR / "wiki-page-validator.agent.yaml",
        ],
        config={
            "generation": config.generation_cfg,
            "language": config.language,
            "model": config.model,
            "forbidden_names": config.forbidden_names,
            "grounding": config.grounding,
        },
    )


def generate_pages(
    batches: list[tuple[str, dict]],
    config: GenerationConfig,
    runner: StudioRunner | None = None,
) -> list[dict]:
    """Generate a wiki page for every entity across `batches`, saving to
    config.output_file after each page (so an interrupted run resumes), and
    return the full page list. All Studio interaction goes through `runner`,
    so this is exercisable with a fake runner and no subprocess."""
    runner = runner or StudioRunner()
    _reset_safety_net_telemetry()

    fingerprint = _page_prompt_fingerprint(config)

    # Resume: keep already-generated complete pages, regenerate failed/empty.
    # STU-589: a page produced under a different prompt/config (stale fingerprint)
    # is dropped only when this run would regenerate it — i.e. its entity is in the
    # current (possibly filtered) batches. Pages outside the filter ride through
    # verbatim, honoring the targeted-regeneration contract; a full run refreshes
    # every stale page.
    regenerable = {
        e.get("canonical_name", "")
        for _, batch in batches
        for e in batch.get("entities", [])
    }
    all_pages = [
        p for p in _load_existing(config.output_file)
        if not p.get("_failed") and not p.get("_dry_run") and _is_page_complete(p)
        and not (p.get("title") in regenerable and p.get("_prompt") != fingerprint)
    ]

    def _commit(page: dict) -> None:
        # A dry run is a preview, not a result: leaving the stub unstamped
        # (_prompt None != fingerprint) makes the resume filter evict it on the
        # next real run instead of skipping the entity as already done (STU-618).
        if not config.dry_run:
            page["_prompt"] = fingerprint
        all_pages.append(page)
        _save(all_pages, config.output_file)

    # --force: evict ONLY the targeted entities (those present in the filtered
    # batches) so they regenerate; every other existing page rides through
    # untouched and is re-saved verbatim.
    if config.force:
        targets = {
            e.get("canonical_name", "")
            for _, batch in batches
            for e in batch.get("entities", [])
        }
        evicted = sorted(p["title"] for p in all_pages if p["title"] in targets)
        all_pages = [p for p in all_pages if p["title"] not in targets]
        if evicted:
            print(f"[generate-wiki-pages] Force — regenerating {len(evicted)} existing page(s): {evicted}", file=sys.stderr)

    done_titles = {p["title"] for p in all_pages}
    if done_titles:
        print(f"[generate-wiki-pages] Resuming — {len(done_titles)} pages already done", file=sys.stderr)

    try:
        for path, batch in batches:
            batch_id = batch.get("batch_id", os.path.basename(path))
            entities = batch.get("entities", [])
            if config.identity_registry is not None:
                for e in entities:
                    config.identity_registry.bind_identity(e)
            print(f"\n[{batch_id}] {len(entities)} entities", file=sys.stderr)
            batch_canonicals = {
                e.get("canonical_name", "") for e in entities if e.get("canonical_name")
            }

            for entity in entities:
                name = entity.get("canonical_name", "?")
                importance = entity.get("importance", "figurant")
                context = entity.get("context_by_chapter", {})

                if name in done_titles:
                    print(f"  [SKIP] {name} (already done)", file=sys.stderr)
                    continue

                if not context:
                    print(f"  [STUB] {name} (no context)", file=sys.stderr)
                    page = make_stub_page(entity, lang=config.language)
                    _commit(page)
                    done_titles.add(name)
                    continue

                if config.dry_run:
                    print(f"  [DRY]  {name}", file=sys.stderr)
                    page = make_stub_page(entity, lang=config.language)
                    page["_dry_run"] = True
                    _commit(page)
                    done_titles.add(name)
                    continue

                print(f"  [GEN]  {name} ({importance})", file=sys.stderr, end="", flush=True)
                try:
                    sections, max_tokens = generation_profile(config.generation_cfg, importance, entity.get("type"))
                    sections = _adjust_relationship_section(sections, entity)
                    page = _run_generation(
                        entity=entity,
                        book_title=config.book_title,
                        model=config.model,
                        timeout=config.timeout,
                        sections=sections,
                        max_tokens=max_tokens,
                        dry_run=config.dry_run,
                        debug_dir=config.debug_dir,
                        forbidden_names=config.forbidden_names,
                        language=config.language,
                        file_path=config.file_path,
                        grounding=config.grounding,
                        sibling_canonicals=batch_canonicals - {name},
                        book_config=config.book_config,
                        runner=runner,
                    )
                    _commit(page)
                    if not page.get("_failed"):
                        done_titles.add(name)
                        print(" ✓", file=sys.stderr)
                    else:
                        print(" ⚠ fallback stub", file=sys.stderr)
                except Exception as e:
                    print(f" ✗ {e}", file=sys.stderr)
                    page = make_stub_page(entity, failed=True, lang=config.language)
                    _commit(page)
                    # Do NOT add to done_titles — will be retried on next run
    except KeyboardInterrupt:
        print(f"\n[generate-wiki-pages] Interrupted — {len(all_pages)} pages saved", file=sys.stderr)

    _save(all_pages, config.output_file)
    return all_pages


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--book",
        help="Path to book yaml, e.g. library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml "
             "(standalone mode)",
    )
    parser.add_argument("--model", default=os.environ.get("WIKI_MODEL", "qwen2.5"), help="Ollama model")
    parser.add_argument("--timeout", type=int, default=120, help="Timeout per entity (seconds)")
    parser.add_argument("--importance", nargs="+", choices=["principal", "secondary", "figurant"],
                        help="Only process entities of these importance levels")
    parser.add_argument("--entities", nargs="+",
                        help="Only process entities with these canonical names (case-insensitive)")
    parser.add_argument("--force", action="store_true",
                        help="Regenerate targeted entities even if already done "
                             "(requires --entities and/or --importance)")
    parser.add_argument("--dry-run", action="store_true", help="Skip LLM calls, output stubs only")
    args, _ = parser.parse_known_args()

    if args.force and not (args.entities or args.importance):
        parser.error("--force requires --entities and/or --importance "
                     "(refuse to force-regenerate the whole book)")

    if args.book:
        book_paths = book_paths_from_yaml(args.book)
        book_cfg = load_book_config(args.book)
        pages = run(
            book_cfg, book_paths,
            model=args.model, timeout=args.timeout, importance=args.importance,
            entities=args.entities, force=args.force, dry_run=args.dry_run,
        )
    else:
        # Studio post stage (STU-621): the two `call: wiki-pages` stages already
        # ran the fan-outs; rebuild both passes and run the final replay walk.
        # Always a full, unfiltered run — the subset axes are dev tools (--book).
        payload = studio_io.read_payload()
        book_cfg = yaml.safe_load(payload.get("additional_context", "") or "") or {}
        book_paths = studio_io.paths_from_payload(payload)
        pages = post_generation(
            book_cfg, book_paths,
            _map_output_from_payload(payload, VERDICT_STAGE),
            _map_output_from_payload(payload, RETRY_VERDICT_STAGE),
        )
        failed = sum(1 for p in pages if p.get("_failed"))
        studio_io.write_output({"pages": len(pages), "failed": failed})


def _prepare_generation(
    book_cfg: dict,
    book_paths,
    *,
    model: str,
    timeout: int,
    importance: list[str] | None = None,
    entities: list[str] | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> tuple[GenerationConfig | None, list[tuple[str, dict]]]:
    """Build the generation config + batches shared by `--book`, plan, probe and
    post (STU-621). Returns `(None, [])` on the terminal no-batches cases (having
    already written the empty artifact for an unfiltered run)."""
    validation_cfg = book_cfg.get("validation", {})
    forbidden_names = validation_cfg.get("forbidden_names", [])
    if forbidden_names:
        print(f"[generate-wiki-pages] Forbidden names active: {forbidden_names}", file=sys.stderr)
    grounding_cfg = validation_cfg.get("grounding", {}) or {}
    if grounding_cfg.get("llm"):
        print(
            f"[generate-wiki-pages] LLM grounding active "
            f"(model: {grounding_cfg.get('llm_model', 'mistral:7b-instruct')})",
            file=sys.stderr,
        )

    # STU-443 (pas 4): generation's identity binding consults the registry, the
    # single source of truth, instead of trusting the identity carried by the
    # batch artifact. None → registry absent, keep the batch identity as-is.
    identity_registry = Registry.load_from_processing(book_paths.processing)
    if identity_registry is None:
        print("[generate-wiki-pages] registry.json not found — identity from batch artifact", file=sys.stderr)

    batches = load_batch_files(str(book_paths.wiki_inputs), importance, entities)
    if not batches:
        # A filtered run that matches nothing must NOT wipe the existing file —
        # exit without saving. Only the unfiltered "no batches at all" case
        # writes an empty result (fresh/empty book).
        if importance or entities:
            print("[generate-wiki-pages] Filter matched zero entities — nothing to do, "
                  "existing pages left untouched.", file=sys.stderr)
            return None, []
        print("[WARN] No batch files found or all batches empty.", file=sys.stderr)
        _save([], str(book_paths.processing / "wiki_pages.json"))
        return None, []

    total_entities = sum(len(b["entities"]) for _, b in batches)
    print(f"[generate-wiki-pages] {total_entities} entities across {len(batches)} batches | model={model}", file=sys.stderr)

    config = GenerationConfig(
        book_title=load_book_title(str(book_paths.processing / "epub_data.json")),
        generation_cfg=book_cfg.get("generation", {}),
        output_file=str(book_paths.processing / "wiki_pages.json"),
        debug_dir=book_paths.processing / "wiki_page_item_debug",
        model=model,
        timeout=timeout,
        dry_run=dry_run,
        forbidden_names=forbidden_names,
        language=output_language(book_cfg),
        file_path=book_cfg.get("file_path", ""),
        grounding=grounding_cfg,
        book_config=book_cfg,
        identity_registry=identity_registry,
        force=force,
    )
    return config, batches


def run(
    book_cfg: dict,
    book_paths,
    *,
    model: str,
    timeout: int,
    importance: list[str] | None = None,
    entities: list[str] | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> list[dict]:
    """Standalone (`--book`) path: the plan/fan-out/replay walk with the two
    fan-outs shelled as nested `studio run` subprocesses (`generate_pages_fanout`)."""
    config, batches = _prepare_generation(
        book_cfg, book_paths, model=model, timeout=timeout,
        importance=importance, entities=entities, force=force, dry_run=dry_run,
    )
    if config is None:
        return []
    pages = generate_pages_fanout(batches, config)
    _print_generation_summary(pages)
    _write_identity_telemetry(book_paths.processing)
    return pages


def _print_generation_summary(pages: list[dict], file=None) -> None:
    """Print a final summary of generation results to stderr."""
    if file is None:
        file = sys.stderr
    failed = [p for p in pages if p.get("_failed")]
    insufficient = [p for p in pages if p.get("_insufficient_data")]
    succeeded = len(pages) - len(failed) - len(insufficient)
    print(
        f"\n[generate-wiki-pages] Done — {len(pages)} total, {succeeded} succeeded, "
        f"{len(failed)} failed, {len(insufficient)} insufficient data",
        file=file,
    )
    for p in failed:
        print(f"  [FAILED] {p.get('title', '?')}", file=file)
    for p in insufficient:
        print(f"  [INSUFFICIENT DATA] {p.get('title', '?')}", file=file)
    print(
        f"[generate-wiki-pages] identity safety nets — force_identity: "
        f"{_SAFETY_NET_TRIGGERS.get('force_identity', 0)}, identity_recovery: "
        f"{_SAFETY_NET_TRIGGERS.get('identity_recovery', 0)} (0/0 ⇒ removable, spec §3.5 step 4)",
        file=file,
    )


def _write_identity_telemetry(processing_dir: Path) -> None:
    """Durable per-run record of identity safety-net triggers. The milestone M1
    exit criterion ('the STU-318/319 safety nets no longer trigger') is checked
    by reading these across consecutive validation runs (spec §3.5 step 4)."""
    path = processing_dir / "identity_telemetry.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"safety_net_triggers": dict(_SAFETY_NET_TRIGGERS)}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def _save(pages: list[dict], output_file: str) -> None:
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    validated = studio_io.to_dict([WikiPage(**p) for p in pages])
    studio_io.from_dict(list[WikiPage], validated)  # self-check: never write off-schema
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({"pages": validated}, f, ensure_ascii=False, indent=2)


def _load_existing(output_file: str) -> list[dict]:
    # Intentionally unvalidated: this is the resume-on-crash reader for the
    # incremental generation loop below (needs to tolerate a partial/legacy
    # file on disk) — matches chapter_summary.py's
    # _load_existing_chapter_summaries precedent. _save() above re-validates
    # on every write, so a corrupt entry never survives past the next save.
    if os.path.exists(output_file):
        try:
            with open(output_file, encoding="utf-8") as f:
                return json.load(f).get("pages", [])
        except Exception:
            pass
    return []


def _is_page_complete(page: dict) -> bool:
    content = page.get("content", "")
    return isinstance(content, str) and bool(content.strip())


def _contains_template_placeholder(page: dict, lang: str = "fr") -> bool:
    """Reject responses that leak prompt placeholders into final content."""
    patterns = _placeholder_patterns(lang)
    content = str(page.get("content", "") or "")
    for pattern in patterns:
        if pattern.search(content):
            return True
    infobox = page.get("infobox_fields", {}) or {}
    for value in infobox.values():
        text = str(value or "")
        for pattern in patterns:
            if pattern.search(text):
                return True
    return False


if __name__ == "__main__":
    main()
