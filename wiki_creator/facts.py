"""Deterministic per-entity fact extraction for wiki infobox extracted-fact
slots. Vocabulary comes from cue_words (passed in), never hardcoded here.
Home for the growing fact-extractor family (titles now; status/affiliation
in later slices)."""
from __future__ import annotations

import re
from typing import Iterable

_WORD_RE = re.compile(r"\b\w+\b")


def extract_titles(name_variants: Iterable[str], role_words: list[str]) -> list[str]:
    """Role-word titles found in an entity's name variants (aliases, mentions,
    canonical name). Whole-word, case-insensitive match against `role_words`;
    returns unique, title-cased titles in first-seen order. Empty when
    `role_words` is empty."""
    role_set = {w.lower() for w in (role_words or []) if w}
    if not role_set:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for variant in name_variants or []:
        for word in _WORD_RE.findall(str(variant).lower()):
            if word in role_set and word not in seen:
                seen.add(word)
                found.append(word.capitalize())
    return found
