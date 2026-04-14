#!/usr/bin/env python3
"""
Orchestrator for wiki creation pipeline.

Usage:
    python run_wiki.py --book books/carlos-ruiz-zafon/le-jeu-de-lange.yaml
    python run_wiki.py --book books/carlos-ruiz-zafon/le-jeu-de-lange.yaml --restart wiki-resolution
    python run_wiki.py --book books/carlos-ruiz-zafon/le-jeu-de-lange.yaml --restart wiki-preparation
    python run_wiki.py --book books/carlos-ruiz-zafon/le-jeu-de-lange.yaml --restart pages-export
    python run_wiki.py --book books/carlos-ruiz-zafon/le-jeu-de-lange.yaml --retries 5
    python run_wiki.py --book books/carlos-ruiz-zafon/le-jeu-de-lange.yaml --status
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from wiki_creator.paths import book_paths_from_yaml

PIPELINES = ["wiki-extraction", "wiki-resolution", "wiki-preparation", "wiki-generation", "pages-export"]


def required_files(book_path: str) -> dict[str, list[str]]:
    p = book_paths_from_yaml(book_path)
    return {
        "wiki-extraction": [
            str(p.processing / "splits.json"),
            str(p.processing / "epub_data.json"),
        ],
        "wiki-resolution": [
            str(p.processing / "entities_classified.json"),
            str(p.processing / "chapter_summaries.json"),
        ],
        "wiki-preparation": [
            str(p.processing / "relationships_classified.json"),
            str(p.wiki_inputs),
        ],
        "wiki-generation": [
            str(p.processing / "wiki_pages.json"),
        ],
        "pages-export": [],
    }


def clean_files(book_path: str) -> dict[str, list[str]]:
    """Files to delete per pipeline when --clean is used.

    Intentionally differs from required_files(): chapter_summaries.json is
    owned by wiki-extraction (only depends on its output) so it is cleaned
    when restarting from wiki-extraction, but NOT when restarting from
    wiki-resolution or later.
    """
    p = book_paths_from_yaml(book_path)
    return {
        "wiki-extraction": [
            str(p.processing / "splits.json"),
            str(p.processing / "epub_data.json"),
            str(p.processing / "chapter_summaries.json"),
        ],
        "wiki-resolution": [
            str(p.processing / "entities_classified.json"),
        ],
        "wiki-preparation": [
            str(p.processing / "relationships_classified.json"),
            str(p.wiki_inputs),
        ],
        "wiki-generation": [
            str(p.processing / "wiki_pages.json"),
        ],
        "pages-export": [],
    }


# Scripts to run before a pipeline (pre-steps)
PRE_STEPS = {
    "wiki-resolution":  ["python", "scripts/chapter_summary.py", "--book"],
    "wiki-preparation": ["python", "scripts/classify_relationships.py", "--book"],
    "wiki-generation":  ["python", "scripts/generate_wiki_pages.py", "--book"],
}


def book_slug(book_path: str) -> str:
    p = Path(book_path)
    # e.g. sarah_j_maas__throne-of-glass__01-throne-of-glass
    return "__".join([p.parent.parent.parent.name, p.parent.parent.name, p.stem])


def state_path(book_path: str) -> Path:
    return Path(".wiki_runs") / book_slug(book_path) / "current_run.json"


def load_state(book_path: str) -> dict:
    path = state_path(book_path)
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {"book": book_slug(book_path), "stages": {}}


def save_state(book_path: str, state: dict) -> None:
    path = state_path(book_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(state, f, indent=2)


def run_pipeline(pipeline: str, book_path: str, extra_args: list[str] | None = None) -> bool:
    """Run a Studio pipeline. Returns True on success."""
    cmd = [
        "studio", "run", pipeline,
        "--input-file", book_path,
        "--live",
    ]
    if extra_args:
        cmd.extend(extra_args)
    print(f"\n{'='*60}", flush=True)
    print(f"Running: {' '.join(cmd)}", flush=True)
    print(f"{'='*60}", flush=True)
    result = subprocess.run(cmd)
    return result.returncode == 0


def check_outputs(pipeline: str, book_path: str) -> list[str]:
    """Return list of missing output files for a pipeline."""
    return [f for f in required_files(book_path).get(pipeline, []) if not os.path.exists(f)]


def print_status(book_path: str) -> None:
    state = load_state(book_path)
    print(f"\nBook: {state.get('book', '?')}")
    for pipeline in PIPELINES:
        stage_state = state.get("stages", {}).get(pipeline, {})
        status = stage_state.get("status", "not_started")
        attempt = stage_state.get("attempt", 0)
        suffix = f" (attempt {attempt})" if attempt > 1 else ""
        print(f"  {pipeline}: {status}{suffix}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Wiki creation orchestrator")
    parser.add_argument("--book", required=True, help="Path to book YAML config")
    parser.add_argument("--restart", choices=PIPELINES, help="Restart from this pipeline")
    parser.add_argument("--retries", type=int, default=3, help="Max attempts per pipeline")
    parser.add_argument("--clean", action="store_true", help="Delete outputs of restarted stages before running")
    parser.add_argument("--status", action="store_true", help="Show run status and exit")
    args = parser.parse_args()

    if not Path(args.book).exists():
        print(f"[ERROR] Book config not found: {args.book}", file=sys.stderr)
        sys.exit(1)

    if args.status:
        print_status(args.book)
        return

    state = load_state(args.book)

    start_idx = 0
    if args.restart:
        start_idx = PIPELINES.index(args.restart)
        # Mark restarted pipeline and all subsequent as pending
        for pipeline in PIPELINES[start_idx:]:
            state.setdefault("stages", {}).pop(pipeline, None)
        save_state(args.book, state)

    if args.clean:
        outputs = clean_files(args.book)
        for pipeline in PIPELINES[start_idx:]:
            for path_str in outputs.get(pipeline, []):
                p = Path(path_str)
                if p.is_dir():
                    print(f"  [clean] removing dir {p}")
                    shutil.rmtree(p)
                elif p.exists():
                    print(f"  [clean] removing {p}")
                    p.unlink()

    for pipeline in PIPELINES[start_idx:]:
        stage_state = state.setdefault("stages", {}).get(pipeline, {})

        # Skip if already completed AND output files are still present
        if stage_state.get("status") == "completed":
            missing = check_outputs(pipeline, args.book)
            if not missing:
                print(f"  {pipeline}: already completed, skipping")
                continue
            print(f"  {pipeline}: outputs missing ({', '.join(missing)}), re-running")
            state["stages"][pipeline] = {}
            save_state(args.book, state)

        # Run pre-steps before the pipeline (e.g. generate_wiki_pages.py before wiki-generation)
        if pipeline in PRE_STEPS:
            pre_cmd = PRE_STEPS[pipeline] + [args.book]
            print(f"\n[pre-step] {' '.join(pre_cmd)}", flush=True)
            pre_result = subprocess.run(pre_cmd)
            if pre_result.returncode != 0:
                print(f"\n[ERROR] Pre-step failed for {pipeline}. Aborting.")
                sys.exit(1)

        attempt = 0
        success = False
        while attempt < args.retries:
            attempt += 1
            state.setdefault("stages", {})[pipeline] = {
                "status": "running",
                "attempt": attempt,
            }
            save_state(args.book, state)

            ok = run_pipeline(pipeline, args.book)

            if ok:
                missing = check_outputs(pipeline, args.book)
                if missing:
                    print(f"\n[WARN] {pipeline} succeeded but expected files are missing:")
                    for f in missing:
                        print(f"  {f}")
                    ok = False

            if ok:
                state["stages"][pipeline] = {"status": "completed", "attempt": attempt}
                save_state(args.book, state)
                success = True
                break
            else:
                state["stages"][pipeline] = {
                    "status": "failed",
                    "attempt": attempt,
                }
                save_state(args.book, state)
                if attempt < args.retries:
                    print(f"\n  {pipeline} failed (attempt {attempt}/{args.retries}), retrying...")

        if not success:
            print(f"\n[ERROR] {pipeline} failed after {args.retries} attempts. Aborting.")
            print(f"  Tip: fix the issue then run: python run_wiki.py --book {args.book} --restart {pipeline}")
            sys.exit(1)

    print("\nDone! All pipelines completed successfully.")
    print_status(args.book)


if __name__ == "__main__":
    main()
