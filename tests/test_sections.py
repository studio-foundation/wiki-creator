from wiki_creator.sections import SECTION_TITLES


def test_section_titles_cover_known_keys():
    assert SECTION_TITLES["biography"] == "Biographie"
    assert SECTION_TITLES["relationships"] == "Relations"
    assert SECTION_TITLES["references"] == "Références"
    assert SECTION_TITLES["narrative_role"] == "Rôle dans le récit"
