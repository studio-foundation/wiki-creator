#!/usr/bin/env python3
"""
Stage 2: Section filtering — tag front/back matter so it is never extracted.

Script executor interface: reads JSON from stdin, writes JSON to stdout.

Post-step of the section-filter split (STU-589). The LLM verdict arrives from
the `call: section-filter-verdict` stage (native invocation, no subprocess);
this stage parses it, caches it, and re-emits the epub-parse payload with
`frontmatter: true` set on the sections that are not part of the work.

Input:  { "all_stage_outputs": {"epub-parse": {...}, "section-filter-verdict": {...}} }
Output: the epub-parse payload, chapters tagged.
"""

import json
import sys
from pathlib import Path

from wiki_creator.chapters import number_chapters
from wiki_creator.section_filter import (
    apply_frontmatter,
    load_cached_drops,
    parse_drop_verdict,
    save_drop_cache,
    section_rows,
)
from wiki_creator import studio_io

VERDICT_STAGE = "section-filter-verdict"


def tag_frontmatter_sections(
    chapters: list[dict], verdict_output: object | None, cache_path: Path
) -> list[dict]:
    """Tag front/back matter in place, from cache or the call stage's verdict.

    Never raises and never removes a section: a book whose verdict cannot be
    obtained keeps every section, loudly (STU-529).
    """
    if not chapters:
        return []
    rows = section_rows(chapters)
    drops = load_cached_drops(cache_path, rows)
    if drops is None:
        if verdict_output is None:
            print(
                f"[section-filter] WARNING: no verdict (call skipped or failed) — "
                f"keeping all {len(rows)} sections; "
                "front/back matter will be extracted as narrative",
                file=sys.stderr,
            )
            return []
        drops = parse_drop_verdict(verdict_output, {row["id"] for row in rows})
        save_drop_cache(cache_path, rows, drops)

    tagged = apply_frontmatter(chapters, drops)
    print(f"[section-filter] {len(tagged)}/{len(rows)} sections dropped as front/back matter", file=sys.stderr)
    for section in tagged:
        print(f"[section-filter]   - {section['id']} ({section['title']}): {section['reason']}", file=sys.stderr)
    return tagged


def epub_output_from_payload(payload: dict) -> dict:
    previous = payload.get("previous_outputs") or {}
    epub_data = previous.get("epub-parse")
    if not isinstance(epub_data, dict):
        epub_data = payload.get("previous_stage_output")
    if not isinstance(epub_data, dict):
        epub_data = payload.get("all_stage_outputs", {}).get("epub-parse")
    return epub_data if isinstance(epub_data, dict) else {}


def _verdict_from_payload(payload: dict) -> object | None:
    verdict = payload.get("all_stage_outputs", {}).get(VERDICT_STAGE)
    if verdict is None:
        verdict = payload.get("previous_outputs", {}).get(VERDICT_STAGE)
    return verdict


def main() -> None:
    payload = studio_io.read_payload()
    epub_data = epub_output_from_payload(payload)
    chapters = epub_data.get("chapters") or []
    if not chapters:
        json.dump({"error": "missing epub-parse chapters"}, sys.stdout)
        sys.exit(1)

    paths = studio_io.paths_from_payload(payload)
    paths.processing.mkdir(parents=True, exist_ok=True)
    tag_frontmatter_sections(
        chapters,
        verdict_output=_verdict_from_payload(payload),
        cache_path=paths.processing / "section_filter.json",
    )
    # The only place both the reading order and the front-matter verdict are
    # known — every later stage reads the field instead of re-deriving it.
    number_chapters(chapters)

    # epub_data.json is the on-disk source for the stages that do not read stdin
    # (chapter_summary --book, wiki_preparation); the tags have to reach it too.
    epub_data_path = paths.processing / "epub_data.json"
    if epub_data_path.exists():
        with open(epub_data_path, "w", encoding="utf-8") as f:
            json.dump(epub_data, f, ensure_ascii=False)

    json.dump(epub_data, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
