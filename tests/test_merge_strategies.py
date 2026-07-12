"""Tests for wiki_creator/merge_strategies.py — EntityRegistry pas 2 (STU-442)."""
from wiki_creator.merge_strategies import (
    STRATEGY_VOCABULARY,
    compose_evidence,
    normalize_method,
    recover_chapter_id,
    strategy_for,
)


def test_normalize_method_renames_only_the_two_target_methods():
    assert normalize_method("title_alias") == "title_apposition"
    assert normalize_method("llm") == "llm_confirm"
    # everything else is preserved verbatim
    for kept in ("pure_title", "role_symmetric", "pattern", "cooccurrence"):
        assert normalize_method(kept) == kept
    # unknown/empty degrade gracefully
    assert normalize_method("") == "unknown"
    assert normalize_method("weird") == "weird"


def test_strategy_for_builds_normalized_decision():
    d = strategy_for("pure_title").propose(
        "perrington", "duke", evidence="Duke Perrington, the duke, scowled.",
        confidence="medium",
    )
    assert d.strategy == "pure_title"
    assert d.inputs == ("perrington", "duke")
    assert d.confidence == "medium"
    # content-derived id is stable
    d2 = strategy_for("pure_title").propose(
        "perrington", "duke", evidence="Duke Perrington, the duke, scowled.",
        confidence="medium",
    )
    assert d.decision_id == d2.decision_id


def test_recover_chapter_id_matches_full_registry_sentence():
    full = {
        "e1": {"mentions_by_chapter": {"ch05": ["Brullo — the Master — nodded at Celaena."]}},
    }
    assert recover_chapter_id("Brullo — the Master — nodded at Celaena.", full) == "ch05"
    assert recover_chapter_id("no such sentence", full) is None
    assert recover_chapter_id("", full) is None


def test_compose_evidence_embeds_chapter_when_present():
    assert compose_evidence("a snippet", "ch03") == "a snippet [chapter=ch03]"
    assert compose_evidence("a snippet", None) == "a snippet"


def test_vocabulary_is_the_single_source_of_truth():
    # the two renames are declared; identity entries are explicit for readability
    assert STRATEGY_VOCABULARY["title_alias"] == "title_apposition"
    assert STRATEGY_VOCABULARY["llm"] == "llm_confirm"
