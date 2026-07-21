from wiki_creator import page_templates as pt


def test_slot_label_localized():
    assert pt.slot_label("status", "en") == "Status"
    assert pt.slot_label("status", "fr") == "Statut"


def test_slot_label_fallback_titlecase():
    assert pt.slot_label("made_up_token", "en") == "Made Up Token"


def test_output_language_precedence():
    # STU-510: explicit generation.output_language wins.
    # STU-607: the default follows the book's own language (book_language) instead
    # of a hardcoded French, so an English source yields an English wiki.
    # export.categories.language is a separate axis (category labels) and
    # deliberately does NOT drive output language.
    assert pt.output_language({"generation": {"output_language": "en"}}) == "en"
    assert pt.output_language({"generation": {"output_language": "fr"}}) == "fr"
    # STU-607: an English book defaults to English output.
    assert pt.output_language({"spacy_model": "en_core_web_lg"}) == "en"
    assert pt.output_language({"language": "en"}) == "en"
    # No language signal at all still degrades to the historical French default.
    assert pt.output_language(None) == "fr"
    assert pt.output_language({}) == "fr"
    assert pt.output_language({"export": {"categories": {"language": "en"}}}) == "fr"


def test_language_name():
    assert pt.language_name("fr") == "French"
    assert pt.language_name("en") == "English"
    assert pt.language_name("xx") == "xx"  # unknown code degrades to itself


def test_length_guide_per_tier():
    assert pt.length_guide("principal").startswith("4 to 6 paragraphs")
    assert pt.length_guide("figurant").startswith("1 short paragraph")
    # unknown tier falls back to the figurant guide
    assert pt.length_guide("made_up") == pt.length_guide("figurant")


def test_section_brief_localized_and_fallback():
    assert pt.section_brief("PERSON", "biography", "fr").startswith("Qui est ce personnage")
    assert pt.section_brief("PERSON", "biography", "en").startswith("Who this character is")
    # OTHER falls back to PERSON's briefs (as SECTION_DEFINITIONS.get(etype, PERSON) did)
    assert pt.section_brief("OTHER", "biography", "en") == pt.section_brief("PERSON", "biography", "en")
    # a token with no declared brief returns None
    assert pt.section_brief("PERSON", "references", "fr") is None


def test_few_shot_example_localized():
    assert pt.few_shot_example("fr")["content"].startswith("## Infobox")
    assert "## Biography" in pt.few_shot_example("en")["content"]
    assert "## Biographie" in pt.few_shot_example("fr")["content"]
    # unknown language degrades to the French example
    assert pt.few_shot_example("xx") == pt.few_shot_example("fr")
