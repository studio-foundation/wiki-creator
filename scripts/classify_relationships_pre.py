#!/usr/bin/env python3
"""Pre-step of the relationship-classify split (STU-621): build the fan-out items.

Script executor interface: reads JSON from stdin, writes JSON to stdout.

Folds the co-occurrence graph onto canonical entities, splits it into
classifiable interpersonal pairs, and emits one map item per pair for the
following `call: classify-relationships` stage. `needs_verdict` is false when
there is nothing to classify (only pass-through pairs, or a missing input); the
call is then condition-skipped and the post stage writes the pass-through set.

The per-pair resume lives in the engine map (STU-589/605), keyed on the item
input + fingerprint, so this stage does no cache check.

Input:  { "additional_context": "<book yaml>" }
Output: { "pairs", "prompt_fingerprint", "needs_verdict" }
"""

import yaml

from scripts.classify_relationships import prepare_classify
from wiki_creator import studio_io


def main() -> None:
    payload = studio_io.read_payload()
    book_cfg = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    prep, skip = prepare_classify(book_cfg, studio_io.paths_from_payload(payload))

    if skip or not prep["items"]:
        studio_io.write_output({"pairs": [], "prompt_fingerprint": "", "needs_verdict": False})
        return

    # A pair carries no title/name key, so the engine's map label would be `#i`
    # and the --stream-items view (STU-626) could not name it. A label derived
    # from the pair gives it identity; it re-keys the item once (STU-560), which
    # a re-run absorbs.
    pairs = [
        {**pair, "label": f"{pair.get('entity_a', '?')} <=> {pair.get('entity_b', '?')}"}
        for pair in prep["items"]
    ]

    studio_io.write_output(
        {
            "pairs": pairs,
            "prompt_fingerprint": prep["fingerprint"],
            "needs_verdict": True,
        }
    )


if __name__ == "__main__":
    main()
