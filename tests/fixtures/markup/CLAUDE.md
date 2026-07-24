# CLAUDE.md — tests/fixtures/markup/

Markup regression corpus. Moved verbatim from the root CLAUDE.md Gotchas section so it loads only when working under `tests/fixtures/markup/`.

## Gotchas

- Markup corpus (STU-525): `tests/fixtures/markup/` is the parser's regression
  record — one `<publisher>-<shape>.html` per real convention (tags, classes,
  charrefs, whitespace byte-exact from the publisher's file; prose swapped for
  filler), paired with a `.txt` holding the text the parser must produce.
  `tests/test_markup_corpus.py` parametrizes over it. Three things are
  load-bearing. (1) **The `.txt` is hand-written, never generated** — deriving it
  from `parse_epub` asserts only that the parser agrees with itself, the
  circularity STU-524 removed from the e2e fixture. It caught a wrong prediction
  of mine on the first pass: `eragon-epigraph-em-split` really does render
  `elit .`, because the source really is `</em>&#13;\n .` — the publisher's
  space, not our bug. (2) **Shapes are keyed on tag names, never classes**
  (`tests/fixtures/markup/harvest.py`, re-runs the survey against a local
  library): the parser only sees tags, and Brisingr does its small-caps with a
  bare `<small>` while Eragon uses `<span class="small1">` — same shape.
  Classes stay in the snippet as provenance. (3) **The harvest writes nothing** —
  a new shape is a prompt for a human (swap the prose, hand-write the `.txt`),
  not a patch. Reverting `_flatten_inline_markup` reds 9 of the 15 snippets.
  The corpus found two bugs on its first run, both invisible to markup we wrote
  ourselves: STU-531 (`\r`) and STU-532 (block-level dropcap), both since fixed.
  A shape recorded but not fixed gets a `strict=True` xfail naming its issue —
  never an expected text edited down to what the parser happens to emit.
