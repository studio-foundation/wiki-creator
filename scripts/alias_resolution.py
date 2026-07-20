#!/usr/bin/env python3
"""
Stage: alias-resolution

Consumes resolved entities from resolve-clusters and conservatively merges PERSON
entities when local mention context contains strong alias or reveal evidence.
"""

import json
import os
import re
import sys
import warnings
from pathlib import Path

import yaml
from collections.abc import Callable

from wiki_creator import studio_io
from wiki_creator.lang import load_lang_config, infer_language
from wiki_creator.llm import ollama
from wiki_creator.registry import EntityRecord, Registry, normalize_name
from wiki_creator.tokens import contains_token_run


def _empty_stats() -> dict:
    return {
        "candidates_considered": 0,
        "merges_applied": 0,
        "merges_by_method": {"cooccurrence": 0, "llm": 0, "title_alias": 0, "role_symmetric": 0, "pure_title": 0, "series_seed": 0},
        "ambiguous_pairs": 0,
        "llm_attempts": 0,
        "llm_confirmed": 0,
        "llm_failed": 0,
    }


_LLM_PROMPT_TEMPLATE = """\
Given two character entities from a novel, determine if they refer to the same person.

Entity A: "{name_a}"
Snippets:
{snippets_a}

Entity B: "{name_b}"
Snippets:
{snippets_b}

Signal: "{signal}"

Reply ONLY with valid JSON:
{{"same_person": true/false, "confidence": "high"/"medium"/"low", "evidence": "<one sentence>"}}"""


def _fmt_snippets(snippets: list[str]) -> str:
    if not snippets:
        return "- (no context available)"
    return "\n".join(f"- {s[:200]}" for s in snippets)


def make_ollama_confirmer(model: str, url: str, timeout: int) -> Callable:
    """Return an llm_confirmer callable backed by Ollama."""

    def confirmer(candidate: dict) -> dict | None:
        entity_a = candidate["entity_a"]
        entity_b = candidate["entity_b"]
        evidence = candidate["evidence"]
        persons_full = candidate.get("persons_full", {})

        snippets_a = _pick_snippets(entity_a, persons_full)
        snippets_b = _pick_snippets(entity_b, persons_full)

        prompt = _LLM_PROMPT_TEMPLATE.format(
            name_a=entity_a.get("canonical_name", ""),
            name_b=entity_b.get("canonical_name", ""),
            snippets_a=_fmt_snippets(snippets_a),
            snippets_b=_fmt_snippets(snippets_b),
            signal=evidence.get("snippet", "")[:300],
        )

        return ollama.generate_json(prompt, model=model, url=url, timeout=timeout, num_predict=128)

    return confirmer


def _load_persons_full(processing_dir: Path) -> dict:
    path = processing_dir / "persons_full.json"
    if not path.exists():
        return {}
    return studio_io.load_full_file(path, "persons_full")


def _entity_names(entity: dict) -> list[str]:
    names = [entity.get("canonical_name", "")]
    names.extend(entity.get("aliases", []))
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        cleaned = str(name or "").strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def _gather_contexts(entity: dict, persons_full: dict) -> list[str]:
    snippets: list[str] = []
    for source_id in entity.get("source_ids", []):
        entry = persons_full.get(source_id)
        if entry is None:
            continue
        for mentions in entry.mentions_by_chapter.values():
            for snippet in mentions:
                if isinstance(snippet, str) and snippet.strip():
                    snippets.append(snippet.strip())
    return snippets


def _pick_snippets(entity: dict, persons_full: dict, n: int = 3) -> list[str]:
    """Return up to n snippets for entity, prioritising those containing the canonical name."""
    all_snippets = _gather_contexts(entity, persons_full)
    name = (entity.get("canonical_name") or "").lower()
    with_name = [s for s in all_snippets if name and name in s.lower()]
    without_name = [s for s in all_snippets if s not in with_name]
    ordered = with_name + without_name
    return ordered[:n]


