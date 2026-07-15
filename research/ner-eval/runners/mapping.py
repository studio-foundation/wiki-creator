"""Native model output -> taxonomy spans. Pure; no heavy ML import, so the
mappers are unit-testable with fakes.

The label table is not restated here: `entity_taxonomy.ner_label_map()` reads
`wiki_creator/templates/base.yaml`, the STU-505 single authority. A stock label
the taxonomy does not claim (spaCy's DATE, CARDINAL, ...) is dropped, which is
what the extraction stage does with it too.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))  # research/ner-eval/runners
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
sys.path.insert(0, _ROOT)

from wiki_creator.entity_taxonomy import ner_label_map  # noqa: E402


def map_spacy(ents) -> list[dict]:
    """spaCy Doc.ents -> taxonomy spans. Covers both stock and wiki-ner-en:
    the custom model emits taxonomy labels already, which map to themselves."""
    table = ner_label_map()
    out = []
    for e in ents:
        entity_type = table.get(e.label_)
        if entity_type:
            out.append({"start": e.start_char, "end": e.end_char, "label": entity_type})
    return out


def map_gliner(entities: list[dict], label_to_type: dict[str, str]) -> list[dict]:
    """GLiNER entities -> taxonomy spans, via the natural-language label that was
    asked for. GLiNER echoes the requested label back in `label`."""
    out = []
    for e in entities:
        entity_type = label_to_type.get(e["label"])
        if entity_type:
            out.append({"start": e["start"], "end": e["end"], "label": entity_type})
    return out
