#!/usr/bin/env python3
"""External validator of the `wiki-preparation` contract.

Reads the stage output on stdin, prints `{valid, errors}` on stdout. Enforces
the `batches` array-of-objects shape ({batch_id, file, entity_count}) the
contract previously described only in a comment.
"""

import json
import sys

from wiki_creator.contract_validators import batches_errors


def main() -> None:
    output = json.load(sys.stdin)
    errors = batches_errors(output)
    json.dump({"valid": not errors, "errors": errors}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