def _is_pure_title(name: str, role_words: list[str]) -> bool:
    """Return True if name is a bare title, not a title + proper name.

    Recognises:
      * single-word roles: 'Master', 'King'
      * enumerated role phrases: 'Crown Prince' when 'crown prince' ∈ role_words
      * modifier + role head: 'Crown Prince', 'High Lord' — a multi-word phrase whose
        HEAD noun (last token) is a role word, so the leading modifier need not be
        enumerated (STU-471). English titles are head-final, so the head carries the
        role. A title + surname ('Captain Westfall') keeps a non-role head and is
        therefore NOT pure — it is handled by _detect_title_alias instead.
    """
    name_lower = name.lower()
    if not name_lower:
        return False
    role_set = {r.lower() for r in role_words}
    # Match the full name as a role phrase (e.g. "Crown Prince" in {"crown prince", ...})
    if name_lower in role_set:
        return True
    tokens = name_lower.split()
    # Match token-by-token (e.g. "Master" where "master" in role_set)
    if all(t in role_set for t in tokens):
        return True
    # Modifier + role head: last token is a role word ("Crown Prince" -> "prince").
    return len(tokens) > 1 and tokens[-1] in role_set


def _pick_canonical_name(
    entity_a: dict,
    entity_b: dict,
    persons_full: dict,
    role_words: list[str] | None = None,
) -> str:
    role_words = role_words or []
    counts: dict[str, int] = {}
    for entity in (entity_a, entity_b):
        for name in _entity_names(entity):
            counts[name] = 0
    for entity in (entity_a, entity_b):
        contexts = " ".join(_gather_contexts(entity, persons_full)).lower()
        for name in counts:
            counts[name] += contexts.count(name.lower())
    return sorted(
        counts,
        key=lambda name: (
            _is_pure_title(name, role_words),   # False (0) sorts before True (1) — proper names first
            -counts[name],
            -len(name.split()),
            -len(name),
            name.lower(),
        ),
    )[0]


def _merge_entities(
    entity_a: dict,
    entity_b: dict,
    evidence: dict,
    persons_full: dict,
    role_words: list[str] | None = None,
) -> dict:
    canonical = _pick_canonical_name(entity_a, entity_b, persons_full, role_words=role_words)
    alias_names = sorted({name for entity in (entity_a, entity_b) for name in _entity_names(entity)}, key=str.lower)
    source_ids = sorted({sid for entity in (entity_a, entity_b) for sid in entity.get("source_ids", [])})
    merged_from = [
        entity.get("canonical_name", "")
        for entity in (entity_a, entity_b)
        if entity.get("canonical_name") and entity.get("canonical_name") != canonical
    ]
    return {
        "canonical_name": canonical,
        "type": "PERSON",
        "aliases": alias_names,
        "source_ids": source_ids,
        "relevant": bool(entity_a.get("relevant", True) or entity_b.get("relevant", True)),
        "alias_resolution": {
            "merged_from": merged_from,
            "evidence": [evidence],
            "confidence": evidence["confidence"],
            "method": evidence["method"],
        },
    }


def _detect_series_seed(
    entity_a: dict,
    entity_b: dict,
    seed_lookup: dict[str, EntityRecord] | None,
) -> dict | None:
    """Series seeding (STU-485): two entities whose names are known aliases of
    the same series-registry entity are the same person — identity established
    in a prior tome, no local evidence needed. Names must be *distinct*
    surfaces (normalize_name) so this only replays known alias links, never
    folds same-name duplicates that upstream stages deliberately kept apart.
    """
    if not seed_lookup:
        return None
    for name_a in _entity_names(entity_a):
        record = seed_lookup.get(normalize_name(name_a))
        if record is None:
            continue
        for name_b in _entity_names(entity_b):
            if normalize_name(name_b) == normalize_name(name_a):
                continue
            if seed_lookup.get(normalize_name(name_b)) is record:
                books = ", ".join(record.books) or "prior tomes"
                return {
                    "method": "series_seed",
                    "confidence": "high",
                    "snippet": (
                        f"series registry: '{name_a}' and '{name_b}' are known "
                        f"aliases of '{record.canonical_name}' (books: {books})"
                    ),
                }
    return None


