#!/usr/bin/env python3
"""
Stage: alias-resolution

Consumes resolved entities from resolve-clusters and conservatively merges PERSON
entities when local mention context contains strong alias or reveal evidence.
"""

import json
import os
import re
import socket
import sys
import urllib.error
import urllib.request
import warnings
from pathlib import Path

import yaml
from collections.abc import Callable
from typing import Literal, TypedDict

# Ensure project root is importable when running as `python scripts/<file>.py`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from wiki_creator.paths import book_paths_from_epub, BookPaths
from wiki_creator.lang import load_lang_config, infer_language


class AliasPair(TypedDict):
    entity_a: str
    entity_b: str
    confidence: Literal["high", "medium"]
    source: Literal["pattern", "cooccurrence", "title_alias"]
    snippet: str


_WINDOW_SIZE = 300  # tokens


def _paths_from_payload(payload: dict) -> BookPaths:
    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    file_path = ctx.get("file_path")
    if not file_path:
        raise ValueError("missing file_path in additional_context")
    return book_paths_from_epub(file_path)


def _empty_stats() -> dict:
    return {
        "candidates_considered": 0,
        "merges_applied": 0,
        "merges_by_method": {"pattern": 0, "cooccurrence": 0, "llm": 0, "title_alias": 0},
        "ambiguous_pairs": 0,
        "llm_attempts": 0,
        "llm_confirmed": 0,
        "llm_failed": 0,
    }


_OLLAMA_URL = "http://localhost:11434"

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


