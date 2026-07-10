from wiki_creator import page_templates as pt


def test_canonical_from_legacy_french():
    assert pt.canonical_relationship("employeur/employé") == "employment"
    assert pt.canonical_relationship("antagoniste") == "antagonist"


def test_canonical_passthrough_and_unknown():
    assert pt.canonical_relationship("family") == "family"   # already canonical
    assert pt.canonical_relationship(None) is None
    assert pt.canonical_relationship("gibberish") is None


def test_relationship_label_localized():
    assert pt.relationship_label("antagonist", "en") == "Antagonist"
    assert pt.relationship_label("antagonist", "fr") == "Antagoniste"
    # unknown token/lang falls back to the token
    assert pt.relationship_label("antagonist", "de") == "antagonist"
