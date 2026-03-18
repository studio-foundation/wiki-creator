import json
import pytest
from scripts.wiki_page_validator import parse_payload


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
