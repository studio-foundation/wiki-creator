"""Per-language template packs (STU-732): the i18n checks the inline
``{fr:, en:}`` maps in base.yaml made structurally impossible.

The packs are the mirror of ``cue_words/`` for output strings (see
``tests/test_lang.py``): one file per language, every shipped pack loaded here,
and a gap against the English reference pack fails the suite instead of shipping
a page with an untranslated — or, before the split, a French — string on it.
"""
import pytest
import yaml

from wiki_creator import entity_taxonomy as et
from wiki_creator import page_templates as pt

REFERENCE = pt.FALLBACK_LANG

# The few-shot example's infobox keys ARE localized content — the example shows
# the writer the infobox keys to emit, which differ per language (`nom` vs
# `name`). Parity stops here: the block is one opaque blob per pack.
OPAQUE = {("few_shot", "infobox_fields")}


def _paths(value, prefix=()):
    """Every leaf path in a pack, so parity compares keys and not just blocks."""
    if isinstance(value, dict) and prefix not in OPAQUE:
        for key, sub in value.items():
            yield from _paths(sub, (*prefix, key))
    else:
        yield prefix


def _keys(lang):
    return set(_paths(pt.load_lang_template(lang)))


def test_shipped_packs_are_discovered_reference_first():
    assert pt.shipped_languages()[0] == REFERENCE
    assert set(pt.shipped_languages()) == {"en", "fr"}


def test_every_shipped_pack_declares_every_reference_key():
    """The parity check. A key in en.yaml missing from another pack renders in
    English on that language's wiki — visible to the reader, invisible to us."""
    reference = _keys(REFERENCE)
    for lang in pt.shipped_languages():
        missing = reference - _keys(lang)
        assert not missing, (
            f"lang/{lang}.yaml is missing {sorted('.'.join(p) for p in missing)}"
        )


def test_no_pack_declares_a_key_the_reference_lacks():
    """The converse: a key only one pack declares resolves for that language and
    raises for every other, so the reference pack must be the superset."""
    reference = _keys(REFERENCE)
    for lang in pt.shipped_languages():
        extra = _keys(lang) - reference
        assert not extra, (
            f"lang/{lang}.yaml declares {sorted('.'.join(p) for p in extra)}, "
            f"absent from the {REFERENCE} reference pack"
        )


def test_no_pack_value_is_empty():
    for lang in pt.shipped_languages():
        for path in _paths(pt.load_lang_template(lang)):
            value = pt.localized(lang, *path)
            assert str(value).strip(), f"lang/{lang}.yaml: {'.'.join(path)} is empty"


# --- base.yaml structure ↔ pack coverage ------------------------------------
# base.yaml keeps structure only, and its structure references string keys. The
# packs are what turns those keys into text, so a token declared there and
# nowhere in en.yaml renders titlecased (or raises) at generation time.


def test_every_slot_token_has_a_label():
    base = pt.load_base_template()
    labels = pt.load_lang_template(REFERENCE)["labels"]
    tokens = {slot["token"] for _etype, slot in pt._iter_slots(base)}
    assert tokens <= labels.keys(), sorted(tokens - labels.keys())


def test_every_generated_infobox_row_carries_a_label():
    """The generated template (STU-729) labels every row but the header from the
    pack, so an unlabelled token would ship a titlecased English token as the row
    label of a French wiki."""
    base = pt.load_base_template()
    labels = pt.load_lang_template(REFERENCE)["labels"]
    for etype in et.declared_types(base):
        _header, *rows = pt.infobox_tokens(etype, base) or [None]
        for token in rows:
            assert token in labels, f"{etype} infobox row {token} has no label"


def test_every_relationship_and_sub_role_token_has_a_label():
    reference = pt.load_lang_template(REFERENCE)
    assert set(pt.relationship_tokens()) <= reference["relationship_labels"].keys()
    assert set(pt.sub_role_tokens()) <= reference["sub_role_labels"].keys()


def test_every_type_with_a_category_key_has_a_category_default():
    base = pt.load_base_template()
    for etype in et.declared_types(base):
        if et.category_key(etype, base):
            assert et.category_default(etype, REFERENCE), etype


def test_base_template_holds_no_localized_map():
    """The split's own guard: a reinstated ``{fr:, en:}`` map in base.yaml is read
    by nothing now, so it would drift out of the packs in silence."""
    langs = set(pt.shipped_languages())

    def walk(node, path=()):
        if isinstance(node, dict):
            assert not (node.keys() & langs), f"base.yaml#{'.'.join(path)} is a localized map"
            for key, sub in node.items():
                walk(sub, (*path, str(key)))
        elif isinstance(node, list):
            for i, sub in enumerate(node):
                walk(sub, (*path, str(i)))

    walk(pt.load_base_template())


# --- the fallback chain -----------------------------------------------------


def test_requested_language_wins():
    assert pt.chrome_label("collapse", "fr") == "Masquer"
    assert pt.chrome_label("collapse", "en") == "Hide"


def test_a_language_with_no_pack_resolves_through_english():
    assert pt.load_lang_template("de") == {}
    assert pt.chrome_label("collapse", "de") == "Hide"
    assert pt.stub_message("failed", "de") == pt.stub_message("failed", "en")
    assert pt.section_brief("PERSON", "biography", "de") == \
        pt.section_brief("PERSON", "biography", "en")


def test_a_key_missing_from_the_reference_pack_raises():
    with pytest.raises(pt.TemplatePackError) as exc:
        pt.chrome_label("no_such_chrome_key", "fr")
    msg = str(exc.value)
    assert "no_such_chrome_key" in msg
    assert "en.yaml" in msg  # actionable pointer, like LangPackError's


def test_an_unlabelled_token_still_renders():
    # slot_label is the one helper that must not raise: a book may declare its
    # own slot via generation.template.<TYPE>.add, and no pack knows its token.
    assert pt.slot_label("made_up_token", "fr") == "Made Up Token"


def test_language_name_does_not_fall_back_to_english():
    # It names the pack, so answering "English" for a German book would order
    # English prose from the writer.
    assert pt.language_name("de") == "de"


def test_packs_are_valid_yaml_mappings():
    for lang in pt.shipped_languages():
        with open(pt.LANG_PACK_DIR / f"{lang}.yaml", encoding="utf-8") as f:
            assert isinstance(yaml.safe_load(f), dict)
