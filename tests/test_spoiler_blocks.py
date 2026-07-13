from wiki_creator.spoiler_blocks import wrap_collapsible

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
