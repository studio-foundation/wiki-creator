# tests/conftest.py already adds the project root to sys.path, so scripts/ is
# importable directly (same convention as tests/test_generate_wiki_pages.py).
import scripts.generate_wiki_pages as gwp


def test_batch_bound_value_nom():
    entity = {"canonical_name": "Celaena Sardothien", "aliases": ["Celaena"]}
    assert gwp._batch_bound_value(entity, "nom") == "Celaena Sardothien"


def test_batch_bound_value_alias_joins():
    entity = {"canonical_name": "Chaol Westfall", "aliases": ["Chaol", "Captain Westfall"]}
    assert gwp._batch_bound_value(entity, "alias") == "Chaol, Captain Westfall"


def test_batch_bound_value_alias_empty_is_none():
    assert gwp._batch_bound_value({"canonical_name": "X", "aliases": []}, "alias") is None
    assert gwp._batch_bound_value({"canonical_name": "X"}, "alias") is None


def test_batch_bound_value_type_and_unknown_are_none():
    entity = {"canonical_name": "X", "type": "PLACE", "aliases": []}
    assert gwp._batch_bound_value(entity, "type") is None
    assert gwp._batch_bound_value(entity, "affiliation") is None


def _person_entity():
    return {"canonical_name": "Verin", "type": "PERSON", "importance": "secondary",
            "aliases": ["Ver"]}


def test_bind_overwrites_swapped_nom():
    page = {"infobox_fields": {"nom": "Kaltain", "affiliation": "Adarlan"}}
    gwp._bind_batch_fields(page, _person_entity(), {})
    assert page["infobox_fields"]["nom"] == "Verin"          # overwritten from batch
    assert page["infobox_fields"]["affiliation"] == "Adarlan"  # non-batch-bound untouched


def test_bind_sets_alias_and_skips_type():
    page = {"infobox_fields": {}}
    gwp._bind_batch_fields(page, _person_entity(), {})
    assert page["infobox_fields"]["nom"] == "Verin"
    assert page["infobox_fields"]["alias"] == "Ver"
    assert "type" not in page["infobox_fields"]              # type never bound


def test_bind_creates_infobox_and_is_noop_without_config():
    page = {}
    gwp._bind_batch_fields(page, _person_entity(), None)     # None config → no-op
    assert page.get("infobox_fields", {}) == {}
    gwp._bind_batch_fields(page, _person_entity(), {})       # dict config → binds
    assert page["infobox_fields"]["nom"] == "Verin"


def test_generation_profile_uses_template_order():
    # legacy-style book config; sections must come back in the config's order
    config = {"principal": {"sections_by_type": {"PERSON": [
        "infobox", "biography", "personality", "relationships", "references"]}}}
    sections, _ = gwp.generation_profile(config, "principal", "PERSON")
    assert sections == ["infobox", "biography", "personality", "relationships", "references"]


def test_generation_profile_base_default_when_no_config():
    sections, max_tokens = gwp.generation_profile({}, "figurant", "PERSON")
    assert sections[0] == "infobox"
    assert "biography" in sections
    assert isinstance(max_tokens, int)


def test_generation_profile_unknown_type_falls_back():
    sections, _ = gwp.generation_profile({}, "principal", None)
    assert "infobox" in sections and "biography" in sections
