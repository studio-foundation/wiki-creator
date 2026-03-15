"""Validate a NER dataset in JSONL format.

Each line must be a JSON object with:
  - "text": str
  - "entities": list of {"start": int, "end": int, "label": str, "text": str}

Validation rules:
  - text[start:end] must equal entity["text"]
  - start >= 0 and end <= len(text)
  - no overlapping spans (auto-resolved by keeping the longest span when resolve=True)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def resolve_overlaps(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove overlapping spans by keeping the longest one.

    When two spans overlap, the shorter one is dropped. In case of equal
    length, the one that starts earlier is kept.
    """
    if not entities:
        return entities

    # Sort by length descending, then by start ascending (stable tie-break)
    by_length = sorted(entities, key=lambda e: (-(e["end"] - e["start"]), e["start"]))

    kept: list[dict] = []
    for ent in by_length:
        start, end = ent["start"], ent["end"]
        # Accept this entity only if it doesn't overlap any already-kept span
        if not any(start < k["end"] and end > k["start"] for k in kept):
            kept.append(ent)

    # Restore original start-order
    kept.sort(key=lambda e: e["start"])
    return kept


def validate_example(example: dict[str, Any], *, resolve: bool = False) -> list[str]:
    """Return a list of error strings. Empty list means the example is valid.

    If *resolve* is True, overlapping spans are auto-fixed in-place (longest
    span wins) before validation, so overlap errors are never returned.
    """
    errors: list[str] = []

    if "text" not in example:
        errors.append("missing field: text")
        return errors
    if "entities" not in example:
        errors.append("missing field: entities")
        return errors

    text: str = example["text"]
    entities: list[dict] = example["entities"]

    # Auto-resolve overlaps before checking
    if resolve:
        example["entities"] = resolve_overlaps(entities)
        entities = example["entities"]

    # Validate each entity individually
    spans: list[tuple[int, int]] = []
    for i, ent in enumerate(entities):
        start = ent.get("start", 0)
        end = ent.get("end", 0)

        # Bounds check
        if start < 0 or end > len(text) or start >= end:
            errors.append(
                f"entity[{i}] offset out of bounds: [{start},{end}) in text of length {len(text)}"
            )
            continue

        # Text match check
        extracted = text[start:end]
        if extracted != ent.get("text", ""):
            errors.append(
                f"entity[{i}] text mismatch: text[{start}:{end}]={extracted!r} != {ent.get('text')!r}"
            )

        spans.append((start, end))

    # Overlap check (only on spans that passed bounds)
    spans.sort()
    for j in range(len(spans) - 1):
        a_start, a_end = spans[j]
        b_start, b_end = spans[j + 1]
        if b_start < a_end:
            errors.append(
                f"overlapping spans: [{a_start},{a_end}) and [{b_start},{b_end})"
            )

    return errors


def validate_dataset(
    examples: list[dict[str, Any]], *, resolve: bool = False
) -> dict[str, Any]:
    """Validate a list of examples and return aggregate stats."""
    valid_examples: list[dict] = []
    rejected = 0
    label_counts: dict[str, int] = {}

    for ex in examples:
        errors = validate_example(ex, resolve=resolve)
        if errors:
            rejected += 1
        else:
            valid_examples.append(ex)
            for ent in ex.get("entities", []):
                label = ent.get("label", "UNKNOWN")
                label_counts[label] = label_counts.get(label, 0) + 1

    return {
        "total": len(examples),
        "valid": len(valid_examples),
        "rejected": rejected,
        "label_counts": label_counts,
        "valid_examples": valid_examples,
    }


def _load_jsonl(path: Path) -> list[dict]:
    examples = []
    with open(path) as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                examples.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"  [WARN] {path.name}:{lineno}: JSON decode error: {e}", file=sys.stderr)
    return examples


def main(paths: list[Path], *, resolve: bool = False) -> None:
    all_examples: list[dict] = []
    for p in paths:
        examples = _load_jsonl(p)
        print(f"{p.name}: {len(examples)} examples loaded")
        all_examples.extend(examples)

    stats = validate_dataset(all_examples, resolve=resolve)

    print(f"\n--- Summary ---")
    print(f"Total   : {stats['total']}")
    print(f"Valid   : {stats['valid']}")
    print(f"Rejected: {stats['rejected']}")
    print(f"\nLabel distribution (valid examples):")
    for label, count in sorted(stats["label_counts"].items()):
        print(f"  {label:10s} {count}")

    if stats["rejected"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Validate NER dataset JSONL files")
    parser.add_argument("files", nargs="+", type=Path, help="JSONL files to validate")
    parser.add_argument(
        "--resolve-overlaps",
        action="store_true",
        help="Auto-fix overlapping spans by keeping the longest one",
    )
    args = parser.parse_args()
    main(args.files, resolve=args.resolve_overlaps)
