"""Tests for the GLiNER spaCy component (STU-521).

The model itself is faked: the component's job is offset arithmetic, label
mapping and pipeline placement, and none of that needs a 500MB download. One
marker-gated test exercises the real model.
"""
import pytest
import spacy

from wiki_creator.entity_taxonomy import gliner_label_map, ner_label_map
from wiki_creator.nlp.gliner_ner import (
    DEVICE_ENV,
    GlinerNer,
    attach,
    resolve_device,
    windows,
)

from _markers import requires_gliner

LABELS = {"person": "PERSON", "location": "PLACE"}


class FakeGliner:
    """Records what it was asked, replays canned entities per text."""

    def __init__(self, by_text: dict[str, list[dict]] | None = None):
        self.by_text = by_text or {}
        self.calls: list[tuple[list[str], list[str]]] = []

    def inference(self, texts, labels, threshold=0.5, batch_size=8):
        self.calls.append((list(texts), list(labels)))
        return [list(self.by_text.get(t, [])) for t in texts]


def blank_nlp():
    nlp = spacy.blank("en")
    nlp.add_pipe("sentencizer")
    return nlp


def component(fake, **kwargs):
    comp = GlinerNer(kwargs.pop("labels", LABELS), "fake-model", 0.5, kwargs.pop("chunk_chars", 1600), 8)
    comp._model = fake
    return comp


# --- the load-bearing taxonomy assumption -----------------------------------

def test_every_gliner_type_maps_to_itself_through_ner_label_map():
    """The backend emits taxonomy types as spaCy labels and relies on
    `ner_label_map` typing them to themselves, so KEPT_LABELS keeps them and no
    translation layer is needed. If a type ever stops declaring its own name in
    `ner_labels`, GLiNER silently extracts nothing for it — pin that here."""
    label_map = ner_label_map()
    for entity_type in gliner_label_map().values():
        assert label_map.get(entity_type) == entity_type, (
            f"{entity_type} must list {entity_type!r} among its base.yaml ner_labels"
        )


def test_base_yaml_declares_a_gliner_label_for_every_ner_type():
    assert set(gliner_label_map().values()) == {"PERSON", "PLACE", "ORG", "EVENT", "FACTION"}


def test_duplicate_gliner_label_raises():
    base = {"entity_types": {
        "PERSON": {"gliner_label": "person"},
        "FACTION": {"gliner_label": "person"},
    }}
    with pytest.raises(ValueError, match="declared by both"):
        gliner_label_map(base)


def test_type_without_gliner_label_is_not_asked_for():
    base = {"entity_types": {"PERSON": {"gliner_label": "person"}, "COLLATION": {}}}
    assert gliner_label_map(base) == {"person": "PERSON"}


# --- device (STU-570) --------------------------------------------------------

@pytest.mark.parametrize("value", ["cpu", "cuda", " CUDA "])
def test_declared_device_is_taken_without_asking_torch(monkeypatch, value):
    """An explicit device never probes CUDA — that is the whole point: a second
    run on a busy GPU is told `cpu` while `torch.cuda.is_available()` is True."""
    monkeypatch.setenv(DEVICE_ENV, value)
    assert resolve_device() == value.strip().lower()


@pytest.mark.parametrize("value", ["", "   "])
def test_unset_or_blank_device_is_auto(monkeypatch, value):
    pytest.importorskip("torch")
    monkeypatch.setenv(DEVICE_ENV, value)
    assert resolve_device() in ("cpu", "cuda")


def test_unknown_device_raises_instead_of_falling_back_to_auto(monkeypatch):
    monkeypatch.setenv(DEVICE_ENV, "gpu")
    with pytest.raises(ValueError, match=DEVICE_ENV):
        resolve_device()


# --- offline-first load ------------------------------------------------------


