#!/usr/bin/env python3
"""
Stage: Entity Classification (STU-231)
Computes total_mentions + chapters_present per entity, then assigns importance tiers.

Pipeline position:
  ... → relationship-extraction → **entity-classification** → wiki-generation

Input (via Studio context):
  previous_outputs.relationship-extraction:
    { "entities": [{canonical_name, type, aliases, source_ids, relevant}],
      "relationships": [...], "stats": {...}, "narrator": ... }
  additional_context: YAML string (book.input.yaml) with "thresholds" key
  Files: persons_full.json, places_full.json, orgs_full.json, events_full.json (project root)

Output (stdout):
  {
    "entities": [{ ...same fields..., "total_mentions": int, "chapters_present": int, "importance": str }],
    "relationships": [...passthrough...],
    "stats": { "principal": int, "secondary": int, "figurant": int, "ignored": int, "thresholds_used": str },
    "narrator": ...passthrough...
  }

importance values: "principal" | "secondary" | "figurant" | "ignored"

Standalone test:
  python scripts/entity_classification.py --test
"""

import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

# Ensure project root is importable when running as `python scripts/<file>.py`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from wiki_creator.paths import book_paths_from_epub, BookPaths
from wiki_creator.lang import load_lang_config, infer_language

_VALID_TYPES = {"PERSON", "PLACE", "ORG", "EVENT", "OTHER"}


def _paths_from_payload(payload: dict) -> BookPaths:
    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    file_path = ctx.get("file_path")
    if not file_path:
        raise ValueError("missing file_path in additional_context")
    return book_paths_from_epub(file_path)


# --- Pure functions (testable) ---

def get_total_mentions(
    entity: dict,
    persons_full: dict,
    places_full: dict,
    orgs_full: dict,
    events_full: dict | None = None,
) -> tuple[int, int]:
    """Return (total_mentions, chapters_present) for a resolved entity.

    Aggregates mentions across all source_ids from the matching type registry.
    """
    type_to_registry = {
        "PERSON": persons_full,
        "PLACE": places_full,
        "ORG": orgs_full,
        "EVENT": events_full or {},
    }
    total = 0
    chapters: set[str] = set()
    for sid in entity.get("source_ids", []):
        # Primary lookup by current type, fallback across registries for retagged entities.
        entry = type_to_registry.get(entity.get("type", ""), {}).get(sid, {})
        if not entry:
            for alt in ("PERSON", "PLACE", "ORG", "EVENT"):
                candidate = type_to_registry.get(alt, {}).get(sid, {})
                if candidate:
                    entry = candidate
                    break
        for ch, mentions in entry.get("mentions_by_chapter", {}).items():
            total += len(mentions)
            if mentions:
                chapters.add(ch)
    return total, len(chapters)


MIN_ENTITIES_FOR_AUTO = 4
# Conservative absolute thresholds used when a type has too few entities for
# percentiles to be meaningful (n < MIN_ENTITIES_FOR_AUTO).  Better to
# under-score a rare entity than to award "principal" to a 3-mention place.
_ABSOLUTE_FALLBACK_THRESHOLDS: dict[str, int] = {
    "principal": 20,
    "secondary": 10,
    "figurant": 3,
}


def compute_auto_thresholds(
    mention_counts: list[tuple[str, str, int]],
) -> dict[str, dict[str, int]]:
    """Compute percentile-based importance thresholds per entity type.

    Args:
        mention_counts: list of (canonical_name, type, total_mentions)

    Returns:
        { "PERSON": { "principal": N, "secondary": M, "figurant": K }, ... }
        An entity is "principal" if mentions >= principal threshold, etc.

    When a type has fewer than MIN_ENTITIES_FOR_AUTO entities, percentiles are
    statistically meaningless (e.g. p90 on 2 values == the maximum).  In that
    case _ABSOLUTE_FALLBACK_THRESHOLDS are used instead so a 3-mention entity
    can never be promoted to "principal" purely by being alone in its type.
    """
    by_type: dict[str, list[int]] = defaultdict(list)
    for _, etype, count in mention_counts:
        by_type[etype].append(count)

    thresholds: dict[str, dict[str, int]] = {}
    for etype, counts in by_type.items():
        sorted_counts = sorted(counts)
        n = len(sorted_counts)

        if n < MIN_ENTITIES_FOR_AUTO:
            thresholds[etype] = dict(_ABSOLUTE_FALLBACK_THRESHOLDS)
            continue

        def percentile(p: float, _sorted=sorted_counts, _n=n) -> int:
            if _n == 0:
                return 0
            idx = max(0, int(_n * p) - 1)
            return _sorted[min(idx, _n - 1)]

        thresholds[etype] = {
            "principal": percentile(0.90),   # top 10%
            "secondary": percentile(0.60),   # 10-40%
            "figurant": percentile(0.10),    # 40-90%
            # below p10 → ignored
        }
    return thresholds


