"""Entity-name canonicalization for the series merge (STU-719).

``registry.normalize_name`` folds case and accents and stops there, which is
enough inside one book — the tome that wrote ``Saw-Horse`` wrote it that way
everywhere — and not enough across tomes, where the same character reaches the
merge as ``Saw-Horse``, ``Sawhorse``, ``BILLINA`` and ``THE shaggy man``.
``canonical_key`` is the stricter key: what two surfaces must share to be the
same entity. ``preferred_display_name`` picks which of those surfaces a reader
should see.

Unifying this with the role-title and honorific rules that ``alias_resolution``
and ``entity_classification`` each carry their own copy of is STU-724 — it
changes identity merging inside a book, so it needs the library-wide sweep this
module deliberately does not.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

from wiki_creator.registry import normalize_name

_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def _normalized_set(words: Iterable[str]) -> set[str]:
    return {key for key in (normalize_name(w) for w in words) if key}


def _strip_leading_determiner(text: str, determiners: Iterable[str]) -> str:
    """Drop one leading determiner token from an already-normalized ``text``."""
    for determiner in sorted(_normalized_set(determiners), key=len, reverse=True):
        if text.startswith(f"{determiner} "):
            return text[len(determiner) + 1 :]
    return text


def canonical_key(name: str, determiners: Iterable[str] = ()) -> str:
    """Identity key for a surface form: ``normalize_name``, then a leading-article
    strip and punctuation/whitespace folding.

    ``Saw-Horse`` == ``Sawhorse``, ``Tik-tok`` == ``Tiktok``, ``BILLINA`` ==
    ``Billina``, and — given the language's ``determiners`` — ``THE shaggy man``
    == ``Shaggy Man``. Honorifics survive the fold, so ``Mr Beaver`` and
    ``Mrs Beaver`` stay distinct (STU-541/585). Empty for a name carrying no
    alphanumeric character; callers never merge on an empty key.
    """
    return _NON_ALNUM.sub("", _strip_leading_determiner(normalize_name(name), determiners))


def preferred_display_name(names: Iterable[str], determiners: Iterable[str] = ()) -> str:
    """The most reader-facing of several spellings of one name.

    Only ever called on surfaces that already share a ``canonical_key``, so it
    chooses a spelling, never a referent: a shouty extraction artifact loses to
    its cased twin (``BILLINA`` -> ``Billina``), an article-led one to its bare
    form (``THE shaggy man`` -> ``Shaggy Man``). Ties break on input order.
    """
    candidates = [str(n) for n in names if str(n).strip()]
    if not candidates:
        return ""

    def rank(name: str) -> tuple[bool, bool, bool, int]:
        letters = [c for c in name if c.isalpha()]
        normalized = normalize_name(name)
        return (
            bool(letters) and all(c.isupper() for c in letters),
            normalized != _strip_leading_determiner(normalized, determiners),
            bool(letters) and all(c.islower() for c in letters),
            candidates.index(name),
        )

    return min(candidates, key=rank)


def is_generic_role_name(
    name: str,
    role_words: Iterable[str],
    determiners: Iterable[str] = (),
    connectors: Iterable[str] = (),
) -> bool:
    """True when ``name`` says only what someone *is*, never who: every content
    token is a role word (``King``, ``Captain``), or the whole phrase is an
    enumerated role (``Guardian of the Gates`` when a reader declared it).

    The series merge needs exactly this distinction. A generic role names a
    different referent in every tome — Ev's Queen is not Oz's — so it cannot
    become one cross-tome page. A role qualified by a proper noun (``Nome King``,
    ``Princess Langwidere``) names one character and must survive, which is why
    this is stricter than alias-resolution's head-noun rule.
    """
    role_set = _normalized_set(role_words)
    if not role_set:
        return False
    if normalize_name(name) in role_set:
        return True
    skip = _normalized_set(determiners) | _normalized_set(connectors)
    tokens = [t for t in _NON_ALNUM.sub(" ", normalize_name(name)).split() if t not in skip]
    return bool(tokens) and all(t in role_set for t in tokens)
