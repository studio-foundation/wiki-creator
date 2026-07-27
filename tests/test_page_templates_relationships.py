from wiki_creator import page_templates as pt


def test_canonical_from_legacy_french():
    assert pt.canonical_relationship("employeur/employé") == "employment"
    assert pt.canonical_relationship("antagoniste") == "enemy"


def test_canonical_passthrough_and_unknown():
    assert pt.canonical_relationship("family") == "family"   # already canonical
    assert pt.canonical_relationship(None) is None
    assert pt.canonical_relationship("gibberish") is None


def test_relationship_label_localized():
    assert pt.relationship_label("enemy", "en") == "Enemy"
    assert pt.relationship_label("enemy", "fr") == "Ennemi"
    # unknown token/lang falls back to the token
    assert pt.relationship_label("enemy", "de") == "enemy"


# --- sub-roles (STU-665) ----------------------------------------------------


def test_sub_role_tokens_cover_immediate_kin_and_romance():
    tokens = set(pt.sub_role_tokens())
    assert {"father", "mother", "son", "daughter", "sibling", "spouse", "partner"} <= tokens
    # Extended kin is deliberately excluded (cutoff criterion).
    assert "cousin" not in tokens
    assert "grandfather" not in tokens


def test_sub_role_definitions_carry_a_criterion():
    defs = pt.sub_role_definitions()
    assert all(d["name"] and d["description"] for d in defs)
    assert {d["name"] for d in defs} == set(pt.sub_role_tokens())


def test_sub_role_label_localized_and_fallback():
    assert pt.sub_role_label("father", "en") == "father"
    assert pt.sub_role_label("father", "fr") == "père"
    assert pt.sub_role_label("father", "de") == "father"   # unknown lang → token
    assert pt.sub_role_label("gibberish", "en") == "gibberish"  # unknown token → itself
