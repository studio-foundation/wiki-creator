from wiki_creator import page_templates as pt


def test_slot_label_localized():
    assert pt.slot_label("status", "en") == "Status"
    assert pt.slot_label("status", "fr") == "Statut"


def test_slot_label_fallback_titlecase():
    assert pt.slot_label("made_up_token", "en") == "Made Up Token"


def test_output_language_precedence():
    assert pt.output_language({"generation": {"output_language": "fr"}}) == "fr"
    assert pt.output_language({"export": {"categories": {"language": "en"}}}) == "en"
    assert pt.output_language(None) == "en"
    # generation.output_language wins over export
    cfg = {"generation": {"output_language": "fr"},
           "export": {"categories": {"language": "en"}}}
    assert pt.output_language(cfg) == "fr"
