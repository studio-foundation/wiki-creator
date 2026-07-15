#!/usr/bin/env python3
"""
Stage 1: EPUB Parsing
Script executor interface: reads JSON from stdin, writes JSON to stdout.

Input:  { "file_path": "/path/to/book.epub" }
Output: { "title": "...", "author": "...", "chapters": [{ "id": "...", "title": "...", "content": "..." }], "pov_detection": { "pov": "...", "first_person_count": int, "total_tokens": int, "confidence": "..." } }
"""

import html
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


def clean_chapter_text(text: str) -> str:
    """Normalize chapter text to remove noise before NLP processing."""
    # 0. Unicode NFC normalization — must be first to compose combining characters
    text = unicodedata.normalize('NFC', text)

    # 1. Resolve typographic ligatures (ﬁ → fi, ﬂ → fl, ﬀ → ff, …)
    for lig, repl in _LIGATURES.items():
        text = text.replace(lig, repl)

    # 2. Normalize apostrophe-like Unicode chars and guillemets
    for apostrophe in _APOSTROPHE_VARIANTS:
        text = text.replace(apostrophe, "'")
    text = text.replace('\u00ab', '"').replace('\u00bb', '"')  # « » → "

    # 3. Unescape HTML entities (&nbsp; → \xa0, &mdash; → —, etc.)
    text = html.unescape(text)

    # 3b. Normalize non-breaking spaces → regular space
    #     html.unescape() converts &nbsp; → \xa0, so this comes after step 3.
    text = text.replace('\u00a0', ' ').replace('\u202f', ' ')

    # 4. Collapse runs of 2+ newlines into exactly \n\n (paragraph break)
    text = re.sub(r'\n{2,}', '\n\n', text)

    # 5. Replace remaining single \n with a space
    text = re.sub(r'(?<!\n)\n(?!\n)', ' ', text)

    # 5b. Joindre lettre majuscule isolée + mot suivant en minuscule
    #     Artefact lettrine HTML : <span>P</span>edro → "P\nedro" (via BS4) → après step 5 → "P edro" → "Pedro"
    #     Doit venir APRÈS step 5 pour que le \n ait déjà été converti en espace.
    #     Ne touche pas "M. Pedro" (suivi d'un point) ni les fins de phrase.
    text = re.sub(r'(?<!\w)([A-ZÀÂÇÉÈÊËÎÏÔÙÛÜ]) ([a-záàâçéèêëîïôùûü])', r'\1\2', text)

    # 5c. Re-insert spaces eaten after À (e.g. "Àla" → "À la", "Àson" → "À son").
    #     Fixes EPUB encoding artifacts where the space after the preposition À was lost.
    #     Also restores any "À la" → "Àla" false positive introduced by step 5b above.
    text = re.sub(r'À([a-zéèêëàâùûüîïôœæç])', r'À \1', text)

    # 6. Normalize runs of spaces/tabs to a single space
    text = re.sub(r'[ \t]{2,}', ' ', text)

    # 6b. Repair English I-contractions split by EPUB/tokenization artifacts
    #     so spaCy sees "I'll"/"I've"/"I'd"/"I'm" instead of stray tokens.
    text = re.sub(r"\bI\s*'\s*([a-z]{1,6})\b", r"I'\1", text)

    # 7. Strip each paragraph
    paragraphs = [p.strip() for p in text.split('\n\n')]
    text = '\n\n'.join(p for p in paragraphs if p)

    return text.strip()


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
        raw_text = soup.get_text(separator="\n", strip=True)
        cleaned = clean_chapter_text(raw_text)
        if len(cleaned) < MIN_CHAPTER_CHARS:
            continue
        chapters.append({
            "id": item.get_id(),
            "title": _extract_chapter_title(soup, item, toc_titles),
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
