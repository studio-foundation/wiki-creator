#!/usr/bin/env python3
"""Plan stage of the wiki-pages split (STU-621): enumerate the fan-out items.

Script executor interface: reads JSON from stdin, writes JSON to stdout.

Runs the deterministic generation walk with a CollectingRunner (STU-612) to
enumerate exactly the item calls the generation would dispatch — data gates,
section order and the per-relation set included — and emits them as attempt-1
`wiki-pages` map items. `needs_verdict` is false when there is nothing to
generate; the following `call: wiki-pages` is then condition-skipped.

Input:  { "additional_context": "<book yaml>" }
Output: { "items", "prompt_fingerprint", "needs_verdict" }
"""

import yaml

from scripts.generate_wiki_pages import plan_generation
from wiki_creator import studio_io


def main() -> None:
    payload = studio_io.read_payload()
    book_cfg = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    book_paths = studio_io.paths_from_payload(payload)
    studio_io.write_output(plan_generation(book_cfg, book_paths))


if __name__ == "__main__":
    main()
