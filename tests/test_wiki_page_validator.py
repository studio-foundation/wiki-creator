import json
import pytest
from scripts.wiki_page_validator import (
    parse_payload,
    check_language_fr,
    check_epub_ids,
    check_infobox_keys,
    check_series_anchor,
    check_forbidden_series,
    check_forbidden_names,
    check_identity_match,
    check_references_book_title,
    validate_page,
    build_feedback,
)


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


def test_check_epub_ids_detects_xhtml():
    page = {"content": "mentionné dans C07.xhtml pour la première fois."}
    assert check_epub_ids(page) != []


def test_check_epub_ids_passes_clean():
    page = {"content": "Celaena est introduite au chapitre 7."}
    assert check_epub_ids(page) == []


def test_check_infobox_keys_detects_prefixed():
    page = {"infobox_fields": {"- Statut": "Assassine", "Titre": "Champion"}}
    assert check_infobox_keys(page) != []


def test_check_infobox_keys_passes_clean():
    page = {"infobox_fields": {"Statut": "Assassine"}}
    assert check_infobox_keys(page) == []


def test_check_series_anchor_detects_missing():
    page = {"content": "Celaena est une assassine redoutable."}
    meta = {"series": "Throne of Glass"}
    errors = check_series_anchor(page, meta)
    assert any("série" in e.lower() for e in errors)


def test_check_series_anchor_passes_present():
    page = {"content": "Celaena Sardothien est un personnage principal de Throne of Glass."}
    meta = {"series": "Throne of Glass"}
    assert check_series_anchor(page, meta) == []


def test_check_forbidden_series_detects_keyword():
    page = {"content": "Celaena est un personnage de Kingkiller Chronicle.", "infobox_fields": {}}
    meta = {"forbidden_series": ["Kingkiller Chronicle", "The Selection"]}
    errors = check_forbidden_series(page, meta)
    assert any("Kingkiller" in e for e in errors)


def test_check_forbidden_series_checks_infobox_too():
    page = {"content": "Texte propre.", "infobox_fields": {"Série": "The Selection"}}
    meta = {"forbidden_series": ["The Selection"]}
    errors = check_forbidden_series(page, meta)
    assert errors != []


def test_check_forbidden_series_passes_clean():
    page = {"content": "Celaena est une assassine de Throne of Glass.", "infobox_fields": {}}
    meta = {"forbidden_series": ["Kingkiller Chronicle"]}
    assert check_forbidden_series(page, meta) == []


def test_check_forbidden_series_empty_list():
    page = {"content": "N'importe quel contenu.", "infobox_fields": {}}
    meta = {}
    assert check_forbidden_series(page, meta) == []


def test_check_forbidden_names_detects_in_content():
    page = {"content": "Celaena, aussi connue sous le nom d'Aelin Galathynius.", "infobox_fields": {}}
    meta = {"forbidden_names": ["Aelin Galathynius"]}
    errors = check_forbidden_names(page, meta)
    assert any("Aelin Galathynius" in e for e in errors)


def test_check_forbidden_names_detects_in_infobox():
    page = {"content": "Texte propre.", "infobox_fields": {"alias": "Aelin"}}
    meta = {"forbidden_names": ["Aelin"]}
    errors = check_forbidden_names(page, meta)
    assert errors != []


def test_check_forbidden_names_passes_clean():
    page = {"content": "Celaena Sardothien est une assassine.", "infobox_fields": {}}
    meta = {"forbidden_names": ["Aelin Galathynius"]}
    assert check_forbidden_names(page, meta) == []


def test_check_forbidden_names_empty_config():
    page = {"content": "N'importe quel contenu.", "infobox_fields": {}}
    meta = {}
    assert check_forbidden_names(page, meta) == []


def test_validate_page_returns_valid_when_clean():
    page = {
        "title": "Celaena",
        "importance": "principal",
        "entity_type": "PERSON",
        "infobox_fields": {"Statut": "Assassine"},
        "content": "Celaena Sardothien est l'héroïne de Throne of Glass.",
    }
    meta = {"series": "Throne of Glass", "forbidden_series": []}
    result = validate_page(page, meta)
    assert result["valid"] is True
    assert result["errors"] == []


