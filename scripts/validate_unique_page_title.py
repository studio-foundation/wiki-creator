#!/usr/bin/env python3
"""External validator `unique-page-title` of the `wiki-page` contract.

Reads the `wiki-page` stage output on stdin, prints `{valid, errors}` on stdout.
Two pages rendering to the same `page_filename` fail the run.
"""

import json
import sys

from wiki_creator.page_validators import duplicate_page_titles


def main() -> None:
    output = json.load(sys.stdin)
    errors = duplicate_page_titles(output.get("pages") or [])
    json.dump({"valid": not errors, "errors": errors}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
