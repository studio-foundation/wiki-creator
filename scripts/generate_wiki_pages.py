#!/usr/bin/env python3
"""
Standalone pre-processing script: generate wiki pages via Ollama.

Run this BEFORE the wiki-generation Studio pipeline.
Results are saved to <book processing dir>/wiki_pages.json and loaded
by load_wiki_pages.py inside the pipeline.

Usage:
    python scripts/generate_wiki_pages.py --book library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml
    python scripts/generate_wiki_pages.py --book library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml --model llama3:8b
    python scripts/generate_wiki_pages.py --book library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml --importance principal secondary
    python scripts/generate_wiki_pages.py --book library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml --dry-run
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
from wiki_creator.lang import book_language
from wiki_creator.page_templates import resolve_template
from wiki_creator.paths import book_paths_from_yaml
from wiki_creator import studio_io
from wiki_creator.registry import Registry, normalize_name

DEFAULT_NUM_PREDICT = 1024

_DEFAULT_SECTIONS_BY_IMPORTANCE = {
    "principal": ["infobox", "biography", "personality", "physical", "powers", "relationships", "trivia", "references"],
    "secondary": ["infobox", "biography", "relationships", "references"],
    "figurant": ["infobox", "biography"],
}
_SECTION_TITLES = {
    "infobox": "Infobox",
    "biography": "Biographie",
    "personality": "Personnalité",
    "physical": "Description physique",
    "powers": "Pouvoirs",
    "relationships": "Relations",
    "trivia": "Anecdotes",
    "references": "Références",
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

_PLACEHOLDER_PATTERNS = (
    re.compile(r"<[^>\n]{1,80}>"),
    re.compile(r"\bsi connu\b", re.IGNORECASE),
    re.compile(r"contenu en fran[çc]ais bas[ée] uniquement sur les extraits", re.IGNORECASE),
)


def _content_template_for_sections(sections: list[str]) -> str:
    blocks = []
    for section in sections:
        title = _SECTION_TITLES.get(section, section.replace("_", " ").title())
        if section == "infobox":
            blocks.append(
                f"## {title}\\n\\n"
                "- Nom: Inconnu\\n"
                "- Rôle: Inconnu\\n"
                "- Affiliation: Inconnue"
            )
        else:
            blocks.append(f"## {title}\\n\\nInformations non disponibles dans les extraits fournis.")
    return "\\n\\n".join(blocks)


def _assemble_section_blocks(blocks: list[str]) -> str:
    """Join non-empty section markdown blocks with a blank line."""
    return "\n\n".join(b.strip() for b in blocks if b and b.strip())


def _references_block(book_title: str) -> str:
    """Deterministic References section — lists only the book title (no LLM)."""
    return f"## {_SECTION_TITLES['references']}\n\n- {book_title}"


def _isolate_section(content: str, section: str) -> str | None:
    """Return only the requested section's markdown block from a single-section
    generation, dropping any leaked foreign blocks (e.g. a ## Infobox echoed from
    the few-shot). If the model returned just the body with no heading, wrap it
    under the section's title. Returns None if nothing usable remains."""
    title = _SECTION_TITLES.get(section, section.replace("_", " ").title())
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
    non_infobox = [blk for norm, blk in blocks if norm != _SECTION_TITLES["infobox"].lower()]
    if len(non_infobox) == 1:
        return non_infobox[0]
    return None