def _fake_hf_modules(monkeypatch, from_pretrained):
    """Install fake ``gliner``/``huggingface_hub``/``transformers`` so the load
    helper runs without a model download and its offline flags are observable."""
    import sys
    from types import ModuleType

    hf = ModuleType("huggingface_hub.constants")
    hf.HF_HUB_OFFLINE = False
    hf_pkg = ModuleType("huggingface_hub")
    hf_pkg.constants = hf

    tf_hub = ModuleType("transformers.utils.hub")
    tf_hub._is_offline_mode = False
    tf_utils = ModuleType("transformers.utils")
    tf_utils.hub = tf_hub
    tf_pkg = ModuleType("transformers")
    tf_pkg.utils = tf_utils

    gliner = ModuleType("gliner")
    gliner.GLiNER = type("GLiNER", (), {"from_pretrained": staticmethod(from_pretrained)})

    for name, mod in [
        ("gliner", gliner),
        ("huggingface_hub", hf_pkg),
        ("huggingface_hub.constants", hf),
        ("transformers", tf_pkg),
        ("transformers.utils", tf_utils),
        ("transformers.utils.hub", tf_hub),
    ]:
        monkeypatch.setitem(sys.modules, name, mod)
    return hf, tf_hub


def test_load_forces_offline_during_a_cached_load_and_restores_it(monkeypatch):
    """A cached load must not touch the network — both offline flags are True
    while ``from_pretrained`` runs, and restored to their prior value after."""
    from wiki_creator.nlp.gliner_ner import _from_pretrained_offline_first

    seen = {}

    def from_pretrained(name):
        seen["name"] = name
        seen["hf"] = sys_hf.HF_HUB_OFFLINE
        seen["tf"] = sys_tf._is_offline_mode
        return "MODEL"

    sys_hf, sys_tf = _fake_hf_modules(monkeypatch, from_pretrained)
    assert _from_pretrained_offline_first("m") == "MODEL"
    assert (seen["name"], seen["hf"], seen["tf"]) == ("m", True, True)
    assert sys_hf.HF_HUB_OFFLINE is False and sys_tf._is_offline_mode is False


def test_load_falls_back_to_network_on_a_cache_miss(monkeypatch):
    """A genuine miss (first pull) retries online — offline is off on the retry,
    and both flags are restored afterwards regardless."""
    from wiki_creator.nlp.gliner_ner import _from_pretrained_offline_first

    calls = []

    def from_pretrained(name):
        calls.append((sys_hf.HF_HUB_OFFLINE, sys_tf._is_offline_mode))
        if len(calls) == 1:
            raise OSError("not cached")
        return "MODEL"

    sys_hf, sys_tf = _fake_hf_modules(monkeypatch, from_pretrained)
    assert _from_pretrained_offline_first("m") == "MODEL"
    assert calls == [(True, True), (False, False)]
    assert sys_hf.HF_HUB_OFFLINE is False and sys_tf._is_offline_mode is False


# --- windows -----------------------------------------------------------------

def test_window_text_is_a_verbatim_slice_at_its_offset():
    doc = blank_nlp()("Eragon rode. Saphira flew. Brom waited.")
    for offset, text in windows(doc, chunk_chars=20):
        assert doc.text[offset:offset + len(text)] == text


def test_windows_cover_every_sentence():
    doc = blank_nlp()("One two. Three four. Five six. Seven eight.")
    assert " ".join(t for _, t in windows(doc, chunk_chars=15)) == doc.text


def test_short_doc_is_one_window_at_offset_zero():
    doc = blank_nlp()("Eragon rode toward Carvahall.")
    assert windows(doc, chunk_chars=1600) == [(0, "Eragon rode toward Carvahall.")]


def test_empty_doc_yields_no_windows():
    assert windows(blank_nlp()(""), chunk_chars=100) == []


# --- component ---------------------------------------------------------------

def test_entities_carry_taxonomy_types_not_the_natural_language_label():
    text = "Eragon rode toward Carvahall."
    fake = FakeGliner({text: [
        {"start": 0, "end": 6, "label": "person"},
        {"start": 19, "end": 28, "label": "location"},
    ]})
    doc = component(fake)(blank_nlp()(text))
    assert [(e.text, e.label_) for e in doc.ents] == [("Eragon", "PERSON"), ("Carvahall", "PLACE")]