def assign_importance(
    entity_type: str,
    total_mentions: int,
    chapters_present: int,  # available for future min_chapters threshold support
    thresholds: dict[str, dict[str, int]],
) -> str:
    """Assign importance tier based on thresholds dict.

    thresholds shape: { "PERSON": { "principal": N, "secondary": M, "figurant": K } }
    Falls back to "figurant" for unknown types (conservative: generate a short page).
    """
    t = thresholds.get(entity_type)
    if not t:
        return "figurant"

    if total_mentions >= t["principal"]:
        return "principal"
    elif total_mentions >= t["secondary"]:
        return "secondary"
    elif total_mentions >= t["figurant"]:
        return "figurant"
    else:
        return "ignored"


def classify_entities(
    entities: list[dict],
    persons_full: dict,
    places_full: dict,
    orgs_full: dict,
    thresholds_config: str | dict,
    events_full: dict | None = None,
    geo_keywords=None,
    event_keywords=None,
    concept_keywords=None,
    role_words=None,
    role_patterns=None,
    geo_suffixes=None,
) -> list[dict]:
    """Enrich entities with total_mentions, chapters_present, and importance.

    Args:
        entities: resolved entities from entity-resolution / relationship-extraction
        persons_full / places_full / orgs_full / events_full: raw entity registries
        thresholds_config: "auto" or explicit dict from book.input.yaml

    Returns:
        Same list with 3 new fields per entity.
    """
    # Step 1: compute mention counts for all entities
    mention_data: list[tuple[str, str, int, int]] = []
    for entity in entities:
        if not entity.get("relevant", True):
            mention_data.append((entity["canonical_name"], entity.get("type", "OTHER"), 0, 0))
            continue
        total, chapters = get_total_mentions(entity, persons_full, places_full, orgs_full, events_full)
        mention_data.append((entity["canonical_name"], entity.get("type", "OTHER"), total, chapters))

    # Step 2: compute thresholds
    if thresholds_config == "auto":
        threshold_input = [(name, etype, total) for name, etype, total, _ in mention_data]
        thresholds = compute_auto_thresholds(threshold_input)
    else:
        thresholds = _parse_explicit_thresholds(thresholds_config)

    # Step 3: assign importance
    result = []
    for entity, (name, etype, total, chapters) in zip(entities, mention_data):
        if entity.get("relevant", True):
            importance = assign_importance(etype, total, chapters, thresholds)
        else:
            importance = "ignored"
        enriched = {**entity, "total_mentions": total, "chapters_present": chapters, "importance": importance}
        result.append(enriched)
    return result


def _parse_explicit_thresholds(config: dict) -> dict[str, dict[str, int]]:
    """Convert book.input.yaml explicit thresholds to internal format."""
    thresholds: dict[str, dict[str, int]] = {}

    char_cfg = config.get("characters", {})
    if char_cfg:
        thresholds["PERSON"] = {
            "principal": char_cfg.get("principal", {}).get("min_mentions", 50),
            "secondary": char_cfg.get("secondary", {}).get("min_mentions", 10),
            "figurant": char_cfg.get("figurant", {}).get("min_mentions", 3),
        }

    loc_cfg = config.get("locations", {})
    if loc_cfg:
        thresholds["PLACE"] = {
            "principal": loc_cfg.get("major", {}).get("min_mentions", 20),
            "secondary": loc_cfg.get("minor", {}).get("min_mentions", 3),
            "figurant": 1,
        }

    org_cfg = config.get("organizations", {})
    if org_cfg:
        thresholds["ORG"] = {
            "principal": org_cfg.get("major", {}).get("min_mentions", 10),
            "secondary": org_cfg.get("minor", {}).get("min_mentions", 3),
            "figurant": 1,
        }

    return thresholds


