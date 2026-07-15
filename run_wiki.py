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
    python run_wiki.py --series library/christopher_paolini/inheritance
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from wiki_creator.paths import book_paths_from_yaml
from wiki_creator.series import discover_series_books

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
            str(p.processing / "registry.json"),
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
            str(p.processing / "registry.json"),
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


# Scripts to run before a pipeline (pre-steps). Each pipeline maps to a list
# of commands, run in order; a non-zero return code aborts the run.
PRE_STEPS: dict[str, list[list[str]]] = {
    "wiki-resolution": [
        ["python", "scripts/chapter_summary.py", "--book"],
    ],
    "wiki-preparation": [
        ["python", "scripts/classify_relationships.py", "--book"],
        ["python", "scripts/build_event_layer.py", "--book"],
    ],
    "wiki-generation": [
        ["python", "scripts/generate_wiki_pages.py", "--book"],
        ["python", "scripts/generate_book_synopsis.py", "--book"],
        ["python", "scripts/generate_event_pages.py", "--book"],
        ["python", "scripts/consolidate_editorial_stance.py", "--book"],
    ],
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


def run_book(book_path: str, *, restart: str | None, retries: int, clean: bool) -> None:
    """Run the full pipeline for one book. Exits the process on failure."""
    state = load_state(book_path)

    start_idx = 0
    if restart:
        start_idx = PIPELINES.index(restart)
        # Mark restarted pipeline and all subsequent as pending
        for pipeline in PIPELINES[start_idx:]:
            state.setdefault("stages", {}).pop(pipeline, None)
        save_state(book_path, state)

    if clean:
        outputs = clean_files(book_path)
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
            missing = check_outputs(pipeline, book_path)
            if not missing:
                print(f"  {pipeline}: already completed, skipping")
                continue
            print(f"  {pipeline}: outputs missing ({', '.join(missing)}), re-running")
            state["stages"][pipeline] = {}
            save_state(book_path, state)

        # Run pre-steps before the pipeline (e.g. generate_wiki_pages.py before wiki-generation)
        for pre_step in PRE_STEPS.get(pipeline, []):
            pre_cmd = pre_step + [book_path]
            print(f"\n[pre-step] {' '.join(pre_cmd)}", flush=True)
            pre_result = subprocess.run(pre_cmd)
            if pre_result.returncode != 0:
                print(f"\n[ERROR] Pre-step failed for {pipeline}. Aborting.")
                sys.exit(1)

        attempt = 0
        success = False
        while attempt < retries:
            attempt += 1
            state.setdefault("stages", {})[pipeline] = {
                "status": "running",
                "attempt": attempt,
            }
            save_state(book_path, state)

            ok = run_pipeline(pipeline, book_path)

            if ok:
                missing = check_outputs(pipeline, book_path)
                if missing:
                    print(f"\n[WARN] {pipeline} succeeded but expected files are missing:")
                    for f in missing:
                        print(f"  {f}")
                    ok = False

            if ok:
                state["stages"][pipeline] = {"status": "completed", "attempt": attempt}
                save_state(book_path, state)
                success = True
                break
            else:
                state["stages"][pipeline] = {
                    "status": "failed",
                    "attempt": attempt,
                }
                save_state(book_path, state)
                if attempt < retries:
                    print(f"\n  {pipeline} failed (attempt {attempt}/{retries}), retrying...")

        if not success:
            print(f"\n[ERROR] {pipeline} failed after {retries} attempts. Aborting.")
            print(f"  Tip: fix the issue then run: python run_wiki.py --book {book_path} --restart {pipeline}")
            sys.exit(1)

    print(f"\nDone! All pipelines completed for {book_path}.")
    print_status(book_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Wiki creation orchestrator")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--book", help="Path to a single book YAML config")
    src.add_argument(
        "--series",
        help="Path to a series dir (library/<author>/<series>); runs every tome "
        "under books/ in reading order, propagating the accumulated series registry",
    )
    parser.add_argument("--restart", choices=PIPELINES, help="Restart from this pipeline (single-book only)")
    parser.add_argument("--retries", type=int, default=3, help="Max attempts per pipeline")
    parser.add_argument("--clean", action="store_true", help="Delete outputs of restarted stages before running")
    parser.add_argument("--status", action="store_true", help="Show run status and exit")
    parser.add_argument(
        "--max-chapters",
        type=int,
        help="Subset test runs: cap extraction to the first N chapters (sets WIKI_MAX_CHAPTERS "
        "for every stage). Combine with --restart wiki-extraction --clean to re-slice an existing run.",
    )
    args = parser.parse_args()

    if args.max_chapters is not None:
        # Single source of truth: parse_epub reads WIKI_MAX_CHAPTERS; every stage
        # downstream just consumes the already-truncated artifacts.
        os.environ["WIKI_MAX_CHAPTERS"] = str(args.max_chapters)
        print(f"[subset] limiting run to the first {args.max_chapters} chapters")

    if args.series:
        try:
            books = discover_series_books(args.series)
        except FileNotFoundError as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            sys.exit(1)
        if args.status:
            for book in books:
                print_status(str(book))
            return
        print(f"Series run: {len(books)} tomes in {args.series}")
        for i, book in enumerate(books, 1):
            print(f"\n{'#'*60}\n# Tome {i}/{len(books)}: {book}\n{'#'*60}")
            run_book(str(book), restart=None, retries=args.retries, clean=args.clean)
        print(f"\nDone! Series complete ({len(books)} tomes).")
        return

    if not Path(args.book).exists():
        print(f"[ERROR] Book config not found: {args.book}", file=sys.stderr)
        sys.exit(1)

    if args.status:
        print_status(args.book)
        return

    run_book(args.book, restart=args.restart, retries=args.retries, clean=args.clean)


if __name__ == "__main__":
    main()
