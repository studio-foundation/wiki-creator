from wiki_creator.spoiler_blocks import (
    inject_relationship_index,
    relationship_index_lines,
    spoiler_collapse_after,
    wrap_collapsible,
    wrap_relation_collapsibles,
)

BODY = (
    "== Biographie ==\n\nNé au chapitre 1.\n\n"
    "== Pouvoirs ==\n\nRévélés plus tard."
)


def test_wrap_gates_block_above_threshold():
    units = [
        {"section": "biography", "revealed_at_chapter": 1},
        {"section": "powers", "revealed_at_chapter": 20},
    ]
    out = wrap_collapsible(BODY, units, collapse_after=5)
    # biography (ch.1 <= 5) stays open
    assert '== Biographie ==\n\nNé au chapitre 1.' in out
    assert 'Biographie ==\n\nNé' in out and 'mw-collapsible' in out
    # powers (ch.20 > 5) is wrapped, expand text names the chapter
    assert 'data-expandtext="Chapitre 20 — révéler"' in out
    assert '<div class="mw-collapsible mw-collapsed"' in out
    assert '</div>' in out


def test_wrap_none_and_unmatched_left_open():
    units = [{"section": "biography", "revealed_at_chapter": None}]
    out = wrap_collapsible(BODY, units, collapse_after=5)
    assert "mw-collapsible" not in out  # None chapter + unmatched Pouvoirs → untouched
    assert out == BODY


def test_wrap_threshold_boundary_is_strict():
    units = [{"section": "biography", "revealed_at_chapter": 5}]
    out = wrap_collapsible(BODY, units, collapse_after=5)
    assert "mw-collapsible" not in out  # exactly == threshold stays open


def _entity():
    return {
        "canonical_name": "Celaena Sardothien",
        "aliases": ["Lillian Gordaina"],
        "relationships": [
            {"entity_a": "Celaena Sardothien", "entity_b": "Chaol",
             "relationship_type": "amoureux", "chapters": ["C01.xhtml", "C55.xhtml"]},
            {"entity_a": "Cain", "entity_b": "Celaena Sardothien",
             "relationship_type": "antagoniste", "chapters": ["C07.xhtml"]},
            {"entity_a": "Celaena Sardothien", "entity_b": "Ghost",
             "relationship_type": None, "chapters": ["C03.xhtml"]},
            {"entity_a": "Celaena Sardothien", "entity_b": "NoChap",
             "relationship_type": "ami", "chapters": []},
        ],
    }


def test_relationship_index_lines_content_and_order():
    lines = relationship_index_lines(_entity())
    # untyped (Ghost) and chapter-less (NoChap) excluded
    assert lines == [
        "* [[Cain]] — antagoniste (ch.7)",          # reveal ch.7, most recent first
        "* [[Chaol]] — amoureux (ch.1→ch.55)",      # reveal ch.1
    ]


def test_relationship_index_lines_empty_when_no_typed():
    assert relationship_index_lines({"canonical_name": "X", "relationships": []}) == []


REL_BODY = "== Biographie ==\n\nBio.\n\n== Relations ==\n\nProse FR.\n"


def test_inject_appends_index_under_relations():
    out = inject_relationship_index(REL_BODY, ["* [[Chaol]] — amoureux (ch.1→ch.55)"])
    assert "Prose FR." in out
    assert "''Évolution :''" in out
    assert "* [[Chaol]] — amoureux (ch.1→ch.55)" in out
    # index sits inside the Relations section, not after Biographie
    assert out.index("Évolution") > out.index("Relations")
    assert out.index("Évolution") > out.index("Bio.")


def test_inject_noop_without_relations_or_lines():
    assert inject_relationship_index("== Biographie ==\n\nBio.", ["* x"]) == "== Biographie ==\n\nBio."
    assert inject_relationship_index(REL_BODY, []) == REL_BODY


def test_spoiler_collapse_after_reads_config():
    assert spoiler_collapse_after({"generation": {"spoiler": {"collapse_after_chapter": 3}}}) == 3
    assert spoiler_collapse_after({}) is None
    assert spoiler_collapse_after({"generation": {}}) is None


_REL_BODY = (
    "== Relations ==\n\n"
    "=== [[Celaena]] ===\n\nProse arc jusqu'à la fin.\n\n"
    "=== [[Cain]] ===\n\nRival de la compétition.\n\n"
    "== Anecdotes ==\n\nFait divers.\n"
)


def test_wrap_relation_gates_subsection_above_threshold():
    units = [{"name": "Celaena", "revealed_at_chapter": 55},
             {"name": "Cain", "revealed_at_chapter": 2}]
    out = wrap_relation_collapsibles(_REL_BODY, units, collapse_after=3)
    # Celaena (55 > 3) wrapped; Cain (2 <= 3) not
    assert 'data-expandtext="Chapitre 55 — révéler"' in out
    assert out.count("mw-collapsible") == 1
    assert "=== [[Cain]] ===" in out.split("mw-collapsible")[0] or "Cain" in out
    # Anecdotes (outside Relations) never wrapped
    assert "Fait divers." in out
    assert out.index("Fait divers.") > out.index("mw-collapsible")


def test_wrap_relation_boundary_is_strict():
    units = [{"name": "Celaena", "revealed_at_chapter": 3}]
    out = wrap_relation_collapsibles(_REL_BODY, units, collapse_after=3)
    assert "mw-collapsible" not in out


def test_wrap_relation_unmatched_and_none_left_open():
    units = [{"name": "Celaena", "revealed_at_chapter": None},
             {"name": "Ghost", "revealed_at_chapter": 99}]
    out = wrap_relation_collapsibles(_REL_BODY, units, collapse_after=3)
    assert "mw-collapsible" not in out