def _tokens_between_are_connective(
    between: str, connective_words: set[str], determiners: set[str]
) -> bool:
    """True when every word in ``between`` is a connective (article/preposition) or
    pure punctuation — the marker of apposition rather than conjunction.

    "" / " - the " -> apposition (only 'the' + punctuation).
    ", of course, sat with " -> NOT apposition ('course', 'sat', 'with' are content words).

    A comma AND a determiner is enumeration, not apposition (STU-559): apposition
    renames without re-determining ("Dorian Havilliard, Crown Prince of Adarlan"),
    whereas a comma followed by a fresh determined noun phrase opens a new phrase
    that may head its own clause — "As for Zar'roc, the Shade might have it" merged
    the antagonist into a sword. A dash keeps its determiner ("Brullo — the Master —"),
    which is why the comma is the gate and the determiner alone is not.
    """
    saw_comma = False
    for raw in between.split():
        saw_comma = saw_comma or "," in raw
        core = raw.strip(".,;:!?\"'”“’‘—–-()[]").lower()
        if not core:
            continue  # pure punctuation between the two names
        if core not in connective_words:
            return False
        if saw_comma and core in determiners:
            return False
    return True


def _is_apposition(
    sentence: str,
    title: str,
    name: str,
    connective_words: set[str],
    determiners: set[str] = frozenset(),
) -> bool:
    """True when ``name`` sits in apposition to ``title`` within ``sentence``.

    Apposition = the two phrases are adjacent, separated only by connective words
    and/or punctuation ("Master Brullo", "Brullo - the Master -", "Crown Prince Dorian").
    A conjunction like "The Crown Prince sat with Perrington" is NOT apposition:
    content words sit between the two, so they denote distinct people (STU-430).
    """
    low = sentence.lower()
    title_spans = [(m.start(), m.end()) for m in re.finditer(re.escape(title.lower()), low)]
    name_spans = [(m.start(), m.end()) for m in re.finditer(re.escape(name.lower()), low)]
    if not title_spans or not name_spans:
        return False
    for t0, t1 in title_spans:
        for n0, n1 in name_spans:
            if n0 >= t0 and n1 <= t1:
                continue  # name is a substring of the title occurrence — not evidence
            if n0 >= t1:
                between = sentence[t1:n0]
            elif t0 >= n1:
                between = sentence[n1:t0]
            else:
                continue  # spans overlap without nesting — inconclusive
            if _tokens_between_are_connective(between, connective_words, determiners):
                return True
    return False


