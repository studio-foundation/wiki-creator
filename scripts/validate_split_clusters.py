#!/usr/bin/env python3
"""External validator of the `split-clusters` contract.

Reads the stage output on stdin, prints `{valid, errors}` on stdout. Checks the
container shape (`singles_resolved` a list, `by_type` a dict of lists) only —
the type vocabulary is deliberately not named here (STU-505 moved it into
base.yaml; naming the keys would re-freeze it).
"""

import json
import sys

from wiki_creator.contract_validators import split_clusters_errors


def main() -> None:
    output = json.load(sys.stdin)
    errors = split_clusters_errors(output)
    json.dump({"valid": not errors, "errors": errors}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
