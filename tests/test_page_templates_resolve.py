from wiki_creator import page_templates as pt


def test_resolve_person_principal_includes_all_tiers():
    rt = pt.resolve_template("PERSON", "principal")
    tokens = [s.token for s in rt.sections()]
    assert "biography" in tokens
    assert "personality" in tokens  # principal-only
    assert "references" in tokens


def test_resolve_person_figurant_is_minimal():
    rt = pt.resolve_template("PERSON", "figurant")
    section_tokens = [s.token for s in rt.sections()]
    assert "biography" in section_tokens
    assert "references" in section_tokens   # references is MIN at every tier
    assert "personality" not in section_tokens  # principal-only, filtered out
    info_tokens = [s.token for s in rt.infobox()]
    assert "nom" in info_tokens
    assert "species" not in info_tokens  # species starts at secondary


def test_resolve_unknown_type_returns_empty():
    rt = pt.resolve_template("MONSTER", "principal")
    assert rt.slots == ()


def test_resolve_person_narrative_role_secondary_and_principal_only():
    """STU-479 (SP1): the 'Rôle dans le récit' arc section (Event Layer, SP0)
    is OPT for PERSON at secondary/principal — figurants stay minimal."""
    for importance in ("secondary", "principal"):
        rt = pt.resolve_template("PERSON", importance)
        assert "narrative_role" in [s.token for s in rt.sections()]
    figurant = pt.resolve_template("PERSON", "figurant")
    assert "narrative_role" not in [s.token for s in figurant.sections()]


def test_resolve_place_events_available_at_every_tier():
    """STU-480 (SP2): the 'événements' section (Event Layer, SP0) is OPT for
    PLACE at all tiers — even a figurant place can host a narratively
    important event."""
    for importance in ("figurant", "secondary", "principal"):
        rt = pt.resolve_template("PLACE", importance)
        tokens = [s.token for s in rt.sections()]
        assert "events" in tokens
