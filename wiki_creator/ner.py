"""How a book's proper nouns are found (STU-521, STU-537). Pure; no ML imports.

Declared in the book YAML, opt-in per book:

    ner:
      invented_names: true                # false (default) — spaCy finds the entities
      model: urchade/gliner_large-v2.1
      threshold: 0.5

`invented_names` states a property of the *book*, not a backend: are its proper
nouns invented (Garrow, Durza, Ra'zac) or real-world English (Peter, Lucy)?
spaCy's NER only recognises what it has memorised, so an invented name falls to
ORG — on Eragon it typed Garrow (112 mentions, the uncle) and Durza (the
antagonist) as ORG, and 26 of the 66 entities it called PERSON were not people
(STU-537). GLiNER types by prompt, so an unseen name costs it nothing: on the
same book, typing accuracy went 50/103 to 84/103 against an LLM oracle roster.
A book with real-world names has no such problem and pays nothing for spaCy.

GLiNER replaces the entity step only — spaCy still tokenizes and tags, so
`spacy_model` keeps its meaning either way.

An unknown option raises rather than degrading to the default. STU-470 found
`wiki-ner-en` had been silently running on the one book it had memorised for
months; a misconfiguration that quietly falls back is that same bug.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

DEFAULT_MODEL = "urchade/gliner_large-v2.1"
DEFAULT_THRESHOLD = 0.5

EXTRACTION_CONFIG_FILE = "extraction_config.json"

_KEYS = {"invented_names", "model", "threshold"}


@dataclass(frozen=True)
class NerConfig:
    invented_names: bool = False
    model: str = DEFAULT_MODEL
    threshold: float = DEFAULT_THRESHOLD


def ner_config(book_config: dict | None) -> NerConfig:
    raw = (book_config or {}).get("ner")
    if raw is None:
        return NerConfig()
    if not isinstance(raw, dict):
        raise ValueError(f"book YAML `ner` must be a mapping, got {type(raw).__name__}")

    unknown = sorted(set(raw) - _KEYS)
    if unknown:
        raise ValueError(
            f"book YAML `ner` has unknown key(s): {', '.join(unknown)}; "
            f"known keys are {', '.join(sorted(_KEYS))}"
        )

    invented_names = raw.get("invented_names", False)
    if not isinstance(invented_names, bool):
        raise ValueError(
            f"book YAML `ner.invented_names` must be a boolean, got {invented_names!r}"
        )

    threshold = raw.get("threshold", DEFAULT_THRESHOLD)
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool) or not 0 < threshold <= 1:
        raise ValueError(f"book YAML `ner.threshold` must be a number in (0, 1], got {threshold!r}")

    return NerConfig(invented_names, raw.get("model", DEFAULT_MODEL), float(threshold))


def extraction_fingerprint(book_config: dict | None) -> dict:
    """The resolved config the extraction artifacts were produced under (STU-560).

    Extraction keeps no cache of its own, but the orchestrator skips a completed
    stage on file presence alone. So a `ner` flip read correctly from the book
    YAML stayed unapplied — the three books configured for GLiNER were all
    rendering entities typed by spaCy, and nothing said so. An artifact that does
    not declare the config that produced it cannot be invalidated by a config
    change.
    """
    return {"ner": asdict(ner_config(book_config))}
