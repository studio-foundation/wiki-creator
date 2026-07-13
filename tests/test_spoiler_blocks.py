from wiki_creator.spoiler_blocks import relationship_index_lines, wrap_collapsible

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