FEW_SHOT_EXAMPLE = {
    "title": "John Doe",
    "importance": "principal",
    "entity_type": "PERSON",
    "infobox_fields": {
        "nom": "John Doe",
        "nom complet": "Jonathan Aldric Doe",
        "alias": "Le Fantôme, Jay",
        "rôle": "Espion de la Couronne, ancien soldat",
        "affiliation": "La Guilde des Ombres (ancienne), Couronne d'Arenell",
        "statut": "Actif",
    },
    "content": (
        "## Infobox\n\n"
        "- Nom: John Doe\n"
        "- Nom complet: Jonathan Aldric Doe\n"
        "- Alias: Le Fantôme, Jay\n"
        "- Rôle: Espion de la Couronne, ancien soldat\n"
        "- Affiliation: La Guilde des Ombres (ancienne), Couronne d'Arenell\n"
        "- Statut: Actif\n\n"
        "## Biographie\n\n"
        "John Doe, né Jonathan Aldric Doe, est un espion au service de la Couronne d'Arenell. "
        "Ancien soldat reconverti après la chute de la forteresse de Veldrath, il opère sous le pseudonyme "
        "**Le Fantôme** dans les cercles criminels de la capitale. Sa double identité — homme de cour le jour, "
        "informateur la nuit — lui permet d'infiltrer des réseaux que les services officiels du roi ne peuvent atteindre.\n\n"
        "Après la trahison de son ancien commandant lors du siège de Veldrath, Doe a rompu avec l'armée régulière "
        "et disparu pendant trois ans. Il réapparaît à Arenell sous une fausse identité marchande, avant d'être "
        "recruté par la conseillère Mira Vayne pour des missions que le Conseil préfère nier.\n\n"
        "## Personnalité\n\n"
        "Doe est méthodique et difficile à lire. Il parle peu, observe beaucoup, et donne rarement son opinion "
        "sans qu'on la lui demande. Ceux qui le côtoient décrivent une loyauté sélective : il honore ses engagements "
        "à la lettre, mais ne s'investit pas au-delà de ce qui a été convenu. Sous cette froideur calculée affleure "
        "parfois un humour sec, surtout dans les situations les plus tendues.\n\n"
        "Son rapport à la violence est pragmatique — ni enthousiaste ni réticent. Il considère les moyens selon "
        "leur efficacité, ce qui le met régulièrement en friction avec les idéalistes de son entourage.\n\n"
        "## Description physique\n\n"
        "Grand, brun, avec une cicatrice linéaire qui part du coin de l'œil gauche jusqu'à la mâchoire — "
        "séquelle d'un interrogatoire à Veldrath. Il s'habille de façon à ne pas attirer l'attention : teintes "
        "sombres, coupes fonctionnelles, aucun bijou. Seul détail invariable : une chevalière en argent terne "
        "à l'annulaire droit, dont l'origine n'est jamais expliquée.\n\n"
        "## Pouvoirs et compétences\n\n"
        "Doe ne possède aucune magie. Ses compétences sont entièrement acquises : infiltration, déguisement, "
        "combat rapproché, et une mémoire quasi photographique des visages et des plans d'architecture. "
        "Il parle couramment quatre langues, dont le dialecte du Sud qu'il utilise pour ses couvertures marchandes.\n\n"
        "## Relations\n\n"
        "**[[Mira Vayne]]** — mentor/protégé. Sa recruteuse et supérieure directe ; "
        "leur relation est professionnelle, teintée d'une méfiance mutuelle que ni l'un ni l'autre ne cherche vraiment à dissoudre.\n\n"
        "**[[Lira]]** — allié. Une informante de la Guilde des Ombres avec qui Doe a partagé une mission à Veldrath.\n\n"
        "**[[Le Commandant Arek]]** — antagoniste. L'ancien supérieur dont la trahison à Veldrath a redéfini la trajectoire de Doe.\n\n"
        "## Anecdotes\n\n"
        "- Le surnom \"Le Fantôme\" lui a été donné par les membres de la Guilde, non par ses alliés de la Couronne.\n"
        "- Sa couverture marchande implique un commerce de tissus importés du Sud — un choix qui justifie "
        "ses déplacements fréquents entre les provinces."
    ),
}

# Définitions des sections par entity_type
SECTION_DEFINITIONS = {
    "PERSON": {
        "Infobox": "Champs factuels clés : nom, alias, rôle, affiliation, statut. Omets les champs inconnus.",
        "Biographie": "Qui est ce personnage et quel est son rôle dans le monde. Les événements servent de contexte, pas de liste chronologique.",
        "Personnalité": "Traits observés avec ancrage textuel. Évite les adjectifs génériques sans preuve. Montre les contradictions ou tensions internes si elles existent.",
        "Description physique": "Détails physiques confirmés par le texte uniquement. Concis.",
        "Pouvoirs": "Capacités ou compétences distinctives. Si aucun pouvoir magique, décris les compétences pratiques.",
        "Relations": "Une entrée en gras par relation significative, suivie d'une description de la nature du lien. Format: **Nom** — description.",
        "Anecdotes": "Faits spécifiques et concrets qui ne rentrent pas dans les autres sections. Pas de re-résumé de la biographie.",
    },
    "PLACE": {
        "Infobox": "Nom, type de lieu, région/pays, statut (actif, ruiné, etc.). Omets les champs inconnus.",
        "Description": "Ce qu'est ce lieu, où il se trouve, à quoi il ressemble d'après les extraits.",
        "Histoire": "Événements passés liés à ce lieu mentionnés dans le texte.",
        "Habitants et factions": "Groupes ou personnages associés à ce lieu.",
        "Anecdotes": "Détails spécifiques qui ne rentrent pas ailleurs.",
    },
    "ORG": {
        "Infobox": "Nom, type d'organisation, affiliation, statut. Omets les champs inconnus.",
        "Description": "Ce qu'est cette organisation, son rôle et ses objectifs d'après les extraits.",
        "Membres notables": "Personnages affiliés mentionnés dans le texte.",
        "Histoire": "Événements impliquant cette organisation.",
        "Anecdotes": "Détails spécifiques qui ne rentrent pas ailleurs.",
    },
    "EVENT": {
        "Infobox": "Nom, type d'événement, lieu, période si mentionnée. Omets les champs inconnus.",
        "Description": "Ce qu'est cet événement et son importance dans le récit.",
        "Déroulement": "Ce qui se passe lors de cet événement d'après les extraits.",
        "Participants": "Personnages impliqués.",
        "Anecdotes": "Détails spécifiques qui ne rentrent pas ailleurs.",
    },
}

