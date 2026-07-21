#!/usr/bin/env python3
"""Pre-step of the section-filter split (STU-589): build the classifier's input.

Script executor interface: reads JSON from stdin, writes JSON to stdout.

Emits the rendered section list and whether a verdict is still needed — the
`call: section-filter-verdict` stage that follows runs the LLM only when
`needs_verdict` is true (cache miss). The verdict cache stays keyed on the rows
themselves (STU-529), so this stage deciding "no call needed" is exactly the
old in-script cache hit.

Input:  { "previous_outputs": {"epub-parse": {...}} }  (or previous_stage_output)
Output: { "book_title", "sections", "needs_verdict" }
"""

import json
import sys

from wiki_creator import studio_io
from wiki_creator.section_filter import load_cached_drops, render_section_list, section_rows
from scripts.section_filter import epub_output_from_payload


def main() -> None:
    payload = studio_io.read_payload()
    epub_data = epub_output_from_payload(payload)
    chapters = epub_data.get("chapters") or []
    if not chapters:
        json.dump({"error": "missing epub-parse chapters"}, sys.stdout)
        sys.exit(1)

    paths = studio_io.paths_from_payload(payload)
    rows = section_rows(chapters)
    cached = load_cached_drops(paths.processing / "section_filter.json", rows)

    json.dump(
        {
            "book_title": str(epub_data.get("title") or ""),
            "sections": render_section_list(rows),
            "needs_verdict": cached is None,
        },
        sys.stdout,
        ensure_ascii=False,
    )


if __name__ == "__main__":
    main()
