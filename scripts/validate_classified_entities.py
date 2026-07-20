#!/usr/bin/env python3
"""External validator of the `entity-classification` contract.

Reads the stage output on stdin, prints `{valid, errors}` on stdout. The type
vocabulary is read from `base.yaml#entity_types` here at execution time
(`entity_taxonomy.resolution_types`), so FACTION and any later type are covered
without editing this file — the drift the restated enum comment caused (STU-505
shipped FACTION; the comment still read PERSON|PLACE|ORG|EVENT|OTHER) cannot
recur.
"""

import json
import sys

from wiki_creator.contract_validators import classified_entity_errors
from wiki_creator.entity_taxonomy import resolution_types


def main() -> None:
    output = json.load(sys.stdin)
    allowed = set(resolution_types())
    errors = classified_entity_errors(output.get("entities"), allowed)
    json.dump({"valid": not errors, "errors": errors}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
