#!/usr/bin/env python3
"""Pre-step of the relation-reconciliation split (STU-754): build the fan-out items.

Script executor interface: reads JSON from stdin, writes JSON to stdout.

Emits one item per roster gap — the `call: relation-reconciliation-verdict`
stage that follows fans out one agentic search-and-decide call per gap entity
via the engine map (STU-589/605-style per-item resume), mirroring
entity-status-pre. Unlike the entity trio, each item also carries the
book-wide roster and type/sub-role vocabulary: a gap query must be able to
name any roster character as the other party, not just decide a value for
"name" itself.

Input:  { "additional_context": "<book yaml>" }
Output: { "book_title", "gaps", "roster", "relationship_types", "sub_roles",
          "prompt_fingerprint", "needs_verdict" }
"""

import sys

import yaml

from scripts.relation_reconciliation import prepare_reconciliation
from wiki_creator import studio_io


def main() -> None:
    payload = studio_io.read_payload()
    book_cfg = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    paths = studio_io.paths_from_payload(payload)
    prep, skip = prepare_reconciliation(book_cfg, paths)

    if skip:
        _emit()
        return

    if not prep["rows"]:
        print("[relation-reconciliation] no roster gaps — graph is already complete", file=sys.stderr)
        _emit(
            book_title=str(book_cfg.get("title") or paths.processing.name),
            roster=prep["roster_lines"],
            relationship_types=prep["type_defs"],
            sub_roles=prep["sub_role_defs"],
        )
        return

    _emit(
        book_title=str(book_cfg.get("title") or paths.processing.name),
        gaps=[{**row, "book_dir": prep["book_dir"]} for row in prep["rows"]],
        roster=prep["roster_lines"],
        relationship_types=prep["type_defs"],
        sub_roles=prep["sub_role_defs"],
        prompt_fingerprint=prep["fingerprint"],
        needs_verdict=True,
    )


def _emit(
    book_title: str = "",
    gaps: list[dict] | None = None,
    roster: list[str] | None = None,
    relationship_types: list[dict] | None = None,
    sub_roles: list[dict] | None = None,
    prompt_fingerprint: str = "",
    needs_verdict: bool = False,
) -> None:
    studio_io.write_output(
        {
            "book_title": book_title,
            "gaps": gaps or [],
            "roster": roster or [],
            "relationship_types": relationship_types or [],
            "sub_roles": sub_roles or [],
            "prompt_fingerprint": prompt_fingerprint,
            "needs_verdict": needs_verdict,
        }
    )


if __name__ == "__main__":
    main()
