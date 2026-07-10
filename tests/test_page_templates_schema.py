import copy
import pytest
from wiki_creator import page_templates as pt


def test_base_template_loads_and_validates():
    raw = pt.load_base_template()
    assert set(raw["entity_types"]) >= {"PERSON", "PLACE", "ORG", "EVENT"}
    pt.validate_template(raw)  # must not raise


def test_validate_rejects_unknown_provenance():
    raw = copy.deepcopy(pt.load_base_template())
    raw["entity_types"]["PERSON"]["infobox"][0]["provenance"] = "made-up"
    with pytest.raises(ValueError, match="provenance"):
        pt.validate_template(raw)


def test_validate_requires_fallback_for_min_extracted_fact():
    raw = copy.deepcopy(pt.load_base_template())
    slot = {"token": "x", "group": "infobox", "provenance": "extracted-fact",
            "obligation": "MIN", "tiers": ["figurant"]}
    raw["entity_types"]["PERSON"]["infobox"].append(slot)
    with pytest.raises(ValueError, match="fallback"):
        pt.validate_template(raw)
