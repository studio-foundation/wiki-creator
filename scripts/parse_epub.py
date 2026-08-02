#!/usr/bin/env python3
"""
Stage 1: EPUB Parsing
Script executor interface: reads JSON from stdin, writes JSON to stdout.

Input:  { "file_path": "/path/to/book.epub" }
Output: { "title": "...", "author": "...", "chapters": [{ "id": "...", "title": "...", "content": "..." }], "pov_detection": { "pov": "...", "first_person_count": int, "total_tokens": int, "confidence": "..." } }
"""

import json
import os
import re
import sys
import unicodedata
from pathlib import Path
import yaml

# Ensure project root is importable when running as `python scripts/parse_epub.py`.
from wiki_creator.backup import snapshot_book_artifacts
from wiki_creator.canon import resolve_book_source
from wiki_creator.chapters import declared_chapter_marks
from wiki_creator.lang import book_language, load_lang_config
from wiki_creator import studio_io

# Typographic ligatures that EPUB fonts may encode as single codepoints.
_LIGATURES: dict[str, str] = {
    '\ufb00': 'ff',
    '\ufb01': 'fi',
    '\ufb02': 'fl',
    '\ufb03': 'ffi',
    '\ufb04': 'ffl',
    '\ufb05': 'st',
    '\ufb06': 'st',
}

_APOSTROPHE_VARIANTS: tuple[str, ...] = (
    '\u02bb',  # modifier letter turned comma
    '\u2019',  # right single quotation mark
    '\u2018',  # left single quotation mark
    '\u02bc',  # modifier letter apostrophe
    '\u2032',  # prime
    '\uff07',  # fullwidth apostrophe
)


# Inline elements never break a word, so their boundaries must not become separators.
# A dropcap or small-caps opener is markup of this kind: <span>D</span><span>ISCOVERY</span>.
_INLINE_TAGS: tuple[str, ...] = (
    'span', 'em', 'i', 'b', 'strong', 'small', 'sup', 'sub', 'a', 'u', 'cite', 'abbr',
)


def _flatten_inline_markup(soup) -> None:
    """Dissolve inline tags in place so get_text() cannot split a word at their edges."""
    for tag in soup.find_all(_INLINE_TAGS):
        tag.unwrap()
    soup.smooth()


# Block elements end a paragraph. <br> is deliberately absent: it is a soft line
# break (verse, addresses) and stays a space, as it always has.
_BLOCK_TAGS: tuple[str, ...] = (
    'p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'li',
)

# get_text(separator="\n", strip=True) drops whitespace-only strings, so a
# paragraph break cannot be carried by whitespace — it needs a character that
# survives strip(). NUL never occurs in EPUB prose.
_PARAGRAPH_MARK = '\x00'
_PARAGRAPH_MARK_RUN = re.compile(r'[ \t\n]*\x00[ \t\n\x00]*')


def _leaf_blocks(soup) -> list:
    """Blocks holding no other block: a wrapper repeats what its children hold."""
    return [tag for tag in soup.find_all(_BLOCK_TAGS) if not tag.find(_BLOCK_TAGS)]


def _merge_block_dropcaps(soup) -> None:
    """Rejoin a dropcap that is its own block, not its own span (STU-532).

    `_flatten_inline_markup` cannot reach this shape — the word is split across
    two *block* elements — so `_mark_paragraph_breaks` would put a paragraph
    break inside the word. The Hobbit opens this way: `<p>I</p><p>n a hole…</p>`.

    Where STU-519's deleted regex guessed from flat text (and welded `A`+`silvery`
    into a false entity), this reads the markup while the tree is still standing:
    a block holding one capital letter, followed by one starting lowercase. A
    lone capital is a legal English word — a lone capital as an entire paragraph,
    with the next paragraph resuming mid-sentence, is typesetting.

    Must run after `_flatten_inline_markup` (so `<p><span>I</span></p>` has
    already collapsed to `<p>I</p>`) and before `_mark_paragraph_breaks` (whose
    mark for the dropcap block would outlive the block itself).
    """
    blocks = _leaf_blocks(soup)
    for dropcap, body in zip(blocks, blocks[1:]):
        letter = dropcap.get_text().strip()
        if len(letter) != 1 or not letter.isupper():
            continue
        for text in body.strings:
            if not text.strip():
                continue
            if not text.lstrip()[:1].islower():
                break  # a capital resumes a new sentence: two real paragraphs
            text.replace_with(letter + text.lstrip())
            dropcap.decompose()
            break