def _detect_pure_title_in_context(
    entity_a: dict,
    entity_b: dict,
    persons_full: dict,
    roles_naming_one_character: list[str] | None = None,
    connective_words: list[str] | None = None,
    determiners: list[str] | None = None,
) -> dict | None:
    """
    Return evidence if one entity's canonical name is a role the book declares as
    naming one particular character (e.g. "Crown Prince" for Dorian) AND the other
    entity's name appears in apposition to it in either entity's context snippets.

    This handles the case where NER produces a bare title entity ("Master") that refers
    to a named character ("Brullo") — a case _detect_title_alias cannot cover because the
    title entity has no surname remainder.

    The premise — a bare role name designates a named character — holds only for a role
    exactly one character wears, which no signal in the text can establish and a reader
    knows without hesitation (STU-559). Reading it off `role_words` conflated it with
    every other role vocabulary: `rider`, `urgal` and `shade` share that list with
    `king`, so the species merged into the mountain and the Shade into a sword. An
    undeclared book merges nothing here — the safe direction, since a false merge
    invents a character and deletes a real one, whereas a false negative leaves two
    pages that are each still correct.

    Both entities' contexts are scanned because NER attributes an appositive span like
    "Dorian Havilliard, Crown Prince of Adarlan" to the proper-name entity, so the
    decisive sentence may never appear in the title entity's own snippets (STU-440).
    """
    declared = {r.lower() for r in (roles_naming_one_character or [])}
    if not declared:
        return None
    connective_set = {w.lower() for w in (connective_words or [])}
    determiner_set = {w.lower() for w in (determiners or [])}
    for title_entity, proper_entity in ((entity_a, entity_b), (entity_b, entity_a)):
        title_name = title_entity.get("canonical_name", "")
        if title_name.lower() not in declared:
            continue
        proper_names = [n for n in _entity_names(proper_entity) if n]
        if not proper_names:
            continue
        title_lower = title_name.lower()
        for snippet in _gather_contexts(title_entity, persons_full) + _gather_contexts(
            proper_entity, persons_full
        ):
            # Split into sentences so that names in adjacent sentences don't create false matches.
            # Within a sentence, the proper name must sit in apposition to the title.
            sentences = re.split(r'(?<=[.!?])[\u201d\u2019\u201c\u2018"\']?\s+', snippet)
            for sentence in sentences:
                if title_lower not in sentence.lower():
                    continue
                if any(
                    _is_apposition(sentence, title_name, pn, connective_set, determiner_set)
                    for pn in proper_names
                ):
                    return {
                        "method": "pure_title",
                        "confidence": "medium",
                        "snippet": sentence,
                    }
    return None


def _detect_reveal_signal(entity_a: dict, entity_b: dict, persons_full: dict, reveal_words: tuple[str, ...] = ()) -> dict | None:
    contexts = _gather_contexts(entity_a, persons_full) + _gather_contexts(entity_b, persons_full)
    names_a = [name.lower() for name in _entity_names(entity_a)]
    names_b = [name.lower() for name in _entity_names(entity_b)]
    matches: list[str] = []
    seen_a = False
    seen_b = False
    for snippet in contexts:
        lowered = snippet.lower()
        has_a = any(name in lowered for name in names_a)
        has_b = any(name in lowered for name in names_b)
        if not (has_a or has_b):
            continue
        if any(word in lowered for word in reveal_words):
            matches.append(snippet)
            seen_a = seen_a or has_a
            seen_b = seen_b or has_b
    if len(matches) >= 2 and seen_a and seen_b:
        return {
            "method": "cooccurrence",
            "confidence": "medium",
            "snippet": matches[0],
        }
    return None


def _leading_role(name: str, role_words: list[str]) -> str | None:
    """Return the role_word a name leads with ("Mrs Beaver" -> "mrs"), longest match first."""
    name_lower = name.lower()
    for role in sorted(role_words, key=len, reverse=True):
        role_lower = role.lower()
        if name_lower.startswith(role_lower + " "):
            return role_lower
    return None


def _entity_roles(names: list[str], role_words: list[str]) -> set[str]:
    """Return every role_word the entity's names lead with."""
    return {role for name in names if (role := _leading_role(name, role_words))}


def _ambiguous_remainders(entities: list[dict], role_words: list[str]) -> frozenset[str]:
    """Return the remainders the roster attaches to two or more different titles.

    "Beaver" is worn by both "Mr Beaver" and "Mrs Beaver", so it identifies neither
    spouse; "Tumnus" is worn by "Mr Tumnus" alone, so it identifies him.
    """
    roles_by_remainder: dict[str, set[str]] = {}
    for entity in entities:
        for name in _entity_names(entity):
            role = _leading_role(name, role_words)
            if role is None:
                continue
            remainder = name.lower()[len(role) + 1:].strip()
            if remainder:
                roles_by_remainder.setdefault(remainder, set()).add(role)
    return frozenset(remainder for remainder, roles in roles_by_remainder.items() if len(roles) > 1)


