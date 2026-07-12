"""Deterministic grounding checks for generated wiki pages.

Core idea: the generation prompt contains everything the writer was allowed
to know (source excerpts, related entities, chapter summaries). Any proper
noun in the generated page that never appears in that prompt is invented —
a hallucination signal that needs no LLM to detect.

This is the allowlist generalization of the forbidden_names blocklist: it
would have caught the cross-book identity confusions observed in real runs
(Yrene Astellaris, Erawan, "royaume de Ruhn", wrong series titles in the
References section).

Vocabulary (name connectors, elision prefixes) lives in
cue_words/<lang>.json — never hardcoded here.
"""
from __future__ import annotations

import re

from wiki_creator.lang import load_lang_config
from wiki_creator.registry import normalize_name as normalize

# A capitalized word: uppercase letter (incl. accented) + word chars,
# allowing internal apostrophes/hyphens (D'Artagnan, Jean-Luc).
_CAP_WORD_RE = re.compile(r"[A-ZÀ-ÖØ-Þ][\w'’-]*")

# Characters that end a sentence (or open a dialogue line) — a capitalized
# word right after one of these is ordinary sentence case, not evidence of
# a proper noun.
_SENTENCE_BREAK = set(".!?«»\"”—–:;\n")

_MARKDOWN_NOISE_RE = re.compile(r"[*_`#>\[\]()|]")


def _strip_elision(token: str, elision_prefixes: list[str]) -> str:
    """Drop a leading elision (l'Assassine → Assassine)."""
    low = token.casefold().replace("’", "'")
    for prefix in elision_prefixes:
        if low.startswith(prefix) and len(token) > len(prefix):
            return token[len(prefix):]
    return token


def _is_sentence_start(text: str, pos: int) -> bool:
    """True when the character before pos closes a sentence or line."""
    i = pos - 1
    while i >= 0 and text[i] in " \t'’\"“«—–-":
        if text[i] in _SENTENCE_BREAK:
            return True
        i -= 1
    if i < 0:
        return True
    return text[i] in _SENTENCE_BREAK


def extract_name_candidates(content: str, language: str = "fr") -> list[str]:
    """Extract proper-noun candidates from page prose.

    Conservative rules to avoid false positives on sentence case:
    - multi-word capitalized sequences count anywhere (connector words like
      'de'/'du' may join them: "La Colonne de feu", "Nox Owen");
    - a single capitalized word counts only when NOT at a sentence/line
      start (mid-sentence capitalization is a proper noun in prose).
    """
    cfg = load_lang_config(language)
    connectors = {c.casefold() for c in cfg.get("name_connectors", [])}
    elisions = [p.casefold().replace("’", "'") for p in cfg.get("elision_prefixes", [])]

    text = _MARKDOWN_NOISE_RE.sub(" ", content)

    candidates: list[str] = []
    matches = list(_CAP_WORD_RE.finditer(text))
    i = 0
    while i < len(matches):
        start_match = matches[i]
        # Group consecutive capitalized words, allowing connector words
        # (or nothing but spaces) between them.
        j = i
        while j + 1 < len(matches):
            between = text[matches[j].end():matches[j + 1].start()]
            between_words = [w.casefold() for w in between.split()]
            if all(w in connectors for w in between_words) and "\n" not in between:
                j += 1
            else:
                break
        phrase = text[start_match.start():matches[j].end()].strip()
        phrase = _strip_elision(phrase, elisions)
        if j > i:
            candidates.append(phrase)
        elif not _is_sentence_start(text, start_match.start()):
            candidates.append(phrase)
        i = j + 1
    return candidates


def find_ungrounded_names(
    content: str,
    infobox_fields: dict | None,
    source: str,
    language: str = "fr",
    max_names: int = 5,
) -> list[str]:
    """Return proper nouns from the page that never appear in the source.

    A candidate is flagged when at least one of its capitalized tokens is
    absent from the normalized source text — so "Celaena Sardothien" passes
    as long as both tokens are grounded, while "Yrene Astellaris" is
    flagged the moment "Yrene" appears nowhere in the excerpts.
    """
    haystack = normalize(source)
    if not haystack.strip():
        return []

    candidates = list(extract_name_candidates(content or "", language))
    for value in (infobox_fields or {}).values():
        candidates.extend(extract_name_candidates(f". {value}", language))

    flagged: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = normalize(candidate)
        if key in seen:
            continue
        seen.add(key)
        cap_tokens = _CAP_WORD_RE.findall(candidate)
        if any(normalize(tok) not in haystack for tok in cap_tokens):
            flagged.append(candidate)
            if len(flagged) >= max_names:
                break
    return flagged
