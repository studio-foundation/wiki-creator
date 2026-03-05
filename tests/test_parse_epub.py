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
    """&nbsp; is unescaped by html.unescape (becomes \\u00a0, non-breaking space)."""
    result = clean_chapter_text("hello&nbsp;world")
    # html.unescape converts &nbsp; to \u00a0, which is acceptable
    assert "&nbsp;" not in result  # the raw entity is gone
    assert "hello" in result and "world" in result
