"""`wiki` — ergonomic front door over `studio run` (STU-597).

A thin launcher, zero sequencing: every command is one `studio run`/`studio
replay` (or a tome-by-tome loop for a series, like `make run-series`). It owns
no stage order — Studio does. It buys short book aliases, subcommand discovery,
and `--help`.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from wiki_creator import book_import, item_stream, library
from wiki_creator.series import discover_series_books

# Short pipeline verb -> Studio pipeline. `run` is the whole build; the rest are
# single-pipeline dev entries (each sequences nothing).
_PIPELINES = {
    "run": "wiki-full",
    "extraction": "wiki-extraction",
    "resolution": "wiki-resolution",
    "preparation": "wiki-preparation",
    "pages": "pages-export",
}


def _studio_command(pipeline: str, book_path: Path) -> list[str]:
    cmd = ["studio", "run", pipeline, "--input-file", str(book_path), "--live"]
    if pipeline != "wiki-full":
        cmd.append("--verbose")
    # Show each fan-out unit as it lands (Alice <=> Dodo — allies), STU-626.
    if item_stream.studio_supports_stream_items():
        cmd.append("--stream-items")
    return cmd


def _exec(cmd: list[str], *, dry_run: bool) -> int:
    print("$ " + " ".join(cmd))
    if dry_run:
        return 0
    if "--stream-items" in cmd:
        return item_stream.run_studio_with_stream(cmd)
    return subprocess.run(cmd).returncode


def _resolve_book_or_exit(query: str) -> Path | None:
    try:
        return library.resolve_book(query)
    except library.ResolutionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None


# --- book ------------------------------------------------------------------

def _cmd_book_pipeline(args: argparse.Namespace) -> int:
    book_path = _resolve_book_or_exit(args.book)
    if book_path is None:
        return 2
    if args.max_chapters is not None:
        os.environ["WIKI_MAX_CHAPTERS"] = str(args.max_chapters)
    return _exec(_studio_command(_PIPELINES[args.verb], book_path), dry_run=args.dry_run)


def _cmd_book_pages(args: argparse.Namespace) -> int:
    book_path = _resolve_book_or_exit(args.book)
    if book_path is None:
        return 2
    # A slice (--entities/--importance/--force) regenerates only some pages via
    # the standalone generator; bare `pages` runs the whole pages-export pipeline.
    if args.entities or args.importance or args.force:
        cmd = [sys.executable, "scripts/generate_wiki_pages.py", "--book", str(book_path)]
        if args.entities:
            cmd += ["--entities", *args.entities]
        if args.importance:
            cmd += ["--importance", args.importance]
        if args.force:
            cmd.append("--force")
        rc = _exec(cmd, dry_run=args.dry_run)
        if rc != 0:
            return rc
        # The slice writes wiki_pages.json only; re-export so the .wiki files
        # reflect it (assemble -> copyright-check -> wiki-export, from disk).
        return _exec(
            [sys.executable, "scripts/export_pages.py", "--book", str(book_path)],
            dry_run=args.dry_run,
        )
    if args.max_chapters is not None:
        os.environ["WIKI_MAX_CHAPTERS"] = str(args.max_chapters)
    return _exec(_studio_command("pages-export", book_path), dry_run=args.dry_run)


def _cmd_book_add(args: argparse.Namespace) -> int:
    enrich = (lambda title, author: _llm_summary(title, author)) if args.llm else None
    try:
        plan = book_import.generate_book(
            args.epub, root=args.dest, author_slug=args.author,
            series_slug=args.series, number=args.number,
            force=args.force, dry_run=args.dry_run, enrich=enrich,
        )
    except (FileNotFoundError, FileExistsError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    verb = "would write" if args.dry_run else "wrote"
    print(f"{verb} {plan.dest_epub}\n{verb} {plan.dest_yaml}")
    if args.dry_run:
        print("---\n" + plan.yaml_text, end="")
    return 0


# --- series ----------------------------------------------------------------

def _cmd_series(args: argparse.Namespace) -> int:
    try:
        series_dir = library.resolve_series(args.series_name)
    except library.ResolutionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.max_chapters is not None:
        os.environ["WIKI_MAX_CHAPTERS"] = str(args.max_chapters)
    for book_path in discover_series_books(library._PROJECT_ROOT / series_dir):
        rel = Path(book_path).relative_to(library._PROJECT_ROOT)
        print(f"=== {rel} ===")
        rc = _exec(_studio_command("wiki-full", rel), dry_run=args.dry_run)
        if rc != 0:
            return rc
    return 0


# --- top-level: ls / replay / status / logs --------------------------------

def _cmd_ls(args: argparse.Namespace) -> int:
    if args.series:
        for name, path in sorted(library.discover_series().items()):
            print(f"{name}\t{path}")
        return 0
    for book in library.discover_books():
        alias = f" ({', '.join(book.aliases)})" if book.aliases else ""
        print(f"{book.slug}{alias}\t{book.yaml_path}")
    return 0


def _cmd_replay(args: argparse.Namespace) -> int:
    cmd = ["studio", "replay", args.run_id]
    if args.stage is not None:
        cmd += ["--restart", "--stage", args.stage]
    return _exec(cmd, dry_run=args.dry_run)


def _cmd_status(args: argparse.Namespace) -> int:
    cmd = ["studio", "status"] + ([args.run_id] if args.run_id else [])
    return _exec(cmd, dry_run=args.dry_run)


def _cmd_logs(args: argparse.Namespace) -> int:
    return _exec(["studio", "logs", args.run_id], dry_run=args.dry_run)


def _llm_summary(title: str, author: str | None) -> str:
    """Draft a novel_summary for --llm. Low-risk prose, flagged for reader review."""
    import anthropic

    by = f" by {author}" if author else ""
    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY from env
    msg = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=400,
        messages=[{
            "role": "user",
            "content": f'Write a 4-6 sentence plot summary of the novel "{title}"{by}. '
                       "Prose only, no preamble, no spoilers past the first act.",
        }],
    )
    return "".join(getattr(b, "text", "") for b in msg.content).strip()


def _build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    # SUPPRESS so a subparser's default can't clobber the value parsed at the
    # top level (`wiki --dry-run book ...`); read via getattr in main.
    common.add_argument(
        "--dry-run", action="store_true", default=argparse.SUPPRESS,
        help="print the studio command(s) instead of running",
    )

    parser = argparse.ArgumentParser(prog="wiki", description=__doc__, parents=[common])
    sub = parser.add_subparsers(dest="command", required=True)

    ls = sub.add_parser("ls", parents=[common], help="list books (or series with --series)")
    ls.add_argument("--series", action="store_true", help="list series instead")
    ls.set_defaults(func=_cmd_ls)

    # book <verb> ...
    book = sub.add_parser("book", parents=[common], help="operate on one book")
    bsub = book.add_subparsers(dest="verb", required=True)
    for verb in ("run", "extraction", "resolution", "preparation"):
        p = bsub.add_parser(verb, parents=[common], help=f"studio run {_PIPELINES[verb]}")
        p.add_argument("book", help="book slug, alias, series or author")
        p.add_argument("--max-chapters", type=int, help="cap extraction (WIKI_MAX_CHAPTERS)")
        p.set_defaults(func=_cmd_book_pipeline)

    pages = bsub.add_parser("pages", parents=[common], help="pages-export, or a slice with --entities/--importance")
    pages.add_argument("book", help="book slug, alias, series or author")
    pages.add_argument("--max-chapters", type=int, help="cap extraction (WIKI_MAX_CHAPTERS)")
    pages.add_argument("--entities", nargs="+", metavar="NAME", help="regenerate only these pages")
    pages.add_argument("--importance", choices=["principal", "secondary", "figurant"], help="regenerate only this tier")
    pages.add_argument("--force", action="store_true", help="overwrite existing pages")
    pages.set_defaults(func=_cmd_book_pages)

    add = bsub.add_parser("add", parents=[common], help="import an epub and scaffold its YAML")
    add.add_argument("epub", help="path to the epub to import")
    add.add_argument("--dest", default="library", help="library root (default: library)")
    add.add_argument("--author", help="override author slug (else from epub metadata)")
    add.add_argument("--series", help="override series slug (else from epub title)")
    add.add_argument("--number", default="01", help="tome number prefix (default: 01)")
    add.add_argument("--llm", action="store_true", help="draft a novel_summary via LLM")
    add.add_argument("--force", action="store_true", help="overwrite an existing YAML")
    add.set_defaults(func=_cmd_book_add)

    series = sub.add_parser("series", parents=[common], help="run wiki-full over a series in reading order")
    series.add_argument("verb", choices=["run"], help="only 'run'")
    series.add_argument("series_name", metavar="series", help="series name or substring")
    series.add_argument("--max-chapters", type=int, help="cap extraction (WIKI_MAX_CHAPTERS)")
    series.set_defaults(func=_cmd_series)

    replay = sub.add_parser("replay", parents=[common], help="replay a run, or restart it from a stage")
    replay.add_argument("run_id", help="run id (from `wiki status`)")
    replay.add_argument("--stage", help="restart from this stage (index or name)")
    replay.set_defaults(func=_cmd_replay)

    status = sub.add_parser("status", parents=[common], help="show run status")
    status.add_argument("run_id", nargs="?", help="a run id, or omit for the list")
    status.set_defaults(func=_cmd_status)

    logs = sub.add_parser("logs", parents=[common], help="show a run's log")
    logs.add_argument("run_id", help="run id")
    logs.set_defaults(func=_cmd_logs)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    args.dry_run = getattr(args, "dry_run", False)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
