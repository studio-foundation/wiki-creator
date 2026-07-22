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