def test_validate_page_aggregates_all_errors():
    page = {
        "title": "Elena",
        "importance": "secondaire",
        "entity_type": "PERSON",
        "infobox_fields": {},
        "content": "Elena was the queen. She is also known as Philippa. C07.xhtml.",
    }
    meta = {"series": "Throne of Glass", "forbidden_series": ["Kingkiller"]}
    result = validate_page(page, meta)
    assert result["valid"] is False
    assert len(result["errors"]) >= 2


def test_build_feedback_formats_instructions():
    errors = ["❌ Langue anglaise", "❌ ID EPUB"]
    feedback = build_feedback(errors)
    assert "Langue anglaise" in feedback
    assert "corrige" in feedback.lower() or "régénère" in feedback.lower()


def test_check_references_book_title_passes_correct_title():
    page = {"content": "## Biographie\nTexte.\n\n## Références\n- *Throne of Glass* de Sarah J. Maas\n"}
    assert check_references_book_title(page, ["Throne of Glass"]) == []


def test_check_references_book_title_detects_wrong_title():
    page = {"content": "## Biographie\nTexte.\n\n## Références\n- *La Colonne de feu* de Sarah J. Maas\n"}
    errors = check_references_book_title(page, ["Throne of Glass"])
    assert any("La Colonne de feu" in e for e in errors)


def test_check_references_book_title_no_section_passes():
    page = {"content": "## Biographie\nTexte sans références.\n"}
    assert check_references_book_title(page, ["Throne of Glass"]) == []


def test_check_references_book_title_no_italics_passes():
    page = {"content": "## Références\nVoir le livre source.\n"}
    assert check_references_book_title(page, ["Throne of Glass"]) == []


def test_check_references_book_title_multi_book_passes():
    page = {"content": "## Références\n- *Tome 1* et *Tome 2*\n"}
    assert check_references_book_title(page, ["Tome 1", "Tome 2"]) == []


def test_check_references_book_title_underscore_italics():
    page = {"content": "## Références\n- _Mauvais Titre_\n"}
    errors = check_references_book_title(page, ["Throne of Glass"])
    assert any("Mauvais Titre" in e for e in errors)


def test_validate_page_catches_wrong_references_title(tmp_path):
    """validate_page catches unauthorized title in Références when file_path resolves."""
    # Fake epub_data.json at the right path
    processing_dir = tmp_path / "processing_output" / "01-mybook"
    processing_dir.mkdir(parents=True)
    (processing_dir / "epub_data.json").write_text('{"title": "My Book"}', encoding="utf-8")

    # Fake epub path that book_paths_from_epub can derive a slug from
    epub_path = tmp_path / "books" / "01-mybook.epub"
    epub_path.parent.mkdir(parents=True)
    epub_path.touch()

    page = {
        "title": "Hero",
        "importance": "principal",
        "entity_type": "PERSON",
        "infobox_fields": {},
        "content": "Hero est un personnage de My Book.\n\n## Références\n- *Wrong Title*\n",
    }
    meta = {
        "file_path": str(epub_path),
        "series": "My Book",
        "forbidden_series": [],
    }
    result = validate_page(page, meta)
    assert result["valid"] is False
    assert any("Wrong Title" in e for e in result["errors"])


def test_validate_page_skips_references_check_when_no_file_path():
    """validate_page does not crash and skips the check when file_path is missing."""
    page = {
        "title": "Hero",
        "importance": "principal",
        "entity_type": "PERSON",
        "infobox_fields": {},
        "content": "Hero est un personnage de My Book.\n\n## Références\n- *Any Title*\n",
    }
    meta = {"series": "My Book", "forbidden_series": []}
    result = validate_page(page, meta)
    assert "valid" in result  # no crash, check was skipped


