#!/usr/bin/env python3
"""Standalone relationship classifier: calls Ollama directly, no Studio subprocess.

Usage:
    python scripts/classify_relationships.py --book library/.../book.yaml
    python scripts/classify_relationships.py --book library/.../book.yaml --model qwen2.5
    python scripts/classify_relationships.py --book library/.../book.yaml --dry-run

Input:  processing_output/<slug>/relationships.json
Output: processing_output/<slug>/relationships_classified.json

Saves incrementally after each pair. Resumes if output file already exists.
"""
import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wiki_creator.paths import book_paths_from_yaml
from scripts.relationship_classifier_validator import (
    check_relationship_type_valid,
    check_evidence_contains_both_names,
    check_evolution_not_generic,
)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MAX_ATTEMPTS = 3
_NON_INTERPERSONAL_TYPES = frozenset({"PLACE", "OTHER"})

# Verbatim system prompt from .studio/agents/relationship-classifier.agent.yaml
SYSTEM_PROMPT = """\
Respond with ONLY a valid JSON object. No markdown fences, no explanation, no other text.

You classify the relationship between two characters in a novel.

You receive input with:
- entity_a: name of character A
- entity_b: name of character B
- cooccurrence_count: number of times they appear together
- sample_contexts: list of short text excerpts where both appear
- novel_summary: (optional) a short narrative summary of the novel for context

When novel_summary is provided, use it as background context only — do NOT let it override
the specific relationship type visible in the excerpts.
Choose the MOST SPECIFIC relationship type.
Use "employeur/employé" ONLY when a clear hierarchical employment relationship is the PRIMARY dynamic.
Allies, friends, family, and romantic interests MUST use their specific type.
When in doubt between two types, choose the more specific one.

CRITICAL — co-occurrence vs direct interaction:
Before assigning a relationship_type, verify that at least one excerpt shows entity_a and entity_b
interacting directly (speaking to each other, acting on each other, being in the same scene together
with a meaningful exchange). If the excerpts only show that both characters appear in the same chapter
or are mentioned in proximity WITHOUT a direct interaction between them, you MUST return
relationship_type: null. Do NOT infer a relationship from co-occurrence alone.

Return exactly:
{
  "relationship_type": "famille|mentor/protégé|amoureux|antagoniste|allié|employeur/employé|ami|connaissance|autre|null",
  "direction": "symétrique|A→B|B→A|null",
  "evolution": "one sentence describing HOW the relationship changes across the provided chapters, or null if no change is observable — do NOT write \\"relation stable\\" or any equivalent filler",
  "key_moments": ["chXX: short description"],
  "evidence": "verbatim sentence or short passage from sample_contexts that best demonstrates the direct interaction between entity_a and entity_b — must contain both names or clear references to both"
}

Rules:
- Base your answer on the provided excerpts and novel_summary
- Do not invent facts
- Return valid JSON only
- key_moments must reference ONLY events explicitly present in the provided sample_contexts
- The \\"chXX:\\" prefix must match the chapter ID from the excerpt header
- For pairs with cooccurrence_count >= 5: you MUST include at least 1 key_moment extracted from sample_contexts
- If no specific moment can be identified despite searching all excerpts, return: [\\"no specific moment identifiable in provided excerpts\\"]
- evidence must be a verbatim excerpt from sample_contexts showing BOTH entity_a and entity_b; if relationship_type is null, set evidence to null\
"""


def call_ollama(prompt: str, model: str, timeout: int = 120) -> str | None:
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 300},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read()).get("response", "")
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return None  # OSError covers socket.timeout; URLError covers connection errors


def _should_classify(pair: dict, entity_types: dict[str, str]) -> bool:
    for key in ("entity_a", "entity_b"):
        if entity_types.get(pair.get(key, ""), "") in _NON_INTERPERSONAL_TYPES:
            return False
    return True


def _validate(clf: dict, pair: dict) -> list[str]:
    # Local wrapper: returns list[str] of errors.
    # The validator module's validate_classification() returns a dict — not used here.
    errors: list[str] = []
    errors += check_relationship_type_valid(clf)
    errors += check_evolution_not_generic(clf)
    errors += check_evidence_contains_both_names(clf, pair)  # pair must have entity_a, entity_b
    return errors


