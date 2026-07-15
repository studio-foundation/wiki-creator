#!/usr/bin/env python3
"""
Stage 2: Section filtering — tag front/back matter so it is never extracted.

Script executor interface: reads JSON from stdin, writes JSON to stdout.

Runs between epub-parse and entity-extraction, and re-emits the epub-parse
payload with `frontmatter: true` set on the sections that are not part of the
work. It is a separate stage precisely because it is the only part of extraction
that needs the network: epub-parse stays deterministic and offline.

Input:  { "previous_outputs": {"epub-parse": {...}} }  (or previous_stage_output)
Output: the epub-parse payload, chapters tagged.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from wiki_creator.section_filter import (
    apply_frontmatter,
    load_cached_drops,
    parse_drop_verdict,
    render_section_list,
    save_drop_cache,
    section_rows,
)
from wiki_creator import studio_io

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_TIMEOUT_SECONDS = 300


def _run_section_filter(rows: list[dict], book_title: str) -> tuple[dict[str, str], str | None]:
    """Classify sections with one `studio run`. Returns (drops, error)."""
    item_input = {"book_title": book_title, "sections": render_section_list(rows)}
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".yaml", delete=False) as tmp:
        yaml.safe_dump(item_input, tmp, sort_keys=False, allow_unicode=True)
        input_path = tmp.name

    cmd = ["studio", "run", "section-filter-item", "--input-file", input_path, "--json"]
    try:
        result = subprocess.run(
            cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=_TIMEOUT_SECONDS
        )
    except FileNotFoundError:
        return {}, "studio_cli_missing"
    except subprocess.TimeoutExpired:
        return {}, "studio_run_timeout"
    finally:
        Path(input_path).unlink(missing_ok=True)

    if result.returncode != 0:
        return {}, "studio_run_failed"
    run_payload = studio_io.extract_first_json_object(result.stdout or "")
    if run_payload is None:
        return {}, "studio_output_json_parse_error"

    stage_output = studio_io.extract_stage_output_from_run_payload(run_payload, "section-filter-item")
    if stage_output is None:
        run_id = str(run_payload.get("id") or "").strip()
        if run_id:
            stage_output = studio_io.load_studio_stage_output(run_id, "section-filter-item")
    if stage_output is None:
        return {}, "studio_run_output_missing"

    return parse_drop_verdict(stage_output, {row["id"] for row in rows}), None


def tag_frontmatter_sections(chapters: list[dict], book_title: str, cache_path: Path) -> list[dict]:
    """Tag front/back matter in place, from cache or one LLM call.

    Never raises and never removes a section: a book whose verdict cannot be
    obtained keeps every section, loudly.
    """
    if not chapters:
        return []
    rows = section_rows(chapters)
    drops = load_cached_drops(cache_path, rows)
    if drops is None:
        drops, error = _run_section_filter(rows, book_title)
        if error:
            print(
                f"[section-filter] WARNING: {error} — keeping all {len(rows)} sections; "
                "front/back matter will be extracted as narrative",
                file=sys.stderr,
            )
            return []
        save_drop_cache(cache_path, rows, drops)

    tagged = apply_frontmatter(chapters, drops)
    print(f"[section-filter] {len(tagged)}/{len(rows)} sections dropped as front/back matter", file=sys.stderr)
    for section in tagged:
        print(f"[section-filter]   - {section['id']} ({section['title']}): {section['reason']}", file=sys.stderr)
    return tagged


def _epub_output_from_payload(payload: dict) -> dict:
    previous = payload.get("previous_outputs") or {}
    epub_data = previous.get("epub-parse")
    if not isinstance(epub_data, dict):
        epub_data = payload.get("previous_stage_output")
    if not isinstance(epub_data, dict):
        epub_data = payload.get("all_stage_outputs", {}).get("epub-parse")
    return epub_data if isinstance(epub_data, dict) else {}


def main() -> None:
    payload = studio_io.read_payload()
    epub_data = _epub_output_from_payload(payload)
    chapters = epub_data.get("chapters") or []
    if not chapters:
        json.dump({"error": "missing epub-parse chapters"}, sys.stdout)
        sys.exit(1)

    paths = studio_io.paths_from_payload(payload)
    paths.processing.mkdir(parents=True, exist_ok=True)
    tag_frontmatter_sections(
        chapters,
        book_title=str(epub_data.get("title") or ""),
        cache_path=paths.processing / "section_filter.json",
    )

    # epub_data.json is the on-disk source for the stages that do not read stdin
    # (chapter_summary --book, wiki_preparation); the tags have to reach it too.
    epub_data_path = paths.processing / "epub_data.json"
    if epub_data_path.exists():
        with open(epub_data_path, "w", encoding="utf-8") as f:
            json.dump(epub_data, f, ensure_ascii=False)

    json.dump(epub_data, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
