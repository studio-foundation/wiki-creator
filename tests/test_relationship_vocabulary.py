"""base.yaml is the single authority for the relationship vocabulary (STU-477).

These tests pin the wiring rather than the wording: unwire any consumer from
`relationships.enum` and one fails. Without them the enum stays what it was before
STU-477 — a declared table nothing reads (see the dead `relationship_tokens` /
`canonical_relationship` helpers this issue put to work).
"""
import re
from pathlib import Path

import pytest
import yaml

from wiki_creator import page_templates as pt
from wiki_creator.relationship_eval import load_gold, NULL_LABEL

import scripts.relationship_classifier_validator as validator
from scripts.relationship_extraction import _run_studio_classifier_item

GOLD_FIXTURE = Path(__file__).parent / "fixtures" / "relationship_eval" / "throne-of-glass-01.yaml"
CLASSIFIER_PROMPT = (
    Path(__file__).resolve().parents[1]
    / ".studio"
    / "agents"
    / "relationship-classifier.agent.yaml"
)

# The graduated middle ground STU-477 exists to make expressible: the audit's
# ami→amoureux jump had no type between "friend" and "romance".
GRADUATED_TYPES = {
    "budding_attraction",
    "strained_friendship",
    "friendly_rivalry",
    "wary_alliance",
}


def test_every_type_declares_an_application_criterion():
    """A type with no description guides nothing — the LLM would apply it on vibes."""
    undescribed = [d["name"] for d in pt.relationship_definitions() if not d["description"]]
    assert undescribed == []


def test_graduated_types_are_declared():
    assert GRADUATED_TYPES <= set(pt.relationship_tokens())


def test_validator_accepts_every_declared_type():
    """The validator reads base.yaml — no second hardcoded copy of the enum."""
    for token in pt.relationship_tokens():
        assert validator.check_relationship_type_valid({"relationship_type": token}) == []


def test_validator_rejects_a_type_absent_from_base_yaml():
    errors = validator.check_relationship_type_valid({"relationship_type": "soulmates"})
    assert len(errors) == 1
    assert "soulmates" in errors[0]


def test_validator_rejects_the_pre_stu477_french_surface_string():
    """Legacy strings map to a token for *rendering* old artifacts; they are not
    a vocabulary the classifier may still emit."""
    assert validator.check_relationship_type_valid({"relationship_type": "amoureux"})


def test_classifier_payload_carries_the_vocabulary(monkeypatch):
    """The types travel with the payload, injected at the one point both callers
    cross — so no caller can dispatch a pair without a vocabulary."""
    captured = {}

    def fake_run(cmd, **kwargs):
        input_path = cmd[cmd.index("--input-file") + 1]
        captured["payload"] = yaml.safe_load(Path(input_path).read_text(encoding="utf-8"))
        raise FileNotFoundError  # short-circuit: we only care about the payload

    monkeypatch.setattr("scripts.relationship_extraction.subprocess.run", fake_run)
    _run_studio_classifier_item(
        {"entity_a": "A", "entity_b": "B"}, novel_summary="", additional_context=""
    )

    sent = captured["payload"]["relationship_types"]
    assert [d["name"] for d in sent] == pt.relationship_tokens()
    assert all(d["description"] for d in sent)


def test_gold_fixture_only_expects_declared_types():
    """Guards fixture↔enum drift: a gold label the enum doesn't declare would score
    the classifier against a vocabulary it can never emit."""
    declared = set(pt.relationship_tokens()) | {NULL_LABEL}
    undeclared = {
        label
        for gp in load_gold(GOLD_FIXTURE)
        for label in gp.acceptable
        if label not in declared
    }
    assert undeclared == set()


@pytest.mark.parametrize(
    "pair, forbidden",
    [
        (("Celaena", "Chaol"), "friend"),   # under-read: the strain is the truth of book 1
        (("Celaena", "Chaol"), "romance"),  # over-read: the romance lands in book 2
    ],
)
def test_gold_pins_the_audit_case_between_friend_and_romance(pair, forbidden):
    gold = {gp.key: gp for gp in load_gold(GOLD_FIXTURE)}
    entry = gold[tuple(sorted(pair))]
    assert forbidden not in entry.acceptable
    assert set(entry.acceptable) <= GRADUATED_TYPES


def _prompt_type_mentions() -> set[str]:
    """Relationship types the classifier prompt names as concrete instructions.

    Mechanical, never a hand-kept list — a second copy of the enum is exactly what
    STU-477 deleted, and it would rot the same way. The tokens are read out of the
    prompt's own instruction grammar: the structural-rule arrows (`PATTERN → token:`,
    where STU-472's renamed `antagonist` survived) and the role-asymmetric exception's
    `classify the pair (a, or b ...)`. snake_case is deliberately not scanned — the
    prompt's JSON field names (`relationship_type`, `key_moments`) share that shape.
    """
    prompt = yaml.safe_load(CLASSIFIER_PROMPT.read_text(encoding="utf-8"))["system_prompt"]
    tokens = set(re.findall(r"→\s*([a-z][a-z_]*)", prompt))
    pair = re.search(r"classify the pair \(([a-z_]+),\s*or\s+([a-z_]+)", prompt)
    if pair:
        tokens |= set(pair.groups())
    return tokens


def test_prompt_names_only_declared_relationship_types():
    """The prompt is the third consumer of the vocabulary, and STU-472 pinned none of it.

    That rename touched `base.yaml` and the validator's world but missed this prompt,
    which kept ordering the model to return `antagonist`; the validator then rejected
    it and RALPH-retried every structural pair to death. `rg` skips `.studio/` and no
    test read the prompt, so the suite stayed green through the whole rename. This
    fails the moment the prompt names a type absent from `relationship_tokens()`.
    """
    mentions = _prompt_type_mentions()
    assert mentions, "extracted no type tokens from the prompt — the instruction grammar moved"
    undeclared = mentions - set(pt.relationship_tokens())
    assert undeclared == set(), f"prompt names types absent from base.yaml: {sorted(undeclared)}"