def _collect_context_sentences(
    entity: dict,
    persons_full: dict,
    places_full: dict,
    orgs_full: dict,
    events_full: dict,
    max_sentences: int = 20,
) -> list[str]:
    """Collect context snippets for an entity from all registries using source_ids."""
    registries = (persons_full, places_full, orgs_full, events_full or {})
    snippets: list[str] = []
    for sid in entity.get("source_ids", []):
        for reg in registries:
            entry = reg.get(sid)
            if not entry:
                continue
            for chapter_mentions in entry.get("mentions_by_chapter", {}).values():
                for sentence in chapter_mentions:
                    snippets.append(sentence)
                    if len(snippets) >= max_sentences:
                        return snippets
    return snippets


def _normalize_entity_type(
    entity: dict,
    persons_full: dict,
    places_full: dict,
    orgs_full: dict,
    events_full: dict,
    geo_keywords=None,
    event_keywords=None,
    concept_keywords=None,
    geo_suffixes=None,
) -> str:
    """Deterministic type normalization for common extraction confusions."""
    _geo = geo_keywords if geo_keywords is not None else frozenset()
    _evt = event_keywords if event_keywords is not None else frozenset()
    _concept = concept_keywords if concept_keywords is not None else frozenset()
    _geo_sfx = geo_suffixes if geo_suffixes is not None else frozenset()

    name = str(entity.get("canonical_name", "") or "").strip()
    if not name:
        return entity.get("type", "OTHER")

    lowered = name.lower()
    current_type = str(entity.get("type", "OTHER") or "OTHER").upper()

    if lowered in _concept:
        return "OTHER"
    if lowered in {"samhuinn", "yulemas"}:
        return "EVENT"

    context = " ".join(
        _collect_context_sentences(entity, persons_full, places_full, orgs_full, events_full)
    ).lower()
    text = f"{lowered} {context}"

    geo_hits = sum(1 for kw in _geo if kw in text)
    event_hits = sum(1 for kw in _evt if kw in text)
    concept_hits = sum(1 for kw in _concept if kw in text)

    # Conservative PERSON retag: only with explicit geopolitical evidence.
    if current_type == "PERSON":
        name_tokens = set(re.split(r"[\s'\-]+", lowered))
        if name_tokens & _geo_sfx:
            return "PLACE"
        geo_patterns = (
            rf"\b(?:kingdom|country|continent|empire)\s+of\s+{re.escape(lowered)}\b",
            rf"\b(?:royaume|pays|continent|empire)\s+(?:d'|de )?{re.escape(lowered)}\b",
            rf"\b{re.escape(lowered)}\s+(?:kingdom|country|continent|empire)\b",
        )
        if any(re.search(pattern, text) for pattern in geo_patterns):
            return "PLACE"
        return current_type

    if concept_hits >= 2 and concept_hits >= geo_hits:
        return "OTHER"
    if current_type in {"ORG", "PLACE", "OTHER"} and event_hits >= 2 and event_hits > geo_hits:
        return "EVENT"
    if current_type in {"ORG", "PLACE", "OTHER"} and geo_hits >= 2 and geo_hits >= event_hits:
        return "PLACE"

    # Cross-registry retag: PLACE entity whose source_ids include a persons_full entry
    # with ≥3 mentions was likely merged from a bare-name PLACE extraction error.
    if current_type == "PLACE":
        persons_mention_count = sum(
            sum(
                len(v) if isinstance(v, list) else 1
                for v in persons_full.get(sid, {}).get("mentions_by_chapter", {}).values()
            )
            for sid in entity.get("source_ids", [])
            if sid in persons_full
        )
        if persons_mention_count >= 3:
            return "PERSON"

    return current_type