def _mark_paragraph_breaks(soup) -> None:
    """Mark block boundaries in place so get_text() cannot flatten them away.

    The mark goes *after* the tag, not inside it, so `_extract_chapter_title`'s
    `heading.get_text()` stays clean. Must run after `_flatten_inline_markup`:
    the two mutate the same tree, and marking a tag that is about to be
    unwrapped would strand its mark mid-word.
    """
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.insert_after(_PARAGRAPH_MARK)


def clean_chapter_text(text: str) -> str:
    """Normalize a chapter's extracted text for NLP.

    Input is always `_flatten_inline_markup` + `_mark_paragraph_breaks` +
    `get_text(separator="\\n", strip=True)`, i.e. "\\n".join of non-empty
    stripped strings, with `_PARAGRAPH_MARK` at every block boundary. Newlines
    are therefore tag boundaries only, and the marks become the \\n\\n paragraph
    breaks (STU-523). No HTML entities reach here (html.parser resolves charrefs
    at parse time).
    """
    # 1. Unicode NFC normalization — must be first to compose combining characters
    text = unicodedata.normalize('NFC', text)

    # 2. Resolve typographic ligatures (ﬁ → fi, ﬂ → fl, ﬀ → ff, …)
    for lig, repl in _LIGATURES.items():
        text = text.replace(lig, repl)

    # 3. Normalize apostrophe-like Unicode chars and guillemets
    for apostrophe in _APOSTROPHE_VARIANTS:
        text = text.replace(apostrophe, "'")
    text = text.replace('\u00ab', '"').replace('\u00bb', '"')  # « » → "

    # 4. Normalize non-breaking spaces → regular space
    text = text.replace('\u00a0', ' ').replace('\u202f', ' ')

    # 5. Every \n is a tag boundary, never a word or paragraph boundary. A \r is
    #    source whitespace too: it reaches here from a &#13; charref, which
    #    html.parser resolves at parse time (6 of the 16 books ship them, and
    #    Eragon puts one between the two words of a chapter title). Step 6
    #    collapses the pair a \r\n leaves behind.
    text = text.replace('\r', ' ').replace('\n', ' ')

    # 6. Normalize runs of spaces/tabs to a single space
    text = re.sub(r'[ \t]{2,}', ' ', text)

    # 7. Marked block boundaries become paragraph breaks; nesting emits several
    #    marks for one boundary (a <p> inside a <div>), so a run collapses to one.
    text = _PARAGRAPH_MARK_RUN.sub('\n\n', text)

    # 8. Strip each paragraph and drop the empty ones
    paragraphs = [p.strip() for p in text.split('\n\n')]
    return '\n\n'.join(p for p in paragraphs if p)


# Project Gutenberg wraps the work in machine-readable markers; the license
# header sits before START and the full license after END, both embedded inside
# a content spine item — so section-filter (whole-section) cannot drop them
# (STU-627). The title between EBOOK and *** varies per book, hence `.*?`.
_GUTENBERG_START = re.compile(
    r'\*\*\*\s*START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*',
    re.IGNORECASE | re.DOTALL,
)
_GUTENBERG_END = re.compile(
    r'\*\*\*\s*END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*',
    re.IGNORECASE | re.DOTALL,
)


def strip_gutenberg_boilerplate(chapters: list[dict]) -> list[dict]:
    """Drop Project Gutenberg header/footer boilerplate (STU-627).

    The work lives strictly between the START and END markers. Everything before
    START (the license preamble) and after END (the full license) is boilerplate
    that leaks junk entities like `Project Gutenberg`/`United States` into
    extraction. The markers may sit inside a content section, so this slices
    within the marked chapter and drops whole sections outside the pair. A book
    with no markers (non-Gutenberg source) is returned unchanged.
    """
    for i, ch in enumerate(chapters):
        m = _GUTENBERG_START.search(ch["content"])
        if m:
            ch["content"] = ch["content"][m.end():].strip()
            chapters = chapters[i:]
            break
    for i, ch in enumerate(chapters):
        m = _GUTENBERG_END.search(ch["content"])
        if m:
            ch["content"] = ch["content"][:m.start()].strip()
            chapters = chapters[:i + 1]
            break
    return [ch for ch in chapters if ch["content"].strip()]