def test_validate_page_skips_references_check_when_title_empty(tmp_path):
    """validate_page skips the references check when epub_data.json has no title."""
    processing_dir = tmp_path / "processing_output" / "01-mybook"
    processing_dir.mkdir(parents=True)
    (processing_dir / "epub_data.json").write_text('{"title": ""}', encoding="utf-8")

    epub_path = tmp_path / "books" / "01-mybook.epub"
    epub_path.parent.mkdir(parents=True)
    epub_path.touch()

    page = {
        "title": "Hero",
        "importance": "principal",
        "entity_type": "PERSON",
        "infobox_fields": {},
        "content": "Hero est un personnage de My Book.\n\n## Références\n- *Any Title*\n",
    }
    meta = {
        "file_path": str(epub_path),
        "series": "My Book",
        "forbidden_series": [],
    }
    # Empty title → check skipped → no references error
    result = validate_page(page, meta)
    assert not any("Titre non autorisé" in e for e in result.get("errors", []))


# --- Language gate (A4) ---


def test_language_gate_skips_fr_check_for_english_book():
    page = {"title": "Elias", "importance": "principal", "entity_type": "PERSON",
            "infobox_fields": {}, "content": "Elias is the captain. He was a sailor."}
    result = validate_page(page, {"language": "en"})
    assert not any("anglais" in e for e in result["errors"])


def test_language_gate_defaults_to_fr():
    page = {"title": "Elias", "importance": "principal", "entity_type": "PERSON",
            "infobox_fields": {}, "content": "Elias is the captain. He was a sailor."}
    result = validate_page(page, {})
    assert any("anglais" in e for e in result["errors"])


def test_language_gate_explicit_fr_still_checks():
    page = {"title": "Elias", "importance": "principal", "entity_type": "PERSON",
            "infobox_fields": {}, "content": "Elias is the captain."}
    result = validate_page(page, {"language": "fr"})
    assert any("anglais" in e for e in result["errors"])


# --- Identity grounding v1 (A5) ---


def test_identity_match_passes_exact_title():
    page = {"title": "Celaena Sardothien", "infobox_fields": {"nom": "Celaena Sardothien"}}
    assert check_identity_match(page, {"title": "Celaena Sardothien"}) == []


def test_identity_match_passes_containment_both_ways():
    page = {"title": "Celaena", "infobox_fields": {"nom": "Celaena Sardothien"}}
    assert check_identity_match(page, {"title": "Celaena Sardothien"}) == []
    page2 = {"title": "Celaena Sardothien", "infobox_fields": {}}
    assert check_identity_match(page2, {"title": "Celaena"}) == []


def test_identity_match_detects_wrong_infobox_name():
    # Real regression from run 15: page 'Verin' with infobox nom='Kaltain'
    page = {"title": "Verin", "infobox_fields": {"nom": "Kaltain"}}
    errors = check_identity_match(page, {"title": "Verin"})
    assert any("Kaltain" in e for e in errors)


def test_identity_match_detects_title_drift():
    # Real regression from run 15: entity 'Philippa' titled 'Philippe'
    page = {"title": "Philippe", "infobox_fields": {}}
    errors = check_identity_match(page, {"title": "Philippa"})
    assert any("Philippe" in e for e in errors)


def test_identity_match_accent_insensitive():
    page = {"title": "Néhémia", "infobox_fields": {"nom": "Nehemia Ytger"}}
    assert check_identity_match(page, {"title": "Nehemia"}) == []


def test_identity_match_ignores_non_identity_infobox_keys():
    page = {"title": "Celaena", "infobox_fields": {"allégeance": "Adarlan", "statut": "vivante"}}
    assert check_identity_match(page, {"title": "Celaena"}) == []


def test_identity_match_skips_without_expected_title():
    page = {"title": "Anything", "infobox_fields": {"nom": "Someone Else"}}
    assert check_identity_match(page, {}) == []


def test_validate_page_includes_identity_errors():
    page = {"title": "Verin", "importance": "secondary", "entity_type": "PERSON",
            "infobox_fields": {"nom": "Kaltain"}, "content": "Texte en français correct."}
    result = validate_page(page, {"title": "Verin", "language": "fr"})
    assert result["valid"] is False
    assert any("Kaltain" in e for e in result["errors"])