def _is_role_entity_name(name: str, role_words=None, role_patterns=None) -> bool:
    _roles = role_words if role_words is not None else frozenset()
    _patterns = role_patterns if role_patterns is not None else ()
    lowered = (name or "").strip().lower()
    if not lowered:
        return False
    if lowered in _roles:
        return True
    if any(re.search(pattern, lowered) for pattern in _patterns):
        return True
    # Token membership: compound nouns like "Royal Guard" or "Captain Westfall"
    # qualify if at least one token is a role word.
    tokens = re.split(r"[\s'\-]+", lowered)
    return any(token in _roles for token in tokens if token)


def _filter_intra_entity_relationships(
    entities: list[dict],
    relationships: list[dict],
) -> list[dict]:
    """Drop relationships where both names resolve to the same canonical entity.

    After alias-resolution, two names that were separate pre-merge entities may
    now be the canonical_name and an alias of the same entity.  Keeping such
    pairs would produce absurd self-relations in the wiki output (STU-282).
    """
    name_to_canonical: dict[str, str] = {}
    for entity in entities:
        canonical = entity.get("canonical_name", "")
        if not canonical:
            continue
        name_to_canonical[canonical.lower()] = canonical
        for alias in entity.get("aliases", []):
            if alias:
                name_to_canonical[alias.lower()] = canonical

    result = []
    for rel in relationships:
        a = name_to_canonical.get((rel.get("entity_a") or "").lower())
        b = name_to_canonical.get((rel.get("entity_b") or "").lower())
        if a and b and a == b:
            continue
        result.append(rel)
    return result


def _build_alias_merge_map(entities: list[dict]) -> dict[str, str]:
    """Map every alias (and canonical_name) to its canonical_name.

    Used to canonicalize relationship names after alias-resolution so that
    'Chaol', 'Captain Westfall', and 'Chaol Westfall' all rewrite to the
    canonical, and duplicate pairs are aggregated by _rewrite_relationships.
    """
    m: dict[str, str] = {}
    for e in entities:
        canonical = e.get("canonical_name", "")
        if not canonical:
            continue
        for name in [canonical] + list(e.get("aliases", [])):
            if name:
                m[name] = canonical
    return m


def _rewrite_relationships(relationships: list[dict], merge_map: dict[str, str]) -> list[dict]:
    """Rewrite relationships after merges and aggregate duplicate pairs."""
    aggregated: dict[tuple[str, str], dict] = {}
    for rel in relationships:
        a = merge_map.get(rel.get("entity_a", ""), rel.get("entity_a", ""))
        b = merge_map.get(rel.get("entity_b", ""), rel.get("entity_b", ""))
        if not a or not b or a == b:
            continue
        key = tuple(sorted((a, b)))
        base = aggregated.get(key)
        if base is None:
            base = {k: v for k, v in rel.items()}
            base["entity_a"], base["entity_b"] = key
            base["cooccurrence_count"] = int(rel.get("cooccurrence_count", 0) or 0)
            aggregated[key] = base
        else:
            base["cooccurrence_count"] = int(base.get("cooccurrence_count", 0) or 0) + int(
                rel.get("cooccurrence_count", 0) or 0
            )
    return list(aggregated.values())


def _merge_entity_fields(target: dict, source: dict) -> None:
    target_aliases = list(target.get("aliases", []))
    source_aliases = list(source.get("aliases", []))
    if source.get("canonical_name"):
        source_aliases.append(source["canonical_name"])
    merged_aliases = []
    seen = set()
    for alias in target_aliases + source_aliases:
        if not alias or alias == target.get("canonical_name") or alias in seen:
            continue
        seen.add(alias)
        merged_aliases.append(alias)
    target["aliases"] = merged_aliases
    target["source_ids"] = sorted(set(target.get("source_ids", [])) | set(source.get("source_ids", [])))
    target["relevant"] = bool(target.get("relevant", True) or source.get("relevant", True))


