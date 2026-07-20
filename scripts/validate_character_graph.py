#!/usr/bin/env python3
"""External validator of the `build-character-graph` contract.

Reads the stage output on stdin, prints `{valid, errors}` on stdout. Enforces
the node/link shapes and the two literal enums (`type == CHARACTER`,
`edge_type == INTERACTION`) that the contract previously carried only as a
comment against `required_fields: [graph, delta]`.
"""

import json
import sys

from wiki_creator.contract_validators import character_graph_errors


def main() -> None:
    output = json.load(sys.stdin)
    errors = character_graph_errors(output)
    json.dump({"valid": not errors, "errors": errors}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
