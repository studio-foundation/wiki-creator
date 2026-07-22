#!/usr/bin/env python3
"""Pre-step of the event-pages split (STU-621): build the fan-out items.

Script executor interface: reads JSON from stdin, writes JSON to stdout.

Emits one `wiki-pages` map item per selected event (one child run through the
wiki-page-item pipeline). The selection and unique titling are deterministic
(`plan_event_pages`), so the post stage rebuilds the same ordered list and zips
the map results back by index. `needs_verdict` is false when nothing clears the
salience threshold — the call is then condition-skipped and the post stage skips
the pages.

Input:  { "additional_context": "<book yaml>" }
Output: { "items", "prompt_fingerprint", "needs_verdict" }
"""

import yaml

from scripts.generate_event_pages import (
    build_event_item,
    event_pages_prompt_fingerprint,
    plan_event_pages,
)
from scripts.generate_wiki_pages import wiki_pages_map_item
from wiki_creator import studio_io
from wiki_creator.page_templates import output_language


def main() -> None:
    payload = studio_io.read_payload()
    book_cfg = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    paths = studio_io.paths_from_payload(payload)
    language = output_language(book_cfg)

    plan = plan_event_pages(paths.processing, book_cfg=book_cfg, language=language)
    if plan is None:
        studio_io.write_output({"items": [], "prompt_fingerprint": "", "needs_verdict": False})
        return
    planned, meta = plan

    items = []
    for event, title in planned:
        item_input, _entity = build_event_item(
            event, title,
            book_title=meta["book_title"], forbidden_names=meta["forbidden_names"],
            max_tokens=meta["max_tokens"], language=language,
            file_path=meta["file_path"], all_events=meta["all_events"],
        )
        items.append(wiki_pages_map_item(item_input, attempt=1))

    studio_io.write_output(
        {
            "items": items,
            "prompt_fingerprint": event_pages_prompt_fingerprint(),
            "needs_verdict": bool(items),
        }
    )


if __name__ == "__main__":
    main()
