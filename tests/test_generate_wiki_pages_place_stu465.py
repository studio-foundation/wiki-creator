"""STU-465: PLACE pages failed silently as `biography_failed`.

Sectioned generation isolates a single section by its French title
("## Biographie"). PLACE entities are article-shaped: the model returns several
place-titled blocks (Géographie, Histoire, Culture…) per page, which
`_isolate_section` discarded as a false biography failure. Non-PERSON types must
route to single-shot generation, which keeps the multi-section article as-is.
"""
from pathlib import Path

import scripts.generate_wiki_pages as gwp

# Verbatim shape of what the LLM actually returns for a PLACE biography call:
# multiple place-appropriate headings, none titled "Biographie".
EYLLWE_CONTENT = (
    "## Géographie et situation politique\n\n"
    "Eyllwe est l'un des derniers pays à résister à la domination d'Adarlan.\n\n"
    "## Domination adarlanienne et rébellion\n\n"
    "Eyllwe subit l'oppression croissante d'Adarlan.\n\n"
    "## Culture et langue\n\n"
    "Eyllwe possède une culture distincte, avec sa propre langue."
)


def _place_entity():
    return {
        "canonical_name": "Eyllwe",
        "type": "PLACE",
        "importance": "principal",
        "context_by_chapter": {"C01": ["Eyllwe résiste à Adarlan."]},
        "relationships": [],
    }


def _fake_place_item(content):
    return {
        "title": "Eyllwe",
        "importance": "principal",
        "entity_type": "PLACE",
        "infobox_fields": {},
        "content": content,
    }


def test_isolate_section_drops_multi_block_place_content():
    """Documents the root cause: sectioned isolation returns None for a valid
    multi-section PLACE article because no block is titled 'Biographie'."""
    assert gwp._isolate_section(EYLLWE_CONTENT, "biography") is None


def test_place_entity_routes_to_single_shot(monkeypatch):
    """Non-PERSON types must NOT go through sectioned isolation."""
    monkeypatch.setattr(gwp, "_run_generation_sectioned",
                        lambda **kw: {"_which": "sectioned"})
    monkeypatch.setattr(gwp, "_run_generation_for_entity",
                        lambda **kw: {"_which": "single_shot"})
    page = gwp._run_generation(
        entity=_place_entity(), book_title="ToG", model="m", timeout=10,
        sections=["infobox", "biography", "references"], max_tokens=800,
        dry_run=False, debug_dir=Path("/tmp"))
    assert page["_which"] == "single_shot"


def test_person_entity_routes_to_sectioned(monkeypatch):
    """PERSON keeps section-scoped generation."""
    monkeypatch.setattr(gwp, "_run_generation_sectioned",
                        lambda **kw: {"_which": "sectioned"})
    monkeypatch.setattr(gwp, "_run_generation_for_entity",
                        lambda **kw: {"_which": "single_shot"})
    entity = {"canonical_name": "Chaol", "type": "PERSON", "importance": "principal",
              "context_by_chapter": {"C01": ["ctx"]}, "relationships": []}
    page = gwp._run_generation(
        entity=entity, book_title="ToG", model="m", timeout=10,
        sections=["infobox", "biography"], max_tokens=800,
        dry_run=False, debug_dir=Path("/tmp"))
    assert page["_which"] == "sectioned"


def test_rich_place_produces_non_empty_page(monkeypatch, tmp_path):
    """Non-regression (issue target #3): a context-rich PLACE (Eyllwe) must
    produce a non-empty, non-failed page from its multi-section LLM output."""
    monkeypatch.setattr(gwp, "_run_wiki_page_item",
                        lambda **kw: _fake_place_item(EYLLWE_CONTENT))
    page = gwp._run_generation(
        entity=_place_entity(), book_title="Throne of Glass", model="m", timeout=10,
        sections=["infobox", "biography", "physical", "references"], max_tokens=800,
        dry_run=False, debug_dir=tmp_path / "debug")
    assert not page.get("_failed")
    assert page["content"].strip()
    assert "Géographie" in page["content"]
    assert "Culture" in page["content"]


def test_failed_stub_message_distinct_from_insufficient():
    """Issue target #2: a technical failure must not be labelled with the
    data-insufficiency message that masked it."""
    entity = {"canonical_name": "Eyllwe", "importance": "principal", "type": "PLACE"}
    failed = gwp.make_stub_page(entity, failed=True)
    insufficient = gwp.make_stub_page(entity, insufficient_data=True)
    assert failed["content"] != insufficient["content"]
    assert "insuffisantes" not in failed["content"].lower()
    assert "insuffisantes" in insufficient["content"].lower()
