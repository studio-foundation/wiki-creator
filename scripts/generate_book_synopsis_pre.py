#!/usr/bin/env python3
"""Pre-step of the book-synopsis split (STU-621): build the fan-out item.

Script executor interface: reads JSON from stdin, writes JSON to stdout.

Emits the single `wiki-pages` map item for the synopsis page (one child run
through the wiki-page-item pipeline). `needs_verdict` is false when there is
nothing to summarize (no events.json, or it is empty) — the call is then
condition-skipped and the post stage skips the page.

Input:  { "additional_context": "<book yaml>" }
Output: { "items", "prompt_fingerprint", "needs_verdict" }
"""

import sys

import yaml

from scripts.generate_book_synopsis import (
    build_synopsis_item,
    read_events,
    synopsis_prompt_fingerprint,
)
from scripts.generate_wiki_pages import load_book_title, wiki_pages_map_item
from wiki_creator import studio_io
from wiki_creator.lang import book_language


def main() -> None:
    payload = studio_io.read_payload()
    book_cfg = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    paths = studio_io.paths_from_payload(payload)

    events = read_events(paths.processing)
    if not events:
        print("[synopsis] no events — no synopsis fan-out", file=sys.stderr)
        studio_io.write_output({"items": [], "prompt_fingerprint": "", "needs_verdict": False})
        return

    book_title = load_book_title(str(paths.processing / "epub_data.json"))
    item_input, _entity, _forbidden = build_synopsis_item(
        events, book_title=book_title, book_cfg=book_cfg, language=book_language(book_cfg)
    )
    studio_io.write_output(
        {
            "items": [wiki_pages_map_item(item_input, attempt=1)],
            "prompt_fingerprint": synopsis_prompt_fingerprint(),
            "needs_verdict": True,
        }
    )


if __name__ == "__main__":
    main()
