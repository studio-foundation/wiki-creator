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


def test_batch_bound_value_apparition_single_book():
    entity = {"canonical_name": "X", "books": ["01-throne-of-glass"]}
    assert gwp._batch_bound_value(entity, "apparition") == "Apparaît au tome 1"


def test_batch_bound_value_apparition_multi_book_and_lang():
    entity = {"canonical_name": "X", "books": ["01-throne-of-glass", "02-crown-of-midnight"]}
    assert gwp._batch_bound_value(entity, "apparition") == (
        "Apparaît au tome 1, dernière apparition tome 2"
    )
    assert gwp._batch_bound_value(entity, "apparition", "en") == (
        "First appears in book 1, last appears in book 2"
    )


def test_batch_bound_value_apparition_no_books_is_none():
    assert gwp._batch_bound_value({"canonical_name": "X"}, "apparition") is None
    assert gwp._batch_bound_value({"canonical_name": "X", "books": []}, "apparition") is None


def test_bind_batch_fields_sets_apparition_infobox_field():
    entity = {"canonical_name": "Verin", "type": "PERSON", "importance": "secondary",
              "aliases": ["Ver"], "books": ["01-throne-of-glass", "02-crown-of-midnight"]}
    book_config = {"export": {"categories": {"language": "fr"}}}
    page = {"infobox_fields": {}}
    gwp._bind_batch_fields(page, entity, book_config)
    assert page["infobox_fields"]["apparition"] == (
        "Apparaît au tome 1, dernière apparition tome 2"
    )


def test_bind_batch_fields_apparition_defaults_to_english_language():
    # page_templates.output_language() falls back to "en" absent config —
    # same default the rest of the infobox/category pipeline already uses.
    entity = {"canonical_name": "Verin", "type": "PERSON", "importance": "secondary",
              "aliases": [], "books": ["01-a"]}
    page = {"infobox_fields": {}}
    gwp._bind_batch_fields(page, entity, {})
    assert page["infobox_fields"]["apparition"] == "Appears in book 1"


def test_bind_batch_fields_omits_apparition_when_no_books():
    entity = {"canonical_name": "Verin", "type": "PERSON", "importance": "secondary",
              "aliases": ["Ver"]}
    page = {"infobox_fields": {}}
    gwp._bind_batch_fields(page, entity, {})
    assert "apparition" not in page["infobox_fields"]


def test_make_stub_page_carries_books():
    entity = {"canonical_name": "X", "importance": "figurant", "type": "PERSON",
              "books": ["01-a", "02-b"]}
    page = gwp.make_stub_page(entity)
    assert page["books"] == ["01-a", "02-b"]


def test_make_stub_page_defaults_books_to_empty_list():
    entity = {"canonical_name": "X", "importance": "figurant", "type": "PERSON"}
    page = gwp.make_stub_page(entity)
    assert page["books"] == []


def test_parse_response_forces_books_from_entity():
    entity = {"canonical_name": "X", "importance": "figurant", "type": "PERSON",
              "books": ["01-a"]}
    raw = '{"content": "## Biographie\\n\\nSome content long enough to pass.", "books": ["stale"]}'
    page = gwp.parse_response(raw, entity)
    assert page["books"] == ["01-a"]


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


def test_generation_profile_principal_person_uses_base_template_order():
    # No book config -> sections come from base.yaml's PERSON principal template,
    # whose order differs from the old _DEFAULT_SECTIONS_BY_IMPORTANCE
    # (relationships before personality). Pins that sections are template-sourced.
    sections, _ = gwp.generation_profile({}, "principal", "PERSON")
    assert sections == [
        "infobox", "biography", "backstory", "narrative_role", "relationships", "personality",
        "physical", "powers", "trivia", "references",
    ]


def test_generation_profile_place_secondary_drops_relationships():
    # base.yaml gates PLACE.relationships to principal-only, so even though the
    # book's flat secondary config lists "relationships", it is filtered out for
    # a PLACE at secondary tier. Deliberate type-aware refinement (STU-436).
    config = {"secondary": {"sections": ["infobox", "biography", "relationships", "references"]}}
    sections, _ = gwp.generation_profile(config, "secondary", "PLACE")
    assert "relationships" not in sections
    assert sections == ["infobox", "biography", "references"]

    # Contrast: PERSON.relationships includes secondary in base.yaml, so it is kept.
    person_sections, _ = gwp.generation_profile(config, "secondary", "PERSON")
    assert "relationships" in person_sections


def test_bind_fills_titles_extracted_fact_at_secondary():
    entity = {"canonical_name": "Chaol Westfall", "type": "PERSON",
              "importance": "secondary", "aliases": ["Chaol"], "titles": ["Captain"]}
    page = {"infobox_fields": {}}
    gwp._bind_batch_fields(page, entity, {})
    assert page["infobox_fields"]["titles"] == "Captain"     # extracted-fact bound
    assert page["infobox_fields"]["nom"] == "Chaol Westfall"  # batch-bound still works


def test_bind_omits_titles_when_absent():
    entity = {"canonical_name": "Nehemia", "type": "PERSON",
              "importance": "secondary", "aliases": [], "titles": []}
    page = {"infobox_fields": {}}
    gwp._bind_batch_fields(page, entity, {})
    assert "titles" not in page["infobox_fields"]            # OPT + no value → omitted


def test_extracted_fact_value_titles_and_unknown():
    assert gwp._extracted_fact_value({"titles": ["Captain", "Duke"]}, "titles") == "Captain, Duke"
    assert gwp._extracted_fact_value({"titles": []}, "titles") is None
    assert gwp._extracted_fact_value({"affiliation": "X"}, "affiliation") is None
