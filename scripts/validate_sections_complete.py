#!/usr/bin/env python3
"""External validator of the `section-filter` contract.

Reads the stage output on stdin, prints `{valid, errors}` on stdout. Enforces
the load-bearing invariant the contract stated in prose — sections are tagged,
never removed, so chapters.json stays complete (which keeps STU-489 mention
offsets stable): every emitted chapter must keep a non-empty id and content.
"""

import json
import sys

from wiki_creator.contract_validators import sections_complete_errors


def main() -> None:
    output = json.load(sys.stdin)
    errors = sections_complete_errors(output)
    json.dump({"valid": not errors, "errors": errors}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
