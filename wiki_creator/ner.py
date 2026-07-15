"""Which NER backend a book runs on (STU-521). Pure; no ML imports.

Declared in the book YAML, opt-in per book:

    ner:
      backend: gliner                     # spacy (default) | gliner
      model: urchade/gliner_large-v2.1
      threshold: 0.5

`spacy` keeps the pre-STU-521 behaviour exactly: entities come from the
`spacy_model`'s own NER component. `gliner` replaces the entity step only —
spaCy still tokenizes and tags, so `spacy_model` keeps its meaning either way.

An unknown backend or option raises rather than degrading to the default. STU-470
found `wiki-ner-en` had been silently running on the one book it had memorised
for months; a backend misconfiguration that quietly falls back is that same bug.
"""
from __future__ import annotations

from dataclasses import dataclass

SPACY = "spacy"
GLINER = "gliner"
BACKENDS = (SPACY, GLINER)

DEFAULT_MODEL = "urchade/gliner_large-v2.1"
DEFAULT_THRESHOLD = 0.5

_KEYS = {"backend", "model", "threshold"}


@dataclass(frozen=True)
class NerConfig:
    backend: str = SPACY
    model: str = DEFAULT_MODEL
    threshold: float = DEFAULT_THRESHOLD

    @property
    def uses_gliner(self) -> bool:
        return self.backend == GLINER


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

    backend = raw.get("backend", SPACY)
    if backend not in BACKENDS:
        raise ValueError(
            f"book YAML `ner.backend` must be one of {', '.join(BACKENDS)}, got {backend!r}"
        )

    threshold = raw.get("threshold", DEFAULT_THRESHOLD)
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool) or not 0 < threshold <= 1:
        raise ValueError(f"book YAML `ner.threshold` must be a number in (0, 1], got {threshold!r}")

    return NerConfig(backend, raw.get("model", DEFAULT_MODEL), float(threshold))
