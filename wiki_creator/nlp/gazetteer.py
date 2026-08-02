"""Per-book character gazetteer as a spaCy pipeline component (STU-630).

GLiNER's `gliner_label: person name` asks for *names*, so it under-detects a
common noun pressed into service as a character name — `the Hatter`, `the
Dormouse`, `the Cheshire Cat`, `the Cook` on *Alice in Wonderland*. Those are
book-specific vocabulary the language-wide labels cannot cover (STU-535's Witch
case, one novel over).

The book YAML lists them (`ner.character_names`), and this component matches them
verbatim and types them PERSON, so a reader who knows the novel closes the
recall gap without polluting a language-wide list — the STU-559 shape, applied
to extraction instead of alias-resolution.

It runs *after* the `ner` slot: GLiNER replaces `doc.ents` wholesale, so an
earlier ruler would be discarded. On overlap the gazetteer wins — the reader
declared the name explicitly, so it outranks the model's guess.

Matching is case-sensitive (`ORTH`) by default: these names are capitalised as
names in the text (`the Hatter`), and a lowercase `cook` mid-sentence is the
common noun the character is named after, not the character.

`case_sensitive=False` (`LOWER`) is the STU-778 variant, for a role word
(`classification.roles_naming_one_character`) rather than a declared name: the
book states the word lowercase (`father`), but the text may capitalise it as a
name-substitute (`"your Father had an accident"`) or not. Matching
case-insensitively catches both spellings as *candidate* spans; the extractor's
own `_is_valid_mention` still requires an uppercase first letter, so only the
capitalised, name-like occurrences actually become entities — an ordinary
lowercase "his father" stays the common noun, never a mention.
"""
from __future__ import annotations

from spacy.language import Language
from spacy.matcher import PhraseMatcher
from spacy.util import filter_spans

PERSON_LABEL = "PERSON"


class BookGazetteer:
    """spaCy component adding declared character names to ``doc.ents`` as PERSON."""

    def __init__(self, nlp, names: list[str], label: str, case_sensitive: bool = True):
        self.label = label
        self._matcher = PhraseMatcher(nlp.vocab, attr="ORTH" if case_sensitive else "LOWER")
        patterns = [nlp.make_doc(name) for name in names if name.strip()]
        if patterns:
            self._matcher.add(label, patterns)

    def __call__(self, doc):
        matches = self._matcher(doc)
        if not matches:
            return doc
        gazetteer_spans = [doc[start:end] for _, start, end in matches]
        for span in gazetteer_spans:
            span.label_ = self.label
        # Gazetteer spans first so filter_spans prefers them over an overlapping
        # GLiNER guess of equal length (ties break on list order).
        doc.ents = filter_spans(gazetteer_spans + list(doc.ents))
        return doc


@Language.factory(
    "book_gazetteer",
    default_config={"names": [], "label": PERSON_LABEL, "case_sensitive": True},
)
def make_book_gazetteer(nlp, name: str, names: list[str], label: str, case_sensitive: bool):
    return BookGazetteer(nlp, names, label, case_sensitive)


def attach(
    nlp,
    names: list[str],
    label: str = PERSON_LABEL,
    *,
    case_sensitive: bool = True,
    pipe_name: str = "book_gazetteer",
) -> None:
    """Append the gazetteer after the `ner` slot. No-op when `names` is empty.

    `pipe_name` lets a second gazetteer (e.g. the STU-778 role-seed one) coexist
    with the declared-name gazetteer in the same pipeline — spaCy requires
    distinct pipe names.
    """
    if not names:
        return
    nlp.add_pipe(
        "book_gazetteer",
        name=pipe_name,
        last=True,
        config={"names": names, "label": label, "case_sensitive": case_sensitive},
    )
