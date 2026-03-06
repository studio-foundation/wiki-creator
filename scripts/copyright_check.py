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

import json
import re
import sys
from typing import Dict, List, Tuple


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