# A printed line ends a real sentence with one of these — a period/!/?, a closing
# quote after one, an ellipsis, or a dash trailing off into what follows (STU-768:
# "...and their names were—" leads into a list on the next line). A title-page
# label (a title, "BY", an author or publisher name, a print date) carries none of
# them; it is a name or a date, not a clause.
_SENTENCE_TERMINAL_CHARS = ('.', '!', '?', '…', '—', '–', '’', '”', '"')

# How many leading paragraphs to look through before giving up: a chapter that never
# hits a sentence terminal within this many paragraphs is not a title page glued to
# prose — it is something this heuristic doesn't understand, so it is left alone
# rather than emptied.
_MAX_FRONTMATTER_PARAGRAPHS = 12

# A single label paragraph ahead of the prose is the chapter's own heading
# ("Chapter One" is a leaf block, in-body, exactly like a title-page line, and
# just as terminal-free) — only two or more in a row is a real title-page block.
_MIN_FRONTMATTER_PARAGRAPHS = 2


def strip_inline_frontmatter(chapters: list[dict]) -> list[dict]:
    """Drop a title-page block glued into the book's first chapter (STU-768).

    A Gutenberg "images" edition can pack the title/author/publisher/print-info
    block directly into the *same* spine item as the story, with no chapter
    boundary between them — `is_frontmatter_chapter` cannot help, since the
    whole thing is one chapter, not two. The block prints as a run of short,
    label-like paragraphs with no sentence terminal; the story proper is the
    first paragraph that has one. Only `chapters[0]` is touched — a title page
    is only ever glued to the very start of a book, never mid-book.
    """
    if not chapters:
        return chapters
    paragraphs = chapters[0]["content"].split("\n\n")
    limit = min(len(paragraphs) - 1, _MAX_FRONTMATTER_PARAGRAPHS)
    cut = 0
    for i in range(limit):
        if paragraphs[i].strip().endswith(_SENTENCE_TERMINAL_CHARS):
            break
        cut = i + 1
    else:
        cut = 0  # never hit a sentence terminal within the cap: leave it alone
    if cut < _MIN_FRONTMATTER_PARAGRAPHS:
        cut = 0
    if cut:
        chapters[0]["content"] = "\n\n".join(paragraphs[cut:]).strip()
    return chapters


def _first_person_regex(language: str) -> re.Pattern | None:
    """Build the first-person detection regex from cue_words/<language>.json.

    Vocabulary lives in cue_words (never hardcoded here). Returns None when
    the language config defines no first-person vocabulary — POV detection
    then degrades gracefully to 'omniscient'.
    """
    cfg = load_lang_config(language)
    pronouns = cfg.get("first_person_pronouns", [])
    prefixes = cfg.get("first_person_prefixes", [])
    parts = []
    if pronouns:
        parts.append(r"\b(?:" + "|".join(re.escape(p) for p in pronouns) + r")\b")
    for prefix in prefixes:
        parts.append(r"\b" + re.escape(prefix))
    if not parts:
        return None
    return re.compile("|".join(parts), re.IGNORECASE)


def _thought_markers_regex(language: str) -> re.Pattern | None:
    """Third-person 'thought' markers regex from cue_words/<language>.json."""
    cfg = load_lang_config(language)
    markers = cfg.get("third_person_thought_markers", [])
    if not markers:
        return None
    return re.compile(
        r"\b(?:" + "|".join(re.escape(m) for m in markers) + r")\b",
        re.IGNORECASE,
    )


def detect_pov(text: str, language: str = "fr") -> dict:
    """Detect narrative point of view from raw chapter text.

    `language` selects the pronoun vocabulary from cue_words/<language>.json;
    defaults to 'fr' to preserve historical behavior.
    """
    tokens = text.split()
    total_tokens = len(tokens)
    if total_tokens == 0:
        return {"pov": "omniscient", "first_person_count": 0, "total_tokens": 0, "confidence": "low"}

    fp_re = _first_person_regex(language)
    first_person_count = len(fp_re.findall(text)) if fp_re else 0
    ratio = first_person_count / total_tokens

    if ratio > 0.05:
        confidence = "high"
        pov = "first_person"
    elif ratio > 0.01:
        confidence = "medium"
        pov = "first_person"
    else:
        confidence = "low" if ratio > 0 else "high"
        tm_re = _thought_markers_regex(language)
        has_thought_markers = bool(tm_re.search(text)) if tm_re else False
        pov = "third_limited" if has_thought_markers else "omniscient"

    return {
        "pov": pov,
        "first_person_count": first_person_count,
        "total_tokens": total_tokens,
        "confidence": confidence,
    }


