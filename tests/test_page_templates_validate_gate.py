"""STU-670: `should_validate_page` — which tiers run the grounding validator."""

import pytest

from wiki_creator.page_templates import DEFAULT_VALIDATE_PAGES, should_validate_page


def test_default_grounds_principal_only():
    assert DEFAULT_VALIDATE_PAGES == "principal"
    assert should_validate_page("principal") is True
    assert should_validate_page("secondary") is False
    assert should_validate_page("figurant") is False


def test_floor_is_inclusive_and_covers_above():
    assert should_validate_page("figurant", "secondary") is False
    assert should_validate_page("secondary", "secondary") is True
    assert should_validate_page("principal", "secondary") is True


@pytest.mark.parametrize("tier", ["figurant", "secondary", "principal"])
def test_all_validates_every_tier(tier):
    assert should_validate_page(tier, "all") is True


@pytest.mark.parametrize("tier", ["figurant", "secondary", "principal"])
def test_off_validates_nothing(tier):
    assert should_validate_page(tier, "off") is False


def test_unknown_importance_fails_safe_to_validate():
    assert should_validate_page("ignored", "principal") is True
    assert should_validate_page("", "off") is False  # off is unconditional


def test_unknown_setting_falls_back_to_default_floor():
    assert should_validate_page("secondary", "bogus") is False
    assert should_validate_page("principal", "bogus") is True


def test_setting_is_case_and_whitespace_insensitive():
    assert should_validate_page("secondary", "  ALL ") is True
    assert should_validate_page("secondary", "Off") is False