def _detect_title_alias(
    entity_a: dict,
    entity_b: dict,
    role_words: list[str],
    ambiguous_remainders: frozenset[str] = frozenset(),
) -> dict | None:
    """
    Return evidence dict if one entity's name starts with a role_word and the
    remainder's tokens appear in the other entity's name.

    Example: "Captain Westfall" + role_word "captain"
             → remainder "westfall" in "Chaol Westfall" → match.

    A remainder only discriminates when the other entity bears no differing title
    (STU-541): a role designates one person, so "Westfall" identifies its bearer,
    but "Mr Beaver" and "Mrs Beaver" are a couple whose surname is the very part
    that cannot tell them apart. Titles are compared per entity, not per name —
    once "Beaver" has absorbed "Mr Beaver", it is Mr Beaver, and letting it match
    "Mrs Beaver" would remarry the couple transitively.

    That leaves the bare name itself (STU-542): a remainder the roster attaches to
    two titles identifies no one, so the entity whose whole name IS that remainder
    merges with neither bearer — otherwise iteration order picks the spouse who
    inherits its mentions.
    """
    if not role_words:
        return None
    names_a = _entity_names(entity_a)
    names_b = _entity_names(entity_b)
    roles_a = _entity_roles(names_a, role_words)
    roles_b = _entity_roles(names_b, role_words)
    if roles_a and roles_b and roles_a.isdisjoint(roles_b):
        return None
    for names_title, names_full in ((names_a, names_b), (names_b, names_a)):
        for name in names_title:
            role = _leading_role(name, role_words)
            if role is None:
                continue
            remainder = name.lower()[len(role) + 1:].strip()
            if not remainder:
                continue
            for full_name in names_full:
                if remainder in ambiguous_remainders and full_name.lower() == remainder:
                    continue
                if contains_token_run(full_name.lower(), remainder):
                    return {
                        "method": "title_alias",
                        "confidence": "medium",
                        "snippet": f"{name} / {full_name}",
                    }
    return None


def _build_role_index(relationships: list[dict]) -> dict[tuple[str, str], list[str]]:
    """
    Build an inverted index: (third_party_canonical, relationship_type) → [entity names with this role].

    For each relationship (A ↔ B, rel_type), B is a third party for A and vice versa.
    Skips relationships with null relationship_type.
    """
    index: dict[tuple[str, str], list[str]] = {}
    for rel in relationships:
        rel_type = rel.get("relationship_type")
        if not rel_type:
            continue
        entity_a: str = rel.get("entity_a", "")
        entity_b: str = rel.get("entity_b", "")
        if not entity_a or not entity_b:
            continue
        # A plays a role toward B
        key_a = (entity_b, rel_type)
        index.setdefault(key_a, [])
        # Normalize to lowercase for case-insensitive matching
        if entity_a.lower() not in index[key_a]:
            index[key_a].append(entity_a.lower())
        # B plays a role toward A
        key_b = (entity_a, rel_type)
        index.setdefault(key_b, [])
        if entity_b.lower() not in index[key_b]:
            index[key_b].append(entity_b.lower())
    return index


def _direct_cooccurrence(name_a: str, name_b: str, relationships: list[dict]) -> int:
    """Return the cooccurrence_count for the direct A↔B relationship, or 0."""
    na, nb = name_a.lower(), name_b.lower()
    for rel in relationships:
        ea = rel.get("entity_a", "").lower()
        eb = rel.get("entity_b", "").lower()
        if (ea == na and eb == nb) or (ea == nb and eb == na):
            return rel.get("cooccurrence_count", 0)
    return 0


def _bucket_is_clean(
    bucket: tuple[str, str],
    role_index: dict[tuple[str, str], list[str]],
    relationships: list[dict],
    direct_cooc_max: int,
) -> bool:
    """Return True if no two co-inhabitants of the bucket have high direct cooccurrence."""
    names_in_bucket = role_index.get(bucket, [])
    for ii in range(len(names_in_bucket)):
        for jj in range(ii + 1, len(names_in_bucket)):
            if _direct_cooccurrence(names_in_bucket[ii], names_in_bucket[jj], relationships) > direct_cooc_max:
                return False
    return True


