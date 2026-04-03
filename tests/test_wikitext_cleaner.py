import pytest
from wiki_creator.wikitext_cleaner import clean_wikitext, normalize_infobox_fields


class TestCleanWikitext:
    def test_strip_categories(self):
        text = "Some text.\n[[Category:Characters]]\n[[Category:Alive]]"
        assert clean_wikitext(text) == "Some text."

    def test_strip_gallery(self):
        text = "Before.\n<gallery expand=\"true\">\nimage.png\n</gallery>\nAfter."
        assert clean_wikitext(text) == "Before.\nAfter."

    def test_strip_templates(self):
        text = "Text {{stub}} here."
        assert clean_wikitext(text) == "Text  here."

    def test_strip_references_tag(self):
        text = "Text.\n<references/>\nMore."
        assert clean_wikitext(text) == "Text.\nMore."

    def test_convert_bold(self):
        text = "'''Abraxos''' is a wyvern."
        assert clean_wikitext(text) == "**Abraxos** is a wyvern."

    def test_convert_italic(self):
        text = "''Heir of Fire'' is a book."
        assert clean_wikitext(text) == "*Heir of Fire* is a book."

    def test_convert_link_with_text(self):
        text = "She is [[Manon Blackbeak|Manon]]'s wyvern."
        assert clean_wikitext(text) == "She is Manon's wyvern."

    def test_convert_link_plain(self):
        text = "A [[wyvern]] of great power."
        assert clean_wikitext(text) == "A wyvern of great power."

    def test_remove_empty_sections(self):
        text = "## Biography\nSome text.\n\n### ''Queen of Shadows''\n\n### ''Kingdom of Ash''\nMore text."
        result = clean_wikitext(text)
        assert "### *Queen of Shadows*" not in result
        assert "More text." in result

    def test_strip_file_links(self):
        text = "[[File:Image.png|thumb|Caption]]\nText."
        assert clean_wikitext(text) == "Text."

    def test_full_cleanup(self):
        text = (
            "'''Abraxos''' is [[Manon Blackbeak|Manon]]'s [[wyvern]].\n\n"
            "## Biography\n\nHe was a bait beast.\n\n"
            "### ''Queen of Shadows''\n\n"
            "### ''Kingdom of Ash''\n\nHe fought.\n\n"
            "## Gallery\n<gallery>\nimage.png\n</gallery>\n\n"
            "## References\n<references/>\n\n"
            "[[Category:Characters]]"
        )
        result = clean_wikitext(text)
        assert result.startswith("**Abraxos** is Manon's wyvern.")
        assert "[[Category" not in result
        assert "<gallery>" not in result
        assert "Queen of Shadows" not in result
        assert "He fought." in result


class TestNormalizeInfoboxFields:
    def test_rename_english_keys(self):
        fields = {"name": "Abraxos", "allegiance": "Manon", "status": "Alive"}
        result = normalize_infobox_fields(fields)
        assert result == {"nom": "Abraxos", "affiliation": "Manon", "statut": "Alive"}

    def test_drop_image_fields(self):
        fields = {"name": "Abraxos", "image": "photo.jpg", "caption": "A wyvern"}
        result = normalize_infobox_fields(fields)
        assert result == {"nom": "Abraxos"}

    def test_passthrough_unknown_keys(self):
        fields = {"species": "Wyvern", "origin": "Morath"}
        result = normalize_infobox_fields(fields)
        assert result == {"species": "Wyvern", "origin": "Morath"}

    def test_drop_collapse_fields(self):
        fields = {"affcollapse": "off", "statcollapse": "off", "name": "X"}
        result = normalize_infobox_fields(fields)
        assert result == {"nom": "X"}

    def test_strip_wiki_markup_in_values(self):
        fields = {"partner": "[[Narene]] (mate)"}
        result = normalize_infobox_fields(fields)
        assert result == {"partner": "Narene (mate)"}

    def test_empty_input(self):
        assert normalize_infobox_fields({}) == {}
