#!/usr/bin/env python3
"""Re-run the markup survey against a local library checkout (STU-525).

The corpus next to this file is the parser's regression record: one snippet per
publisher convention, harvested from real EPUBs. The EPUBs are gitignored
(commercial, ~2.6 MB each), so the corpus is what remains committed — and it can
only stay honest if adding a book *surfaces* its conventions instead of hiding
them. That is this script's whole job:

    python tests/fixtures/markup/harvest.py --library library/

It writes nothing. Two reasons, both deliberate:

  - The expected text (<name>.txt) must be hand-written. Generating it from
    parse_epub would assert only that the parser agrees with itself — the
    circularity STU-524 removed from the e2e fixture.
  - The prose must be swapped for filler by a human. These are commercial books.

So a NEW shape is a prompt, not a patch: copy the candidate, replace the words,
keep tags/classes/charrefs/whitespace byte-exact, and write the .txt by hand
from what the text *should* be.

## What counts as a shape

A block where flattening the inline markup changes the text — i.e. where a tag
edge would otherwise land in the output — plus block-level dropcaps, which no
amount of inline flattening can reach (STU-532).

Shapes are keyed on `(block tag, inline tag, kind)`, never on class names. The
parser only sees tag names; `<span class="small1">` and `<span class="f_ITAL">`
are one shape to it, and keying on classes would report every publisher's CSS
vocabulary as a new parser concern. Classes stay in the committed snippet as
provenance, so the corpus still records which house wrote what.

A block contributes one unit per inline tag it contains, so a minimal committed
snippet (`p` + `sup`) still covers that unit inside a real paragraph that also
carries `<i>` and `<span>`. Coverage is per tag pair, not per block.
"""
import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.parse_epub import (  # noqa: E402
    _INLINE_TAGS,
    _flatten_inline_markup,
    _leaf_blocks,
    _mark_paragraph_breaks,
    _merge_block_dropcaps,
    clean_chapter_text,
)

CORPUS_DIR = Path(__file__).resolve().parent
WORD = re.compile(r"\w", re.UNICODE)

WORD_SPLIT = "word-split"      # a tag edge lands inside a word: the STU-519 class
SPACING = "spacing"            # a tag edge only strands a space next to punctuation
BLOCK_DROPCAP = "block-dropcap"  # the split is between two blocks: STU-532


def parse(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    _flatten_inline_markup(soup)
    _merge_block_dropcaps(soup)
    _mark_paragraph_breaks(soup)
    return clean_chapter_text(soup.get_text(separator="\n", strip=True))


def unflattened(html: str) -> str:
    """The text with no inline flattening — what the parser produced pre-STU-519."""
    soup = BeautifulSoup(html, "html.parser")
    _mark_paragraph_breaks(soup)
    return clean_chapter_text(soup.get_text(separator="\n", strip=True))


def splits_a_word(broken: str, fixed: str) -> bool:
    """Does a space `broken` inserted sit between two word characters of `fixed`?"""
    i = j = 0
    while i < len(broken) and j < len(fixed):
        if broken[i] == fixed[j]:
            i += 1
            j += 1
        elif broken[i] == " ":
            before = fixed[j - 1] if j else ""
            after = fixed[j] if j < len(fixed) else ""
            if WORD.match(before) and WORD.match(after):
                return True
            i += 1
        else:
            return False
    return False


def block_dropcap_pairs(soup):
    """A block holding one capital letter, followed by one starting lowercase.

    The survey question ("where does this shape occur") is not the production
    question ("rejoin it"), so this reads the tree _merge_block_dropcaps has not
    touched. Both follow the same rule; loosen one and this stops reporting what
    the other now merges.
    """
    blocks = _leaf_blocks(soup)
    for first, second in zip(blocks, blocks[1:]):
        head, tail = first.get_text().strip(), second.get_text().strip()
        if len(head) == 1 and head.isupper() and tail[:1].islower():
            yield first, second


def units(soup):
    """Yield ((block_tag, inline_tag, kind), markup) for every shape in the tree."""
    for first, second in block_dropcap_pairs(soup):
        yield (first.name, "-", BLOCK_DROPCAP), f"{first}\n{second}"
    for block in _leaf_blocks(soup):
        frag = str(block)
        broken, fixed = unflattened(frag), parse(frag)
        if broken == fixed:
            continue
        kind = WORD_SPLIT if splits_a_word(broken, fixed) else SPACING
        for inline in {el.name for el in block.find_all(list(_INLINE_TAGS))}:
            yield (block.name, inline, kind), frag


def corpus_units() -> dict:
    covered = {}
    for path in sorted(CORPUS_DIR.glob("*.html")):
        soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
        for unit, _ in units(soup):
            covered.setdefault(unit, path.name)
    return covered


def survey(library: Path) -> dict:
    shapes = defaultdict(list)
    for epub_path in sorted(library.rglob("*.epub")):
        try:
            book = epub.read_epub(str(epub_path), options={"ignore_ncx": True})
        except Exception as exc:  # a corrupt book must not hide the other fifteen
            print(f"[WARN] unreadable, skipped: {epub_path.name}: {exc}", file=sys.stderr)
            continue
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            html = item.get_content().decode("utf-8", "replace")
            for unit, frag in units(BeautifulSoup(html, "html.parser")):
                shapes[unit].append((epub_path.name, item.get_name(), frag))
    return shapes


def _label(unit) -> str:
    block, inline, kind = unit
    return f"<{block}> {inline:6s} {kind}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Survey a local library for markup shapes.")
    ap.add_argument("--library", type=Path, default=Path("library"),
                    help="library checkout to survey (default: library/)")
    ap.add_argument("--show-covered", action="store_true",
                    help="also list the shapes the corpus already covers")
    args = ap.parse_args()

    if not args.library.is_dir():
        print(f"no such library: {args.library}", file=sys.stderr)
        return 2

    covered = corpus_units()
    shapes = survey(args.library)
    if not shapes:
        print(f"no markup shape found under {args.library}/ — nothing to survey")
        return 0

    new = sorted((u for u in shapes if u not in covered), key=lambda u: -len(shapes[u]))
    for unit in new:
        hits = shapes[unit]
        books = sorted({book for book, _, _ in hits})
        book, item, frag = hits[0]
        print(f"\nNEW      {_label(unit):34s} {len(hits):6d}x  {len(books)} book(s): {', '.join(books[:3])}")
        print(f"         first seen: {book} :: {item}")
        print(f"         candidate:  {frag[:400]!r}")

    if args.show_covered:
        for unit in sorted(u for u in shapes if u in covered):
            print(f"COVERED  {_label(unit):34s} {len(shapes[unit]):6d}x  {covered[unit]}")

    for name in sorted({n for u, n in covered.items() if u not in shapes}):
        print(f"\nSTALE    {name}\n         no book under {args.library}/ shows this shape any more")

    stale = len({n for u, n in covered.items() if u not in shapes})
    print(f"\n{len(shapes)} shapes under {args.library}/ — "
          f"{len(shapes) - len(new)} covered, {len(new)} new, {stale} stale corpus file(s)")
    return 1 if new else 0


if __name__ == "__main__":
    sys.exit(main())
