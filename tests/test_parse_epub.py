"""Tests for scripts/parse_epub.py."""
import json
import subprocess
import sys
import os
from pathlib import Path

import pytest


def _write_epub(path: Path, title: str) -> None:
    """Minimal readable EPUB: one chapter over MIN_CHAPTER_CHARS."""
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier(title)
    book.set_title(title)
    book.set_language("en")
    chapter = epub.EpubHtml(title="One", file_name="ch1.xhtml", lang="en")
    chapter.content = "<html><body><h1>One</h1><p>" + ("word " * 60) + "</p></body></html>"
    book.add_item(chapter)
    book.toc = (chapter,)
    book.spine = [chapter]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    path.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(path), book)


def _run_parse(file_path: Path) -> dict:
    result = subprocess.run(
        [sys.executable, "scripts/parse_epub.py"],
        input=json.dumps({"additional_context": f"file_path: {file_path}\nlanguage: en\n"}),
        capture_output=True,
        text=True,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_parse_epub_reads_the_source_the_canon_declares(tmp_path):
    """STU-512 wiring: canon.yaml decides which file the stage reads, not file_path.

    file_path anchors identity; the canon declares a different file for the same
    tome. Unwire resolve_book_source in main() and this test fails.
    """
    series = tmp_path / "library" / "author" / "series"
    anchor = series / "books" / "01-book.epub"
    _write_epub(anchor, "DECOY — file_path won")
    _write_epub(series / "books" / "canonical.epub", "CANON SOURCE")
    (series / "canon.yaml").write_text(
        "canon:\n"
        "  primary_source: epub\n"
        "  sources:\n"
        "    - id: canonical\n"
        "      type: epub\n"
        "      book: 01-book\n"
        "      path: books/canonical.epub\n",
        encoding="utf-8",
    )

    assert _run_parse(anchor)["title"] == "CANON SOURCE"


def test_parse_epub_without_canon_reads_file_path(tmp_path):
    """No canon.yaml → historical behavior, byte-identical."""
    anchor = tmp_path / "library" / "author" / "series" / "books" / "01-book.epub"
    _write_epub(anchor, "THE ONLY SOURCE")
    assert _run_parse(anchor)["title"] == "THE ONLY SOURCE"


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
    """A single \\n is a separator, not a word boundary: it becomes a space.

    Word-splitting inline markup is rejoined upstream by _flatten_inline_markup,
    so clean_chapter_text never sees a fragment (STU-519).
    """
    assert clean_chapter_text("I\nntéressant") == "I ntéressant"


def test_clean_carriage_return_is_whitespace_not_text():
    """A \\r reaches here from a &#13; charref, resolved by html.parser (STU-531).

    Six of the sixteen library books ship &#13;; Eragon puts one between the two
    words of a chapter title, which used to come out as 'PALANCAR\\r VALLEY'.
    """
    assert clean_chapter_text("PALANCAR\r\n VALLEY") == "PALANCAR VALLEY"
    assert clean_chapter_text("one\rtwo") == "one two"
    assert "\r" not in _text_of("<p>Title&#13;\n Subtitle</p>")


def test_chapter_text_carries_paragraph_structure():
    """Block boundaries survive extraction as \\n\\n (STU-523)."""
    body = "<p>Paragraph one.</p><p>Paragraph two.</p>"
    assert _text_of(body) == "Paragraph one.\n\nParagraph two."


def test_paragraph_break_is_one_blank_line_however_deep_the_nesting():
    """A <p> inside a <div> marks two boundaries at the same spot — one break."""
    body = "<div><p>One.</p></div><div><p>Two.</p></div>"
    assert _text_of(body) == "One.\n\nTwo."


def test_headings_and_list_items_are_paragraph_boundaries():
    body = "<h1>Title</h1><ul><li>First</li><li>Second</li></ul><blockquote>Quote</blockquote>"
    assert _text_of(body) == "Title\n\nFirst\n\nSecond\n\nQuote"


def test_br_is_a_soft_break_not_a_paragraph_break():
    """<br> separates verse lines inside one paragraph; it stays a space."""
    body = "<p>Roses are red<br/>Violets are blue</p><p>Next paragraph.</p>"
    assert _text_of(body) == "Roses are red Violets are blue\n\nNext paragraph."


def test_source_whitespace_inside_a_paragraph_is_not_a_paragraph_break():
    """Pretty-printed XHTML puts blank lines anywhere; only markup marks breaks."""
    body = "<p>One half\n\n   of a sentence.</p>\n\n\n<p>Next.</p>"
    assert _text_of(body) == "One half of a sentence.\n\nNext."


def test_paragraph_mark_never_survives_into_the_output():
    from scripts.parse_epub import _PARAGRAPH_MARK
    assert _PARAGRAPH_MARK not in _text_of("<p>One.</p><div><p>Two.</p></div>")


def test_clean_multiple_spaces_normalized():
    """Multiple consecutive spaces → single space."""
    assert clean_chapter_text("hello   world") == "hello world"


def test_clean_leading_trailing_whitespace_stripped():
    """Leading/trailing whitespace stripped."""
    assert clean_chapter_text("  hello world  ") == "hello world"


def test_html_entities_are_resolved_by_the_parser():
    """html.parser resolves charrefs at parse time (convert_charrefs default).

    clean_chapter_text therefore never saw an entity — its own html.unescape()
    call was unreachable. &nbsp; still arrives as \\xa0 and needs normalizing.
    """
    result = _text_of("<p>AT&amp;T word&mdash;word hello&nbsp;world</p>")
    assert result == "AT&T word\u2014word hello world"
    assert "\xa0" not in result


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


def test_short_chapter_filter_ignores_paragraph_structure(tmp_path):
    """The 100-char bar measures prose, not \\n\\n (STU-523).

    Ten 9-char paragraphs: 99 chars of prose, but 108 once the nine breaks are
    counted. Counting them lets a page clear the bar on structure alone — which
    is exactly how seven boilerplate pages entered 01_eragon.epub at 99 -> 107.
    """
    from ebooklib import epub
    from scripts.parse_epub import parse_epub

    book = epub.EpubBook()
    book.set_title("Test Book")
    book.set_language("en")

    item = epub.EpubHtml(uid="chap", title="Chapter", file_name="chap.xhtml", lang="en")
    paragraphs = ["Copyright"] * 10
    item.set_content(f"<html><body>{''.join(f'<p>{p}</p>' for p in paragraphs)}</body></html>".encode())

    book.add_item(item)
    book.spine = [("chap", True)]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    epub_path = str(tmp_path / "test.epub")
    epub.write_epub(epub_path, book)

    assert parse_epub(epub_path)["chapters"] == []


def test_parse_epub_preserves_paragraph_breaks(tmp_path):
    """The STU-523 contract, asserted on a real EPUB rather than a synthetic string.

    Held only at the markup level, this contract rotted undetected for the whole
    life of the old clean_chapter_text paragraph steps.
    """
    from ebooklib import epub
    from scripts.parse_epub import parse_epub

    book = epub.EpubBook()
    book.set_title("Test Book")
    book.set_language("en")

    item = epub.EpubHtml(uid="chap", title="Chapter", file_name="chap.xhtml", lang="en")
    paragraphs = [f"Paragraph {i} runs long enough to clear the chapter filter." for i in range(5)]
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    item.set_content(f"<html><body><h1>Chapter One</h1>{body}</body></html>".encode())

    book.add_item(item)
    book.spine = [("chap", True)]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    epub_path = str(tmp_path / "test.epub")
    epub.write_epub(epub_path, book)

    content = parse_epub(epub_path)["chapters"][0]["content"]
    assert content.split("\n\n") == ["Chapter One", *paragraphs]


def _text_of(body: str) -> str:
    """Run the parse_epub text pipeline over one chapter body, as parse_epub does."""
    from bs4 import BeautifulSoup
    from scripts.parse_epub import (
        _flatten_inline_markup,
        _mark_paragraph_breaks,
        _merge_block_dropcaps,
    )

    soup = BeautifulSoup(f"<html><body>{body}</body></html>", "html.parser")
    _flatten_inline_markup(soup)
    _merge_block_dropcaps(soup)
    _mark_paragraph_breaks(soup)
    return clean_chapter_text(soup.get_text(separator="\n", strip=True))


def test_flatten_inline_markup_rejoins_dropcap_span(tmp_path):
    """A dropcap letter in its own span belongs to the word that follows (STU-519).

    Markup copied from a-cruel-and-fated-light.epub: the dropcap and the rest of
    the word are sibling spans, which get_text(separator="\\n") would split.
    """
    body = (
        '<p class="p_CIT"><span class="f_dropcapital">M</span>'
        '<span class="f_ITAL">ove</span>'
        '<span class="f_CIT">, screamed a voice.</span></p>'
    )
    assert _text_of(body) == "Move, screamed a voice."


def test_flatten_inline_markup_rejoins_small_caps_heading():
    """Small-caps chapter openers split the same way (01_eragon.epub)."""
    body = '<h1 class="chapter">D<span class="small1">ISCOVERY</span></h1>'
    assert _text_of(body) == "DISCOVERY"


def test_flatten_inline_markup_keeps_block_level_boundaries():
    """Flattening inline markup must not glue adjacent block elements together."""
    body = "<p>First paragraph ends here</p><p>Second paragraph starts here</p>"
    assert _text_of(body) == "First paragraph ends here\n\nSecond paragraph starts here"


def test_merge_block_dropcaps_rejoins_a_dropcap_in_its_own_block():
    """A dropcap can be its own <p>, not its own <span> (STU-532).

    Markup copied from 00-the_hobbit.epub, whose opening sentence is typeset this
    way. _flatten_inline_markup cannot reach it: the split is between two blocks.
    """
    body = '<p class="calibre4">I</p>\n<p class="calibre4">n a hole there lived a hobbit.</p>'
    assert _text_of(body) == "In a hole there lived a hobbit."


def test_merge_block_dropcaps_joins_without_a_space():
    body = "<p>W</p><p>ord</p>"
    assert _text_of(body) == "Word"


def test_merge_block_dropcaps_leaves_a_lone_capital_before_a_real_sentence():
    """The next block resuming with a capital means two real paragraphs.

    Without this gate the pass would weld any one-letter paragraph — a section
    divider, a list label — onto its neighbour, which is how STU-519's deleted
    regex produced 7361 bogus tokens.
    """
    body = "<p>A</p><p>Silvery cloud drifted past.</p>"
    assert _text_of(body) == "A\n\nSilvery cloud drifted past."


def test_merge_block_dropcaps_ignores_a_multi_letter_block():
    body = "<p>To</p><p>morrow never came.</p>"
    assert _text_of(body) == "To\n\nmorrow never came."


def test_merge_block_dropcaps_ignores_a_spacer_paragraph():
    """The Hobbit puts an &nbsp;-only <p> right before the dropcap."""
    body = '<p>Chapter title</p><p>\xa0</p><p>I</p><p>n a hole there lived a hobbit.</p>'
    assert _text_of(body) == "Chapter title\n\nIn a hole there lived a hobbit."


def test_merge_block_dropcaps_handles_a_dropcap_still_wrapped_in_a_span():
    """Runs after _flatten_inline_markup, so the span is already gone."""
    body = '<p class="dc"><span class="initial">I</span></p><p>n a hole there lived a hobbit.</p>'
    assert _text_of(body) == "In a hole there lived a hobbit."


def test_parse_epub_flattens_inline_markup(tmp_path):
    """parse_epub wires _flatten_inline_markup in before extracting text."""
    from ebooklib import epub
    from scripts.parse_epub import parse_epub

    book = epub.EpubBook()
    book.set_title("Test Book")
    book.set_language("en")

    item = epub.EpubHtml(uid="chap", title="Chapter", file_name="chap.xhtml", lang="en")
    body = '<h1>D<span class="small1">ISCOVERY</span></h1><p>' + "Padding. " * 30 + "</p>"
    item.set_content(f"<html><body>{body}</body></html>".encode())

    book.add_item(item)
    book.spine = [("chap", True)]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    epub_path = str(tmp_path / "test.epub")
    epub.write_epub(epub_path, book)

    content = parse_epub(epub_path, language="en")["chapters"][0]["content"]
    assert content.startswith("DISCOVERY")


def _three_chapter_epub(tmp_path):
    import ebooklib  # noqa: F401
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_title("Test Book")
    book.set_language("fr")
    spine = []
    for i in range(1, 4):
        uid = f"ch{i}"
        item = epub.EpubHtml(uid=uid, title=f"Chapter {i}", file_name=f"{uid}.xhtml", lang="fr")
        item.set_content(("<html><body><p>" + f"Chapitre {i}. " * 30 + "</p></body></html>").encode())
        book.add_item(item)
        spine.append((uid, True))
    book.spine = spine
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    path = str(tmp_path / "test.epub")
    epub.write_epub(path, book)
    return path


def test_parse_epub_max_chapters_truncates(tmp_path):
    """max_chapters keeps only the first N chapters (subset test runs)."""
    from scripts.parse_epub import parse_epub
    epub_path = _three_chapter_epub(tmp_path)
    assert len(parse_epub(epub_path)["chapters"]) == 3
    result = parse_epub(epub_path, max_chapters=2)
    assert len(result["chapters"]) == 2
    assert [c["id"] for c in result["chapters"]] == ["ch1", "ch2"]


def test_parse_epub_max_chapters_none_and_zero_keep_all(tmp_path):
    """None or a non-positive cap is a no-op — the full book is parsed."""
    from scripts.parse_epub import parse_epub
    epub_path = _three_chapter_epub(tmp_path)
    assert len(parse_epub(epub_path, max_chapters=None)["chapters"]) == 3
    assert len(parse_epub(epub_path, max_chapters=0)["chapters"]) == 3


def test_env_max_chapters(monkeypatch):
    """WIKI_MAX_CHAPTERS parsing: absent/empty/<=0 → None, positive → int."""
    from scripts.parse_epub import _env_max_chapters
    monkeypatch.delenv("WIKI_MAX_CHAPTERS", raising=False)
    assert _env_max_chapters() is None
    monkeypatch.setenv("WIKI_MAX_CHAPTERS", "")
    assert _env_max_chapters() is None
    monkeypatch.setenv("WIKI_MAX_CHAPTERS", "0")
    assert _env_max_chapters() is None
    monkeypatch.setenv("WIKI_MAX_CHAPTERS", "-1")
    assert _env_max_chapters() is None
    monkeypatch.setenv("WIKI_MAX_CHAPTERS", "3")
    assert _env_max_chapters() == 3


def test_clean_keeps_one_letter_words_separate():
    """A one-letter word followed by a real word is never merged (STU-519).

    The old lettrine regex collapsed "A silvery" → "Asilvery", a plausible-looking
    toponym the NER then tagged as a PLACE. Dropcaps are rejoined at the HTML level
    instead — see test_parse_epub_dropcap_span_rejoins_its_word.
    """
    assert clean_chapter_text("A silvery cloud drifted") == "A silvery cloud drifted"
    assert clean_chapter_text("A brooding mist") == "A brooding mist"
    assert clean_chapter_text("A hunting knife") == "A hunting knife"
    assert clean_chapter_text("I would go") == "I would go"


def test_clean_unicode_nfc_normalization():
    """Decomposed Unicode (NFD) characters are normalized to NFC."""
    import unicodedata
    # 'é' as NFD (e + combining acute accent) should become NFC 'é'
    nfd_text = unicodedata.normalize('NFD', "héros")
    assert len(nfd_text) > len("héros")  # NFD has more codepoints
    assert clean_chapter_text(nfd_text) == "héros"


def test_clean_ligature_fi():
    """Typographic ﬁ ligature is resolved to 'fi'."""
    assert clean_chapter_text("ﬁction") == "fiction"


def test_clean_ligature_fl():
    """Typographic ﬂ ligature is resolved to 'fl'."""
    assert clean_chapter_text("ﬂeur") == "fleur"


def test_clean_ligature_ff():
    """Typographic ﬀ ligature is resolved to 'ff'."""
    assert clean_chapter_text("ﬀ") == "ff"


def test_clean_ligature_ffi():
    """Typographic ﬃ ligature is resolved to 'ffi'."""
    # "aﬃche" = a + ﬃ(ffi) + che → "affiche"
    assert clean_chapter_text("a\ufb03che") == "affiche"


def test_clean_apostrophe_typographique():
    """Typographic right single quotation mark is normalized to ASCII apostrophe."""
    assert clean_chapter_text("l\u2019ami") == "l'ami"
    assert clean_chapter_text("c\u2019est") == "c'est"


def test_clean_extended_apostrophe_variants():
    """Other apostrophe-like Unicode chars are normalized to ASCII apostrophe."""
    assert clean_chapter_text("I\u02bbll go") == "I'll go"
    assert clean_chapter_text("I\u2032ve seen it") == "I've seen it"


def test_clean_keeps_dialect_elision_intact():
    """A space before an elided-h word is the author's, not damage (STU-519).

    The old I-contraction repair rewrote Eldest's "I 'ope" (a character dropping
    his aitches) to "I'ope". Its only genuine target, Inheritance's "I 'll insult",
    was an inline-markup split now fixed by _flatten_inline_markup.
    """
    assert clean_chapter_text("But I 'ope you and the girl") == "But I 'ope you and the girl"
    assert clean_chapter_text("I'll go now.") == "I'll go now."


def test_clean_guillemets_normalisés():
    """French guillemets « » are normalized to double quotes."""
    assert clean_chapter_text("\u00abBonjour\u00bb") == '"Bonjour"'


def test_clean_keeps_a_grave_proper_nouns_intact():
    """A word starting with À is never split (STU-519).

    The old 'Àla' → 'À la' rule only ever undid step 5b's own damage; its one
    effect on real text was breaking "Plaza dels Àngels" into "À ngels".
    """
    assert clean_chapter_text("la Plaza dels Àngels, siège") == "la Plaza dels Àngels, siège"
    assert clean_chapter_text("À la maison") == "À la maison"


def test_clean_narrow_no_break_space():
    """Narrow no-break space (U+202F) is normalized to a regular space."""
    assert clean_chapter_text("10\u202fkm") == "10 km"


from scripts.parse_epub import detect_pov


def test_detect_pov_first_person_high_confidence():
    """Dense first-person pronouns → first_person, high confidence."""
    text = ("je marchais dans la rue. " * 20 +
            "Il faisait beau. " * 5)
    result = detect_pov(text)
    assert result["pov"] == "first_person"
    assert result["confidence"] == "high"
    assert result["first_person_count"] > 0
    assert result["total_tokens"] > 0


def test_detect_pov_first_person_medium_confidence():
    """Moderate first-person pronoun density → first_person, medium confidence."""
    text = ("je marchais. " * 7 + "Il faisait beau. " * 93)
    result = detect_pov(text)
    assert result["pov"] == "first_person"
    assert result["confidence"] == "medium"


def test_detect_pov_not_first_person():
    """No first-person pronouns → not first_person."""
    text = "Il marchait dans la rue. Elle regardait par la fenêtre. " * 50
    result = detect_pov(text)
    assert result["pov"] != "first_person"


def test_detect_pov_output_shape():
    """Output always has required keys."""
    result = detect_pov("Some text here.")
    assert "pov" in result
    assert "first_person_count" in result
    assert "total_tokens" in result
    assert "confidence" in result


def test_parse_epub_output_includes_pov_detection(tmp_path):
    """parse_epub() output includes pov_detection key."""
    import ebooklib
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_title("Test")
    book.set_language("fr")
    item = epub.EpubHtml(uid="ch1", title="Ch1", file_name="ch1.xhtml", lang="fr")
    content = "<html><body><p>" + ("je marchais dans la rue. " * 30) + "</p></body></html>"
    item.set_content(content.encode())
    book.add_item(item)
    book.spine = [("ch1", True)]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub_path = str(tmp_path / "test.epub")
    epub.write_epub(epub_path, book)

    from scripts.parse_epub import parse_epub
    result = parse_epub(epub_path)
    assert "pov_detection" in result
    assert result["pov_detection"]["pov"] == "first_person"


# --- Language-aware POV detection (cue_words-driven) ---


def test_detect_pov_english_first_person():
    text = "I walked to the harbor. My ship was waiting for me and I felt free. " * 5
    result = detect_pov(text, language="en")
    assert result["pov"] == "first_person"
    assert result["first_person_count"] > 0


def test_detect_pov_english_third_person_default_fr_misses():
    # The same English text analyzed with French vocabulary finds no
    # first-person markers — this documents why language must be threaded.
    text = "I walked to the harbor. My ship was waiting for me and I felt free. " * 5
    result = detect_pov(text)  # default fr
    # 'me' is shared between fr and en vocabularies; ratio stays below the
    # first-person threshold with fr pronouns only.
    assert result["first_person_count"] < detect_pov(text, language="en")["first_person_count"]


def test_detect_pov_english_thought_markers_third_limited():
    text = "The captain looked at the sea. He knew the storm would come. " * 3
    result = detect_pov(text, language="en")
    assert result["pov"] == "third_limited"


def test_detect_pov_unknown_language_raises_loudly():
    # An unsupported language fails loudly at the first stage (STU-451) rather
    # than silently detecting POV with English cue-words.
    from wiki_creator.lang import LangPackError

    with pytest.raises(LangPackError):
        detect_pov("Ein Schiff segelte über das Meer.", language="de")


from scripts.parse_epub import annotate_pov


def test_annotate_pov_persists_per_chapter_fields():
    """Each chapter gets its own pov + pov_confidence, not just the book modal."""
    chapters = [
        {"id": "c1", "content": "Je marche. Je pense donc je suis. Je regarde le ciel."},
        {"id": "c2", "content": "Le roi regarda la salle. Les gardes attendaient en silence."},
    ]
    modal = annotate_pov(chapters, language="fr")
    assert chapters[0]["pov"] == "first_person"
    assert chapters[0]["pov_confidence"] in {"high", "medium", "low"}
    assert "pov" in chapters[1] and "pov_confidence" in chapters[1]
    # Book-level modal is still returned with its historical shape.
    assert set(modal) == {"pov", "first_person_count", "total_tokens", "confidence"}


def test_annotate_pov_empty_chapters():
    """No chapters → omniscient modal, no crash."""
    assert annotate_pov([], language="fr")["pov"] == "omniscient"


from scripts.parse_epub import strip_gutenberg_boilerplate


def test_gutenberg_boilerplate_stripped_when_embedded_in_content_sections():
    """START/END markers sit inside content sections, not their own (STU-627).

    Header before START and footer after END leak `Project Gutenberg` /
    `United States` into extraction; only the text between the markers is the work.
    """
    chapters = [
        {"id": "c1", "content": (
            "The Project Gutenberg eBook of Alice.\n\n"
            "This ebook is for the use of anyone anywhere in the United States.\n\n"
            "*** START OF THE PROJECT GUTENBERG EBOOK ALICE ***\n\n"
            "CHAPTER I. Down the Rabbit-Hole"
        )},
        {"id": "c2", "content": "Alice was beginning to get very tired."},
        {"id": "c3", "content": (
            "THE END.\n\n"
            "*** END OF THE PROJECT GUTENBERG EBOOK ALICE ***\n\n"
            "Project Gutenberg is a registered trademark in the United States."
        )},
    ]
    result = strip_gutenberg_boilerplate(chapters)
    blob = "\n".join(ch["content"] for ch in result)
    assert "Project Gutenberg" not in blob
    assert "United States" not in blob
    assert result[0]["content"].startswith("CHAPTER I")
    assert result[-1]["content"] == "THE END."


def test_gutenberg_boilerplate_drops_whole_sections_outside_the_markers():
    """A boilerplate-only section before START / after END is dropped entirely."""
    chapters = [
        {"id": "c1", "content": "The Project Gutenberg license preamble, United States."},
        {"id": "c2", "content": "*** START OF THE PROJECT GUTENBERG EBOOK X ***"},
        {"id": "c3", "content": "The real story begins here and runs on."},
        {"id": "c4", "content": "*** END OF THE PROJECT GUTENBERG EBOOK X ***"},
        {"id": "c5", "content": "Full license text, Project Gutenberg, United States."},
    ]
    result = strip_gutenberg_boilerplate(chapters)
    assert [ch["id"] for ch in result] == ["c3"]


def test_gutenberg_stripper_is_noop_without_markers():
    """A non-Gutenberg source has no markers and is returned unchanged."""
    chapters = [
        {"id": "c1", "content": "Chapter one, no markers."},
        {"id": "c2", "content": "Chapter two."},
    ]
    result = strip_gutenberg_boilerplate(chapters)
    assert result == chapters


def test_gutenberg_start_marker_matches_this_variant_case_insensitively():
    """Older EPUBs write `START OF THIS PROJECT GUTENBERG EBOOK`, any case."""
    chapters = [
        {"id": "c1", "content": "*** start of this project gutenberg ebook y ***\n\nStory."},
    ]
    result = strip_gutenberg_boilerplate(chapters)
    assert result[0]["content"] == "Story."


from scripts.parse_epub import strip_inline_frontmatter


def test_inline_frontmatter_stripped_from_first_chapter():
    """A title page glued into the story's own chapter is dropped (STU-768).

    Peter Rabbit's Gutenberg "images" edition packs title/author/publisher/print
    info directly ahead of the story in the one spine item holding both — no
    chapter boundary to key `is_frontmatter_chapter` off. Every label line lacks a
    sentence terminal; the story is the first paragraph that has one, even when
    that terminal is a dash trailing into a list rather than a period.
    """
    chapters = [{"id": "c1", "content": (
        "THE TALE OF PETER RABBIT\n\nBY\n\nBEATRIX POTTER\n\nFREDERICK WARNE\n\n"
        "FREDERICK WARNE\n\nFirst published 1902\n\nFrederick Warne & Co., 1902\n\n"
        "Printed and bound in Great Britain by William Clowes Limited, Beccles and London\n\n"
        "Once upon a time there were four little Rabbits, and their names were—"
        "\n\nFlopsy, Mopsy, Cotton-tail, and Peter."
    )}]
    result = strip_inline_frontmatter(chapters)
    assert result[0]["content"] == (
        "Once upon a time there were four little Rabbits, and their names were—"
        "\n\nFlopsy, Mopsy, Cotton-tail, and Peter."
    )


def test_inline_frontmatter_noop_when_chapter_opens_on_prose():
    """A chapter that already opens with a real sentence is untouched."""
    chapters = [{"id": "c1", "content": "Alice was beginning to get very tired.\n\nShe sat by her sister."}]
    result = strip_inline_frontmatter(chapters)
    assert result == chapters


def test_inline_frontmatter_only_touches_the_first_chapter():
    """A title page is only ever glued to the start of a book, never mid-book."""
    chapters = [
        {"id": "c1", "content": "Alice was beginning to get very tired.\n\nShe sat by her sister."},
        {"id": "c2", "content": "BY\n\nSOME AUTHOR\n\nShe fell down the hole."},
    ]
    result = strip_inline_frontmatter(chapters)
    assert result[1]["content"] == "BY\n\nSOME AUTHOR\n\nShe fell down the hole."


def test_inline_frontmatter_gives_up_past_the_lookahead_cap():
    """A chapter that never hits a sentence terminal within the cap is left alone."""
    label_lines = "\n\n".join(f"LABEL {i}" for i in range(20))
    chapters = [{"id": "c1", "content": label_lines}]
    result = strip_inline_frontmatter(chapters)
    assert result == chapters


def test_inline_frontmatter_empty_chapters_list():
    assert strip_inline_frontmatter([]) == []


# --- Splitting a many-chapter spine item at TOC fragment anchors (STU-727) ---


def _packed_epub(tmp_path, *, wrap_in_div=False, lead_paragraphs=0, fragment_toc=True):
    """One spine item holding several chapters, boundaries declared in the TOC.

    The shape `tests/fixtures/e2e/` cannot cover — its whole point is one XHTML per
    chapter. Every Project Gutenberg EPUB packs a dozen chapters into one file and
    separates them only with `file.xhtml#anchor` TOC entries.
    """
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier("packed")
    book.set_title("Packed Book")
    book.set_language("en")

    titles = ["The First Day", "The Second Day", "The Third Day"]
    body = "<html><body>"
    body += "".join(
        f"<p>Front matter paragraph {j} that is long enough on its own.</p>"
        for j in range(lead_paragraphs)
    )
    for i, name in enumerate(titles, start=1):
        heading = f'<h2 id="ch{i}">Chapter {i}. {name}</h2>'
        paras = "".join(
            f"<p>Chapter {i} paragraph {j}, with plenty of words to clear the length bar.</p>"
            for j in range(4)
        )
        chunk = heading + paras
        if wrap_in_div:
            chunk = f'<div class="section">{chunk}</div>'
        body += chunk
    body += "</body></html>"

    item = epub.EpubHtml(uid="packed", title="Packed", file_name="chapters.xhtml", lang="en")
    item.set_content(body.encode())
    book.add_item(item)
    book.spine = [item]
    if fragment_toc:
        book.toc = [epub.Link(f"chapters.xhtml#ch{i}", f"Chapter {i}", f"ch{i}") for i in range(1, 4)]
    else:
        book.toc = (item,)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    path = str(tmp_path / "packed.epub")
    epub.write_epub(path, book)
    return path


def test_packed_item_splits_at_fragment_anchors(tmp_path):
    """A spine item the TOC declares fragments in becomes one chapter per anchor."""
    from scripts.parse_epub import parse_epub

    chapters = parse_epub(_packed_epub(tmp_path), language="en")["chapters"]
    assert [c["id"] for c in chapters] == ["packed#ch1", "packed#ch2", "packed#ch3"]
    assert [c["title"] for c in chapters] == ["Chapter 1", "Chapter 2", "Chapter 3"]
    assert chapters[0]["content"].startswith("Chapter 1. The First Day")
    assert chapters[1]["content"].startswith("Chapter 2. The Second Day")
    # No text bleeds across the boundary.
    assert "Second Day" not in chapters[0]["content"]


def test_packed_item_split_preserves_all_prose(tmp_path):
    """Splitting partitions the text; it never drops or duplicates prose."""
    from scripts.parse_epub import parse_epub

    chapters = parse_epub(_packed_epub(tmp_path), language="en")["chapters"]
    for i, ch in enumerate(chapters, start=1):
        assert ch["content"].count(f"Chapter {i} paragraph 3") == 1
    assert len(chapters) == 3


def test_packed_item_split_carries_paragraph_structure(tmp_path):
    """Each split chapter keeps its \\n\\n block boundaries (STU-523 holds)."""
    from scripts.parse_epub import parse_epub

    first = parse_epub(_packed_epub(tmp_path), language="en")["chapters"][0]
    blocks = first["content"].split("\n\n")
    assert blocks[0] == "Chapter 1. The First Day"
    assert len(blocks) == 5  # heading + 4 paragraphs


def test_packed_item_splits_even_when_anchors_are_nested(tmp_path):
    """Oz wraps some anchors in a <div>; document-order marking still splits right."""
    from scripts.parse_epub import parse_epub

    chapters = parse_epub(_packed_epub(tmp_path, wrap_in_div=True), language="en")["chapters"]
    assert [c["id"] for c in chapters] == ["packed#ch1", "packed#ch2", "packed#ch3"]
    assert chapters[1]["content"].startswith("Chapter 2. The Second Day")
    assert "Second Day" not in chapters[0]["content"]


def test_packed_item_keeps_substantial_front_matter_before_first_anchor(tmp_path):
    """Content before the first anchor is its own leading chapter when it has heft."""
    from scripts.parse_epub import parse_epub

    chapters = parse_epub(_packed_epub(tmp_path, lead_paragraphs=3), language="en")["chapters"]
    assert chapters[0]["id"] == "packed"  # the anchorless lead keeps the item id
    assert "Front matter paragraph 0" in chapters[0]["content"]
    assert [c["id"] for c in chapters[1:]] == ["packed#ch1", "packed#ch2", "packed#ch3"]


def _cut_packed_epub(tmp_path, items):
    """A packed book a converter cut into several files — the STU-735 shape.

    `items` is one `(lead_paragraphs, [chapter_number, ...])` per spine item. The
    lead is the anchorless text opening a file: genuine front matter on the first
    content item, the tail of the previous chapter on a file the converter cut
    mid-chapter. An item declaring no chapters gets no TOC fragment, so it stays a
    whole-file chapter.
    """
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier("cut")
    book.set_title("Cut Book")
    book.set_language("en")

    spine, links = [], []
    for index, (lead_paragraphs, chapter_numbers) in enumerate(items):
        body = "<html><body>"
        body += "".join(
            f"<p>Lead paragraph {j} of item {index}, long enough to clear the length bar.</p>"
            for j in range(lead_paragraphs)
        )
        for n in chapter_numbers:
            body += f'<h2 id="ch{n}">Chapter {n}</h2>'
            body += "".join(
                f"<p>Chapter {n} paragraph {j}, with plenty of words to clear the length bar.</p>"
                for j in range(4)
            )
        body += "</body></html>"
        name = f"part{index}.xhtml"
        item = epub.EpubHtml(uid=f"part{index}", title=f"Part {index}", file_name=name, lang="en")
        item.set_content(body.encode())
        book.add_item(item)
        spine.append(item)
        links += [epub.Link(f"{name}#ch{n}", f"Chapter {n}", f"ch{n}") for n in chapter_numbers]

    book.spine = spine
    book.toc = links
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    path = str(tmp_path / "cut.epub")
    epub.write_epub(path, book)
    return path


def test_cut_item_appends_its_lead_to_the_chapter_it_continues(tmp_path):
    """A file cut mid-chapter opens on that chapter's tail, not on a new chapter."""
    from scripts.parse_epub import parse_epub

    chapters = parse_epub(_cut_packed_epub(tmp_path, [(0, [1, 2]), (2, [3, 4])]), language="en")["chapters"]
    assert [c["id"] for c in chapters] == ["part0#ch1", "part0#ch2", "part1#ch3", "part1#ch4"]
    tail = next(c for c in chapters if c["id"] == "part0#ch2")
    assert "Lead paragraph 0 of item 1" in tail["content"]
    assert "Lead paragraph 1 of item 1" in tail["content"]
    # The tail is welded to its own chapter only, never to the next one.
    assert "Lead paragraph" not in chapters[2]["content"]


def test_cut_item_lead_is_absorbed_as_a_paragraph_not_a_run_on(tmp_path):
    """The weld restores exactly the block boundary the split marker consumed."""
    from scripts.parse_epub import parse_epub

    chapters = parse_epub(_cut_packed_epub(tmp_path, [(0, [1, 2]), (2, [3, 4])]), language="en")["chapters"]
    blocks = chapters[1]["content"].split("\n\n")
    assert blocks[0] == "Chapter 2"
    assert blocks[5].startswith("Lead paragraph 0 of item 1")
    assert len(blocks) == 7  # heading + 4 paragraphs + the 2 tail paragraphs


def test_cut_item_keeps_the_first_items_front_matter_while_absorbing_a_tail(tmp_path):
    """Both shapes at once: front matter stands, a later item's lead is absorbed."""
    from scripts.parse_epub import parse_epub

    chapters = parse_epub(_cut_packed_epub(tmp_path, [(3, [1, 2]), (2, [3, 4])]), language="en")["chapters"]
    assert [c["id"] for c in chapters] == ["part0", "part0#ch1", "part0#ch2", "part1#ch3", "part1#ch4"]
    assert "Lead paragraph 0 of item 0" in chapters[0]["content"]
    assert "Lead paragraph 0 of item 1" in chapters[2]["content"]


def test_lead_after_a_whole_file_chapter_stays_its_own_section(tmp_path):
    """The rule is never 'always append': a previous item that ended at a file
    boundary declared no anchor, so nothing there is mid-chapter to continue."""
    from scripts.parse_epub import parse_epub

    chapters = parse_epub(_cut_packed_epub(tmp_path, [(4, []), (3, [1, 2])]), language="en")["chapters"]
    assert [c["id"] for c in chapters] == ["part0", "part1", "part1#ch1", "part1#ch2"]
    assert "Lead paragraph 0 of item 1" in chapters[1]["content"]
    assert "Lead paragraph" not in chapters[2]["content"]


def test_fragment_free_toc_is_left_untouched(tmp_path):
    """A TOC pointing at whole files (every library EPUB) never splits — one
    chapter per spine item, the pre-STU-727 path, byte-for-byte."""
    from scripts.parse_epub import parse_epub

    chapters = parse_epub(_packed_epub(tmp_path, fragment_toc=False), language="en")["chapters"]
    assert len(chapters) == 1
    assert chapters[0]["id"] == "packed"


def test_declared_anchors_that_do_not_resolve_fall_back_to_whole_item(tmp_path):
    """A TOC fragment naming no element in the file leaves the item whole."""
    from ebooklib import epub
    from scripts.parse_epub import parse_epub

    book = epub.EpubBook()
    book.set_title("Ghost Anchors")
    book.set_language("en")
    item = epub.EpubHtml(uid="only", title="Only", file_name="chapters.xhtml", lang="en")
    item.set_content(
        ("<html><body><h1>Story</h1><p>" + "word " * 60 + "</p></body></html>").encode()
    )
    book.add_item(item)
    book.spine = [item]
    book.toc = [epub.Link("chapters.xhtml#missing", "Ghost", "ghost")]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    path = str(tmp_path / "ghost.epub")
    epub.write_epub(path, book)

    chapters = parse_epub(path, language="en")["chapters"]
    assert len(chapters) == 1
    assert chapters[0]["id"] == "only"


def test_build_toc_fragment_map_keeps_only_in_file_fragments():
    """The map carries `#fragment` hrefs, in order, keyed by filename; whole-file
    hrefs (what `_build_toc_title_map` handles) are absent."""
    from scripts.parse_epub import _build_toc_fragment_map

    class _Link:
        def __init__(self, href, title):
            self.href, self.title = href, title

    toc = [
        _Link("front.xhtml", "Front matter"),
        _Link("body.xhtml#c1", "Chapter 1"),
        _Link("body.xhtml#c2", "Chapter 2"),
        (_Link("body.xhtml#part", "Part One"), [_Link("body.xhtml#c3", "Chapter 3")]),
    ]
    result = _build_toc_fragment_map(toc)
    assert "front.xhtml" not in result
    assert result["body.xhtml"] == [
        ("c1", "Chapter 1"),
        ("c2", "Chapter 2"),
        ("part", "Part One"),
        ("c3", "Chapter 3"),
    ]


# --- A thin TOC superseded by the book's own printed contents (STU-728) ---


_THIN_TOC_TITLES = ["The First Day", "The Second Day", "The Third Day", "The Fourth Day"]


def _thin_toc_epub(tmp_path, *, toc_anchors=1, split_after=None, duplicate_href=False):
    """Several chapters in one XHTML, only some of them anchored in the EPUB TOC.

    The shape STU-727 measured and deferred: every boundary is declared, but in
    the book's own printed LIST OF CHAPTERS rather than in the TOC, so the TOC
    fragment rule alone yields a partial split. Anchors are the empty `<a id=…/>`
    Project Gutenberg emits — the tag `_flatten_inline_markup` unwraps.

    `split_after` cuts the body into two spine items after that many chapters
    while leaving every printed href naming the first half, which is what a
    converter does to a long file (The Road to Oz, chapters 12-24).
    """
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier("thin")
    book.set_title("Thin TOC Book")
    book.set_language("en")

    rows = "".join(
        f'<tr><td><a href="body.xhtml#c{i}">{i}.</a></td><td>{name}</td></tr>'
        for i, name in enumerate(_THIN_TOC_TITLES, start=1)
    )
    if duplicate_href:
        rows = rows.replace('href="body.xhtml#c3"', 'href="body.xhtml#c2"')
    front = epub.EpubHtml(uid="front", title="Front", file_name="front.xhtml", lang="en")
    front.set_content(
        f"<html><body><h1 id='contents'>LIST OF CHAPTERS</h1><table>{rows}</table>"
        "</body></html>".encode()
    )

    def _body(indices):
        out = "<html><body>"
        for i in indices:
            out += f'<p><a id="c{i}"></a></p><h2>{_THIN_TOC_TITLES[i - 1]}</h2>'
            out += "".join(
                f"<p>Chapter {i} paragraph {j}, with plenty of words to clear the bar.</p>"
                for j in range(4)
            )
        return out + "</body></html>"

    all_indices = list(range(1, len(_THIN_TOC_TITLES) + 1))
    bodies = [all_indices]
    if split_after is not None:
        bodies = [all_indices[:split_after], all_indices[split_after:]]
    # The first half keeps the name every printed href points at; the second is the
    # one the converter invented, so its anchors are reachable only by id.
    names = ["body.xhtml", "body1.xhtml"]
    items = [
        epub.EpubHtml(uid=f"body{n}", title="Body", file_name=names[n], lang="en")
        for n in range(len(bodies))
    ]
    for item, indices in zip(items, bodies):
        item.set_content(_body(indices).encode())

    for item in [front, *items]:
        book.add_item(item)
    book.spine = [front, *items]
    book.toc = [
        epub.Link("front.xhtml#contents", "Contents", "contents"),
        *[epub.Link(f"body.xhtml#c{i}", f"TOC name {i}", f"c{i}") for i in range(1, toc_anchors)],
    ]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    path = str(tmp_path / "thin.epub")
    epub.write_epub(path, book)
    return path


def test_thin_toc_is_superseded_by_the_printed_contents(tmp_path):
    """A TOC anchoring one section loses to the printed contents' four."""
    from scripts.parse_epub import parse_epub

    chapters = parse_epub(_thin_toc_epub(tmp_path), language="en")["chapters"]
    assert [c["id"] for c in chapters] == [f"body0#c{i}" for i in range(1, 5)]
    assert [c["title"] for c in chapters] == _THIN_TOC_TITLES
    assert chapters[1]["content"].startswith("The Second Day")
    assert "Second Day" not in chapters[0]["content"]


def test_printed_contents_anchor_survives_inline_flattening(tmp_path):
    """The anchor is an empty `<a id=…/>`, so the split must be marked before
    `_flatten_inline_markup` unwraps it — the whole reason the pipeline reordered."""
    from scripts.parse_epub import parse_epub

    chapters = parse_epub(_thin_toc_epub(tmp_path), language="en")["chapters"]
    assert len(chapters) == 4
    for i, ch in enumerate(chapters, start=1):
        assert ch["content"].count(f"Chapter {i} paragraph 3") == 1


def test_printed_contents_anchors_resolve_in_the_item_that_holds_them(tmp_path):
    """Every printed href names the first half after a converter split the file;
    the fragment is found by id in whichever spine item carries it."""
    from scripts.parse_epub import parse_epub

    chapters = parse_epub(_thin_toc_epub(tmp_path, split_after=2), language="en")["chapters"]
    assert [c["id"] for c in chapters] == ["body0#c1", "body0#c2", "body1#c3", "body1#c4"]
    assert chapters[2]["content"].startswith("The Third Day")


def test_a_toc_as_complete_as_the_printed_contents_keeps_its_own_titles(tmp_path):
    """The gate: the printed contents supersedes a *thinner* TOC, never an equal
    one, so a book correct today never changes source."""
    from scripts.parse_epub import parse_epub

    chapters = parse_epub(_thin_toc_epub(tmp_path, toc_anchors=5), language="en")["chapters"]
    assert [c["title"] for c in chapters] == [f"TOC name {i}" for i in range(1, 5)]


def test_printed_contents_keeps_the_first_of_two_entries_sharing_an_href(tmp_path):
    """The Patchwork Girl's printed contents points chapters 22 and 23 at the same
    anchor; the duplicate is dropped and its text stays with the chapter before it."""
    from scripts.parse_epub import parse_epub

    chapters = parse_epub(_thin_toc_epub(tmp_path, duplicate_href=True), language="en")["chapters"]
    assert [c["title"] for c in chapters] == ["The First Day", "The Second Day", "The Fourth Day"]
    assert "Chapter 3 paragraph 0" in chapters[1]["content"]


def test_whole_file_toc_entries_count_against_the_printed_contents(tmp_path):
    """The library shape: a TOC of whole-file entries, one per chapter, plus a
    handful of in-file links in the body (endnotes, an index). Counting only the
    TOC's *fragments* would read that TOC as declaring nothing and let the endnote
    list supersede it — so the gate counts every entry the TOC declares."""
    from ebooklib import epub
    from scripts.parse_epub import parse_epub

    book = epub.EpubBook()
    book.set_title("Whole File TOC")
    book.set_language("en")
    items = []
    for i in range(1, 5):
        item = epub.EpubHtml(uid=f"c{i}", title=f"Chapter {i}", file_name=f"c{i}.xhtml", lang="en")
        # The endnote anchors resolve, so only the gate keeps them from splitting.
        refs = "".join(
            f'<p><a id="ref{n}"></a>a note reference {n} in the middle of the prose.</p>'
            for n in range(1, 5)
        ) if i == 1 else ""
        item.set_content(
            (f"<html><body><h2>Chapter {i}</h2><p>" + f"chapter {i} word " * 40
             + f"</p>{refs}</body></html>").encode()
        )
        items.append(item)
        book.add_item(item)
    notes = epub.EpubHtml(uid="notes", title="Notes", file_name="notes.xhtml", lang="en")
    notes.set_content(
        ("<html><body><ol>"
         + "".join(f'<li><a href="c1.xhtml#ref{i}">note {i}</a></li>' for i in range(1, 5))
         + "</ol><p>" + "note text " * 40 + "</p></body></html>").encode()
    )
    book.add_item(notes)
    book.spine = [*items, notes]
    book.toc = [epub.Link(f"c{i}.xhtml", f"Chapter {i}", f"c{i}") for i in range(1, 5)]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    path = str(tmp_path / "wholefile.epub")
    epub.write_epub(path, book)

    chapters = parse_epub(path, language="en")["chapters"]
    assert [c["id"] for c in chapters] == ["c1", "c2", "c3", "c4", "notes"]
    # Splitting there would cut each reference into its own sub-minimum segment and
    # drop it, so the leak costs prose without changing the chapter count.
    assert "a note reference 4" in chapters[0]["content"]


def test_build_printed_contents_reads_the_densest_list_of_in_file_links():
    """The book's printed contents is the densest table/list of `#fragment` links;
    a `<div>` is not a list, and a couple of cross-references are not a contents."""
    from bs4 import BeautifulSoup
    from scripts.parse_epub import _build_printed_contents

    contents = BeautifulSoup(
        "<body>"
        '<div><a href="b.xhtml#x">a cross-reference</a><a href="b.xhtml#y">another</a>'
        '<a href="b.xhtml#z">a third</a></div>'
        '<table><tr><td><a href="b.xhtml#c1">1.</a></td><td>Opening</td></tr>'
        '<tr><td><a href="b.xhtml#c2">2.</a></td><td>Middle</td></tr>'
        '<tr><td><a href="b.xhtml#c3">3.</a></td><td>Ending</td></tr></table>'
        '<ul><li><a href="b.xhtml#n1">A footnote</a></li></ul>'
        "</body>",
        "html.parser",
    )
    assert _build_printed_contents([contents]) == [
        ("c1", "Opening"),
        ("c2", "Middle"),
        ("c3", "Ending"),
    ]


def test_build_printed_contents_is_empty_when_the_book_prints_none():
    """Every `library/` EPUB: whole-file hrefs only, so nothing supersedes the TOC."""
    from bs4 import BeautifulSoup
    from scripts.parse_epub import _build_printed_contents

    soup = BeautifulSoup(
        '<body><ul><li><a href="c1.xhtml">One</a></li><li><a href="c2.xhtml">Two</a></li>'
        '<li><a href="c3.xhtml">Three</a></li></ul></body>',
        "html.parser",
    )
    assert _build_printed_contents([soup]) == []


def test_printed_contents_entry_title_falls_back_to_the_link_text():
    """A contents whose link is the whole entry has no row text to prefer."""
    from bs4 import BeautifulSoup
    from scripts.parse_epub import _build_printed_contents

    soup = BeautifulSoup(
        '<body><ul><li><a href="b.xhtml#c1">The Opening</a></li>'
        '<li><a href="b.xhtml#c2">The Middle</a></li>'
        '<li><a href="b.xhtml#c3">The Ending</a></li></ul></body>',
        "html.parser",
    )
    assert _build_printed_contents([soup]) == [
        ("c1", "The Opening"),
        ("c2", "The Middle"),
        ("c3", "The Ending"),
    ]


# --- A book whose sections are marked typographically and nowhere else (STU-736) ---


_PRINTED_MARKS = [
    "1. The Horror in Clay.",
    "2. The Tale of Inspector Legrasse.",
    "3. The Madness from the Sea.",
]


def _typographic_epub(tmp_path, *, wrap_in_div=False, lead_paragraphs=0):
    """Several sections in one XHTML, marked only by the line each one opens with.

    The Call of Cthulhu's shape: the TOC anchors front matter, the book prints no
    contents list, and no section carries a heading — the only marker is a CSS
    class (`<p class="ph1"><i>1. The Horror in Clay.</i></p>`), which no rule may
    read (dracula prints 32 `hr.chap` for its 32 correct chapters).
    """
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier("typographic")
    book.set_title("Typographic Book")
    book.set_language("en")

    body = "<html><body>"
    body += "".join(
        f"<p>Front matter paragraph {j} that is long enough to stand on its own.</p>"
        for j in range(lead_paragraphs)
    )
    for i, mark in enumerate(_PRINTED_MARKS, start=1):
        chunk = f'<hr class="chap"/><p class="ph1"><i>{mark}</i></p>'
        chunk += "".join(
            f"<p>Section {i} paragraph {j}, with plenty of words to clear the length bar.</p>"
            for j in range(4)
        )
        if wrap_in_div:
            chunk = f'<div class="section">{chunk}</div>'
        body += chunk
    body += "</body></html>"

    item = epub.EpubHtml(uid="whole", title="Whole", file_name="whole.xhtml", lang="en")
    item.set_content(body.encode())
    book.add_item(item)
    book.spine = [item]
    book.toc = (item,)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    path = str(tmp_path / "typographic.epub")
    epub.write_epub(path, book)
    return path


def test_declared_chapter_marks_split_a_typographically_marked_book(tmp_path):
    """The book declares the lines it prints; each one opens a section."""
    from scripts.parse_epub import parse_epub

    chapters = parse_epub(
        _typographic_epub(tmp_path), language="en", chapter_marks=_PRINTED_MARKS
    )["chapters"]
    assert [c["title"] for c in chapters] == _PRINTED_MARKS
    assert [c["id"] for c in chapters] == [
        "whole#1-the-horror-in-clay",
        "whole#2-the-tale-of-inspector-legrasse",
        "whole#3-the-madness-from-the-sea",
    ]
    assert chapters[0]["content"].startswith("1. The Horror in Clay.")
    assert "Inspector Legrasse" not in chapters[0]["content"]


def test_the_same_book_undeclared_stays_one_chapter(tmp_path):
    """The STU-539 asymmetry, measured on the shape itself: no declaration, no
    split — which is what keeps every other book byte-identical."""
    from scripts.parse_epub import parse_epub

    chapters = parse_epub(_typographic_epub(tmp_path), language="en")["chapters"]
    assert len(chapters) == 1
    assert chapters[0]["id"] == "whole"


def test_declared_marks_split_preserves_all_prose(tmp_path):
    """Splitting partitions the text; it never drops or duplicates prose."""
    from scripts.parse_epub import parse_epub

    chapters = parse_epub(
        _typographic_epub(tmp_path), language="en", chapter_marks=_PRINTED_MARKS
    )["chapters"]
    for i, ch in enumerate(chapters, start=1):
        assert ch["content"].count(f"Section {i} paragraph 3") == 1


def test_declared_marks_ignore_the_wrapper_printing_the_same_text(tmp_path):
    """Only a leaf block is the mark: a `<div>` around the section prints the mark
    too, and cutting there as well would lose the section to the length gate."""
    from scripts.parse_epub import parse_epub

    chapters = parse_epub(
        _typographic_epub(tmp_path, wrap_in_div=True), language="en", chapter_marks=_PRINTED_MARKS
    )["chapters"]
    assert [c["title"] for c in chapters] == _PRINTED_MARKS


def test_declared_marks_keep_the_front_matter_before_the_first_one(tmp_path):
    """Cthulhu prints its title page and epigraph before section 1; that prose is
    kept as its own leading section, never dropped (the STU-728 lead)."""
    from scripts.parse_epub import parse_epub

    chapters = parse_epub(
        _typographic_epub(tmp_path, lead_paragraphs=3),
        language="en",
        chapter_marks=_PRINTED_MARKS,
    )["chapters"]
    assert chapters[0]["id"] == "whole"
    assert "Front matter paragraph 0" in chapters[0]["content"]
    assert [c["title"] for c in chapters[1:]] == _PRINTED_MARKS


def test_a_declared_mark_the_book_never_prints_warns(tmp_path, capsys):
    """A mistyped line splits nothing and says so — a silent no-op is the bug."""
    from scripts.parse_epub import parse_epub

    chapters = parse_epub(
        _typographic_epub(tmp_path),
        language="en",
        chapter_marks=[*_PRINTED_MARKS, "4. The Section That Is Not There."],
    )["chapters"]
    assert len(chapters) == 3
    assert "4. The Section That Is Not There." in capsys.readouterr().err


def test_declared_marks_match_the_printed_line_across_typesetting_whitespace(tmp_path):
    """The YAML holds what the page shows; the markup holds the typesetter's line
    breaks and `&#13;` charrefs (STU-531) between the words."""
    from ebooklib import epub
    from scripts.parse_epub import parse_epub

    book = epub.EpubBook()
    book.set_title("Wrapped Mark")
    book.set_language("en")
    item = epub.EpubHtml(uid="whole", title="Whole", file_name="whole.xhtml", lang="en")
    item.set_content(
        ("<html><body><p>" + "opening word " * 20 + "</p>"
         "<p class='ph1'><i>1. The Horror\n&#13; in Clay.</i></p><p>"
         + "section word " * 40 + "</p></body></html>").encode()
    )
    book.add_item(item)
    book.spine = [item]
    book.toc = (item,)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    path = str(tmp_path / "wrapped.epub")
    epub.write_epub(path, book)

    chapters = parse_epub(path, language="en", chapter_marks=["1. The Horror in Clay."])["chapters"]
    assert [c["title"] for c in chapters[1:]] == ["1. The Horror in Clay."]


def test_the_call_of_cthulhu_parses_to_its_three_printed_sections():
    """The measured case (STU-736). The tracked EPUB, the tracked book YAML."""
    import yaml

    from scripts.parse_epub import parse_epub
    from wiki_creator.chapters import declared_chapter_marks

    book_yaml = Path(
        "public_domain/h_p_lovecraft/the_call_of_cthulhu/books/01-the_call_of_cthulhu.yaml"
    )
    config = yaml.safe_load(book_yaml.read_text(encoding="utf-8"))
    chapters = parse_epub(
        config["file_path"], language="en", chapter_marks=declared_chapter_marks(config)
    )["chapters"]
    # The lead is the title page, the transcriber's note and the epigraph — front
    # matter the section filter tags, kept rather than dropped.
    assert [c["title"] for c in chapters[1:]] == [
        "1. The Horror in Clay.",
        "2. The Tale of Inspector Legrasse.",
        "3. The Madness from the Sea.",
    ]
    assert chapters[1]["content"].startswith("1. The Horror in Clay.")
    assert "Inspector Legrasse" not in chapters[0]["content"]
