#!/usr/bin/env python3
"""
Orchestrator for wiki creation pipeline.

Usage:
    python run_wiki.py --book books/carlos-ruiz-zafon/le-jeu-de-lange.yaml
    python run_wiki.py --book books/carlos-ruiz-zafon/le-jeu-de-lange.yaml --restart wiki-resolution
    python run_wiki.py --book books/carlos-ruiz-zafon/le-jeu-de-lange.yaml --retries 5
    python run_wiki.py --book books/carlos-ruiz-zafon/le-jeu-de-lange.yaml --status
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

PIPELINES = ["wiki-extraction", "wiki-resolution", "wiki-generation"]

REQUIRED_FILES = {
    "wiki-extraction": [
        "processing_output/splits.json",
        "processing_output/epub_data.json",
    ],
    "wiki-resolution": [
        "processing_output/entities_classified.json",
    ],
    "wiki-generation": [],
}


def book_slug(book_path: str) -> str:
    return Path(book_path).stem


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


def check_outputs(pipeline: str) -> list[str]:
    """Return list of missing output files for a pipeline."""
    return [f for f in REQUIRED_FILES.get(pipeline, []) if not os.path.exists(f)]


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
    parser.add_argument("--status", action="store_true", help="Show run status and exit")
    args = parser.parse_args()

    if args.status:
        print_status(args.book)
        return

    state = load_state(args.book)

    # Determine start pipeline
    start_idx = 0
    if args.restart:
        start_idx = PIPELINES.index(args.restart)
        # Mark restarted pipeline and all subsequent as pending
        for pipeline in PIPELINES[start_idx:]:
            state.setdefault("stages", {}).pop(pipeline, None)
        save_state(args.book, state)

    for pipeline in PIPELINES[start_idx:]:
        stage_state = state.setdefault("stages", {}).get(pipeline, {})

        # Skip if already completed (unless we're restarting)
        if stage_state.get("status") == "completed":
            print(f"  {pipeline}: already completed, skipping")
            continue

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
                missing = check_outputs(pipeline)
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
