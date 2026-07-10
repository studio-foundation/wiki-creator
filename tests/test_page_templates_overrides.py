from wiki_creator import page_templates as pt


def test_section_tokens_parity_shape():
    rt = pt.resolve_template("PERSON", "secondary")
    toks = rt.section_tokens()
    assert toks[0] == "infobox"
    assert "biography" in toks and "references" in toks


def test_legacy_sections_by_type_override_restricts_sections():
    book = {"generation": {"principal": {
        "sections_by_type": {"ORG": ["infobox", "biography", "references"]}}}}
    rt = pt.resolve_template("ORG", "principal", book_config=book)
    assert rt.section_tokens() == ["infobox", "biography", "references"]
    # relationships was in the base ORG.principal set but is excluded by the override
    assert "relationships" not in rt.section_tokens()


def test_new_template_override_removes_slot():
    book = {"generation": {"template": {"PERSON": {"remove": ["powers"]}}}}
    rt = pt.resolve_template("PERSON", "principal", book_config=book)
    assert "powers" not in [s.token for s in rt.sections()]
