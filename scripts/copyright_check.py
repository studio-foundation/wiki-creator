#!/usr/bin/env python3
"""
Stage hook: Copyright Violation Detector (STU-234)
Detects verbatim sequences of ≥15 consecutive words between wiki output and EPUB source.

Hook usage (Studio on_stage_complete):
  python scripts/copyright_check.py --epub <path/to/book.epub>
  (reads wiki pages JSON from stdin: {"pages": [{"title", "content", "importance"}]})

Standalone test:
  python scripts/copyright_check.py --test
  python scripts/copyright_check.py --test --threshold 10
"""

import argparse
import json
import re
import sys
from typing import Dict, List

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup

MIN_CHAPTER_CHARS = 100  # Skip EPUB nav/boilerplate items shorter than this


def tokenize(text: str) -> List[str]:
    """Lowercase, strip punctuation, split on whitespace."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return text.split()


def mask_short_quotes(text: str, max_words: int = 5) -> str:
    """Replace short quoted text (≤max_words words) with neutral filler tokens."""
    def replace_if_short(m: re.Match) -> str:
        content = m.group(1)
        words = content.split()
        if len(words) <= max_words:
            return " ".join(f"QMASK{i}" for i in range(len(words)))
        return m.group(0)

    text = re.sub(r"«([^»]*)»", replace_if_short, text)
    text = re.sub(r'"([^"]*)"', replace_if_short, text)
    return text


def build_source_index(chapters: List[dict], n: int = 15) -> Dict[tuple, str]:
    """
    Build a dict mapping each n-gram tuple to the chapter id where it first appears.
    chapters: list of {"id": str, "content": str}
    """
    index: Dict[tuple, str] = {}
    for chapter in chapters:
        tokens = tokenize(chapter["content"])
        for i in range(len(tokens) - n + 1):
            gram = tuple(tokens[i : i + n])
            if gram not in index:
                index[gram] = chapter["id"]
    return index


def find_violations(
    wiki_tokens: List[str], source_index: Dict[tuple, str], n: int = 15
) -> List[dict]:
    """
    Scan wiki_tokens with a sliding window of size n.
    Returns list of violation dicts: {chapter, wiki_excerpt, consecutive_words}.
    Merges overlapping hits into a single violation.
    """
    violations = []
    i = 0
    while i <= len(wiki_tokens) - n:
        gram = tuple(wiki_tokens[i : i + n])
        if gram in source_index:
            chapter = source_index[gram]
            # Extend to find full run length
            end = i + n
            while end < len(wiki_tokens):
                next_gram = tuple(wiki_tokens[end - n + 1 : end + 1])
                if next_gram in source_index:
                    end += 1
                else:
                    break
            violations.append(
                {
                    "chapter": chapter,
                    "wiki_excerpt": " ".join(wiki_tokens[i:end]),
                    "consecutive_words": end - i,
                }
            )
            i = end
        else:
            i += 1
    return violations


def load_epub_chapters(epub_path: str) -> List[dict]:
    """Extract chapter text from EPUB file. Returns list of {id, content}."""
    book = epub.read_epub(epub_path, options={"ignore_ncx": True})
    chapters = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        text = soup.get_text(separator=" ")
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > MIN_CHAPTER_CHARS:
            chapters.append({"id": item.get_id(), "content": text})
    return chapters


def check_page(page: dict, source_index: Dict[tuple, str], n: int = 15) -> List[dict]:
    """Check a single wiki page for verbatim matches. Returns list of violation dicts."""
    masked = mask_short_quotes(page.get("content", ""), max_words=5)
    tokens = tokenize(masked)
    raw_violations = find_violations(tokens, source_index, n=n)
    return [
        {
            "page_title": page["title"],
            "chapter": v["chapter"],
            "wiki_excerpt": v["wiki_excerpt"],
            "consecutive_words": v["consecutive_words"],
        }
        for v in raw_violations
    ]


def format_output(pages_checked: int, violations: List[dict]) -> dict:
    """Format the hook output JSON."""
    if not violations:
        return {"status": "pass", "checked_pages": pages_checked, "violations": []}

    titles = sorted({v["page_title"] for v in violations})
    titles_str = ", ".join(f"[{t}]" for t in titles)
    feedback = (
        f"Violations copyright détectées dans : {titles_str}. "
        "Reformule ces passages en paraphrasant — "
        "ne reproduis pas les mots exacts du livre source."
    )
    return {
        "status": "fail",
        "checked_pages": pages_checked,
        "violations": violations,
        "feedback": feedback,
    }


def run_check(pages: List[dict], epub_path: str, threshold: int = 15) -> dict:
    """Full pipeline: load epub, build index, check all pages."""
    chapters = load_epub_chapters(epub_path)
    source_index = build_source_index(chapters, n=threshold)
    all_violations = []
    for page in pages:
        all_violations.extend(check_page(page, source_index, n=threshold))
    return format_output(pages_checked=len(pages), violations=all_violations)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--epub", help="Path to EPUB file")
    parser.add_argument("--test", action="store_true", help="Run with fixture data")
    parser.add_argument("--threshold", type=int, default=15, help="Min consecutive words for violation")
    args = parser.parse_args()

    if args.test:
        # Fixture test: inject known verbatim passage to verify detection
        fake_chapters = [
            {
                "id": "ch01",
                "content": (
                    "David Martín prit le manuscrit entre ses mains tremblantes "
                    "et le déposa sur la table en bois verni avec soin et précision."
                ),
            }
        ]
        fake_pages = [
            {
                "title": "Test — verbatim page",
                "content": (
                    "David Martín prit le manuscrit entre ses mains tremblantes "
                    "et le déposa sur la table en bois verni avec soin et précision."
                ),
                "importance": "principal",
            },
            {
                "title": "Test — clean page",
                "content": "Ce personnage est un auteur vivant à Barcelone.",
                "importance": "secondary",
            },
        ]
        source_index = build_source_index(fake_chapters, n=args.threshold)
        violations = []
        for page in fake_pages:
            violations.extend(check_page(page, source_index, n=args.threshold))
        result = format_output(pages_checked=len(fake_pages), violations=violations)
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)

        if result["status"] != "fail":
            print(f"ERROR: Expected fail, got: {result}", file=sys.stderr)
            sys.exit(1)
        if not result["violations"] or result["violations"][0]["page_title"] != "Test — verbatim page":
            print(f"ERROR: Expected violation for 'Test — verbatim page', got: {result['violations']}", file=sys.stderr)
            sys.exit(1)
        print("\n✓ --test passed", file=sys.stderr)
        return

    payload = json.load(sys.stdin)

    # Studio pipeline stage format: {"additional_context": "...", "previous_outputs": {...}}
    # Standalone format: {"pages": [...]}
    pages = payload.get("pages")
    epub_path = args.epub

    if pages is None:
        import yaml
        previous = payload.get("previous_outputs", {})
        wiki_gen = previous.get("wiki-generation", {})
        pages = wiki_gen.get("pages", [])
        if not epub_path:
            try:
                ctx = yaml.safe_load(payload.get("additional_context", "{}") or "{}")
                epub_path = ctx.get("file_path", "")
            except Exception:
                epub_path = ""

    if not epub_path:
        print("Error: epub path not found (pass --epub or run as a pipeline stage with input.file_path)", file=sys.stderr)
        sys.exit(1)

    if not pages:
        json.dump({"status": "pass", "checked_pages": 0, "violations": [], "pages": []}, sys.stdout, ensure_ascii=False)
        return

    result = run_check(pages, epub_path, threshold=args.threshold)
    result["pages"] = pages  # pass through for wiki-export
    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
