# tests/test_export_helpers.py
import pytest
from wiki_creator.export_helpers import (
    page_filename,
    category_tags,
    infobox_template_content,
    main_page_content,
)


def test_page_filename_replaces_spaces():
    assert page_filename("David Martín") == "David_Martín"


def test_page_filename_preserves_accents():
    assert page_filename("Barcelone") == "Barcelone"


def test_category_tags_principal_person():
    labels = {
        "persons": "Personnages",
        "principal": "Personnages principaux",
        "secondary": "Personnages secondaires",
        "locations": "Lieux",
        "organizations": "Organisations",
    }
    tags = category_tags("PERSON", "principal", labels)
    assert "[[Category:Personnages]]" in tags
    assert "[[Category:Personnages principaux]]" in tags


def test_category_tags_secondary_person():
    labels = {
        "persons": "Personnages",
        "principal": "Personnages principaux",
        "secondary": "Personnages secondaires",
        "locations": "Lieux",
        "organizations": "Organisations",
    }
    tags = category_tags("PERSON", "secondary", labels)
    assert "[[Category:Personnages]]" in tags
    assert "[[Category:Personnages secondaires]]" in tags
    assert "[[Category:Personnages principaux]]" not in tags


def test_category_tags_figurant_person():
    labels = {
        "persons": "Personnages",
        "principal": "Personnages principaux",
        "secondary": "Personnages secondaires",
        "locations": "Lieux",
        "organizations": "Organisations",
    }
    tags = category_tags("PERSON", "figurant", labels)
    assert "[[Category:Personnages]]" in tags
    assert "[[Category:Personnages principaux]]" not in tags


def test_category_tags_place():
    labels = {"persons": "P", "principal": "P", "secondary": "P",
              "locations": "Lieux", "organizations": "O"}
    tags = category_tags("PLACE", "principal", labels)
    assert "[[Category:Lieux]]" in tags


def test_category_tags_org():
    labels = {"persons": "P", "principal": "P", "secondary": "P",
              "locations": "L", "organizations": "Organisations"}
    tags = category_tags("ORG", "principal", labels)
    assert "[[Category:Organisations]]" in tags


def test_infobox_template_person_contains_name_field():
    content = infobox_template_content("PERSON")
    assert "{{{name}}}" in content
    assert "{{{status|}}}" in content


def test_infobox_template_place():
    content = infobox_template_content("PLACE")
    assert "{{{name}}}" in content


def test_main_page_content_contains_title():
    pages = [
        {"title": "David Martín", "importance": "principal", "entity_type": "PERSON"},
        {"title": "Barcelone", "importance": "principal", "entity_type": "PLACE"},
        {"title": "Figurant X", "importance": "figurant", "entity_type": "PERSON"},
    ]
    labels = {
        "persons": "Personnages",
        "locations": "Lieux",
        "organizations": "Organisations",
    }
    content = main_page_content(
        book_title="Le Jeu de l'Ange",
        author="Carlos Ruiz Zafón",
        pages=pages,
        labels=labels,
    )
    assert "Le Jeu de l'Ange" in content
    assert "David Martín" in content
    assert "Barcelone" in content
    assert "Category:Personnages" in content
    assert "Category:Lieux" in content


def test_infobox_template_unsupported_type_raises():
    with pytest.raises(ValueError, match="No infobox template"):
        infobox_template_content("EVENT")
