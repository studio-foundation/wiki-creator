"""What a per-character verdict stage does regardless of what it asks.

`entity_status` (STU-488), `entity_affiliation` (STU-551) and `entity_species`
(STU-574) each decide one fact about a PERSON from the book's text and verify
the reply against that text before trusting it (STU-539: these novels are in
the model's training data, so an ungrounded verdict is the model's memory of
the plot, not this book). What differs is the question; that stays in each
stage, this is the rest.

Since STU-753, the evidence is not a pre-selected snippet pack — the agent
searches the book itself (`wiki_creator.book_search`) — so "grounded" means
"verbatim somewhere in the book's full text", not "verbatim in the snippets we
happened to show".

`normalize`'s typographic folding is load-bearing (99a6a71): an EPUB's dialogue
ships curly quotes and the model echoes straight ones, so without folding both
sides every verdict whose evidence sat inside dialogue was silently dropped —
in a novel, where such facts are announced in dialogue.
"""

from __future__ import annotations

import re

from wiki_creator.tokens import contains_token_run

_WHITESPACE_RE = re.compile(r"\s+")

# An EPUB's typesetting uses curly quotes/dashes; the model echoes the same
# sentence back in plain ASCII. Folding both to one form is what lets a
# verbatim quote inside dialogue still match its source.
_TYPOGRAPHIC_TRANSLATION = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "‟": '"',
        "′": "'",
        "″": '"',
        "…": "...",
        "–": "-",
        "—": "-",
        "‑": "-",
    }
)


def fold_typography(text: object) -> str:
    """Typographic folding alone — casefolded, whitespace untouched.

    Length-preserving (a 1:1 char translation), unlike `normalize`'s whitespace
    collapse: a caller that needs an offset into the *original* string
    (`book_search.search_chapters`, quoting a passage back around a match)
    cannot use `normalize` for that — its collapsed whitespace shifts every
    offset past the first run.
    """
    return str(text or "").translate(_TYPOGRAPHIC_TRANSLATION).casefold()


def normalize(text: object) -> str:
    folded = str(text or "").translate(_TYPOGRAPHIC_TRANSLATION)
    return _WHITESPACE_RE.sub(" ", folded).strip().casefold()


def is_quoted(quote: str, snippets: list[dict]) -> bool:
    """True iff ``quote`` is verbatim in one of ``snippets``.

    ``snippets`` is ``[{"text": str}, ...]`` — a pre-selected pack, or (since
    STU-753) a single-entry list wrapping the whole book's text, when the
    caller has no narrower surface to check against.
    """
    needle = normalize(quote)
    if not needle:
        return False
    return any(needle in normalize(snippet.get("text")) for snippet in snippets)


def quote_names_entity(quote: str, name: str, aliases: list[str]) -> bool:
    """True iff ``quote`` mentions ``name`` or one of ``aliases``, by name.

    Free retrieval (STU-753) grounds a quote against the *whole book*, not a
    pre-selected per-entity snippet pack — so `is_quoted` alone no longer rules
    out a real sentence that is simply about someone else. This is the
    replacement for that: "Brom's chest rose one last time" is real book text,
    but it does not belong to Eragon's verdict, because it does not name him.
    A sentence naming two characters ("Eragon watched Brom die") still passes
    for both — the prompt's own grounding rules are what a stage's classifier
    relies on for that ambiguity, same as before STU-753.
    """
    haystack = normalize(quote)
    return any(
        contains_token_run(haystack, normalize(surface), boundary="word")
        for surface in (name, *aliases)
        if str(surface or "").strip()
    )


# Tokenizes on word characters, so a value's punctuation never welds itself to
# the sentence: "…joined the Varden." must still name `Varden`.
_WORD_RE = re.compile(r"\w+")


def quote_names_value(quote: str, value: str) -> bool:
    """True iff ``value``'s tokens appear contiguously in ``quote``.

    The companion of `is_quoted`: that verifies the quote is real, this verifies
    the quote actually names the value a name-returning stage claims from it. A
    stage whose verdict is an enum member (`status`) does not need it; one whose
    verdict is a name — the faction the model infers, the species it reads off —
    can quote a real sentence and pin the wrong value to it (STU-551).

    Whole tokens, never a substring (STU-541, same reason): `beaver` inside
    `Beavers`, or `Order` off *"he ordered the villagers"*, is an accident of
    spelling, not a mention.
    """
    group = _WORD_RE.findall(normalize(value))
    if not group:
        return False
    words = _WORD_RE.findall(normalize(quote))
    return any(
        words[i:i + len(group)] == group for i in range(len(words) - len(group) + 1)
    )
