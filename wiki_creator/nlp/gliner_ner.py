"""GLiNER zero-shot NER as a spaCy pipeline component (STU-521).

Replaces the *entity* step only. spaCy still tokenizes, tags and splits
sentences: `_is_valid_span` needs POS annotation and the extractor needs
`doc.sents`, so `spacy_model` keeps its meaning (STU-521 scope).

Two decisions worth knowing:

**It registers under the pipe name `ner`.** The component exposes `.labels`, so
`log_pipeline`, `_audit_ner_labels` and `_warn_if_no_pos_tagger` introspect it
exactly as they do a stock spaCy NER, and none of them needed a GLiNER branch.

**It emits taxonomy types as spaCy labels**, not the natural-language labels it
asked GLiNER for. `base.yaml#entity_types` declares each type's own name among
its `ner_labels` (PERSON, PLACE, ORG, EVENT, FACTION), so `ner_label_map()` maps
them to themselves and every downstream filter is unchanged — the same trick the
custom wiki-ner-en model relied on.

GLiNER's context window is a few hundred tokens, but the extractor feeds it whole
chapters, so text is cut into sentence-aligned windows here. Windows are slices of
`doc.text` by character offset rather than re-joined sentences: STU-489 persists
mention offsets into the chapter text saved to `chapters.json`, so a window that
does not map back exactly would corrupt them.

Where it runs is read from `WIKI_NER_DEVICE` (STU-570) — a property of the
machine and the moment, so it is neither a book YAML key nor a constant.
"""
from __future__ import annotations

import os
import sys

from spacy.language import Language
from spacy.util import filter_spans

DEVICE_ENV = "WIKI_NER_DEVICE"
DEVICES = ("auto", "cpu", "cuda")

DEFAULT_MODEL = "urchade/gliner_large-v2.1"
DEFAULT_THRESHOLD = 0.5
# ~400 tokens, comfortably inside the model's window. Mirrors the chunk size the
# STU-470 bake-off measured, so the shipped backend is not scored at a size the
# eval never saw.
DEFAULT_CHUNK_CHARS = 1600
DEFAULT_BATCH_SIZE = 8


def resolve_device() -> str:
    """Where GLiNER runs, from ``WIKI_NER_DEVICE``: ``auto`` (default) | cpu | cuda.

    `auto` is the pre-STU-570 behavior — take the GPU when there is one. It is
    the wrong answer for a second concurrent run: one 6 GB GPU cannot hold two
    models, and the run that loses the race burns its RALPH attempts on
    ``torch.OutOfMemoryError``. `cpu` places it instead of hiding the GPU.

    An unknown value raises: a device silently ignored is the misconfiguration
    the `ner` block already refuses to degrade on.
    """
    raw = os.environ.get(DEVICE_ENV, "").strip().lower() or "auto"
    if raw not in DEVICES:
        raise ValueError(f"{DEVICE_ENV} must be one of {', '.join(DEVICES)}, got {raw!r}")
    if raw != "auto":
        return raw
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def windows(doc, chunk_chars: int = DEFAULT_CHUNK_CHARS) -> list[tuple[int, str]]:
    """``(start_char, text)`` windows over *doc*, cut on sentence boundaries.

    Each text is a verbatim slice of ``doc.text``, so a GLiNER offset plus the
    window's ``start_char`` is an exact offset into the chapter.
    """
    out: list[tuple[int, str]] = []
    start = end = None
    for sent in doc.sents:
        if start is None:
            start, end = sent.start_char, sent.end_char
        elif sent.end_char - start > chunk_chars:
            out.append((start, doc.text[start:end]))
            start, end = sent.start_char, sent.end_char
        else:
            end = sent.end_char
    if start is not None:
        out.append((start, doc.text[start:end]))
    return out