def annotate_pov(chapters: list[dict], language: str = "fr") -> dict:
    """Persist per-chapter POV onto each chapter and return the book-level modal.

    Recovers the per-chapter detail that parse_epub previously discarded: writes
    `pov` and `pov_confidence` onto every chapter dict, then returns the modal
    `pov_detection` (unchanged shape) for backward compatibility. The book-level
    result uses the modal per-chapter POV for robustness (avoids dilution in
    mixed-POV or frame-narrative books).
    """
    if not chapters:
        return {"pov": "omniscient", "first_person_count": 0, "total_tokens": 0, "confidence": "low"}

    chapter_results = [detect_pov(ch["content"], language=language) for ch in chapters]
    for ch, r in zip(chapters, chapter_results):
        ch["pov"] = r["pov"]
        ch["pov_confidence"] = r["confidence"]

    pov_counts: dict[str, int] = {}
    for r in chapter_results:
        pov_counts[r["pov"]] = pov_counts.get(r["pov"], 0) + 1
    modal_pov = max(pov_counts, key=lambda p: pov_counts[p])
    total_fp = sum(r["first_person_count"] for r in chapter_results)
    total_tokens = sum(r["total_tokens"] for r in chapter_results)
    agg_ratio = total_fp / total_tokens if total_tokens > 0 else 0
    if modal_pov == "first_person":
        confidence = "high" if agg_ratio > 0.05 else "medium" if agg_ratio > 0.01 else "low"
    else:
        confidence = "high"
    return {
        "pov": modal_pov,
        "first_person_count": total_fp,
        "total_tokens": total_tokens,
        "confidence": confidence,
    }


MIN_CHAPTER_CHARS = 100


def _build_toc_title_map(toc, parent_title: str = "") -> dict:
    """Recursively build a mapping from filename to title from the EPUB TOC.

    When a chapter has only a bare number/short title and belongs to a named
    section, the section name is prepended: "Premier acte … — 15."
    """
    result = {}
    for item in toc:
        if isinstance(item, tuple):
            section, children = item
            href = section.href.split('#')[0] if section.href else ''
            if href and section.title:
                result[href] = section.title
                result[os.path.basename(href)] = section.title
            result.update(_build_toc_title_map(children, parent_title=section.title or parent_title))
        else:
            href = item.href.split('#')[0] if item.href else ''
            if href and item.title:
                # If the chapter title is just a short label (number, roman numeral…)
                # and we have a parent section, prepend it for context.
                title = item.title
                if parent_title and len(title) <= 6:
                    title = f"{parent_title} — {title}"
                result[href] = title
                result[os.path.basename(href)] = title
    return result


def _build_toc_fragment_map(toc) -> dict:
    """Map each spine filename to the TOC's in-file `#fragment` anchors, in order.

    `_build_toc_title_map` keeps only the file half of every href; this keeps the
    fragment half it discards. A publisher that packs many chapters into one spine
    item declares their boundaries here — one TOC entry per chapter, each a
    `file.xhtml#anchor` into the shared file (STU-727). A TOC that points only at
    whole files (every commercial EPUB in the library) yields an empty map, and
    nothing splits.
    """
    result: dict[str, list[tuple[str, str]]] = {}

    def walk(items):
        for item in items:
            if isinstance(item, tuple):
                section, children = item
                walk([section])
                walk(children)
                continue
            href = item.href or ''
            if '#' not in href:
                continue
            filename, fragment = href.split('#', 1)
            if not fragment:
                continue
            result.setdefault(os.path.basename(filename), []).append((fragment, item.title or ''))

    walk(toc)
    return result


def _count_toc_entries(toc) -> int:
    """How many sections the EPUB TOC declares, fragment or whole file.

    The thin-TOC gate (STU-728) compares against this, not against the fragment
    count alone: a commercial EPUB declares one *whole-file* entry per chapter, so
    counting fragments would read its TOC as declaring nothing and let any
    three-entry list of in-file links — endnotes, an index — supersede it.
    """
    total = 0
    for item in toc:
        if isinstance(item, tuple):
            section, children = item
            total += 1 + _count_toc_entries(children)
        else:
            total += 1
    return total


# A list/table of in-file links is the book's own printed contents only if it has
# entries to spare; below this it is a cross-reference, not a table of contents.
MIN_PRINTED_CONTENTS_ANCHORS = 3

