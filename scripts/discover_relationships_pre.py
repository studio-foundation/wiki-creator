#!/usr/bin/env python3
"""Pre-step of the relationship-discovery split (STU-621): build the fan-out items.

Script executor interface: reads JSON from stdin, writes JSON to stdout.

Emits the paragraph-aligned chunks, the PERSON roster, the type vocabulary and
the prompt fingerprint the following `call: discover-relationships` stage fans
out over — one child run per chunk. `needs_verdict` is false when the book has
no work (missing artifacts, empty roster, no chapters); the call is then
condition-skipped and the post stage writes nothing (STU-539 fail-safe).

The per-chunk resume lives in the engine map (STU-589/605), keyed on the item
input + fingerprint, so this stage does no cache check.

Input:  { "additional_context": "<book yaml>" }
Output: { "chunks", "roster", "relationship_types", "prompt_fingerprint", "needs_verdict" }
"""

import yaml

from scripts.discover_relationships import prepare_discovery
from wiki_creator import studio_io


def main() -> None:
    payload = studio_io.read_payload()
    book_cfg = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    prep, skip = prepare_discovery(book_cfg, studio_io.paths_from_payload(payload))

    if skip:
        studio_io.write_output(
            {"chunks": [], "roster": [], "relationship_types": [],
             "prompt_fingerprint": "", "needs_verdict": False}
        )
        return

    studio_io.write_output(
        {
            "chunks": [{"title": c["title"], "text": c["text"]} for c in prep["chunks"]],
            "roster": prep["roster_lines"],
            "relationship_types": prep["type_defs"],
            "prompt_fingerprint": prep["fingerprint"],
            "needs_verdict": True,
        }
    )


if __name__ == "__main__":
    main()
