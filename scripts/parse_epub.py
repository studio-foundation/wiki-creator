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
from wiki_creator.canon import resolve_book_source
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

    # 5. Every \n is a tag boundary, never a word or paragraph boundary
    text = text.replace('\n', ' ')

    # 6. Normalize runs of spaces/tabs to a single space
    text = re.sub(r'[ \t]{2,}', ' ', text)

    # 7. Marked block boundaries become paragraph breaks; nesting emits several
    #    marks for one boundary (a <p> inside a <div>), so a run collapses to one.
    text = _PARAGRAPH_MARK_RUN.sub('\n\n', text)

    # 8. Strip each paragraph and drop the empty ones
    paragraphs = [p.strip() for p in text.split('\n\n')]
    return '\n\n'.join(p for p in paragraphs if p)


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


def parse_epub(file_path: str, language: str = "fr", max_chapters: int | None = None) -> dict:
    import ebooklib
    from ebooklib import epub
    from bs4 import BeautifulSoup

    book = epub.read_epub(file_path)

    title = book.get_metadata("DC", "title")
    title = title[0][0] if title else "Unknown"

    author = book.get_metadata("DC", "creator")
    author = author[0][0] if author else None

    toc_titles = _build_toc_title_map(book.toc)

    # Use EPUB spine order (the official reading order).
    spine_ids = [item_id for item_id, _ in book.spine]
    items_by_id = {
        item.get_id(): item
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT)
    }

    chapters = []
    for spine_id in spine_ids:
        item = items_by_id.get(spine_id)
        if item is None:
            continue
        soup = BeautifulSoup(item.get_content(), "html.parser")
        _flatten_inline_markup(soup)
        chapter_title = _extract_chapter_title(soup, item, toc_titles)
        _mark_paragraph_breaks(soup)
        raw_text = soup.get_text(separator="\n", strip=True)
        cleaned = clean_chapter_text(raw_text)
        # The bar gates prose, so it must not count structure: \n\n is one char
        # wider than the space it replaced, and on 01_eragon.epub that alone was
        # enough to lift seven boilerplate pages over it (STU-523).
        if len(cleaned) - cleaned.count('\n\n') < MIN_CHAPTER_CHARS:
            continue
        chapters.append({
            "id": item.get_id(),
            "title": chapter_title,
            "content": cleaned,
        })

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

    language = book_language(input_data)
    max_chapters = _env_max_chapters()
    if max_chapters is not None:
        print(f"[subset] WIKI_MAX_CHAPTERS={max_chapters}: parsing only the first {max_chapters} chapters", file=sys.stderr)
    # file_path anchors identity (it derives every output path); the series canon
    # policy decides which source is actually read.
    source_path = resolve_book_source(file_path)
    result = parse_epub(str(source_path), language=language, max_chapters=max_chapters)
    result["language"] = language
    paths = studio_io.paths_from_payload(payload)
    paths.processing.mkdir(parents=True, exist_ok=True)
    with open(paths.processing / "epub_data.json", "w", encoding="utf-8") as _f:
        json.dump(result, _f, ensure_ascii=False)
    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