# Where a printed contents list is laid out. A `<div>` is deliberately absent: it
# is also the wrapper *around* the list, so it would absorb whatever sits beside
# it (a list of illustrations, a footnote block) into the same set of anchors.
_CONTENTS_CONTAINERS: tuple[str, ...] = ('table', 'ul', 'ol')


def _contents_entry_title(anchor) -> str:
    """The printed label of one contents entry: its row, minus the link itself.

    A printed contents splits the entry across cells and the link is never the
    title: The Road to Oz links the chapter number (`1.`) and prints the title
    beside it, the Patchwork Girl links the page number (`19`) and prints the
    title before it. Reading the row and dropping the anchor's own text gets the
    title on both, where the row alone drags a page number into it. A contents
    whose link *is* the whole entry falls back to the link.
    """
    row = anchor.find_parent(['tr', 'li'])
    if row is None:
        return anchor.get_text(' ', strip=True)
    outside = [t.strip() for t in row.strings if t.strip() and anchor not in t.parents]
    return ' '.join(outside) or anchor.get_text(' ', strip=True)


def _build_printed_contents(soups) -> list[tuple[str, str]]:
    """The book's own printed list of chapters: `(fragment, title)`, in order.

    A publisher can print the list of chapters in the body — a table of
    `file.xhtml#anchor` links — and leave the EPUB TOC anchoring only front
    matter, which is the thin-TOC shape STU-727 deferred (STU-728). The densest
    such list in the spine is that contents; a book printing none yields `[]`.

    Only the fragment is kept, never the filename: a converter that split the
    source file in two leaves every href naming the first half — The Road to Oz
    points all 24 entries at `-h-0` while chapters 12-24 live in `-h-1` — so the
    anchor is found by id in whichever spine item holds it.
    """
    best: list[tuple[str, str]] = []
    for soup in soups:
        for container in soup.find_all(_CONTENTS_CONTAINERS):
            fragments: list[tuple[str, str]] = []
            seen: set[str] = set()
            for anchor in container.find_all('a', href=True):
                fragment = anchor['href'].partition('#')[2]
                if not fragment or fragment in seen:
                    continue
                seen.add(fragment)
                fragments.append((fragment, _contents_entry_title(anchor)))
            if len(fragments) > len(best):
                best = fragments
    return best if len(best) >= MIN_PRINTED_CONTENTS_ANCHORS else []


# A split marker planted before each anchor: a Private Use codepoint never occurs
# in prose, is non-whitespace (so get_text(strip=True) keeps it as its own string),
# and clean_chapter_text — which runs per segment, after the split — never sees it.
_SPLIT_MARK = ''


def _clears_min_chars(cleaned: str) -> bool:
    """The MIN_CHAPTER_CHARS gate: prose length, not structure (STU-523)."""
    return len(cleaned) - cleaned.count('\n\n') >= MIN_CHAPTER_CHARS


def _plant_split_marks(soup, fragments: list) -> list[tuple[str, str]]:
    """Mark every declared fragment that resolves, in document order; return
    `(id, title)` per section.

    `find_all(id=True)` yields elements in document order, so this is robust to
    anchors nested at different depths (Oz packs some in a `<div>`) — the marker
    lands wherever the anchor sits, and get_text reads the same order.

    Runs **before** `_flatten_inline_markup`: a printed contents list anchors an
    empty `<a id=…/>` (STU-728), and unwrapping that tag would erase the anchor
    before it could be found.
    """
    title_of: dict[str, str] = {}
    for fragment, title in fragments:
        title_of.setdefault(fragment, title)

    ordered, seen = [], set()
    for el in soup.find_all(id=True):
        fid = el.get('id')
        if fid in title_of and fid not in seen:
            el.insert_before(_SPLIT_MARK)
            ordered.append((fid, title_of[fid] or fid))
            seen.add(fid)
    return ordered


_MARK_ID_RE = re.compile(r'\W+', re.UNICODE)


def _mark_id(mark: str) -> str:
    """A chapter id for a printed mark: the mark itself, slugged."""
    return _MARK_ID_RE.sub('-', mark.lower()).strip('-') or 'mark'


def _normalized_line(text: str) -> str:
    """A printed line as a reader transcribes it: one space between words.

    The book YAML holds what the page shows; the markup holds whatever the
    typesetter's line breaks and `&#13;` charrefs (STU-531) left between them.
    """
    return ' '.join(text.split())