def _canonicalize_role_entities(
    entities: list[dict],
    relationships: list[dict],
    persons_full: dict,
    places_full: dict,
    orgs_full: dict,
    events_full: dict,
    role_words=None,
    role_patterns=None,
) -> tuple[list[dict], list[dict], dict[str, str]]:
    """
    Merge unambiguous role entities into PERSON entities; otherwise mark role entities ignored.
    """
    by_name = {e.get("canonical_name", ""): e for e in entities if e.get("canonical_name")}
    merge_map: dict[str, str] = {}
    person_names = {e.get("canonical_name", "") for e in entities if e.get("type") == "PERSON"}

    for entity in entities:
        name = entity.get("canonical_name", "")
        if not name or not _is_role_entity_name(name, role_words=role_words, role_patterns=role_patterns):
            continue

        candidates: list[tuple[int, str]] = []
        for rel in relationships:
            a, b = rel.get("entity_a"), rel.get("entity_b")
            if a == name and b in person_names:
                candidates.append((int(rel.get("cooccurrence_count", 0) or 0), b))
            elif b == name and a in person_names:
                candidates.append((int(rel.get("cooccurrence_count", 0) or 0), a))
        if not candidates:
            entity["type"] = "OTHER"
            entity["relevant"] = False
            continue

        counts: dict[str, int] = defaultdict(int)
        for score, candidate in candidates:
            counts[candidate] += score
        ranked = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        top_name, top_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0

        context = " ".join(
            _collect_context_sentences(entity, persons_full, places_full, orgs_full, events_full)
        ).lower()
        target = by_name.get(top_name, {})
        target_mentions = [target.get("canonical_name", "")] + list(target.get("aliases", []))
        mention_support = sum(1 for token in target_mentions if token and token.lower() in context)

        # Strong-majority merge rule: dominant relationship + textual support in role contexts.
        if top_score >= 3 and top_score >= (second_score * 2 if second_score > 0 else 3) and mention_support >= 1:
            _merge_entity_fields(target, entity)
            merge_map[name] = top_name
            entity["relevant"] = False
        else:
            entity["type"] = "OTHER"
            entity["relevant"] = False

    filtered = [e for e in entities if e.get("canonical_name") not in merge_map]
    rewritten = _rewrite_relationships(relationships, merge_map)
    return filtered, rewritten, merge_map


def _apply_entity_overrides(
    entities: list[dict],
    relationships: list[dict],
    overrides: dict | None,
) -> tuple[list[dict], list[dict], dict[str, str]]:
    """Apply per-book entity overrides: force_type, exclude, merge_into."""
    if not isinstance(overrides, dict) or not overrides:
        return entities, relationships, {}

    by_name = {e.get("canonical_name", ""): e for e in entities if e.get("canonical_name")}
    merge_map: dict[str, str] = {}

    for name, rule in overrides.items():
        if not isinstance(rule, dict):
            continue
        source = by_name.get(name)
        if not source:
            continue

        force_type = rule.get("force_type")
        if isinstance(force_type, str):
            ft = force_type.strip().upper()
            if ft in _VALID_TYPES:
                source["type"] = ft
        if bool(rule.get("exclude")):
            source["relevant"] = False
            if source.get("type") not in {"EVENT", "OTHER"}:
                source["type"] = "OTHER"

        merge_into = rule.get("merge_into")
        if isinstance(merge_into, str) and merge_into in by_name and merge_into != name:
            target = by_name[merge_into]
            _merge_entity_fields(target, source)
            source["relevant"] = False
            merge_map[name] = merge_into

    filtered = [e for e in entities if e.get("canonical_name") not in merge_map]
    rewritten = _rewrite_relationships(relationships, merge_map)
    return filtered, rewritten, merge_map


def _load_type_corrections(processing_dir: Path) -> dict[str, str]:
    """Load persisted LLM type corrections from entity_type_corrections.json.

    Returns a dict of { lowercase_name: target_type } for matching against
    entity canonical_name and aliases. Returns {} if file is absent.
    """
    p = processing_dir / "entity_type_corrections.json"
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as f:
        corrections = json.load(f)
    return {c["name"].lower(): c["to"] for c in corrections if "name" in c and "to" in c}


