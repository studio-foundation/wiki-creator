"""STU-666: per-book narrative_role act structure (weights or explicit ranges)."""

import pytest

from wiki_creator.narrative_arc import (
    DEFAULT_ACT_WEIGHTS,
    NarrativeArc,
    narrative_arc,
)


# --- config parsing ---------------------------------------------------------


def test_absent_block_is_the_2550_25_default():
    arc = narrative_arc({})
    assert arc == NarrativeArc()
    assert arc.weights == DEFAULT_ACT_WEIGHTS
    assert arc.acts is None
    assert narrative_arc({"generation": {}}).weights == DEFAULT_ACT_WEIGHTS


def test_weights_mode_is_parsed():
    arc = narrative_arc({"generation": {"narrative_arc": {"weights": [0.2, 0.6, 0.2]}}})
    assert arc.weights == (0.2, 0.6, 0.2)
    assert arc.acts is None


def test_acts_mode_is_parsed():
    arc = narrative_arc(
        {"generation": {"narrative_arc": {"acts": {"setup": [1, 3], "rising": [4, 22], "resolution": [23, 25]}}}}
    )
    assert arc.weights is None
    assert arc.acts == ((1, 3), (4, 22), (23, 25))


def test_declaring_both_modes_raises():
    with pytest.raises(ValueError, match="mutually exclusive"):
        narrative_arc(
            {"generation": {"narrative_arc": {"weights": [0.25, 0.5, 0.25], "acts": {"setup": [1, 1], "rising": [2, 2], "resolution": [3, 3]}}}}
        )


def test_empty_block_raises():
    with pytest.raises(ValueError, match="must declare"):
        narrative_arc({"generation": {"narrative_arc": {}}})


def test_non_mapping_block_raises():
    with pytest.raises(ValueError, match="must be a mapping"):
        narrative_arc({"generation": {"narrative_arc": [0.25, 0.5, 0.25]}})


@pytest.mark.parametrize("bad", [[0.5, 0.5], [0.3, 0.3, 0.3, 0.1], "x", 3])
def test_weights_wrong_arity_raises(bad):
    with pytest.raises(ValueError):
        narrative_arc({"generation": {"narrative_arc": {"weights": bad}}})


def test_weights_not_summing_to_one_raises():
    with pytest.raises(ValueError, match="sum to 1.0"):
        narrative_arc({"generation": {"narrative_arc": {"weights": [0.2, 0.2, 0.2]}}})


def test_negative_weight_raises():
    with pytest.raises(ValueError, match="non-negative"):
        narrative_arc({"generation": {"narrative_arc": {"weights": [-0.1, 0.6, 0.5]}}})


def test_acts_missing_key_raises():
    with pytest.raises(ValueError, match="exactly setup/rising/resolution"):
        narrative_arc({"generation": {"narrative_arc": {"acts": {"setup": [1, 3], "rising": [4, 22]}}}})


def test_acts_gap_raises():
    with pytest.raises(ValueError, match="contiguous"):
        narrative_arc(
            {"generation": {"narrative_arc": {"acts": {"setup": [1, 3], "rising": [5, 22], "resolution": [23, 25]}}}}
        )


def test_acts_overlap_raises():
    with pytest.raises(ValueError, match="contiguous"):
        narrative_arc(
            {"generation": {"narrative_arc": {"acts": {"setup": [1, 4], "rising": [4, 22], "resolution": [23, 25]}}}}
        )


def test_acts_reversed_range_raises():
    with pytest.raises(ValueError, match="first chapter"):
        narrative_arc(
            {"generation": {"narrative_arc": {"acts": {"setup": [3, 1], "rising": [4, 22], "resolution": [23, 25]}}}}
        )


# --- partition --------------------------------------------------------------


def test_default_partition_matches_2550_25():
    chapters = list(range(1, 13))  # 12 chapters
    (setup, middle, epilogue), weights = NarrativeArc().partition(chapters)
    assert weights == DEFAULT_ACT_WEIGHTS
    # round(12 * .25) = 3 setup, round(12 * .25) = 3 epilogue, 6 middle
    assert setup == {1, 2, 3}
    assert epilogue == {10, 11, 12}
    assert middle == {4, 5, 6, 7, 8, 9}


def test_weights_partition_shifts_boundaries():
    chapters = list(range(1, 11))  # 10 chapters
    (setup, middle, epilogue), _ = NarrativeArc(weights=(0.1, 0.8, 0.1)).partition(chapters)
    assert setup == {1}
    assert epilogue == {10}
    assert middle == set(range(2, 10))


def test_ranges_partition_and_size_weights():
    chapters = [1, 2, 3, 4, 5, 10, 24, 25]
    arc = NarrativeArc(weights=None, acts=((1, 3), (4, 22), (23, 25)))
    (setup, middle, epilogue), weights = arc.partition(chapters)
    assert setup == {1, 2, 3}
    assert middle == {4, 5, 10}
    assert epilogue == {24, 25}
    # weight = act's share of covered chapters: 3/8, 3/8, 2/8
    assert weights == pytest.approx((3 / 8, 3 / 8, 2 / 8))


def test_ranges_not_covering_a_chapter_raises():
    chapters = [1, 2, 30]  # 30 outside the declared span
    arc = NarrativeArc(weights=None, acts=((1, 3), (4, 22), (23, 25)))
    with pytest.raises(ValueError, match="do not cover"):
        arc.partition(chapters)


# --- integration with _narrative_events ------------------------------------


def _person(events):
    return {"type": "PERSON", "canonical_name": "X", "entity_events": events}


def test_narrative_events_default_matches_no_arg():
    import scripts.generate_wiki_pages as gwp

    events = [
        {"chapter": c, "description": f"c{c}", "salience": 0.5}
        for c in range(1, 13)
        for _ in range(2)
    ]
    assert gwp._narrative_events(_person(events)) == gwp._narrative_events(
        _person(events), NarrativeArc()
    )


def test_narrative_events_honors_explicit_ranges():
    import scripts.generate_wiki_pages as gwp

    # Chapters 1-5 are a low-salience exposition the default 25/50/25 under-serves.
    events = [
        {"chapter": c, "description": f"c{c}-{i}", "salience": 0.05 if c <= 5 else 0.9}
        for c in range(1, 11)
        for i in range(3)
    ]
    wide_setup = NarrativeArc(weights=None, acts=((1, 5), (6, 8), (9, 10)))
    picked = gwp._narrative_events(_person(events), wide_setup)
    default = gwp._narrative_events(_person(events))
    early = lambda ps: sum(1 for e in ps if e["chapter"] <= 5)
    # Declaring chapters 1-5 as the setup act gives the exposition more of the
    # budget than the default position split, which cuts it at ~ch2.
    assert early(picked) > early(default)
    assert [e["chapter"] for e in picked] == sorted(e["chapter"] for e in picked)