def _plant_printed_mark_splits(soup, marks: list[str]) -> list[tuple[str, str]]:
    """Mark every block printing one of the book's declared chapter marks (STU-736).

    Returns `(id, title)` per mark found, in document order — the shape
    `_plant_split_marks` returns for an anchored contents. Only a **leaf** block
    can be the mark: a wrapper around it prints the same text, and marking both
    would cut the same boundary twice and lose the section to the length gate.
    """
    wanted = {_normalized_line(mark): mark for mark in marks}
    found, seen = [], set()
    for block in _leaf_blocks(soup):
        mark = wanted.get(_normalized_line(block.get_text()))
        if mark is None or _mark_id(mark) in seen:
            continue
        seen.add(_mark_id(mark))
        block.insert_before(_SPLIT_MARK)
        found.append((_mark_id(mark), mark))
    return found


def _split_item_chapters(soup, item, sections: list[tuple[str, str]]) -> list:
    """Split one spine item into a chapter per marked boundary (STU-727).

    The boundaries are already marked in document order; run the text pipeline
    once, then split the flat text on the marker: segment 0 is the front matter
    before the first boundary, segments 1..N align with `sections`.
    """
    lead_title = _extract_chapter_title(soup, item, {})
    _mark_paragraph_breaks(soup)
    segments = soup.get_text(separator="\n", strip=True).split(_SPLIT_MARK)

    chapters = []
    lead = clean_chapter_text(segments[0])
    if _clears_min_chars(lead):
        chapters.append({"id": item.get_id(), "title": lead_title, "content": lead})
    for (section_id, title), segment in zip(sections, segments[1:]):
        cleaned = clean_chapter_text(segment)
        if not _clears_min_chars(cleaned):
            continue
        chapters.append({
            "id": f"{item.get_id()}#{section_id}",
            "title": title,
            "content": cleaned,
        })
    return chapters


def _continues_previous(chapters: list, lead: dict) -> bool:
    """Is a packed item's anchorless lead the tail of the previous item's chapter?

    A Project Gutenberg converter that cuts a packed spine item into several files
    cuts **mid-chapter** (STU-735): the next file opens on the tail of the previous
    chapter, with no anchor in front of it, so `_split_item_chapters` emitted it as
    a section of its own titled by the filename — 26 chapters where The Road to Oz
    has 24, and its chapter 11 split across two entries.

    A lead is that tail only when the previous item ended *inside* a chapter, i.e.
    its last emitted segment opened at an anchor. The anchorless lead of the first
    content item (no previous chapter) and one following a whole-file chapter are
    genuine front matter, so the rule can never be "always append".
    """
    return "#" not in lead["id"] and bool(chapters) and "#" in chapters[-1]["id"]


def _extract_chapter_title(soup, item, toc_titles: dict) -> str:
    """Find the best human-readable title for a chapter item."""
    name = item.get_name()
    basename = os.path.basename(name)

    # 1. TOC (NCX/nav) — most reliable
    toc_title = toc_titles.get(name) or toc_titles.get(basename)
    if toc_title:
        return toc_title

    # 2. First heading in the HTML
    heading = soup.find(['h1', 'h2', 'h3'])
    if heading:
        text = heading.get_text(strip=True)
        if text:
            return text

    # 3. <title> tag
    title_tag = soup.find('title')
    if title_tag:
        text = title_tag.get_text(strip=True)
        if text:
            return text

    # 4. Fallback: filename
    return basename


def _env_max_chapters() -> int | None:
    """Chapter cap for subset test runs, from WIKI_MAX_CHAPTERS. Absent/empty/<=0 → None."""
    raw = os.environ.get("WIKI_MAX_CHAPTERS", "").strip()
    if not raw:
        return None
    n = int(raw)
    return n if n > 0 else None


