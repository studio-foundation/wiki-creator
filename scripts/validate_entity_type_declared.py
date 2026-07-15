#!/usr/bin/env python3
"""External validator `entity-type-declared` of the `wiki-page` contract.

Reads the `wiki-page` stage output on stdin, prints `{valid, errors}` on stdout.
The authority for the type vocabulary is `wiki_creator/templates/base.yaml`,
read here at execution time — a type absent from it fails the run.
"""

import json
import sys

from wiki_creator.page_templates import load_base_template
from wiki_creator.page_validators import undeclared_entity_types


def main() -> None:
    output = json.load(sys.stdin)
    declared = set(load_base_template().get("entity_types") or {})
    errors = undeclared_entity_types(output.get("pages") or [], declared)
    json.dump({"valid": not errors, "errors": errors}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
