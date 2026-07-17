"""Whole-token matching: does a run of tokens appear in a text as *tokens*, never
as a substring of one.

Two features need this same rule and used to spell it two ways. `alias-resolution`
(STU-541) refused to read `beaver` out of `Beavers` — a shared surname cannot tell
Mr Beaver from Mrs Beaver, and `beaver` sitting inside `Beavers` is an accident of
spelling. `entity_status`'s death circumstance (STU-552) refused to ground the
killer `Son` on `per`**`son`** — a spaCy-mistyped common noun on the PERSON roster
grounding an invented killer.

The one difference between them is load-bearing: what separates a token from its
neighbour. `alias-resolution` splits on whitespace, so a possessive stays glued —
`Durza` is not the token `Durza's`. `entity_status` needs the opposite: a killer
named in the possessive (`Durza's blade took Brom`) is the common case in these
novels, so it lets the boundary cross the apostrophe. That is the ``boundary``
parameter; everything else is one rule.

Callers own their own case/typographic normalization and pass prepared strings —
this decides token boundaries only.
"""

from __future__ import annotations

import re


def contains_token_run(haystack: str, needle: str, *, boundary: str = "whitespace") -> bool:
    """True if ``needle`` appears in ``haystack`` as a whole-token run.

    ``boundary`` decides what separates one token from the next:

    - ``"whitespace"`` (STU-541): only whitespace does, so a possessive or any
      trailing punctuation stays part of its token — ``Durza`` does NOT match
      ``"Durza's blade"``, and ``beaver`` does NOT match ``"Beavers"``.
    - ``"word"`` (STU-552): a regex word boundary does, so a name crossing an
      apostrophe still matches — ``Durza`` matches ``"Durza's blade"`` — while a
      name merely sitting inside a longer word (``Son`` in ``person``) still does
      not.
    """
    needle = needle.strip()
    if not needle:
        return False
    if boundary == "word":
        return re.search(r"\b" + re.escape(needle) + r"\b", haystack) is not None
    if boundary == "whitespace":
        tokens = haystack.split()
        run = needle.split()
        return any(
            tokens[i : i + len(run)] == run
            for i in range(len(tokens) - len(run) + 1)
        )
    raise ValueError(f"unknown boundary {boundary!r}")
