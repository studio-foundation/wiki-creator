#!/usr/bin/env python3
"""Relationship-classifier eval harness (STU-499).

Scores the relationship classifier's *typing quality* against a hand-labelled
gold fixture — the coverage the deterministic e2e goldens can't give (the stage
is LLM, non-deterministic) and the structural validator doesn't (it checks shape,
not correctness). It reports the two rates the classifier's known defects live in:

    false-null rate      real relations the gate wrongly drops to null (STU-495)
    hallucination rate   pure co-occurrence the classifier wrongly types
                         (the Westfall↔Kaltain false-positive)
    over-graded rate     typed pairs claiming a stronger confidence than the
                         excerpts support — a read presented as a fact (STU-476)

Run it BEFORE touching .studio/agents/relationship-classifier.agent.yaml so the
prompt changes from 472/476/477/495/496 are measured, not blind.

Two modes:

  1. Score an existing classified bundle offline — no LLM:
       python scripts/eval_relationship_classifier.py \
           --predictions library/.../processing_output/<slug>/relationships_classified.json

  2. Run the live classifier on the fixture's own excerpts, then score
     (needs the `studio` CLI + a model, like the coref/spaCy-gated paths):
       python scripts/eval_relationship_classifier.py --run --book library/.../01-throne-of-glass.yaml

Default fixture: tests/fixtures/relationship_eval/throne-of-glass-01.yaml.
Writes report.md (and, in --run mode, predictions.json) under --out.
Exit code is non-zero if any --max-*/--min-* threshold is violated (CI gate).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from wiki_creator.relationship_eval import (
    confidences_from_relationships,
    load_gold,
    predictions_from_relationships,
    render_report,
    score,
    score_confidence,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FIXTURE = PROJECT_ROOT / "tests/fixtures/relationship_eval/throne-of-glass-01.yaml"


def _predictions_from_file(path: Path) -> tuple[dict, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    relationships = data.get("relationships", data) if isinstance(data, dict) else data
    return predictions_from_relationships(relationships), confidences_from_relationships(relationships)


def _predictions_from_live_run(gold, book_yaml: Path | None) -> tuple[dict, dict]:
    """Invoke the studio classifier on each gold pair's own excerpts."""
    from scripts.relationship_extraction import _run_studio_classifier_item

    novel_summary = ""
    if book_yaml is not None:
        cfg = yaml.safe_load(book_yaml.read_text(encoding="utf-8")) or {}
        novel_summary = cfg.get("novel_summary") or ""

    predictions: dict[tuple[str, str], str | None] = {}
    confidences: dict[tuple[str, str], str | None] = {}
    for gp in gold:
        pair = {
            "entity_a": gp.entity_a,
            "entity_b": gp.entity_b,
            "cooccurrence_count": gp.cooccurrence_count,
            "sample_contexts": list(gp.sample_contexts),
        }
        print(f"  [CLF] {gp.entity_a}↔{gp.entity_b}", file=sys.stderr, end="", flush=True)
        clf = _run_studio_classifier_item(pair, novel_summary=novel_summary, additional_context="")
        if clf and not clf.get("error"):
            predictions[gp.key] = clf.get("relationship_type")
            confidences[gp.key] = clf.get("confidence")
        else:
            err = clf.get("error", "unknown") if clf else "no response"
            print(f"  [WARN] classifier failed: {err}", file=sys.stderr)
            continue
        print(
            f" → {predictions[gp.key] or 'null'} ({confidences[gp.key] or 'ungraded'})",
            file=sys.stderr,
        )
    return predictions, confidences


def _check_thresholds(metrics: dict, confidence_metrics: dict, args) -> list[str]:
    """Return threshold violations (empty = pass)."""
    failures = []
    ta = metrics["type_accuracy"]
    fn = metrics["false_null_rate"]
    hl = metrics["hallucination_rate"]
    if args.min_type_accuracy is not None and ta is not None and ta < args.min_type_accuracy:
        failures.append(f"type_accuracy {ta:.2f} < min {args.min_type_accuracy:.2f}")
    if args.max_false_null is not None and fn is not None and fn > args.max_false_null:
        failures.append(f"false_null_rate {fn:.2f} > max {args.max_false_null:.2f}")
    if args.max_hallucination is not None and hl is not None and hl > args.max_hallucination:
        failures.append(f"hallucination_rate {hl:.2f} > max {args.max_hallucination:.2f}")
    og = confidence_metrics["overgraded_rate"]
    if args.max_overgraded is not None and confidence_metrics["scored"] and og > args.max_overgraded:
        failures.append(f"overgraded_rate {og:.2f} > max {args.max_overgraded:.2f}")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE, help="gold fixture YAML")
    parser.add_argument("--predictions", type=Path, help="score this classified bundle offline (no LLM)")
    parser.add_argument("--run", action="store_true", help="run the live classifier on the fixture excerpts")
    parser.add_argument("--book", type=Path, help="book YAML (for novel_summary in --run mode)")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "relationship_eval",
                        help="output directory for report.md / predictions.json")
    parser.add_argument("--min-type-accuracy", type=float, default=None)
    parser.add_argument("--max-false-null", type=float, default=None)
    parser.add_argument("--max-hallucination", type=float, default=None)
    parser.add_argument("--max-overgraded", type=float, default=None)
    args = parser.parse_args()

    if not args.predictions and not args.run:
        parser.error("choose a source: --predictions <file> (offline) or --run (live classifier)")

    gold = load_gold(args.fixture)

    if args.predictions:
        predictions, confidences = _predictions_from_file(args.predictions)
    else:
        predictions, confidences = _predictions_from_live_run(gold, args.book)

    metrics = score(gold, predictions)
    confidence_metrics = score_confidence(gold, confidences)
    report = render_report(args.fixture.stem, metrics, confidence_metrics)

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.md").write_text(report, encoding="utf-8")
    if args.run:
        (args.out / "predictions.json").write_text(
            json.dumps(
                {f"{a}||{b}": pred for (a, b), pred in predictions.items()},
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )

    print(report)
    print(f"[eval] report: {args.out / 'report.md'}", file=sys.stderr)

    failures = _check_thresholds(metrics, confidence_metrics, args)
    if failures:
        for f in failures:
            print(f"[eval] THRESHOLD FAILED: {f}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