def classify_pair(
    pair: dict,
    *,
    model: str,
    novel_summary: str | None,
    dry_run: bool = False,
) -> dict:
    """Classify one pair. Returns enriched pair on success, original pair on failure/dry-run.

    Note: Caller is responsible for filtering non-interpersonal pairs via _should_classify.
    """
    if dry_run:
        return pair

    user_msg: dict = {
        "entity_a": pair.get("entity_a", ""),
        "entity_b": pair.get("entity_b", ""),
        "cooccurrence_count": pair.get("cooccurrence_count", 0),
        "sample_contexts": pair.get("sample_contexts", []),
    }
    if novel_summary:
        user_msg["novel_summary"] = novel_summary

    prompt = SYSTEM_PROMPT + "\n\n" + json.dumps(user_msg, ensure_ascii=False)

    for attempt in range(MAX_ATTEMPTS):
        raw = call_ollama(prompt, model=model)
        if raw is None:
            continue
        try:
            clf = json.loads(raw)
        except json.JSONDecodeError:
            continue
        errors = _validate(clf, pair)
        if not errors:
            return {**pair, **clf}
        if attempt < MAX_ATTEMPTS - 1:
            print(
                f"  [RETRY {attempt + 1}] {pair.get('entity_a', '')}↔{pair.get('entity_b', '')}: {errors[0]}",
                file=sys.stderr,
            )

    print(
        f"  [WARN] classification failed after {MAX_ATTEMPTS} attempts: "
        f"{pair.get('entity_a', '')}↔{pair.get('entity_b', '')}",
        file=sys.stderr,
    )
    return pair


def _load_done_keys(output_path: Path) -> tuple[set[tuple[str, str]], list[dict]]:
    """Load already-classified pairs from output file. Returns (done_keys, pairs)."""
    if not output_path.exists():
        return set(), []
    try:
        data = json.loads(output_path.read_text(encoding="utf-8"))
        pairs = data.get("relationships", [])
        keys = {(p["entity_a"], p["entity_b"]) for p in pairs}
        return keys, pairs
    except (json.JSONDecodeError, KeyError):
        return set(), []


def _save(output_path: Path, base: dict, classified: list[dict]) -> None:
    out = {**base, "relationships": classified}
    output_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Classify relationships via direct Ollama calls."
    )
    parser.add_argument(
        "--book", required=True,
        help="Path to book YAML, e.g. library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml",
    )
    parser.add_argument("--model", default=os.environ.get("WIKI_MODEL", "qwen2.5"))
    parser.add_argument("--dry-run", action="store_true", help="Skip Ollama calls, pass pairs through unchanged")
    args = parser.parse_args()

    book_paths = book_paths_from_yaml(args.book)
    input_path = book_paths.processing / "relationships.json"
    output_path = book_paths.processing / "relationships_classified.json"

    if not input_path.exists():
        print(f"[ERROR] Input not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(input_path.read_text(encoding="utf-8"))
    relationships = data.get("relationships", [])
    entity_types = {e["canonical_name"]: e.get("type", "") for e in data.get("entities", [])}
    base = {k: v for k, v in data.items() if k != "relationships"}

    with open(args.book, encoding="utf-8") as f:
        book_cfg = yaml.safe_load(f) or {}
    novel_summary = book_cfg.get("novel_summary") or None

    done_keys, classified = _load_done_keys(output_path)
    if done_keys:
        print(f"[classify-relationships] Resuming — {len(done_keys)} pairs already done", file=sys.stderr)

    to_classify = [r for r in relationships if (r["entity_a"], r["entity_b"]) not in done_keys]
    skip_count = len(relationships) - len(to_classify)
    classifiable = sum(1 for r in to_classify if _should_classify(r, entity_types))

    print(
        f"[classify-relationships] {len(relationships)} pairs total | "
        f"{skip_count} skipped (already done) | "
        f"{classifiable} to classify | model={args.model}",
        file=sys.stderr,
    )

    try:
        for i, pair in enumerate(to_classify, 1):
            label = f"{pair.get('entity_a', '?')}↔{pair.get('entity_b', '?')}"
            if not _should_classify(pair, entity_types):
                print(f"  [SKIP] {label} (non-interpersonal type)", file=sys.stderr)
                classified.append(pair)
            else:
                print(f"  [CLF]  {label} ({i}/{len(to_classify)})", file=sys.stderr, end="", flush=True)
                result = classify_pair(pair, model=args.model, novel_summary=novel_summary, dry_run=args.dry_run)
                classified.append(result)
                status = result.get("relationship_type") or "null"
                print(f" → {status}", file=sys.stderr)
            _save(output_path, base, classified)
    except KeyboardInterrupt:
        print(f"\n[classify-relationships] Interrupted — {len(classified)} pairs saved", file=sys.stderr)

    succeeded = sum(1 for r in classified if r.get("relationship_type") is not None)
    print(
        f"\n[classify-relationships] Done — {len(classified)} total, {succeeded} classified",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
