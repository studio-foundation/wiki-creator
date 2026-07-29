#!/usr/bin/env python3
"""Pre-step of the series-arc split (STU-720): build the fan-out item.

Script executor interface: reads JSON from stdin, writes JSON to stdout.

Emits the single `wiki-pages` map item for the series hub's arc paragraph. The
call it feeds replaces the nested `studio run` subprocess `series-assemble` used
to issue from inside its own stage — the one LLM call of `wiki-series` was the
last one still shaped that way, and it silently produced no arc (STU-720).

Input:  { "additional_context": "<any tome's book yaml>" }
Output: { "items", "prompt_fingerprint", "needs_verdict" }
"""

from scripts.generate_series_arc import run_pre
from wiki_creator import studio_io


def main() -> None:
    studio_io.write_output(run_pre(studio_io.read_payload()))


if __name__ == "__main__":
    main()