def _names_share_token(entity_a: dict, entity_b: dict) -> bool:
    """Return True if any name token of entity_a appears in any name of entity_b."""
    tokens_a: set[str] = set()
    for name in _entity_names(entity_a):
        tokens_a.update(t.lower() for t in name.split() if len(t) > 1)
    for name in _entity_names(entity_b):
        for token in name.split():
            if len(token) > 1 and token.lower() in tokens_a:
                return True
    return False


def _detect_role_symmetric_pairs(
    entities: list[dict],
    relationships: list[dict],
    min_shared: int = 2,
    direct_cooc_max: int = 3,
) -> list[tuple[dict, dict, dict]]:
    """
    Return (entity_a, entity_b, evidence) triples where A and B share ≥ min_shared
    (third_party, relationship_type) buckets AND their direct cooccurrence is ≤ direct_cooc_max.

    Evidence dict has keys: method, confidence, snippet, shared_roles.
    """
    role_index = _build_role_index(relationships)
    persons = [e for e in entities if e.get("type") == "PERSON" and e.get("relevant", True)]

    # Pre-compute signatures for all PERSON entities (once, not per-pair)
    entity_signatures: dict[str, set[tuple[str, str]]] = {}
    for entity in persons:
        name = entity.get("canonical_name", "").lower()
        sig: set[tuple[str, str]] = set()
        for (third_party, rel_type), names in role_index.items():
            if name in names:
                sig.add((third_party, rel_type))
        entity_signatures[name] = sig

    pairs: list[tuple[dict, dict, dict]] = []
    for i in range(len(persons)):
        for j in range(i + 1, len(persons)):
            a, b = persons[i], persons[j]
            name_a = a.get("canonical_name", "").lower()
            name_b = b.get("canonical_name", "").lower()
            if _direct_cooccurrence(name_a, name_b, relationships) > direct_cooc_max:
                continue
            if not _names_share_token(a, b):
                continue
            shared = entity_signatures.get(name_a, set()) & entity_signatures.get(name_b, set())
            if len(shared) < min_shared:
                continue
            # Check for contaminated buckets (shared via confirmed-distinct characters)
            clean_shared = {
                bucket for bucket in shared
                if _bucket_is_clean(bucket, role_index, relationships, direct_cooc_max)
            }
            if len(clean_shared) < min_shared:
                continue
            shared_list = sorted(clean_shared)
            # Use original (non-lowercased) names for the snippet
            orig_name_a = a.get("canonical_name", "")
            orig_name_b = b.get("canonical_name", "")
            snippet = "; ".join(
                f"{orig_name_a} and {orig_name_b} both have '{rel}' relation toward '{third}'"
                for third, rel in shared_list[:2]
            )
            evidence = {
                "method": "role_symmetric",
                "confidence": "medium",
                "snippet": snippet,
                "shared_roles": [{"third_party": t, "relationship_type": r} for t, r in shared_list],
            }
            pairs.append((a, b, evidence))
    return pairs


