"""Tests for scripts/parse_epub.py."""
import json
import subprocess
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_parse_epub_missing_file_path():
    """Missing file_path → error JSON + exit 1."""
    result = subprocess.run(
        [sys.executable, "scripts/parse_epub.py"],
        input=json.dumps({}),
        capture_output=True,
        text=True,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    )
    output = json.loads(result.stdout)
    assert "error" in output
    assert result.returncode == 1


def test_parse_epub_module_imports():
    """parse_epub module can be imported and parse_epub function exists."""
    from scripts.parse_epub import parse_epub
    assert callable(parse_epub)


from scripts.parse_epub import clean_chapter_text


def test_clean_isolated_newline_replaced_by_space():
    """Single \\n inside text → space (A. C.\\nVidal becomes A. C. Vidal)."""
    assert clean_chapter_text("A. C.\nVidal") == "A. C. Vidal"


def test_clean_isolated_newline_mid_word():
    """Single \\n mid-word → space (I\\nntéressant becomes I ntéressant)."""
    assert clean_chapter_text("I\nntéressant") == "I ntéressant"


def test_clean_double_newline_preserved():
    """Double \\n\\n (paragraph break) is preserved."""
    result = clean_chapter_text("Paragraph one.\n\nParagraph two.")
    assert result == "Paragraph one.\n\nParagraph two."


def test_clean_multiple_spaces_normalized():
    """Multiple consecutive spaces → single space."""
    assert clean_chapter_text("hello   world") == "hello world"


def test_clean_leading_trailing_whitespace_stripped():
    """Leading/trailing whitespace stripped."""
    assert clean_chapter_text("  hello world  ") == "hello world"


def test_clean_html_entities_amp():
    """&amp; is unescaped to &."""
    assert clean_chapter_text("AT&amp;T") == "AT&T"


def test_clean_html_mdash():
    """&mdash; is unescaped to the em dash character."""
    result = clean_chapter_text("word&mdash;word")
    assert "\u2014" in result  # em dash U+2014


def test_clean_html_nbsp_handled():
    """&nbsp; est converti en espace standard (pas en \\xa0)."""
    result = clean_chapter_text("hello&nbsp;world")
    assert "&nbsp;" not in result
    assert "\xa0" not in result  # doit être normalisé, pas laissé comme \xa0
    assert result == "hello world"


def test_clean_xa0_normalized_to_space():
    """\\xa0 brut (non-breaking space) est normalisé en espace standard."""
    assert clean_chapter_text("M.\xa0Martín") == "M. Martín"
    assert clean_chapter_text("Mme\xa0Vidal") == "Mme Vidal"


def test_short_chapter_filtered(tmp_path):
    """Chapters with fewer than 100 chars of content are excluded from output."""
    import ebooklib
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_title("Test Book")
    book.set_language("fr")

    short_item = epub.EpubHtml(uid="short", title="Short", file_name="short.xhtml", lang="fr")
    short_item.set_content(b"<html><body><p>Court.</p></body></html>")

    long_item = epub.EpubHtml(uid="long", title="Long", file_name="long.xhtml", lang="fr")
    long_content = "<html><body><p>" + "A" * 150 + "</p></body></html>"
    long_item.set_content(long_content.encode())

    book.add_item(short_item)
    book.add_item(long_item)
    book.spine = [("short", True), ("long", True)]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    epub_path = str(tmp_path / "test.epub")
    epub.write_epub(epub_path, book)

    from scripts.parse_epub import parse_epub
    result = parse_epub(epub_path)

    assert len(result["chapters"]) == 1, f"Expected 1 chapter, got {len(result['chapters'])}"
    assert "A" * 100 in result["chapters"][0]["content"], "Long chapter content missing"


def test_parse_epub_content_is_cleaned(tmp_path):
    """Chapter content returned by parse_epub has isolated \\n replaced by spaces."""
    import ebooklib
    from ebooklib import epub
    import re

    book = epub.EpubBook()
    book.set_title("Test Book")
    book.set_language("fr")

    item = epub.EpubHtml(uid="chap", title="Chapter", file_name="chap.xhtml", lang="fr")
    # Multiple <p> tags: BS4's get_text(separator="\\n") will insert \\n between them.
    # After clean_chapter_text, those isolated \\n become spaces.
    # Total content long enough to pass the 100-char filter.
    sentences = ["Sentence " + str(i) + " with some words." for i in range(10)]
    p_tags = "".join(f"<p>{s}</p>" for s in sentences)
    content = f"<html><body>{p_tags}</body></html>"
    item.set_content(content.encode())

    book.add_item(item)
    book.spine = [("chap", True)]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    epub_path = str(tmp_path / "test.epub")
    epub.write_epub(epub_path, book)

    from scripts.parse_epub import parse_epub
    result = parse_epub(epub_path)

    assert len(result["chapters"]) == 1
    ch_content = result["chapters"][0]["content"]
    # If clean_chapter_text ran, isolated \\n are gone
    assert not re.search(r'(?<!\n)\n(?!\n)', ch_content), \
        "Isolated \\n found — clean_chapter_text was not applied"
    # Sanity: content is not empty and has actual text
    assert "Sentence" in ch_content