def _parse_llm_response(text: str) -> dict | None:
    """Try json.loads, then regex extraction, then return None."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r'\{[^{}]+\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


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

        body = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 128},
        }).encode()
        req = urllib.request.Request(
            f"{url}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
        except (urllib.error.URLError, socket.timeout, OSError):
            return None
        raw = data.get("response", "")
        return _parse_llm_response(raw)

    return confirmer


def _check_ollama_available(url: str, timeout: int = 2) -> bool:
    """Return True if Ollama is reachable at url/api/tags."""
    try:
        req = urllib.request.Request(f"{url}/api/tags", method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except (urllib.error.URLError, socket.timeout, OSError):
        return False


def _load_persons_full(processing_dir: Path) -> dict:
    path = processing_dir / "persons_full.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("persons_full", {})


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


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
        entry = persons_full.get(source_id, {})
        for mentions in entry.get("mentions_by_chapter", {}).values():
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
    """Return True if name consists entirely of role_words (e.g. 'Master', 'Captain')."""
    tokens = name.lower().split()
    if not tokens:
        return False
    role_set = {r.lower() for r in role_words}
    return all(t in role_set for t in tokens)


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


def _detect_pattern_for_names(
    name_a: str,
    name_b: str,
    snippets: list[str],
    pattern_templates: tuple[str, ...] = (),
) -> str | None:
    """Return the first snippet matching an alias pattern for name_a/name_b, or None."""
    if name_a.lower() == name_b.lower():
        return None
    pattern_a_b = [
        t.format(a=re.escape(name_a.lower()), b=re.escape(name_b.lower()))
        for t in pattern_templates
    ]
    pattern_b_a = [
        t.format(a=re.escape(name_b.lower()), b=re.escape(name_a.lower()))
        for t in pattern_templates
    ]
    for snippet in snippets:
        lowered = snippet.lower()
        for pattern in pattern_a_b + pattern_b_a:
            if re.search(pattern, lowered):
                return snippet
    return None


def _detect_pattern_match(
    entity_a: dict,
    entity_b: dict,
    persons_full: dict,
    pattern_templates: tuple[str, ...] = (),
) -> dict | None:
    contexts = _gather_contexts(entity_a, persons_full) + _gather_contexts(entity_b, persons_full)
    names_a = _entity_names(entity_a)
    names_b = _entity_names(entity_b)
    for name_a in names_a:
        for name_b in names_b:
            snippet = _detect_pattern_for_names(name_a, name_b, contexts, pattern_templates)
            if snippet:
                return {"method": "pattern", "confidence": "high", "snippet": snippet}
    return None


def _detect_cooccurrence_window(
    name_a: str,
    name_b: str,
    text: str,
    threshold: int = 2,
) -> str | None:
    """
    Returns a ~200-character snippet from the first co-occurrence zone, or None.

    Tokenizes by whitespace. A name matches if its lowercased tokens appear
    consecutively in the token list.
    """
    tokens = text.split()
    if not tokens:
        return None

    na = name_a.lower()
    nb = name_b.lower()

    def find_positions(name: str) -> list[int]:
        name_tokens = name.split()
        n = len(name_tokens)
        positions = []
        for idx in range(len(tokens) - n + 1):
            if " ".join(tokens[idx: idx + n]).lower() == name:
                positions.append(idx)
        return positions

    pos_a = find_positions(na)
    pos_b = find_positions(nb)

    if not pos_a or not pos_b:
        return None

    # Collect all positions of name_a that have name_b within _WINDOW_SIZE tokens
    # (symmetric: either name can precede the other).
    cooccurrence_centers: list[int] = []
    for pa in pos_a:
        for pb in pos_b:
            if abs(pa - pb) < _WINDOW_SIZE:
                center = min(pa, pb)
                cooccurrence_centers.append(center)
                break

    if len(cooccurrence_centers) < threshold:
        return None

    ws = max(0, cooccurrence_centers[0])
    snippet_tokens = tokens[ws: ws + _WINDOW_SIZE]
    snippet = " ".join(snippet_tokens)
    return snippet[:200]


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


def _detect_title_alias(
    entity_a: dict,
    entity_b: dict,
    role_words: list[str],
) -> dict | None:
    """
    Return evidence dict if one entity's name starts with a role_word and the
    remainder appears in the other entity's canonical name.

    Example: "Captain Westfall" + role_word "captain"
             → remainder "westfall" in "Chaol Westfall" → match.
    """
    if not role_words:
        return None
    names_a = _entity_names(entity_a)
    names_b = _entity_names(entity_b)
    for names_title, names_full in ((names_a, names_b), (names_b, names_a)):
        for name in names_title:
            name_lower = name.lower()
            for role in role_words:
                role_lower = role.lower()
                if not name_lower.startswith(role_lower + " "):
                    continue
                remainder = name_lower[len(role_lower) + 1:].strip()
                if not remainder:
                    continue
                for full_name in names_full:
                    if remainder in full_name.lower():
                        return {
                            "method": "title_alias",
                            "confidence": "medium",
                            "snippet": f"{name} / {full_name}",
                        }
    return None


def detect_named_aliases(
    mentions: dict[str, list[str]],
    text: str,
    reveal_words: tuple[str, ...] | None = None,
    pattern_templates: tuple[str, ...] = (),
) -> list[AliasPair]:
    """
    Detect alias pairs using two deterministic heuristics (zero LLM).

    Args:
        mentions: mapping of entity canonical_name -> list of context snippets
        text: raw concatenated book text, used for token-window co-occurrence
        reveal_words: optional override for reveal signal words
        pattern_templates: regex templates for alias pattern detection

    Returns:
        list of AliasPair, each with entity_a, entity_b, confidence, source, snippet
    """
    if reveal_words is None:
        reveal_words = ()
    names = list(mentions.keys())
    pairs: list[AliasPair] = []

    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            name_a = names[i]
            name_b = names[j]

            # Strategy 1: pattern matching
            all_snippets = mentions[name_a] + mentions[name_b]
            evidence = _detect_pattern_for_names(name_a, name_b, all_snippets, pattern_templates)
            if evidence:
                pairs.append(AliasPair(
                    entity_a=name_a,
                    entity_b=name_b,
                    confidence="high",
                    source="pattern",
                    snippet=evidence,
                ))
                continue

            # Strategy 2: token-window co-occurrence
            if text:
                window_evidence = _detect_cooccurrence_window(name_a, name_b, text)
                if window_evidence:
                    pairs.append(AliasPair(
                        entity_a=name_a,
                        entity_b=name_b,
                        confidence="medium",
                        source="cooccurrence",
                        snippet=window_evidence,
                    ))

    return pairs


def resolve_aliases(
    entities: list[dict],
    persons_full: dict,
    narrator=None,
    llm_confirmer=None,
    reveal_words: tuple[str, ...] = (),
    role_words: list[str] | None = None,
    pattern_templates: tuple[str, ...] = (),
) -> dict:
    stats = _empty_stats()
    role_words = role_words or []
    resolved: list[dict] = []
    consumed: set[int] = set()

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
            evidence = _detect_pattern_match(entity, candidate, persons_full, pattern_templates)
            if evidence:
                merged = _merge_entities(entity, candidate, evidence, persons_full, role_words=role_words)
                stats["merges_applied"] += 1
                stats["merges_by_method"]["pattern"] += 1
                consumed.add(candidate_index)
                break

            title = _detect_title_alias(entity, candidate, role_words)
            if title:
                merged = _merge_entities(entity, candidate, title, persons_full, role_words=role_words)
                stats["merges_applied"] += 1
                stats["merges_by_method"]["title_alias"] += 1
                consumed.add(candidate_index)
                break

            reveal = _detect_reveal_signal(entity, candidate, persons_full, reveal_words=reveal_words)
            if not reveal:
                continue

            if llm_confirmer is None:
                stats["ambiguous_pairs"] += 1
                continue

            stats["llm_attempts"] += 1
            try:
                decision = llm_confirmer({
                    "entity_a": entity,
                    "entity_b": candidate,
                    "evidence": reveal,
                    "persons_full": persons_full,
                }) or {}
            except Exception:
                stats["llm_failed"] += 1
                stats["ambiguous_pairs"] += 1
                continue

            if decision.get("same_person"):
                merged_evidence = {
                    "method": "llm",
                    "confidence": decision.get("confidence", "medium"),
                    "snippet": decision.get("evidence", reveal["snippet"]),
                }
                merged = _merge_entities(entity, candidate, merged_evidence, persons_full, role_words=role_words)
                stats["merges_applied"] += 1
                stats["merges_by_method"]["llm"] += 1
                stats["llm_confirmed"] += 1
                consumed.add(candidate_index)
                break

            stats["ambiguous_pairs"] += 1

        resolved.append(merged or entity)

    return {"entities": resolved, "narrator": narrator, "stats": stats}


def main() -> None:
    payload = json.load(sys.stdin)
    previous_outputs = payload.get("previous_outputs", {})
    all_stage_outputs = payload.get("all_stage_outputs", {})
    # New pipeline: entities come from merge-entities; fall back to resolve-clusters for compat.
    entity_source = (
        all_stage_outputs.get("merge-entities")
        or previous_outputs.get("merge-entities")
        or previous_outputs.get("resolve-clusters")
        or {}
    )
    entities = entity_source.get("entities", [])
    narrator = entity_source.get("narrator")
    # Relationships from relationship-extraction (empty list if stage not run yet).
    relationships: list[dict] = (
        all_stage_outputs.get("relationship-extraction", {}).get("relationships", [])
    )

    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    spacy_model = ctx.get("spacy_model", "en_core_web_lg")
    export_categories = ctx.get("export", {}).get("categories", {})
    language = export_categories.get("language") or infer_language(spacy_model)
    lang_cfg = load_lang_config(language)
    reveal_words = tuple(lang_cfg.get("reveal_words", ()))
    pattern_templates = tuple(lang_cfg.get("alias_pattern_templates", ()))
    role_words: list[str] = list(ctx.get("role_words", []))
    cue_role_words = [w.lower() for w in lang_cfg.get("person_cue_words", [])]
    role_words = list(dict.fromkeys(role_words + cue_role_words))  # dedup, preserve order

    persons_full = {}
    try:
        paths = _paths_from_payload(payload)
        persons_full = _load_persons_full(paths.processing)
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
        ollama_url = os.environ.get("OLLAMA_URL", _OLLAMA_URL)
        llm_model = ctx.get("llm_model", "mistral")
        if _check_ollama_available(ollama_url):
            llm_confirmer = make_ollama_confirmer(llm_model, ollama_url, timeout=30)
        else:
            warnings.warn(
                f"Ollama not available at {ollama_url} — LLM alias confirmation skipped.",
                stacklevel=1,
            )

    result = resolve_aliases(
        entities, persons_full=persons_full, narrator=narrator,
        llm_confirmer=llm_confirmer, reveal_words=reveal_words,
        role_words=role_words, pattern_templates=pattern_templates,
    )
    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