def resolve_aliases(
    entities: list[dict],
    persons_full: dict,
    narrator=None,
    llm_confirmer=None,
    reveal_words: tuple[str, ...] = (),
    role_words: list[str] | None = None,
    roles_naming_one_character: list[str] | None = None,
    connective_words: list[str] | None = None,
    determiners: list[str] | None = None,
    relationships: list[dict] | None = None,
    role_symmetric_min_shared: int = 2,
    seed_lookup: dict[str, EntityRecord] | None = None,
) -> dict:
    stats = _empty_stats()
    role_words = role_words or []
    connective_words = connective_words or []
    relationships = relationships or []
    resolved: list[dict] = []
    consumed: set[int] = set()
    ambiguous_remainders = _ambiguous_remainders(entities, role_words)

    # Pre-compute role-symmetric candidate pairs.
    role_sym_map: dict[tuple[int, int], dict] = {}
    if relationships:
        sym_candidates = _detect_role_symmetric_pairs(
            entities, relationships,
            min_shared=role_symmetric_min_shared,
        )
        name_to_idx = {e.get("canonical_name", ""): i for i, e in enumerate(entities)}
        for ea, eb, ev in sym_candidates:
            ia = name_to_idx.get(ea.get("canonical_name", ""))
            ib = name_to_idx.get(eb.get("canonical_name", ""))
            if ia is not None and ib is not None:
                role_sym_map[(min(ia, ib), max(ia, ib))] = ev

    for index, entity in enumerate(entities):
        if index in consumed:
            continue
        if entity.get("type") != "PERSON" or not entity.get("relevant", True):
            resolved.append(entity)
            continue

        merged = None
        for candidate_index in range(index + 1, len(entities)):
            if candidate_index in consumed:
                continue
            candidate = entities[candidate_index]
            if candidate.get("type") != "PERSON" or not candidate.get("relevant", True):
                continue

            stats["candidates_considered"] += 1

            seed = _detect_series_seed(entity, candidate, seed_lookup)
            if seed:
                merged = _merge_entities(entity, candidate, seed, persons_full, role_words=role_words)
                stats["merges_applied"] += 1
                stats["merges_by_method"]["series_seed"] = stats["merges_by_method"].get("series_seed", 0) + 1
                consumed.add(candidate_index)
                break

            title = _detect_title_alias(entity, candidate, role_words, ambiguous_remainders)
            if title:
                merged = _merge_entities(entity, candidate, title, persons_full, role_words=role_words)
                stats["merges_applied"] += 1
                stats["merges_by_method"]["title_alias"] += 1
                consumed.add(candidate_index)
                break

            pure_title = _detect_pure_title_in_context(
                entity, candidate, persons_full,
                roles_naming_one_character=roles_naming_one_character,
                connective_words=connective_words,
                determiners=determiners,
            )
            if pure_title:
                merged = _merge_entities(entity, candidate, pure_title, persons_full, role_words=role_words)
                stats["merges_applied"] += 1
                stats["merges_by_method"]["pure_title"] = stats["merges_by_method"].get("pure_title", 0) + 1
                consumed.add(candidate_index)
                break

            reveal = _detect_reveal_signal(entity, candidate, persons_full, reveal_words=reveal_words)

            # Check role-symmetric signal only when reveal is absent
            role_sym = None
            if not reveal:
                pair_key = (min(index, candidate_index), max(index, candidate_index))
                role_sym = role_sym_map.get(pair_key)

            signal = reveal or role_sym
            if not signal:
                continue

            if llm_confirmer is None:
                stats["ambiguous_pairs"] += 1
                continue

            stats["llm_attempts"] += 1
            try:
                decision = llm_confirmer({
                    "entity_a": entity,
                    "entity_b": candidate,
                    "evidence": signal,
                    "persons_full": persons_full,
                }) or {}
            except Exception:
                stats["llm_failed"] += 1
                stats["ambiguous_pairs"] += 1
                continue

            if decision.get("same_person"):
                method = signal.get("method", "llm")
                merged_evidence = {
                    "method": method if method == "role_symmetric" else "llm",
                    "confidence": decision.get("confidence", "medium"),
                    "snippet": decision.get("evidence", signal["snippet"]),
                }
                merged = _merge_entities(entity, candidate, merged_evidence, persons_full, role_words=role_words)
                stats["merges_applied"] += 1
                stat_key = "role_symmetric" if method == "role_symmetric" else "llm"
                stats["merges_by_method"][stat_key] += 1
                stats["llm_confirmed"] += 1
                consumed.add(candidate_index)
                break

            stats["ambiguous_pairs"] += 1

        resolved.append(merged or entity)

    return {"entities": resolved, "narrator": narrator, "stats": stats}


