#!/usr/bin/env python3
"""Pre-step of the chapter-summary split (STU-621): build the fan-out items.

Script executor interface: reads JSON from stdin, writes JSON to stdout.

Emits the per-chapter map items and the prompt fingerprint the following
`call: chapter-summaries-verdict` stage fans out over — one child run per
pending narrative chapter. `needs_verdict` is true only in `llm` summary mode
with at least one chapter; in extractive mode the call is condition-skipped and
the post stage summarizes deterministically, no LLM.

The per-chapter resume lives in the engine map (STU-589/605), so this stage does
no cache check — it only enumerates the items, keyed on content + fingerprint.

Input:  { "additional_context": "<book yaml>" }
Output: { "chapters": [<item>...], "prompt_fingerprint": "...", "needs_verdict": bool }
"""

import sys

import yaml

from scripts.chapter_summary import (
    _chapter_summary_item_input,
    _read_epub_data,
    pending_chapters,
    resolve_summary_inputs,
)
from wiki_creator import studio_io


def main() -> None:
    payload = studio_io.read_payload()
    paths = studio_io.paths_from_payload(payload)
    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    chapters = _read_epub_data(paths).get("chapters", [])
    inp = resolve_summary_inputs(ctx, paths)
    cfg = inp["config"]

    pending = pending_chapters(chapters)
    items = [_chapter_summary_item_input(chapter, cfg) for chapter in pending]
    needs_verdict = cfg.mode == "llm" and bool(pending)
    if not needs_verdict:
        print(
            f"[chapter-summary] extractive mode or no narrative chapters "
            f"({len(pending)} pending) — no LLM fan-out",
            file=sys.stderr,
        )

    studio_io.write_output(
        {
            "chapters": items,
            "prompt_fingerprint": inp["fingerprint"],
            "needs_verdict": needs_verdict,
        }
    )


if __name__ == "__main__":
    main()