def _apply_llm_type_corrections(
    entities: list[dict],
    corrections_map: dict[str, str],
) -> None:
    """Apply persisted LLM type corrections to entities (in-place).

    Matches by canonical_name first, then aliases (all lowercase).
    Corrections have lower priority than _apply_entity_overrides —
    call this BEFORE entity_overrides in run_studio_mode().
    """
    for entity in entities:
        name = (entity.get("canonical_name") or "").lower()
        match = corrections_map.get(name)
        if match is None:
            for alias in entity.get("aliases", []):
                match = corrections_map.get((alias or "").lower())
                if match is not None:
                    break
        if match is not None and entity.get("type") != match:
            print(
                f"[CORRECTIONS] {entity['canonical_name']}: {entity['type']} → {match} (from entity_type_corrections.json)",
                file=sys.stderr,
            )
            entity["type"] = match


# --- Studio entrypoint ---

def _load_entity_files(processing_dir: Path) -> tuple[dict, dict, dict, dict]:
    """Read *_full.json files from the processing directory. Return empty dicts if missing."""
    def load(name: str, key: str) -> dict:
        p = processing_dir / name
        if p.exists():
            with open(p, encoding="utf-8") as f:
                return json.load(f).get(key, {})
        return {}

    return (
        load("persons_full.json", "persons_full"),
        load("places_full.json", "places_full"),
        load("orgs_full.json", "orgs_full"),
        load("events_full.json", "events_full"),
    )


def run_studio_mode() -> None:
    payload = json.load(sys.stdin)
    prev_outputs = payload.get("previous_outputs", {})
    all_stage_outputs = payload.get("all_stage_outputs", {})
    rel_output = (
        prev_outputs.get("relationship-extraction")
        or all_stage_outputs.get("relationship-extraction")
        or {}
    )
    # Entities: prefer alias-resolution output (post-merge) when available, fall back to
    # relationship-extraction (original pipeline order) for backward compatibility.
    alias_output = (
        prev_outputs.get("alias-resolution")
        or all_stage_outputs.get("alias-resolution")
        or {}
    )
    entities = alias_output.get("entities") or rel_output.get("entities", [])
    narrator = alias_output.get("narrator") or rel_output.get("narrator", None)
    # Strip sample_contexts and chapters from relationships — not needed by wiki-generation
    # (reduces context size from ~800k to manageable for the writer LLM)
    relationships = [
        {k: v for k, v in r.items() if k not in ("sample_contexts", "chapters")}
        for r in rel_output.get("relationships", [])
    ]
    # STU-285: canonicalize alias names → canonical_name, then deduplicate and aggregate
    alias_map = _build_alias_merge_map(entities)
    relationships = _rewrite_relationships(relationships, alias_map)
    relationships = _filter_intra_entity_relationships(entities, relationships)

    if not entities:
        json.dump({"error": "missing relationship-extraction output"}, sys.stdout, ensure_ascii=False)
        sys.exit(1)

    additional_ctx = payload.get("additional_context", "")
    book_input = yaml.safe_load(additional_ctx) if additional_ctx else {}
    thresholds_config = book_input.get("thresholds", "auto")
    entity_overrides = book_input.get("entity_overrides", {})

    # Language-specific keyword sets from cue_words JSON
    spacy_model = book_input.get("spacy_model", "en_core_web_lg")
    language = (
        book_input.get("export", {}).get("categories", {}).get("language")
        or infer_language(spacy_model)
    )
    lang_cfg = load_lang_config(language)
    geo_keywords = frozenset(lang_cfg.get("geo_keywords", []))
    event_keywords = frozenset(lang_cfg.get("event_keywords", []))
    geo_suffixes = frozenset(lang_cfg.get("geo_suffixes", []))

    # Book-specific classification hints from book YAML
    classification = book_input.get("classification", {})
    concept_keywords = frozenset(classification.get("concept_keywords", []))
    role_words = frozenset(classification.get("role_words", [])) or frozenset(lang_cfg.get("role_words", []))
    role_patterns = tuple(classification.get("role_patterns", [])) or tuple(lang_cfg.get("role_patterns", []))

    paths = _paths_from_payload(payload)
    persons_full, places_full, orgs_full, events_full = _load_entity_files(paths.processing)

    # Deterministic type normalization before scoring.
    for entity in entities:
        entity["type"] = _normalize_entity_type(
            entity, persons_full, places_full, orgs_full, events_full,
            geo_keywords=geo_keywords,
            event_keywords=event_keywords,
            concept_keywords=concept_keywords,
            geo_suffixes=geo_suffixes,
        )

    # Apply persisted LLM type corrections (STU-302).
    # Priority: after heuristic normalization, before role canonicalization and manual overrides.
    llm_corrections = _load_type_corrections(paths.processing)
    _apply_llm_type_corrections(entities, llm_corrections)

    # Role/title entities should not become autonomous pages; merge unambiguous aliases.
    entities, relationships, _ = _canonicalize_role_entities(
        entities,
        relationships,
        persons_full,
        places_full,
        orgs_full,
        events_full,
        role_words=role_words,
        role_patterns=role_patterns,
    )

    # Optional per-book explicit overrides (highest priority).
    entities, relationships, _ = _apply_entity_overrides(
        entities,
        relationships,
        entity_overrides,
    )

    enriched = classify_entities(
        entities,
        persons_full,
        places_full,
        orgs_full,
        thresholds_config,
        events_full=events_full,
        geo_keywords=geo_keywords,
        event_keywords=event_keywords,
        concept_keywords=concept_keywords,
        role_words=role_words,
        role_patterns=role_patterns,
        geo_suffixes=geo_suffixes,
    )

    from collections import Counter
    importance_counts = Counter(e["importance"] for e in enriched)

    output = {
        "entities": enriched,
        "relationships": relationships,
        "stats": {
            "principal": importance_counts.get("principal", 0),
            "secondary": importance_counts.get("secondary", 0),
            "figurant": importance_counts.get("figurant", 0),
            "ignored": importance_counts.get("ignored", 0),
            "thresholds_used": "auto" if thresholds_config == "auto" else "explicit",
        },
        "narrator": narrator,
    }

    paths.processing.mkdir(parents=True, exist_ok=True)
    with open(paths.processing / "entities_classified.json", "w", encoding="utf-8") as _f:
        json.dump(output, _f, ensure_ascii=False)

    json.dump(output, sys.stdout, ensure_ascii=False)


