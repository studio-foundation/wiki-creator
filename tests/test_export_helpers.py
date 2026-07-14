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


def test_page_filename_sanitizes_slashes():
    assert "/" not in page_filename("Le Café / Bar")


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


def _labels_with_tomes():
    return {
        "persons": "Personnages",
        "principal": "Personnages principaux",
        "secondary": "Personnages secondaires",
        "locations": "Lieux",
        "organizations": "Organisations",
        "persons_by_tome": "Personnages du Tome {n}",
        "locations_by_tome": "Lieux du Tome {n}",
        "organizations_by_tome": "Organisations du Tome {n}",
    }


def test_category_tags_person_present_in_two_tomes_gets_both_categories():
    # STU-486 test spec: an entity present in tomes 1 and 2 comes out with
    # both per-tome categories.
    tags = category_tags(
        "PERSON", "principal", _labels_with_tomes(),
        books=["01-throne-of-glass", "02-crown-of-midnight"],
    )
    assert "[[Category:Personnages du Tome 1]]" in tags
    assert "[[Category:Personnages du Tome 2]]" in tags


def test_category_tags_tome_two_only_entity_has_no_tome_one_category():
    # STU-486 test spec: a tome-2-only entity does not carry the tome 1 category.
    tags = category_tags(
        "PERSON", "principal", _labels_with_tomes(), books=["02-crown-of-midnight"]
    )
    assert "[[Category:Personnages du Tome 2]]" in tags
    assert "[[Category:Personnages du Tome 1]]" not in tags


def test_category_tags_no_books_omits_tome_categories():
    tags = category_tags("PERSON", "principal", _labels_with_tomes(), books=[])
    assert not any("du Tome" in t for t in tags)
    tags_none = category_tags("PERSON", "principal", _labels_with_tomes(), books=None)
    assert not any("du Tome" in t for t in tags_none)


def test_category_tags_tome_categories_for_place_and_org():
    labels = _labels_with_tomes()
    place_tags = category_tags("PLACE", "principal", labels, books=["01-a"])
    assert "[[Category:Lieux du Tome 1]]" in place_tags
    org_tags = category_tags("ORG", "principal", labels, books=["01-a"])
    assert "[[Category:Organisations du Tome 1]]" in org_tags


def test_category_tags_missing_tome_label_config_skips_silently():
    # No <type>_by_tome key configured (older book yaml) -> no crash, no tags.
    labels = {"persons": "Personnages", "principal": "P", "secondary": "S",
              "locations": "L", "organizations": "O"}
    tags = category_tags("PERSON", "principal", labels, books=["01-a"])
    assert not any("Tome" in t for t in tags)


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


def test_infobox_template_event():
    content = infobox_template_content("EVENT")
    assert "{{{name}}}" in content
    assert "{{{participants|}}}" in content
    assert "{{{chapitre|}}}" in content


def test_infobox_template_unsupported_type_raises():
    with pytest.raises(ValueError, match="No infobox template"):
        infobox_template_content("OTHER")


def test_category_tags_event():
    labels = {"events": "Événements"}
    assert category_tags("EVENT", "principal", labels) == ["[[Category:Événements]]"]


def test_main_page_lists_events_when_present():
    labels = {"persons": "Personnages", "locations": "Lieux", "organizations": "Organisations"}
    pages = [
        {"title": "Celaena", "importance": "principal", "entity_type": "PERSON"},
        {"title": "Le duel final", "importance": "principal", "entity_type": "EVENT"},
    ]
    content = main_page_content("Throne of Glass", "Sarah J. Maas", pages, labels)
    assert "== Événements ==" in content
    assert "[[Le duel final]]" in content


def test_main_page_links_synopsis_when_present():
    labels = {"persons": "Personnages", "locations": "Lieux", "organizations": "Organisations"}
    pages = [
        {"title": "Synopsis", "importance": "principal", "entity_type": "SYNOPSIS"},
        {"title": "Celaena", "importance": "principal", "entity_type": "PERSON"},
    ]
    content = main_page_content("Throne of Glass", "Sarah J. Maas", pages, labels)
    assert "[[Synopsis|Synopsis du livre]]" in content


def test_main_page_omits_synopsis_section_when_absent():
    labels = {"persons": "Personnages", "locations": "Lieux", "organizations": "Organisations"}
    pages = [{"title": "Celaena", "importance": "principal", "entity_type": "PERSON"}]
    content = main_page_content("Throne of Glass", "Sarah J. Maas", pages, labels)
    assert "== Synopsis ==" not in content
