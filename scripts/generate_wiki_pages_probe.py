#!/usr/bin/env python3
"""Probe stage of the wiki-pages split (STU-621): collect the attempt-2 retries.

Script executor interface: reads JSON from stdin, writes JSON to stdout.

Replays the attempt-1 map output (from the `wiki-pages-verdict` call) through the
generation walk with a ReplayRunner (STU-612): the in-walk forbidden-name retry
re-requests the same item, which this records as an attempt-2 item. Their prompt
is identical by design, so `attempt: 2` is what busts the engine's item cache and
makes the retry a real second roll. `needs_retry` is false when the first pass
had no forbidden-name hits; the following conditional `call: wiki-pages` is then
skipped.

Input:  { "additional_context": "<book yaml>",
          "all_stage_outputs": {"wiki-pages-verdict": {<map output>}} }
Output: { "items", "needs_retry" }
"""

import yaml

from scripts.generate_wiki_pages import (
    VERDICT_STAGE,
    _map_output_from_payload,
    probe_generation,
)
from wiki_creator import studio_io


def main() -> None:
    payload = studio_io.read_payload()
    book_cfg = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    book_paths = studio_io.paths_from_payload(payload)
    first = _map_output_from_payload(payload, VERDICT_STAGE)
    studio_io.write_output(probe_generation(book_cfg, book_paths, first))


if __name__ == "__main__":
    main()