def run_test_mode() -> None:
    """Hardcoded Le Jeu de l'Ange data for local testing."""
    entities = [
        {"canonical_name": "David Martín", "type": "PERSON", "source_ids": ["entity_001"],
         "aliases": ["Martín", "David"], "relevant": True},
        {"canonical_name": "Pedro Vidal", "type": "PERSON", "source_ids": ["entity_002"],
         "aliases": ["Vidal"], "relevant": True},
        {"canonical_name": "le libraire", "type": "PERSON", "source_ids": ["entity_003"],
         "aliases": [], "relevant": True},
    ]
    persons_full = {
        "entity_001": {"type": "PERSON", "raw_mentions": ["David Martín"],
                       "first_seen": "ch01",
                       "mentions_by_chapter": {"ch01": ["m1", "m2", "m3"], "ch02": ["m4", "m5"],
                                               "ch03": ["m6", "m7"], "ch04": ["m8"]}},
        "entity_002": {"type": "PERSON", "raw_mentions": ["Pedro Vidal"],
                       "first_seen": "ch02",
                       "mentions_by_chapter": {"ch02": ["v1", "v2"], "ch03": ["v3"]}},
        "entity_003": {"type": "PERSON", "raw_mentions": ["le libraire"],
                       "first_seen": "ch05",
                       "mentions_by_chapter": {"ch05": ["l1"]}},
    }
    enriched = classify_entities(entities, persons_full, {}, {}, thresholds_config="auto", events_full={})
    for e in enriched:
        print(f"{e['canonical_name']:30s}  mentions={e['total_mentions']:3d}  chapters={e['chapters_present']}  importance={e['importance']}")


if __name__ == "__main__":
    if "--test" in sys.argv:
        run_test_mode()
    else:
        run_studio_mode()