def _label_chapter_key(key: str) -> str:
    """Convert EPUB file IDs like C25.xhtml to readable labels like Chapter 25."""
    m = re.match(r'^[Cc](\d+)\.xhtml$', key)
    return f"Chapter {int(m.group(1))}" if m else key


# STU-438: how many top relations (already sorted by cooccurrence desc) get
# evidence/key_moments/context sub-lines in the prompt, per page importance.
_RELATIONSHIP_ENRICHMENT_BUDGET = {"principal": 5, "secondary": 3, "figurant": 0}
_MAX_KEY_MOMENTS_PER_RELATION = 2
_SAMPLE_CONTEXT_MAX_CHARS = 200
# Kept in sync with .studio/agents/relationship-classifier.agent.yaml: the
# classifier returns this exact string when no key moment could be identified.
_KEY_MOMENT_SENTINEL = "no specific moment identifiable in provided excerpts"


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


def build_prompt(entity: dict, book_title: str, sections: list[str], forbidden_names: list[str] | None = None) -> str:
    name = entity["canonical_name"]
    etype = entity["type"]
    importance = entity["importance"]
    aliases = entity.get("aliases", [])
    context = entity.get("context_by_chapter", {})
    related_context = entity.get("related_context", [])
    chapter_summary_context = entity.get("chapter_summary_context", [])

    # --- Blocs de contexte ---
    context_lines = []
    for chapter, mentions in list(context.items())[:15]:
        label = _label_chapter_key(chapter)
        for mention in mentions[:3]:
            context_lines.append(f"  [{label}] {mention}")
    context_block = "\n".join(context_lines) if context_lines else "  (no excerpts available)"

    related_lines = []
    for rel in related_context[:5]:
        related_name = rel.get("related_name", "").strip()
        if not related_name:
            continue
        related_type = rel.get("related_type") or "unknown"
        related_importance = rel.get("related_importance") or "unknown"
        cooccurrence = rel.get("cooccurrence_count", 0)
        related_lines.append(
            f"  - Name: {related_name} | Type: {related_type} | Importance: {related_importance} | Cooccurrence count: {cooccurrence}"
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
        rtype = r.get("relationship_type") or "co-occurrence fréquente"
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
    chapter_summary_block = present_block + ("\n\n" + backstory_block if backstory_block else "")

    # --- Paramètres de génération ---
    alias_str = ", ".join(a for a in aliases if a != name) or "none"

    length_guide = {
        "principal": "4 to 6 paragraphs total across all sections.",
        "secondary": "1 to 2 paragraphs for the main section. Keep all other sections brief.",
        "figurant": "1 short paragraph only. Use only the most relevant section.",
    }.get(importance, "1 short paragraph only.")

    sections_str = ", ".join(sections)

    # Définitions des sections pour ce type d'entité
    section_defs = SECTION_DEFINITIONS.get(etype, SECTION_DEFINITIONS["PERSON"])
    section_def_lines = "\n".join(
        f"  - {sec}: {desc}"
        for sec, desc in section_defs.items()
        if sec in sections
    )

    # Few-shot example serialisé
    few_shot_json = json.dumps(FEW_SHOT_EXAMPLE, ensure_ascii=False, indent=2)

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

    has_typed_rels = bool(relationships_block)
    rels_in_sections = "relationships" in sections
    if rels_in_sections and has_typed_rels:
        relations_rule = (
            '- For PERSON entities: ALWAYS include a "## Relations" section when "relationships" is in the sections list AND typed relationships are provided above. Do not skip it.\n'
            '- Each "## Relations" entry must use this format: "**[[related_entity]]** — [relationship_type]. [evolution if available]"\n'
            '- NEVER print cooccurrence_count, a mention count, or "mentions communes" in the output. cooccurrence_count is an internal ranking metric only — it must not appear in reader-facing text.'
        )
        if rels_enriched:
            relations_rule += (
                '\n- Anchor each "## Relations" entry in the evidence quotes, key moments, and contexts provided above: '
                "cite or closely paraphrase these grounded facts instead of paraphrasing the abstract relationship_type. "
                "Do NOT invent moments that are not listed."
            )
    else:
        relations_rule = "- Do NOT include a ## Relations section in the content field. No relationships data is available for this entity."

    return f"""This is a fictional world. The following excerpts are the ONLY authoritative source of truth. Ignore any prior knowledge you have of this book, series, or author.

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
{chapter_summary_block}

---

WRITING RULES (follow strictly):

Tone and register:
- Write in encyclopedic French. Neutral, precise, factual.
- Describe what the entity IS before describing what happens to it.
- When a chapter summary is tagged with a subjective POV, attribute contested claims to that viewpoint ("selon X", "du point de vue de X") rather than stating them as fact.
- Use specific, concrete language. Avoid generic adjectives without textual evidence.
- If aliases exist, introduce them naturally in the biography ("also known as X", "born Y").
- Use ONLY aliases listed in "Known aliases" above. Do NOT infer or invent aliases from context.

Content constraints:
- Every factual claim in your output must be directly supported by one of the GROUNDING EXCERPTS provided above. If you cannot point to a supporting excerpt, do not write the claim.
- Real-world publication dates and author information are strictly forbidden.
- Chapter summaries serve as orientation only. Direct excerpts take priority.
- Do NOT invent plot details, relationships, abilities, or physical traits not supported by excerpts.
- Do NOT turn cooccurrence between entities into narrative causality.
- Confidence markers: each relationship carries a "confidence" tag. State "explicit" relationships as fact (direct affirmation). Phrase "inferred" and "interpretation" relationships tentatively ("semble", "suggère", "pourrait indiquer") — never as established fact. Indirect relationships listed as "inferred: true" are interpretation: mention them only with such hedged phrasing, if at all.
- When referring to related entities or characters, use their name EXACTLY as written in the excerpts or relationships list — do not paraphrase, alter, or approximate names.
- If information is insufficient for a section, omit that section entirely.
- Do NOT write "information not available", "not mentioned in excerpts", or any similar phrase. Omit instead.
- Omit infobox fields entirely if their value is unknown.

Structure:
- Use exactly these sections in this order: {sections_str}.
- Target length: {length_guide}
- The "Infobox" section must use this format: one bullet per field, "- Key: Value".
{relations_rule}
- infobox_fields keys must be plain strings — no leading "- " or "* ". Correct: {{"nom": "X"}}, Wrong: {{"- nom": "X"}}.
- Context labels like [Chapter N] are internal references — never mention them in your output.
- The ## Références section must list ONLY "{book_title}". Do not add any other book, volume, or series title.
- infobox_fields must contain ONLY wiki-relevant fields (name, role, affiliation, etc.). Do NOT include internal data fields such as cooccurrence_count, entity_type, importance, or any metadata.

Section definitions for type {etype}:
{section_def_lines}{forbidden_names_rule}

---

REMINDER: Write ALL content in French. Source excerpts may be in English — your output must always be in French regardless.

Output this JSON object:
{{
  "title": "{name}",
  "importance": "{importance}",
  "entity_type": "{etype}",
  "infobox_fields": {{}},
  "content": "<Markdown string with \\\\n for newlines>"
}}

Output ONLY the JSON. Nothing before, nothing after."""


def _strip_relations_section(content: str) -> str:
    """Remove any ## Relations section from Markdown content.

    Post-processing guard: the LLM may produce a ## Relations section even
    when instructed not to. This strips it deterministically before saving.
    """
    return re.sub(
        r"(?m)^## Relations\s*\n(?:(?!^##\s).*\n?)*",
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


def _batch_bound_value(entity: dict, token: str) -> str | None:
    """Value for a batch-bound infobox token, sourced from the batch entity.
    Returns None for tokens the batch cannot sensibly supply (skipped by the
    binder). `type` is intentionally unsupported: the coarse batch type is
    infobox noise; the specific type is an extracted-fact (slice C)."""
    if token == "nom":
        return entity.get("canonical_name") or None
    if token == "alias":
        aliases = [a for a in (entity.get("aliases") or []) if a]
        return ", ".join(aliases) if aliases else None
    return None


def _extracted_fact_value(entity: dict, token: str) -> str | None:
    """Value for an extracted-fact infobox token, sourced from facts the pipeline
    produced into the batch entity. None when the fact is absent (slot omitted).
    `status`, `affiliation`, and the specific `type` are future slices."""
    if token == "titles":
        titles = [t for t in (entity.get("titles") or []) if t]
        return ", ".join(titles) if titles else None
    return None


def _bind_batch_fields(page: dict, entity: dict, book_config: dict | None) -> None:
    """Overwrite pipeline-sourced infobox tokens with authoritative values, per
    the resolved template: `batch-bound` from the batch identity, `extracted-fact`
    from facts the pipeline produced. `llm-prose` slots are left to the LLM.
    No-op when book_config is None."""
    if book_config is None:
        return
    page.setdefault("infobox_fields", {})
    resolved = resolve_template(entity.get("type"), entity.get("importance"), book_config)
    for slot in resolved.infobox():
        if slot.provenance == "batch-bound":
            value = _batch_bound_value(entity, slot.token)
        elif slot.provenance == "extracted-fact":
            value = _extracted_fact_value(entity, slot.token)
        else:
            continue
        if value:
            page["infobox_fields"][slot.token] = value


# Kept in sync with check_identity_match in scripts/wiki_page_validator.py:
# these are the only validator errors that identity confusion produces.
_IDENTITY_ERROR_MARKERS = ("≠ entité demandée", "ne correspond pas à l'entité")


def _rejection_is_identity_only(run_id: str) -> bool:
    """True iff the validator rejected the run and *every* error it reported is
    an identity error. Guards against smuggling a page past grounding/language
    validators when we recover it."""
    vout = studio_io.load_studio_stage_output(str(run_id), "wiki-page-validator")
    errors = (vout or {}).get("errors") or []
    return bool(errors) and all(
        any(marker in str(e) for marker in _IDENTITY_ERROR_MARKERS) for e in errors
    )


def _recover_identity_rejected_page(
    *, entity: dict, item_result: dict, sibling_canonicals: set[str] | None = None
) -> dict | None:
    """Recover a PERSON page from an identity-only rejected run and force-correct
    its identity fields. Returns the kept page, or None if not recoverable."""
    if entity.get("type") != "PERSON":
        return None
    run_id = str((item_result.get("run_metadata") or {}).get("run_id") or "").strip()
    if not run_id or not _rejection_is_identity_only(run_id):
        return None
    recovered = studio_io.load_studio_stage_output(run_id, "wiki-page-item")
    if not isinstance(recovered, dict):
        return None
    page = parse_response(json.dumps(recovered, ensure_ascii=False), entity)
    if page.get("_failed"):
        return None
    _force_correct_identity(page, entity, sibling_canonicals)
    page["_identity_corrected"] = True
    return page


# STU-465: a technical generation failure and a genuine data famine are
# distinct conditions. Keep their stub content distinct so `_failed` pages are
# not mislabelled with an "insufficient data" message that masks a real failure.
_STUB_CONTENT_FAILED = "## Biographie\n\n*Échec technique de la génération pour cette entité.*"
_STUB_CONTENT_INSUFFICIENT = "## Biographie\n\n*Informations insuffisantes disponibles pour cette entité.*"


def make_stub_page(entity: dict, failed: bool = False, insufficient_data: bool = False) -> dict:
    page = {
        "title": entity["canonical_name"],
        "importance": entity["importance"],
        "entity_type": entity["type"],
        "infobox_fields": {},
        "content": _STUB_CONTENT_FAILED if failed else _STUB_CONTENT_INSUFFICIENT,
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
        "prompt": build_prompt(entity, book_title, sections=sections, forbidden_names=forbidden_names),
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
    )
    return _execute_wiki_page_item(item_input, entity, timeout)


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
    run_id = str((run_payload or {}).get("id") or "").strip()
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

    if run_payload is None:
        return {
            "error": "studio_output_json_parse_error",
            "raw_response": combined_output.strip(),
            "run_metadata": run_metadata,
        }

    if not run_id:
        return {
            "error": "studio_run_missing_id",
            "raw_response": combined_output.strip(),
            "run_metadata": run_metadata,
        }

    payload = studio_io.extract_stage_output_from_run_payload(run_payload, "wiki-page-item")
    if payload is None:
        payload = studio_io.load_studio_stage_output(run_id, "wiki-page-item")
    if payload is None:
        return {
            "error": "studio_run_output_missing",
            "raw_response": combined_output.strip(),
            "run_metadata": run_metadata,
        }

    page = parse_response(json.dumps(payload, ensure_ascii=False), entity)
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
) -> str | None:
    """Generate a single section via a scoped wiki-page-item call. Returns the
    section's content block, or None on error / persistent forbidden-name hit."""

    def _once() -> dict:
        return _run_wiki_page_item(
            entity=entity, book_title=book_title, model=model, timeout=timeout,
            sections=[section], max_tokens=max_tokens, forbidden_names=forbidden_names,
            language=language, file_path=file_path, grounding=grounding,
        )

    result = _once()
    if not isinstance(result, dict) or result.get("error"):
        return None
    content = _isolate_section(result.get("content") or "", section) or ""
    if section == "relationships" and not entity.get("relationships"):
        content = _strip_relations_section(content)
    if forbidden_names and _check_forbidden_names({"content": content, "infobox_fields": {}}, forbidden_names):
        result = _once()
        if not isinstance(result, dict) or result.get("error"):
            return None
        content = _isolate_section(result.get("content") or "", section) or ""
        if section == "relationships" and not entity.get("relationships"):
            content = _strip_relations_section(content)
        if _check_forbidden_names({"content": content, "infobox_fields": {}}, forbidden_names):
            return None
    content = content.strip()
    return content or None


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
) -> dict:
    if not entity.get("context_by_chapter", {}):
        return make_stub_page(entity, insufficient_data=True)
    if dry_run:
        return make_stub_page(entity)

    item_result = _run_wiki_page_item(
        entity=entity,
        book_title=book_title,
        model=model,
        timeout=timeout,
        sections=sections,
        max_tokens=max_tokens,
        forbidden_names=forbidden_names,
        language=language,
        file_path=file_path,
        grounding=grounding,
    )
    if isinstance(item_result, dict) and item_result.get("error"):
        recovered = _recover_identity_rejected_page(
            entity=entity,
            item_result=item_result,
            sibling_canonicals=sibling_canonicals,
        )
        _save_generation_debug_artifact(debug_dir, entity, item_result)
        if recovered is not None:
            _record_safety_net("identity_recovery")
            _bind_batch_fields(recovered, entity, book_config)
            print(" ⚠ identity-corrected from rejected run", file=sys.stderr, end="", flush=True)
            return recovered
        return make_stub_page(entity, failed=True)
    typed_rels = entity.get("relationships", [])
    if isinstance(item_result, dict) and "content" in item_result:
        if "relationships" not in sections or not typed_rels:
            item_result["content"] = _strip_relations_section(item_result["content"] or "")

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
                language=language,
                file_path=file_path,
                grounding=grounding,
            )
            if isinstance(item_result, dict) and item_result.get("error"):
                _save_generation_debug_artifact(debug_dir, entity, item_result)
                return make_stub_page(entity, failed=True)
            if isinstance(item_result, dict) and "content" in item_result:
                if "relationships" not in sections or not typed_rels:
                    item_result["content"] = _strip_relations_section(item_result["content"] or "")
            hits = _check_forbidden_names(item_result, forbidden_names)
            if hits:
                print(f" ✗ spoiler persists ({', '.join(hits)})", file=sys.stderr, end="", flush=True)
                page = make_stub_page(entity, failed=True)
                page["_spoiler_rejected"] = True
                return page

    if (
        entity.get("type") == "PERSON"
        and isinstance(item_result, dict)
        and "content" in item_result
        and _force_correct_identity(item_result, entity, sibling_canonicals)
    ):
        _record_safety_net("force_identity")
        print(" ⚠ nom force-corrected", file=sys.stderr, end="", flush=True)

    if isinstance(item_result, dict) and "content" in item_result:
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
) -> dict:
    if not entity.get("context_by_chapter", {}):
        return make_stub_page(entity, insufficient_data=True)
    if dry_run:
        return make_stub_page(entity)

    content_sections = [s for s in sections if s not in ("infobox", "references")]
    blocks: list[str] = []
    for section in content_sections:
        block = _generate_one_section(
            entity=entity, section=section, book_title=book_title, model=model,
            timeout=timeout, max_tokens=max_tokens, forbidden_names=forbidden_names,
            language=language, file_path=file_path, grounding=grounding,
        )
        if block:
            blocks.append(block)
        elif section == "biography":
            _save_generation_debug_artifact(debug_dir, entity, {"error": "biography_failed"})
            return make_stub_page(entity, failed=True)
        # else: OPT section omitted

    if not blocks:
        return make_stub_page(entity, failed=True)

    if "references" in sections:
        blocks.append(_references_block(book_title))

    page = {
        "title": entity["canonical_name"],
        "importance": entity["importance"],
        "entity_type": entity["type"],
        "infobox_fields": {},
        "content": _assemble_section_blocks(blocks),
    }
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
) -> dict:
    """Route generation by entity type.

    PERSON uses section-scoped prose (slice E): the few-shot trains stable French
    section titles ("Biographie", "Personnalité"…) that `_isolate_section` can
    extract cleanly. PLACE/ORG/EVENT are article-shaped — the model titles them
    itself (Géographie, Histoire, Culture…) and returns several blocks per page.
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


def parse_response(raw: str, entity: dict) -> dict:
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
        page.setdefault("infobox_fields", {})
        page.setdefault("content", "")
        if not _is_page_complete(page):
            print(f"    [WARN] Empty content for {entity['canonical_name']}, using failed stub", file=sys.stderr)
            return make_stub_page(entity, failed=True)
        if not page["infobox_fields"] and page["content"]:
            page["infobox_fields"] = _extract_infobox_fields_from_content(page["content"])
        page["infobox_fields"] = _clean_infobox_fields(page["infobox_fields"])
        if _contains_template_placeholder(page):
            print(
                f"    [WARN] Placeholder/template leak for {entity['canonical_name']}, using failed stub",
                file=sys.stderr,
            )
            return make_stub_page(entity, failed=True)
        content_len = len(page["content"].strip())
        if content_len < _MIN_CONTENT_CHARS_WARNING:
            print(
                f"    [WARN] Contenu très court pour {entity['canonical_name']} ({content_len} chars) — vérifier la sortie LLM",
                file=sys.stderr,
            )
        return page
    except json.JSONDecodeError:
        print(f"    [WARN] JSON parse failed for {entity['canonical_name']}, using stub", file=sys.stderr)
        return make_stub_page(entity)


def load_batch_files(wiki_inputs_dir: str, importance_filter: list[str] | None) -> list[tuple[str, dict]]:
    """Load all batch files from wiki_inputs_dir, optionally filtering by importance."""
    if not os.path.isdir(wiki_inputs_dir):
        print(f"[ERROR] {wiki_inputs_dir}/ not found. Run wiki-preparation first.", file=sys.stderr)
        sys.exit(1)

    batch_files = sorted(f for f in os.listdir(wiki_inputs_dir) if f.endswith(".json"))
    result = []
    for fname in batch_files:
        path = os.path.join(wiki_inputs_dir, fname)
        with open(path, encoding="utf-8") as f:
            batch = json.load(f)
        if importance_filter:
            batch["entities"] = [e for e in batch.get("entities", []) if e.get("importance") in importance_filter]
        if batch.get("entities"):
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

    max_tokens = profile.get("max_tokens_per_page", DEFAULT_NUM_PREDICT)
    try:
        max_tokens = int(max_tokens)
    except (TypeError, ValueError):
        max_tokens = DEFAULT_NUM_PREDICT
    if max_tokens < 64:
        max_tokens = 64
    return sections, max_tokens


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--book", required=True,
        help="Path to book yaml, e.g. library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml",
    )
    parser.add_argument("--model", default=os.environ.get("WIKI_MODEL", "qwen2.5"), help="Ollama model")
    parser.add_argument("--timeout", type=int, default=120, help="Timeout per entity (seconds)")
    parser.add_argument("--importance", nargs="+", choices=["principal", "secondary", "figurant"],
                        help="Only process entities of these importance levels")
    parser.add_argument("--dry-run", action="store_true", help="Skip LLM calls, output stubs only")
    args = parser.parse_args()

    _reset_safety_net_telemetry()
    book_paths = book_paths_from_yaml(args.book)
    output_file = str(book_paths.processing / "wiki_pages.json")
    wiki_inputs_dir = str(book_paths.wiki_inputs)
    book_cfg = load_book_config(args.book)
    generation_cfg = book_cfg.get("generation", {})
    validation_cfg = book_cfg.get("validation", {})
    forbidden_names = validation_cfg.get("forbidden_names", [])
    if forbidden_names:
        print(f"[generate-wiki-pages] Forbidden names active: {forbidden_names}", file=sys.stderr)
    book_lang = book_language(book_cfg)
    book_file_path = book_cfg.get("file_path", "")
    grounding_cfg = validation_cfg.get("grounding", {}) or {}
    if grounding_cfg.get("llm"):
        print(
            f"[generate-wiki-pages] LLM grounding active "
            f"(model: {grounding_cfg.get('llm_model', 'mistral:7b-instruct')})",
            file=sys.stderr,
        )

    book_title = load_book_title(str(book_paths.processing / "epub_data.json"))
    batches = load_batch_files(wiki_inputs_dir, args.importance)

    # STU-443 (pas 4): generation's identity binding consults the registry, the
    # single source of truth, instead of trusting the identity carried by the
    # batch artifact. None → registry absent, keep the batch identity as-is.
    identity_registry = Registry.load_from_processing(book_paths.processing)
    if identity_registry is None:
        print("[generate-wiki-pages] registry.json not found — identity from batch artifact", file=sys.stderr)

    if not batches:
        print("[WARN] No batch files found or all batches empty after filter.", file=sys.stderr)
        _save([], output_file)
        return

    total_entities = sum(len(b["entities"]) for _, b in batches)
    print(f"[generate-wiki-pages] {total_entities} entities across {len(batches)} batches | model={args.model}", file=sys.stderr)

    # Load existing pages to resume interrupted runs
    all_pages = [p for p in _load_existing(output_file) if not p.get("_failed") and _is_page_complete(p)]
    done_titles = {p["title"] for p in all_pages}
    debug_dir = book_paths.processing / "wiki_page_item_debug"
    if done_titles:
        print(f"[generate-wiki-pages] Resuming — {len(done_titles)} pages already done", file=sys.stderr)

    try:
        for path, batch in batches:
            batch_id = batch.get("batch_id", os.path.basename(path))
            entities = batch.get("entities", [])
            if identity_registry is not None:
                for e in entities:
                    identity_registry.bind_identity(e)
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
                    page = make_stub_page(entity)
                    all_pages.append(page)
                    _save(all_pages, output_file)
                    done_titles.add(name)
                    continue

                if args.dry_run:
                    print(f"  [DRY]  {name}", file=sys.stderr)
                    page = make_stub_page(entity)
                    all_pages.append(page)
                    _save(all_pages, output_file)
                    done_titles.add(name)
                    continue

                print(f"  [GEN]  {name} ({importance})", file=sys.stderr, end="", flush=True)
                try:
                    sections, max_tokens = generation_profile(generation_cfg, importance, entity.get("type"))
                    typed_rels = entity.get("relationships", [])
                    if (
                        entity.get("type") == "PERSON"
                        and len(typed_rels) >= 3
                        and "relationships" not in sections
                    ):
                        sections = list(sections) + ["relationships"]
                    page = _run_generation(
                        entity=entity,
                        book_title=book_title,
                        model=args.model,
                        timeout=args.timeout,
                        sections=sections,
                        max_tokens=max_tokens,
                        dry_run=args.dry_run,
                        debug_dir=debug_dir,
                        forbidden_names=forbidden_names,
                        language=book_lang,
                        file_path=book_file_path,
                        grounding=grounding_cfg,
                        sibling_canonicals=batch_canonicals - {name},
                        book_config=book_cfg,
                    )
                    all_pages.append(page)
                    _save(all_pages, output_file)
                    if not page.get("_failed"):
                        done_titles.add(name)
                        print(" ✓", file=sys.stderr)
                    else:
                        print(" ⚠ fallback stub", file=sys.stderr)
                except Exception as e:
                    print(f" ✗ {e}", file=sys.stderr)
                    page = make_stub_page(entity, failed=True)
                    all_pages.append(page)
                    _save(all_pages, output_file)
                    # Do NOT add to done_titles — will be retried on next run
    except KeyboardInterrupt:
        print(f"\n[generate-wiki-pages] Interrupted — {len(all_pages)} pages saved", file=sys.stderr)
    _print_generation_summary(all_pages)
    _write_identity_telemetry(book_paths.processing)


def _print_generation_summary(pages: list[dict], file=None) -> None:
    """Print a final summary of generation results to stderr."""
    if file is None:
        file = sys.stderr
    failed = [p for p in pages if p.get("_failed")]
    insufficient = [p for p in pages if p.get("_insufficient_data")]
    succeeded = len(pages) - len(failed) - len(insufficient)
    print(
        f"\n[generate-wiki-pages] Done — {len(pages)} total, {succeeded} succeeded, "
        f"{len(failed)} failed, {len(insufficient)} données insuffisantes",
        file=file,
    )
    for p in failed:
        print(f"  [FAILED] {p.get('title', '?')}", file=file)
    for p in insufficient:
        print(f"  [INSUFFICIENT DATA] {p.get('title', '?')}", file=file)
    print(
        f"[generate-wiki-pages] identity safety nets — force_identity: "
        f"{_SAFETY_NET_TRIGGERS.get('force_identity', 0)}, identity_recovery: "
        f"{_SAFETY_NET_TRIGGERS.get('identity_recovery', 0)} (0/0 ⇒ retirable, spec §3.5 pas 4)",
        file=file,
    )


def _write_identity_telemetry(processing_dir: Path) -> None:
    """Durable per-run record of identity safety-net triggers. The milestone M1
    exit criterion ('les safety nets STU-318/319 ne se déclenchent plus') is
    checked by reading these across consecutive validation runs (spec §3.5 pas 4)."""
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
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({"pages": pages}, f, ensure_ascii=False, indent=2)


def _load_existing(output_file: str) -> list[dict]:
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


def _contains_template_placeholder(page: dict) -> bool:
    """Reject responses that leak prompt placeholders into final content."""
    content = str(page.get("content", "") or "")
    for pattern in _PLACEHOLDER_PATTERNS:
        if pattern.search(content):
            return True
    infobox = page.get("infobox_fields", {}) or {}
    for value in infobox.values():
        text = str(value or "")
        for pattern in _PLACEHOLDER_PATTERNS:
            if pattern.search(text):
                return True
    return False


if __name__ == "__main__":
    main()