def parse_epub(
    file_path: str,
    language: str = "fr",
    max_chapters: int | None = None,
    chapter_marks: list[str] | None = None,
) -> dict:
    import ebooklib
    from ebooklib import epub
    from bs4 import BeautifulSoup

    book = epub.read_epub(file_path)

    title = book.get_metadata("DC", "title")
    title = title[0][0] if title else "Unknown"

    author = book.get_metadata("DC", "creator")
    author = author[0][0] if author else None

    toc_titles = _build_toc_title_map(book.toc)
    toc_fragments = _build_toc_fragment_map(book.toc)

    # Use EPUB spine order (the official reading order).
    spine_ids = [item_id for item_id, _ in book.spine]
    items_by_id = {
        item.get_id(): item
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT)
    }

    spine = [
        (items_by_id[spine_id], BeautifulSoup(items_by_id[spine_id].get_content(), "html.parser"))
        for spine_id in spine_ids
        if spine_id in items_by_id
    ]

    # A book that declares the chapter marks it prints declares them whole
    # (STU-736): they are the contents, and no anchored source is read beside
    # them. An edition needing this has no anchors to union anyway — that is why
    # its reader had to write them down.
    marks = chapter_marks or []
    printed_contents = [] if marks else _build_printed_contents(soup for _, soup in spine)

    # A thin TOC — one declaring fewer sections than the book's own printed list of
    # chapters — is superseded by that list, whole (STU-728). The more complete
    # contents wins; the two are never unioned, or a printed list would inherit the
    # thin TOC's front-matter anchors as extra chapter boundaries.
    if marks or len(printed_contents) > _count_toc_entries(book.toc):
        toc_fragments = {}
    else:
        printed_contents = []

    chapters = []
    found_marks: set[str] = set()
    for item, soup in spine:
        if marks:
            sections = _plant_printed_mark_splits(soup, marks)
            found_marks.update(title for _, title in sections)
        else:
            # A spine item holding fragment anchors the contents declares holds
            # several chapters; split it at those publisher-declared boundaries
            # (STU-727).
            fragments = toc_fragments.get(os.path.basename(item.get_name())) or printed_contents
            sections = _plant_split_marks(soup, fragments) if fragments else []
        _flatten_inline_markup(soup)
        _merge_block_dropcaps(soup)
        if sections:
            split = _split_item_chapters(soup, item, sections)
            if split:
                if _continues_previous(chapters, split[0]):
                    chapters[-1]["content"] += "\n\n" + split.pop(0)["content"]
                chapters.extend(split)
                continue
        chapter_title = _extract_chapter_title(soup, item, toc_titles)
        _mark_paragraph_breaks(soup)
        raw_text = soup.get_text(separator="\n", strip=True)
        cleaned = clean_chapter_text(raw_text)
        # The bar gates prose, so it must not count structure: \n\n is one char
        # wider than the space it replaced, and on 01_eragon.epub that alone was
        # enough to lift seven boilerplate pages over it (STU-523).
        if not _clears_min_chars(cleaned):
            continue
        chapters.append({
            "id": item.get_id(),
            "title": chapter_title,
            "content": cleaned,
        })

    for mark in marks:
        if mark not in found_marks:
            print(f"parse_epub: declared chapter mark not printed anywhere: {mark!r}", file=sys.stderr)

    chapters = strip_gutenberg_boilerplate(chapters)
    chapters = strip_inline_frontmatter(chapters)

    if max_chapters is not None and max_chapters > 0:
        chapters = chapters[:max_chapters]

    # Compute per-chapter POV (persisted onto each chapter) + book-level modal.
    pov_detection = annotate_pov(chapters, language=language)

    return {"title": title, "author": author, "chapters": chapters, "pov_detection": pov_detection}


def main():
    payload = studio_io.read_payload()
    input_data = yaml.safe_load(payload.get("additional_context", "")) or {}
    file_path = input_data.get("file_path")

    if not file_path:
        json.dump({"error": "missing field: file_path"}, sys.stdout)
        sys.exit(1)

    paths = studio_io.paths_from_payload(payload)
    # STU-760: snapshot before anything below writes a byte — the first action
    # of wiki-full's first executing stage.
    snapshot_book_artifacts(paths)

    language = book_language(input_data)
    max_chapters = _env_max_chapters()
    if max_chapters is not None:
        print(f"[subset] WIKI_MAX_CHAPTERS={max_chapters}: parsing only the first {max_chapters} chapters", file=sys.stderr)
    # file_path anchors identity (it derives every output path); the series canon
    # policy decides which source is actually read.
    source_path = resolve_book_source(file_path)
    result = parse_epub(
        str(source_path),
        language=language,
        max_chapters=max_chapters,
        chapter_marks=declared_chapter_marks(input_data),
    )
    result["language"] = language
    paths.processing.mkdir(parents=True, exist_ok=True)
    with open(paths.processing / "epub_data.json", "w", encoding="utf-8") as _f:
        json.dump(result, _f, ensure_ascii=False)
    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
