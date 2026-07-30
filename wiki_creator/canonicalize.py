"""Entity-name canonicalization — one normalization key for every surface that
has to decide whether two names are the same name (STU-719, STU-724).

Pure module, no I/O, beside ``registry.py`` — the registry owns identity, so it
owns the key identity is decided on.

``registry.normalize_name`` folds case and accents and stops there, which was
enough inside one book and not enough anywhere else. Casing, spacing,
punctuation and leading articles were then folded independently at every site
that needed them, and forgotten at the next: STU-636 folded ``Queen``/``The
Queen`` on a roster, STU-719 met the same pair (plus ``BILLINA``, ``Saw-Horse``,
``THE shaggy man``) at series scope; STU-541's honorific rule lived in
alias-resolution and STU-585 found clustering remarrying the Beavers one stage
upstream. The rule lives here now, and the sites read it instead of restating
it — ``entity_clustering``, ``alias_resolution``, ``series``.

Two keys, because two questions:

* :func:`canonical_key` answers *are these the same name* — it strips a leading
  article, which carries no referent (``The Queen`` is ``Queen``), and keeps an
  honorific, which discriminates one (``Mr Beaver`` is not ``Mrs Beaver``,
  STU-541/585).
* :func:`canonical_tokens` answers *are these names comparable* — it strips
  whatever vocabulary the caller declares strippable (titles, honorifics,
  articles), leaving the tokens a similarity rule works on.

Both fold case, accents and punctuation, and neither ever strips the last
token: a name that is nothing but a title is identified by that title, not
emptied (STU-636). The key keeps word boundaries, so it doubles as the form a
token-run match reads (``alias_resolution``); two surfaces that differ only by a
word split (``Tinwoodman`` / ``Tin Woodman``) therefore stay distinct, the
conservative direction on a merge (STU-538/549).

Two role predicates, because two questions again: :func:`is_bare_role` is
alias-resolution's head-noun rule (``Crown Prince`` is a title), while
:func:`is_generic_role_name` is the stricter series test — *every* content token
must be a role, so ``Nome King`` survives the cross-tome drop.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from functools import lru_cache

from wiki_creator.registry import normalize_name

# Punctuation is dropped, never replaced by a space: `Saw-Horse` and `Sawhorse`
# are one entity (STU-719), as are `Tik-tok` and `Tiktok`.
_PUNCTUATION_RE = re.compile(r"[^\w\s]", re.UNICODE)
_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def fold_tokens(text: object) -> list[str]:
    """Case-, accent- and punctuation-folded tokens of a surface form."""
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _PUNCTUATION_RE.sub("", stripped.casefold()).split()


@lru_cache(maxsize=None)
def _fold_vocabulary(words: tuple[str, ...]) -> frozenset[str]:
    return frozenset(token for word in words for token in fold_tokens(word))


def fold_vocabulary(words: Iterable[str]) -> frozenset[str]:
    """The folded tokens a declared vocabulary matches against.

    Folding both sides is what makes `M.` match the cue word `m.` and `Mère`
    match `mere` — a vocabulary written by a reader, compared to text. Cached:
    clustering folds the same book vocabulary once per candidate pair.
    """
    return _fold_vocabulary(tuple(words))


def canonical_tokens(name: object, strippable: Iterable[str] = ()) -> list[str]:
    """Folded tokens of ``name`` with its leading ``strippable`` tokens removed.

    The last token is never stripped (STU-636): ``The Queen`` reduces to
    ``["queen"]`` and matches a bare ``Queen``, while ``The King`` reduces to
    ``["king"]`` and stays distinct.
    """
    tokens = fold_tokens(name)
    vocabulary = fold_vocabulary(strippable)
    while len(tokens) > 1 and tokens[0] in vocabulary:
        tokens = tokens[1:]
    return tokens


def canonical_key(name: object, determiners: Iterable[str] = ()) -> str:
    """The identity key of a surface form — equal keys are the same name.

    ``Saw-Horse`` == ``Sawhorse``, ``Tik-tok`` == ``Tiktok``, ``BILLINA`` ==
    ``Billina``, and — given the language's ``determiners`` — ``THE shaggy man``
    == ``Shaggy Man``. An honorific is deliberately *not* strippable here: a role
    designates one person, an honorific tells two apart (STU-541/585). Empty for
    a name carrying no alphanumeric character; callers never merge on an empty
    key.
    """
    return " ".join(canonical_tokens(name, determiners))


def _normalized_set(words: Iterable[str]) -> set[str]:
    return {key for key in (normalize_name(w) for w in words) if key}


def _strip_leading_determiner(text: str, determiners: Iterable[str]) -> str:
    """Drop one leading determiner token from an already-normalized ``text``."""
    for determiner in sorted(_normalized_set(determiners), key=len, reverse=True):
        if text.startswith(f"{determiner} "):
            return text[len(determiner) + 1 :]
    return text


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


def is_bare_role(name: object, roles: Iterable[str], articles: Iterable[str] = ()) -> bool:
    """True when ``name`` is a bare title rather than a title + proper name.

    Recognises a single-word role (``Master``), an enumerated role phrase
    (``Crown Prince``), and a modifier + role head (``High Lord`` — English
    titles are head-final, so the head carries the role, STU-471). A title plus
    a surname (``Captain Westfall``) keeps a non-role head and is not bare.

    This is alias-resolution's rule, inside one book, where a title designating
    one character is exactly what merges. The series merge asks a stricter
    question — see :func:`is_generic_role_name`.
    """
    tokens = canonical_tokens(name, articles)
    if not tokens:
        return False
    role_set = {canonical_key(role) for role in roles}
    if " ".join(tokens) in role_set:
        return True
    if all(token in role_set for token in tokens):
        return True
    return len(tokens) > 1 and tokens[-1] in role_set


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