def main() -> None:
    payload = studio_io.read_payload()
    previous_outputs = payload.get("previous_outputs", {})
    all_stage_outputs = payload.get("all_stage_outputs", {})
    # Entities come from resolve-clusters (STU-590 removed the merge-entities passthrough).
    entity_source = (
        all_stage_outputs.get("resolve-clusters")
        or previous_outputs.get("resolve-clusters")
        or {}
    )
    entities = entity_source.get("entities", [])
    narrator = entity_source.get("narrator")
    # Relationships from relationship-extraction (empty list if stage not run yet).
    relationships: list[dict] = (
        all_stage_outputs.get("relationship-extraction", {})
        or previous_outputs.get("relationship-extraction", {})
    ).get("relationships", [])

    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    spacy_model = ctx.get("spacy_model", "en_core_web_lg")
    export_categories = ctx.get("export", {}).get("categories", {})
    language = export_categories.get("language") or infer_language(spacy_model)
    lang_cfg = load_lang_config(language)
    reveal_words = tuple(lang_cfg.get("reveal_words", ()))
    classification_cfg = ctx.get("classification", {}) or {}
    role_words: list[str] = list(classification_cfg.get("role_words", []))
    cue_role_words = [w.lower() for w in lang_cfg.get("person_cue_words", [])]
    role_words = list(dict.fromkeys(role_words + cue_role_words))  # dedup, preserve order
    # Book-declared only, never cue_words: the question is which roles THIS novel
    # gives to a single character (STU-559), which no language-wide list can answer.
    roles_naming_one_character: list[str] = list(
        classification_cfg.get("roles_naming_one_character", [])
    )
    determiners = [w.lower() for w in lang_cfg.get("determiners", [])]
    # Apposition-safe words: articles/determiners + name connectors. Absent keys degrade
    # to an empty collection (only adjacency/punctuation counts as apposition then).
    connective_words = list(dict.fromkeys(
        determiners + [w.lower() for w in lang_cfg.get("name_connectors", [])]
    ))

    persons_full = {}
    seed_lookup: dict[str, EntityRecord] = {}
    try:
        paths = studio_io.paths_from_payload(payload)
        persons_full = _load_persons_full(paths.processing)
        # Series seeding (STU-485): tome N starts from the identities
        # accumulated over tomes 1..N-1.
        seed_lookup = Registry.load_seed_table(paths.series_registry)
        if seed_lookup:
            print(
                f"[alias-resolution] series seeding active: "
                f"{len(seed_lookup)} known surfaces from {paths.series_registry}",
                file=sys.stderr,
            )
    except ValueError:
        persons_full = {}

    llm_confirmer = None
    use_llm = ctx.get("use_llm", False)
    if not use_llm:
        print(
            "UserWarning: LLM alias confirmation is disabled (use_llm not set in book config). "
            "Title-based aliases (e.g. 'Captain Westfall', 'Crown Prince') will NOT be resolved. "
            "Set use_llm: true in your book YAML to enable.",
            file=sys.stderr,
        )
    if use_llm:
        ollama_url = os.environ.get("OLLAMA_URL", ollama.DEFAULT_URL)
        llm_model = ctx.get("llm_model", "mistral")
        if ollama.is_available(ollama_url):
            llm_confirmer = make_ollama_confirmer(llm_model, ollama_url, timeout=30)
        else:
            warnings.warn(
                f"Ollama not available at {ollama_url} — LLM alias confirmation skipped.",
                stacklevel=1,
            )

    result = resolve_aliases(
        entities, persons_full=persons_full, narrator=narrator,
        llm_confirmer=llm_confirmer, reveal_words=reveal_words,
        role_words=role_words,
        roles_naming_one_character=roles_naming_one_character,
        connective_words=connective_words, determiners=determiners,
        relationships=relationships,
        role_symmetric_min_shared=ctx.get("role_symmetric_min_shared", 2),
        seed_lookup=seed_lookup,
    )
    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
