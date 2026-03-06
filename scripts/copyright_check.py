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
