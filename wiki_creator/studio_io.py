"""Studio script-executor protocol helpers (STU-445).

Centralizes the payload/stdin boilerplate that was duplicated verbatim across
``scripts/*.py``. Every stage script should read its input via
``payload = studio_io.read_payload()`` and derive book paths via
``studio_io.paths_from_payload(payload)`` instead of re-defining the same
private helpers.

Covers three families of duplication:

* stdin/stdout protocol: :func:`read_payload`, :func:`write_output`
* ``additional_context`` YAML -> :class:`~wiki_creator.paths.BookPaths`:
  :func:`paths_from_payload`
* Studio run-output recovery (log scraping for ``*-item`` fan-out):
  :func:`extract_first_json_object`, :func:`studio_run_log_path`,
  :func:`extract_stage_output_from_run_payload`, :func:`load_studio_stage_output`,
  plus :func:`slugify_filename`.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import IO

import yaml

from wiki_creator.paths import BookPaths, book_paths_from_epub

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_payload(stream: IO[str] | None = None) -> dict:
    """Read and parse the Studio script-executor payload from ``stream``.

    Defaults to ``sys.stdin``. Studio always sends a JSON object on stdin, even
    for stages that ignore it, so every ``main()`` must consume it.
    """
    return json.load(stream if stream is not None else sys.stdin)


def paths_from_payload(payload: dict, *, strict: bool = True) -> BookPaths | None:
    """Derive :class:`BookPaths` from the payload's ``additional_context`` YAML.

    The YAML must carry a ``file_path`` pointing at the book EPUB/YAML. When
    ``strict`` (default), a missing ``file_path`` raises ``ValueError``; when
    ``strict=False`` it returns ``None`` (unit-test tolerant mode used by
    scripts like ``split_clusters``/``relationship_extraction``).
    """
    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    file_path = ctx.get("file_path")
    if not file_path:
        if strict:
            raise ValueError("missing file_path in additional_context")
        return None
    return book_paths_from_epub(file_path)


def write_output(
    data: object,
    stream: IO[str] | None = None,
    *,
    ensure_ascii: bool = False,
    indent: int | None = None,
) -> None:
    """Write ``data`` as JSON to ``stream`` (defaults to ``sys.stdout``)."""
    json.dump(
        data,
        stream if stream is not None else sys.stdout,
        ensure_ascii=ensure_ascii,
        indent=indent,
    )


# --- Studio run-output recovery ------------------------------------------------


def extract_first_json_object(text: str) -> dict | None:
    """Return the first balanced JSON object embedded in ``text``, else ``None``."""
    decoder = json.JSONDecoder()
    for i, ch in enumerate(str(text or "")):
        if ch != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(text[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            return candidate
    return None


def studio_run_log_path(run_id: str) -> Path | None:
    """Locate the ``.studio/runs/*-<run_id>.jsonl`` log for ``run_id``."""
    runs_dir = PROJECT_ROOT / ".studio" / "runs"
    run_id = str(run_id or "").strip()
    matches = sorted(runs_dir.glob(f"*-{run_id}.jsonl"))
    if not matches and run_id:
        matches = sorted(runs_dir.glob(f"*-{run_id[:8]}.jsonl"))
    if not matches:
        return None
    return matches[-1]


def extract_stage_output_from_run_payload(
    run_payload: dict, stage_name: str
) -> dict | None:
    """Pull a successful stage's ``output`` dict from a run summary payload."""
    stages = run_payload.get("stages", [])
    if not isinstance(stages, list):
        return None
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        if stage.get("stage_name") != stage_name:
            continue
        if stage.get("status") != "success":
            continue
        output = stage.get("output")
        if isinstance(output, dict):
            return output
    return None


def load_studio_stage_output(run_id: str, stage_name: str) -> dict | None:
    """Scrape a stage's success ``output`` from the run's JSONL event log."""
    log_path = studio_run_log_path(run_id)
    if log_path is None or not log_path.exists():
        return None

    with open(log_path, encoding="utf-8") as f:
        for line in f:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event") != "stage_complete":
                continue
            if event.get("stage") != stage_name:
                continue
            if event.get("status") != "success":
                continue
            output = event.get("output")
            if isinstance(output, dict):
                return output
    return None


def slugify_filename(value: str) -> str:
    """Slugify ``value`` into a safe filename stem."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    slug = slug.strip("._")
    return slug or "untitled"
