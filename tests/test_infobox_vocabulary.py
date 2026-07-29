"""The infobox template and the page renderer share one vocabulary (STU-729).

The bug this guards: the hand-kept ``infobox_source`` declared ``{{{name}}}`` /
``{{{first_seen}}}`` while the renderer emitted ``nom`` / ``apparition``, so every
infobox row — including the character-name header — rendered empty. The template is
now generated from the declared infobox tokens, and every renderer must emit only
those tokens.
"""
import re

import pytest

import scripts.generate_wiki_pages as gwp
from wiki_creator.entity_taxonomy import declared_types
from wiki_creator.event_pages import event_infobox_fields
from wiki_creator.infobox_relationships import INFOBOX_BUCKET_TOKENS
from wiki_creator.page_templates import infobox_tokens, render_infobox_source

_PARAM_RE = re.compile(r"\{\{\{(\w+)")


def _params(source: str) -> set[str]:
    return set(_PARAM_RE.findall(source))


@pytest.mark.parametrize("lang", ["fr", "en"])
@pytest.mark.parametrize("etype", declared_types())
def test_generated_template_declares_exactly_the_declared_tokens(etype, lang):
    tokens = infobox_tokens(etype)
    source = render_infobox_source(etype, lang)
    if not tokens:
        assert source is None
        return
    # The header carries the name token, the rest are labelled rows — together the
    # template's parameters are exactly the declared token set, in both languages.
    assert _params(source) == set(tokens)
    assert source.startswith('<includeonly>\n{| class="infobox"\n|-\n! colspan="2" | {{{' + tokens[0] + "}}}")


def test_relationship_buckets_are_person_tokens():
    # The Family/Romance/Friends/Enemies infobox rows are built independently of the
    # template — they must stay a subset of what PERSON declares.
    assert set(INFOBOX_BUCKET_TOKENS) <= set(infobox_tokens("PERSON"))


def test_event_builder_emits_only_event_tokens():
    event = {
        "description": "the duel",
        "participants": ["Cain", "Celaena"],
        "places": ["Rifthold"],
        "chapter": 48,
        "outcome": "Celaena wins",
    }
    # `nom` is added by generate_event_pages alongside the deterministic event facts.
    emitted = {"nom", *event_infobox_fields(event).keys()}
    assert emitted <= set(infobox_tokens("EVENT"))


def test_binder_drops_writer_leaked_keys_for_a_location():
    # The Oz symptom in miniature: a location writer emits `name`/`place_type`/`region`
    # (no matching template parameter). After binding, only declared PLACE tokens
    # survive, so nothing renders into a row the template never declares.
    entity = {"canonical_name": "Emerald City", "type": "PLACE",
              "importance": "principal", "books": ["01-oz"]}
    page = {"infobox_fields": {"name": "Emerald City", "place_type": "City", "region": "Oz"}}
    gwp._bind_batch_fields(page, entity, {"generation": {"output_language": "en"}})
    assert set(page["infobox_fields"]) <= set(infobox_tokens("PLACE"))
    assert page["infobox_fields"]["nom"] == "Emerald City"
    assert "name" not in page["infobox_fields"]
    assert "place_type" not in page["infobox_fields"]
    assert "region" not in page["infobox_fields"]
