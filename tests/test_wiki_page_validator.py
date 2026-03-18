import json
import pytest
from scripts.wiki_page_validator import parse_payload, check_language_fr


def test_parse_payload_extracts_page_and_input():
    payload = {
        "previous_outputs": {
            "wiki-page-item": {
                "title": "Celaena",
                "importance": "principal",
                "entity_type": "PERSON",
                "infobox_fields": {"Statut": "Assassine"},
                "content": "Celaena est une assassine.",
            }
        },
        "additional_context": "file_path: library/foo/books/01.yaml\nseries: Throne of Glass",
    }
    page, meta = parse_payload(payload)
    assert page["title"] == "Celaena"
    assert meta["series"] == "Throne of Glass"


def test_check_language_fr_passes_french():
    page = {"content": "Celaena est une assassine connue dans tout le royaume."}
    errors = check_language_fr(page)
    assert errors == []


def test_check_language_fr_detects_english():
    page = {"content": "Celaena is the best assassin in the kingdom. She was known as Laena."}
    errors = check_language_fr(page)
    assert any("anglais" in e for e in errors)


def test_check_language_fr_passes_mixed_names():
    page = {"content": "Celaena Sardothien est une assassine du royaume d'Adarlan."}
    errors = check_language_fr(page)
    assert errors == []
