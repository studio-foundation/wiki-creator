"""Registry-owned canonicalization (STU-724): one normalization key for every
surface that has to decide whether two names are the same name.

Pure module, no I/O, beside ``registry.py`` — the registry owns identity, so it
owns the key identity is decided on.

Before this, casing, spacing, punctuation and leading articles were folded
independently at every site that needed them — and forgotten at the next one:
STU-636 folded ``Queen``/``The Queen`` on a roster, STU-719 met the same pair
again at series scope; STU-541's honorific rule lived in alias-resolution and
STU-585 found clustering remarrying the Beavers one stage upstream. The rule
now lives here, and the three sites (``entity_clustering``, ``alias_resolution``,
``series``) read it instead of restating it.

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
emptied (STU-636).
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from functools import lru_cache

# Punctuation is dropped, never replaced by a space: `Saw-Horse` and `Sawhorse`
# are one entity (STU-719), as are `Tik-tok` and `Tiktok`.
_PUNCTUATION_RE = re.compile(r"[^\w\s]", re.UNICODE)


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


def canonical_key(name: object, articles: Iterable[str] = ()) -> str:
    """The identity key of a surface form — equal keys are the same name.

    ``articles`` is the language's determiners (``cue_words/<lang>.json``);
    without them the key still folds case, accents, punctuation and spacing.
    An honorific is deliberately *not* strippable here: a role designates one
    person, an honorific tells two apart (STU-541).
    """
    return " ".join(canonical_tokens(name, articles))


def is_bare_role(name: object, roles: Iterable[str], articles: Iterable[str] = ()) -> bool:
    """True when ``name`` is a bare title rather than a title + proper name.

    Recognises a single-word role (``Master``), an enumerated role phrase
    (``Crown Prince``), and a modifier + role head (``High Lord`` — English
    titles are head-final, so the head carries the role, STU-471). A title plus
    a surname (``Captain Westfall``) keeps a non-role head and is not bare.
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
