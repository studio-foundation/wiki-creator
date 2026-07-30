#!/usr/bin/env python3
"""Deterministic half of the validate-wiki-run audit (no LLM, no network).

    python scripts/audit_run.py metrics     --book <book.yaml>
    python scripts/audit_run.py gt-validate --book <book.yaml> [--from-wiki | --pages FILE]
    python scripts/audit_run.py trace       --book <book.yaml> --terms "Aelin" "Terrasen"
    python scripts/audit_run.py coverage    --book <book.yaml>
    python scripts/audit_run.py batch-stats --book <book.yaml>
    python scripts/audit_run.py providers

Every path is resolved from the book YAML (wiki_creator/paths.py); the
ground-truth corpus resolves to the tome subdirectory when one exists.

gt-validate page sources, one per corpus gate:
- default: processing_output/<slug>/wiki_pages.json (the fresh run);
- --from-wiki: pages rebuilt from the rendered output/<slug>/*.wiki — gate 1,
  a clean committed run must produce zero violations;
- --pages FILE: any JSON page list — gate 2, poisoned pages that must be
  flagged (a corpus with no teeth is worse than none).

Exit codes: gt-validate exits 1 on violations (0 on advisories only);
everything else reports and exits 0. Pure logic in wiki_creator/audit.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from wiki_creator import audit
from wiki_creator.ground_truth import load_entries, resolve_gt_dir
from wiki_creator.paths import book_paths_from_yaml


def _book_ctx(book: str):
    paths = book_paths_from_yaml(book)
    slug = paths.processing.name
    return paths, slug


def _load_gt(paths, slug):
    gt_dir = resolve_gt_dir(paths.series_dir, slug)
    if gt_dir is None:
        return None, None, None
    entries, by_entity = load_entries(gt_dir)
    return gt_dir, entries, by_entity


def _known_issues(paths) -> dict | None:
    ki = paths.series_dir / "audits" / "known_issues.json"
    return json.loads(ki.read_text()) if ki.exists() else None


def cmd_metrics(args) -> int:
    paths, _ = _book_ctx(args.book)
    pages = audit.load_pages(paths.processing / "wiki_pages.json")
    result = audit.page_metrics(pages, _known_issues(paths))
    for r in result["rows"]:
        issues = ", ".join(r["issues"]) if r["issues"] else "OK"
        print(f"{r['title'][:30]:<30} {str(r['importance']):<10} "
              f"{str(r['entity_type']):<8} ib={r['infobox_len']} {r['lang']} | {issues}")
    print()
    for k, v in result["summary"].items():
        print(f"{k}: {v}")
    return 0


def cmd_gt_validate(args) -> int:
    paths, slug = _book_ctx(args.book)
    gt_dir, entries, by_entity = _load_gt(paths, slug)
    if entries is None:
        print(f"No ground-truth corpus for {slug} — step n/a (say so in the audit).")
        return 2
    if args.pages:
        pages = audit.load_pages(args.pages)
        source = args.pages
    elif args.from_wiki:
        pages = audit.pages_from_wiki_dir(paths.output)
        source = str(paths.output)
    else:
        pages = audit.load_pages(paths.processing / "wiki_pages.json")
        source = str(paths.processing / "wiki_pages.json")
    print(f"=== GROUND-TRUTH VALIDATION ===\ncorpus: {gt_dir}\npages:  {source}\n")

    results = audit.validate_ground_truth(pages, entries, by_entity)
    violations = advisories = 0
    for r in results:
        if r.violations:
            violations += len(r.violations)
            print(f"❌ {r.title}")
            for v in r.violations:
                print(f"   {v}")
        elif r.advisories:
            print(f"⚠️  {r.title}")
        else:
            print(f"✅ {r.title}")
        for a in r.advisories:
            advisories += 1
            print(f"   ℹ {a}")
    print(f"\nTotal ground-truth violations: {violations}")
    print(f"Weak signals (not counted, known_relations not exhaustive): {advisories}")
    return 1 if violations else 0


def cmd_trace(args) -> int:
    paths, _ = _book_ctx(args.book)
    stages = audit.default_stage_files(paths.processing, paths.wiki_inputs)
    traced = audit.trace_terms(args.terms, stages)
    print("=== UPSTREAM TRACE ===\n")
    for term, info in traced.items():
        print(f"--- Term: '{term}' ---")
        for name, found in info["stages"]:
            status = "✓" if found else ("?" if found is None else "·")
            marker = " ⬅ INTRODUCED HERE" if info["first_seen"] == name and found else ""
            print(f"  {status} {name}{marker}")
        if info["first_seen"]:
            print(f"  → Responsible component: {info['first_seen']}\n")
        else:
            print("  → Not found upstream — pure LLM hallucination at generation\n")
    return 0


def cmd_coverage(args) -> int:
    paths, _ = _book_ctx(args.book)
    cov = audit.coverage(paths.processing, paths.wiki_inputs)
    print("=== COVERAGE ===\n")
    if cov["missing_from_pages"]:
        print(f"Batch entities WITHOUT a generated page ({len(cov['missing_from_pages'])}):")
        for name in cov["missing_from_pages"]:
            reason = "_failed" if name in cov["failed_pages"] else "page absent"
            print(f"  ✗ {name} — {reason}")
    else:
        print("Every batch entity has a generated page ✓")
    if cov["failed_pages"]:
        print(f"\n_failed pages ({len(cov['failed_pages'])}):")
        for name in cov["failed_pages"]:
            print(f"  ✗ {name}")
    if cov["filtered_before_batch"]:
        print(f"\nClassified but filtered before the batches ({len(cov['filtered_before_batch'])}):")
        for name in cov["filtered_before_batch"]:
            print(f"  ○ {name}")
    print(f"\nSummary: {len(cov['batch_entities'])} batch entities, "
          f"{len(cov['pages'])} pages, {len(cov['failed_pages'])} _failed")
    return 0


def cmd_batch_stats(args) -> int:
    paths, slug = _book_ctx(args.book)
    _, _, by_entity = _load_gt(paths, slug)
    stats = audit.batch_stats(paths.wiki_inputs, by_entity)
    print("=== WEAK ENTITIES ===\n")
    weak = stats["weak"]
    if weak:
        for r in sorted(weak, key=lambda x: len(x["issues"]) + len(x["mismatches"]), reverse=True):
            print(f"⚠ {r['name']} ({r['rels']} rels): {'; '.join(r['issues'])}")
            for m in r["mismatches"]:
                print(f"   REL_TYPE_GT_MISMATCH: {m}")
    else:
        print("No weak entity detected ✓")
    clean = [r["name"] for r in stats["entities"] if not r["issues"] and not r["mismatches"]]
    if clean:
        print(f"\nClean entities ({len(clean)}): {', '.join(clean)}")
    print("\n=== GLOBAL ===")
    for k, v in stats["global"].items():
        print(f"{k}: {v}")
    return 0


def cmd_providers(args) -> int:
    mix = audit.provider_mix(Path.cwd())
    for name, found in mix.items():
        print(f"{name:30} {found.get('provider', '?')}/{found.get('model', '?')}")
    print("\nNB: the book YAML can override a stage (e.g. generation.chapter_summary.llm_model) — check it.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic run-audit checks")
    sub = parser.add_subparsers(dest="cmd", required=True)

    for name, fn, needs_book in [
        ("metrics", cmd_metrics, True),
        ("gt-validate", cmd_gt_validate, True),
        ("trace", cmd_trace, True),
        ("coverage", cmd_coverage, True),
        ("batch-stats", cmd_batch_stats, True),
        ("providers", cmd_providers, False),
    ]:
        p = sub.add_parser(name)
        p.set_defaults(fn=fn)
        if needs_book:
            p.add_argument("--book", required=True, help="Path to a book YAML config")
    sub.choices["gt-validate"].add_argument("--from-wiki", action="store_true",
                                            help="pages rebuilt from output/<slug>/*.wiki (gate 1)")
    sub.choices["gt-validate"].add_argument("--pages",
                                            help="explicit JSON page list (gate 2: poison set)")
    sub.choices["trace"].add_argument("--terms", nargs="+", required=True)

    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
