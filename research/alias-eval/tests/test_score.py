import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from score import Gold, _entries, gold_by_series, missed_merges  # noqa: E402


def gold_of(*entries) -> Gold:
    gold = Gold()
    for name, entry in entries:
        gold.add(name, entry)
    return gold


LUCY = ("Lucy", {
    "canonical_aliases_book1": ["Lucy", "Queen Lucy the Valiant"],
    "identity_confusion_forbidden": ["alias: Peter", "alias: Daughter of Eve"],
})
SUSAN = ("Susan", {"canonical_aliases_book1": ["Susan", "Queen Susan the Gentle"]})


def test_two_names_of_one_character_are_a_true_positive():
    gold = gold_of(LUCY)
    assert gold.judge("Lucy", "Queen Lucy the Valiant") == "true_positive"


def test_two_characters_are_a_false_positive():
    gold = gold_of(LUCY, SUSAN)
    assert gold.judge("Lucy", "Susan") == "false_positive"


def test_a_name_the_gold_does_not_hold_is_unjudged():
    """The gold covers a handful of characters, never a roster — most merges land here."""
    gold = gold_of(LUCY)
    assert gold.judge("Lucy", "Mr Tumnus") == "unjudged"
    assert gold.judge("Aslan", "Maugrim") == "unjudged"


def test_a_forbidden_confusion_is_false_even_though_the_other_name_is_unknown():
    """`identity_confusion_forbidden` is a merge verdict written down in advance.

    `Daughter of Eve` is on no character's alias list — every rule above it would
    return `unjudged` — but the gold names this exact pair as a confusion a page
    must never make, which is the merge the stage actually produced (STU-543).
    """
    gold = gold_of(LUCY)
    assert gold.judge("Lucy", "Daughter of Eve") == "false_positive"
    assert gold.judge("Daughter of Eve", "Lucy") == "false_positive"


def test_names_are_matched_past_an_article_and_case():
    gold = gold_of(("la Sorcière Blanche", {
        "canonical_aliases_book1": ["the White Witch", "the Witch"],
    }))
    assert gold.judge("The Witch", "White Witch") == "true_positive"


def test_entries_reads_both_gold_shapes():
    """The corpora nest several characters per file — `the_four_children.json` holds
    peter/susan/edmund/lucy as sub-objects, and a reader keyed on a top-level
    `entity` sees none of them."""
    flat = {"entity": "Aslan", "canonical_aliases_book1": ["Aslan", "the Lion"]}
    assert [name for name, _ in _entries(flat)] == ["Aslan"]

    nested = {
        "entities": ["Peter", "Lucy"],
        "peter": {"canonical_aliases_book1": ["Peter", "High King"]},
        "lucy": {"entity": "Lucy", "canonical_aliases_book1": ["Lucy"]},
        "note": "a string sub-value must not be read as an entry",
    }
    assert sorted(name for name, _ in _entries(nested)) == ["Lucy", "peter"]


def test_inheritance_gold_forbids_eragon_uluthrek():
    """STU-544: Uluthrek is Angela's Urgal name; `Eragon = Uluthrek` is the FP the
    quote check let through. The gold entry is what makes that merge scoreable — a
    later-book confusion forbidden under a book-1 character (Eragon)."""
    gold = gold_by_series().get("inheritance")
    assert gold is not None, "inheritance ground-truth corpus not found"
    assert gold.judge("Eragon", "Uluthrek") == "false_positive"


def test_missed_merges_are_only_the_pairs_the_gold_can_see():
    gold = gold_of(LUCY)
    roster = [{"name": "Lucy"}, {"name": "Queen Lucy the Valiant"}, {"name": "Mr Tumnus"}]
    assert missed_merges(roster, [], gold) == [("Lucy", "Lucy", "Queen Lucy the Valiant")]
    merged = [{"a": "Queen Lucy the Valiant", "b": "Lucy"}]
    assert missed_merges(roster, merged, gold) == []
