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

import dataclasses
import json
import re
import sys
import types
import typing
from pathlib import Path
from typing import IO, Any, Literal, Union, get_args, get_origin

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
    text = str(text or "")
    decoder = json.JSONDecoder()
    i = text.find("{")
    while i != -1:
        try:
            candidate, _ = decoder.raw_decode(text[i:])
        except json.JSONDecodeError:
            end = _brace_span_end(text, i)
            # STU-533: an object with no closing brace is truncated, not noise.
            # Scanning into it would return one of its nested objects — a fragment
            # the caller never asked for, which reads as a successful parse.
            if end is None:
                return None
            i = text.find("{", end)
            continue
        if isinstance(candidate, dict):
            return candidate
        i = text.find("{", i + 1)
    return None


def _brace_span_end(text: str, start: int) -> int | None:
    """Index just past the ``}`` closing the ``{`` at ``start``, else ``None``."""
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return None


def extract_run_id(text: str) -> str:
    """Return the run id from a ``studio run --json`` stdout, else ``""``.

    Read independently of the payload parse: ``id`` is the run's own first key,
    so it survives the 8 KiB stdout truncation the payload does not (STU-533).
    """
    match = re.search(r'"id"\s*:\s*"([^"]+)"', str(text or ""))
    return match.group(1) if match else ""


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


class ArtifactSchemaError(ValueError):
    """Raised when an artifact does not match its declared schema."""


def to_dict(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_dict(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, list):
        return [to_dict(v) for v in obj]
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    return obj


def from_dict(schema: Any, data: Any, path: str = "$") -> Any:
    origin = get_origin(schema)

    if origin in (list, typing.List):
        (elem,) = get_args(schema)
        if not isinstance(data, list):
            raise ArtifactSchemaError(f"{path}: expected array, got {type(data).__name__}")
        return [from_dict(elem, v, f"{path}[{i}]") for i, v in enumerate(data)]

    if origin in (dict, typing.Dict):
        _k, val = get_args(schema)
        if not isinstance(data, dict):
            raise ArtifactSchemaError(f"{path}: expected object, got {type(data).__name__}")
        return {k: from_dict(val, v, f"{path}.{k}") for k, v in data.items()}

    if origin is Union or origin is types.UnionType:
        members = get_args(schema)
        if data is None and type(None) in members:
            return None
        non_none = [m for m in members if m is not type(None)]
        return from_dict(non_none[0], data, path)

    if origin is Literal:
        allowed = get_args(schema)
        if data not in allowed:
            raise ArtifactSchemaError(f"{path}: {data!r} not one of {allowed}")
        return data

    if isinstance(schema, type) and dataclasses.is_dataclass(schema):
        if not isinstance(data, dict):
            raise ArtifactSchemaError(f"{path}: expected object for {schema.__name__}, got {type(data).__name__}")
        hints = typing.get_type_hints(schema)
        fields = {f.name: f for f in dataclasses.fields(schema)}
        unknown = sorted(set(data) - set(fields))
        if unknown:
            raise ArtifactSchemaError(f"{path}: unknown keys {unknown} for {schema.__name__}")
        kwargs = {}
        for name, f in fields.items():
            if name in data:
                kwargs[name] = from_dict(hints[name], data[name], f"{path}.{name}")
            elif f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING:
                raise ArtifactSchemaError(f"{path}: missing required field {name!r}")
        return schema(**kwargs)

    if schema in (int, float, str, bool):
        if schema is float and isinstance(data, int) and not isinstance(data, bool):
            return float(data)
        if isinstance(data, bool) != (schema is bool):
            raise ArtifactSchemaError(f"{path}: expected {schema.__name__}, got {type(data).__name__}")
        if not isinstance(data, schema):
            raise ArtifactSchemaError(f"{path}: expected {schema.__name__}, got {type(data).__name__}")
        return data

    # Any / untyped dict|list: pass through unvalidated (free-form fields like stats/infobox_fields)
    return data


def save_artifact(path, obj: Any, schema: Any) -> None:
    payload = to_dict(obj)
    from_dict(schema, payload)  # roundtrip self-check: never write off-schema
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


def load_artifact(path, schema: Any) -> Any:
    with open(path, encoding="utf-8") as f:
        return from_dict(schema, json.load(f))


def load_full_file(path, json_key: str) -> dict:
    """Load a ``*_full.json`` artifact, validate it against ``dict[str, EntityFull]``.

    These files are wrapped under ``json_key`` (``persons_full``, …); falls
    back to the raw payload itself for unwrapped fixtures/older runs (matches
    the unwrap behavior write_registry.py relied on pre-STU-447).
    """
    from wiki_creator.types import EntityFull

    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return from_dict(dict[str, EntityFull], raw.get(json_key, raw))
