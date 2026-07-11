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
