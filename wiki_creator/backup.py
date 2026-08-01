"""Automatic pre-run snapshot of a book's gitignored artifacts (STU-760).

Automates the CLAUDE.local.md "Back Up Before Running On A Real Book" ritual.
Studio's own `on_stage_start` hook cannot see the run's input (Studio 0.15.0
only substitutes `{{tool.*}}`/`{{output.*}}` in hook commands, never the
pipeline input), so this runs as a plain guard at the top of
`scripts/parse_epub.py` instead — wiki-full's first *executing* stage, invoked
exactly once per top-level run (never as a map/fan-out item, never re-entered
by a nested `call`), which gives the same "before anything in this run
overwrites artifacts" guarantee the ticket asked a hook for.
"""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

from wiki_creator.paths import BookPaths

_SNAPSHOT_DIRS = ("processing", "wiki_inputs", "output")


def snapshot_book_artifacts(paths: BookPaths, *, today: date | None = None) -> Path | None:
    """Copy this book's artifacts to `bak_<DD-MM-YY>/` before a run overwrites them.

    Snapshots `processing_output/<slug>`, `wiki_inputs/<slug>`, `output/<slug>`
    and the series `registry.json`, laid out under `bak_<date>/` the same way
    they sit under the series dir. Idempotent per day: an existing
    `bak_<date>/` is left untouched, so a same-day resume or re-run never
    clobbers the snapshot of the day's first run. Skips silently (returns
    `None`) when the book has no artifacts yet (cold book) or today's snapshot
    already exists.
    """
    series_dir = paths.series_dir
    sources = [getattr(paths, name) for name in _SNAPSHOT_DIRS if getattr(paths, name).exists()]
    if paths.series_registry.exists():
        sources.append(paths.series_registry)
    if not sources:
        return None

    stamp = (today or date.today()).strftime("%d-%m-%y")
    bak_dir = series_dir / f"bak_{stamp}"
    if bak_dir.exists():
        return None

    bak_dir.mkdir(parents=True)
    for src in sources:
        dest = bak_dir / src.relative_to(series_dir)
        if src.is_dir():
            shutil.copytree(src, dest)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
    return bak_dir