def _from_pretrained_offline_first(model_name: str):
    """Load GLiNER from the local HF cache first, hitting the network only on a miss.

    The model is a pinned, pre-cached asset (`gliner` extra pulls it once), so a
    cached load must not make a blocking, un-timeout'd HF round-trip on every run:
    when the hub is slow it hangs the extraction stage to its 600s timeout. Both
    ``huggingface_hub`` and ``transformers`` read their offline flag into a module
    global at import, so the env var (set here, after import) and the
    ``local_files_only`` kwarg (ignored by the nested deberta tokenizer load) are
    both too late — the two live globals are toggled instead, which every call
    reads. A genuine cache miss (first pull) restores them and falls back to the
    network.
    """
    from gliner import GLiNER
    import huggingface_hub.constants as hf
    import transformers.utils.hub as tf

    hf_prev, tf_prev = hf.HF_HUB_OFFLINE, tf._is_offline_mode
    hf.HF_HUB_OFFLINE = tf._is_offline_mode = True
    try:
        return GLiNER.from_pretrained(model_name)
    except Exception:
        hf.HF_HUB_OFFLINE = tf._is_offline_mode = False
        return GLiNER.from_pretrained(model_name)
    finally:
        hf.HF_HUB_OFFLINE, tf._is_offline_mode = hf_prev, tf_prev


class GlinerNer:
    """spaCy component setting ``doc.ents`` from GLiNER predictions."""

    def __init__(self, labels: dict[str, str], model: str, threshold: float,
                 chunk_chars: int, batch_size: int):
        if not labels:
            raise ValueError(
                "GLiNER backend has no labels; declare `gliner_label` on the types "
                "in base.yaml#entity_types"
            )
        self.label_to_type = dict(labels)
        self.threshold = threshold
        self.chunk_chars = chunk_chars
        self.batch_size = batch_size
        self.model_name = model
        self._model = None

    @property
    def labels(self) -> tuple[str, ...]:
        """Taxonomy types this component can emit — read by the load-time audit."""
        return tuple(sorted(set(self.label_to_type.values())))

    def _load(self):
        if self._model is None:
            device = resolve_device()
            self._model = _from_pretrained_offline_first(self.model_name).to(device)
            print(f"[nlp] gliner '{self.model_name}' on {device} "
                  f"labels={self.label_to_type}", file=sys.stderr)
        return self._model

    def __call__(self, doc):
        chunks = windows(doc, self.chunk_chars)
        if not chunks:
            return doc
        predictions = self._load().inference(
            [text for _, text in chunks],
            list(self.label_to_type),
            threshold=self.threshold,
            batch_size=self.batch_size,
        )
        spans = []
        for (offset, _), entities in zip(chunks, predictions):
            for ent in entities:
                entity_type = self.label_to_type.get(ent["label"])
                if not entity_type:
                    continue
                # contract: GLiNER cuts on its own tokenizer, so a span can land
                # mid-token for spaCy. Contracting to whole tokens keeps
                # `_is_valid_span`'s POS lookups meaningful; a span with no whole
                # token inside it yields None and is dropped.
                span = doc.char_span(
                    offset + ent["start"], offset + ent["end"],
                    label=entity_type, alignment_mode="contract",
                )
                if span is not None:
                    spans.append(span)
        # doc.ents forbids overlap; windows never overlap, but two labels can
        # claim the same span within one window. Longest wins.
        doc.ents = filter_spans(spans)
        return doc


@Language.factory(
    "gliner_ner",
    default_config={
        "labels": {},
        "model": DEFAULT_MODEL,
        "threshold": DEFAULT_THRESHOLD,
        "chunk_chars": DEFAULT_CHUNK_CHARS,
        "batch_size": DEFAULT_BATCH_SIZE,
    },
)
def make_gliner_ner(nlp, name: str, labels: dict[str, str], model: str,
                    threshold: float, chunk_chars: int, batch_size: int):
    return GlinerNer(labels, model, threshold, chunk_chars, batch_size)


def attach(nlp, labels: dict[str, str], model: str = DEFAULT_MODEL,
           threshold: float = DEFAULT_THRESHOLD,
           chunk_chars: int = DEFAULT_CHUNK_CHARS,
           batch_size: int = DEFAULT_BATCH_SIZE) -> None:
    """Put GLiNER in the pipeline's `ner` slot, replacing any stock NER."""
    config = {"labels": labels, "model": model, "threshold": threshold,
              "chunk_chars": chunk_chars, "batch_size": batch_size}
    if "ner" in nlp.pipe_names:
        nlp.replace_pipe("ner", "gliner_ner", config=config)
    else:
        nlp.add_pipe("gliner_ner", name="ner", config=config)