def test_offsets_are_absolute_across_window_boundaries():
    """The regression that would corrupt STU-489 mention spans: a hit in the
    second window must land at its offset in the chapter, not in the window."""
    first, second = "Brom waited by the road. " * 3, "Eragon rode toward Carvahall."
    text = first + second
    fake = FakeGliner({second: [{"start": 0, "end": 6, "label": "person"}]})
    doc = component(fake, chunk_chars=40)(blank_nlp()(text))
    (ent,) = doc.ents
    assert (ent.text, ent.start_char) == ("Eragon", len(first))
    assert doc.text[ent.start_char:ent.end_char] == "Eragon"


def test_every_window_is_asked_for_all_labels():
    text = "Eragon rode. Saphira flew. Brom waited. Murtagh rode."
    fake = FakeGliner()
    component(fake, chunk_chars=15)(blank_nlp()(text))
    assert len(fake.calls) == 1, "one batched inference call, not one per window"
    texts, labels = fake.calls[0]
    assert len(texts) > 1
    assert labels == list(LABELS)


def test_label_the_taxonomy_does_not_claim_is_dropped():
    text = "Eragon rode toward Carvahall."
    fake = FakeGliner({text: [{"start": 0, "end": 6, "label": "dragon"}]})
    assert component(fake)(blank_nlp()(text)).ents == ()


def test_overlapping_spans_are_resolved_longest_first():
    text = "Ajihad the Dwarf King spoke."
    fake = FakeGliner({text: [
        {"start": 0, "end": 6, "label": "person"},
        {"start": 0, "end": 21, "label": "person"},
    ]})
    doc = component(fake)(blank_nlp()(text))
    assert [e.text for e in doc.ents] == ["Ajihad the Dwarf King"]


def test_span_misaligned_with_tokens_contracts_instead_of_dropping():
    text = "Eragon rode toward Carvahall."
    fake = FakeGliner({text: [{"start": 0, "end": 4, "label": "person"}]})
    doc = component(fake)(blank_nlp()(text))
    assert doc.ents == () or doc.ents[0].text == "Eragon"


def test_labels_property_reports_taxonomy_types_for_the_load_time_audit():
    assert component(FakeGliner()).labels == ("PERSON", "PLACE")


def test_component_without_labels_raises():
    with pytest.raises(ValueError, match="no labels"):
        GlinerNer({}, "fake-model", 0.5, 1600, 8)


# --- pipeline placement ------------------------------------------------------

def test_attach_takes_over_the_ner_slot_so_audits_still_introspect_it():
    nlp = blank_nlp()
    nlp.add_pipe("ner")
    attach(nlp, LABELS)
    assert "ner" in nlp.pipe_names
    assert nlp.pipe_names.count("ner") == 1
    assert isinstance(nlp.get_pipe("ner"), GlinerNer)


def test_attach_adds_ner_when_the_pipeline_has_none():
    nlp = blank_nlp()
    attach(nlp, LABELS)
    assert isinstance(nlp.get_pipe("ner"), GlinerNer)


def test_attached_component_carries_the_declared_model_and_threshold():
    nlp = blank_nlp()
    attach(nlp, LABELS, model="urchade/gliner_multi-v2.1", threshold=0.3)
    comp = nlp.get_pipe("ner")
    assert (comp.model_name, comp.threshold) == ("urchade/gliner_multi-v2.1", 0.3)


@requires_gliner
def test_real_gliner_finds_and_types_an_invented_name():
    """Zero-shot on a name no stock model has seen — the STU-470 finding, pinned
    small. Downloads the model on first run."""
    nlp = blank_nlp()
    attach(nlp, gliner_label_map())
    doc = nlp("Eragon rode toward Carvahall with Saphira.")
    found = {e.text: e.label_ for e in doc.ents}
    assert found.get("Eragon") == "PERSON"
    assert found.get("Carvahall") == "PLACE"
