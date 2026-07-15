"""End-to-end smoke test — EPUB → parse → NER extraction on an original,
copyright-free mini-novella (tests/fixtures/e2e/).

Purpose: make the pipeline verifiable from a fresh clone. Real books
(EPUBs) are never committed, so this is the only in-repo path that
exercises the extraction stages against an actual EPUB file.

Tier 1 (always runs): EPUB build + scripts/parse_epub.py.
Tier 2 (skips without en_core_web_sm): scripts/entity_extraction.py.

The chapters are committed XHTML (fixtures/e2e/ch0*.xhtml), not prose this
module wraps in tags: a fixture the test authors can only contain the markup
the parser already expects, which is why 1500 green tests never saw STU-519
(STU-524).
"""
import json
import subprocess
import sys
import unicodedata
import zipfile
from pathlib import Path

import pytest
import yaml

from _markers import requires_en_sm

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "e2e"

CHAPTER_TITLES = ["Harbor Fog", "The Granite Hall", "Warehouse Nine", "North"]

BOOK_TITLE = "The Salt Guild Ledger"
BOOK_AUTHOR = "Wiki Creator Fixtures"

_CONTAINER = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="EPUB/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

_OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">smoke-novella</dc:identifier>
    <dc:title>{title}</dc:title>
    <dc:creator>{author}</dc:creator>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
{manifest}
  </manifest>
  <spine toc="ncx">
{spine}
  </spine>
</package>
"""

_NCX = """<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head><meta name="dtb:uid" content="smoke-novella"/></head>
  <docTitle><text>{title}</text></docTitle>
  <navMap>
{nav_points}
  </navMap>
</ncx>
"""


def _build_smoke_epub(tmp_path: Path) -> Path:
    """Zip the committed fixture chapters into an EPUB, byte-for-byte.

    Written as a raw zip on purpose: ebooklib's `write_epub` pretty-prints
    XHTML, inserting whitespace between sibling elements — which turns a
    dropcap's `<span>M</span><span>ove</span>` into two real words and destroys
    the very shapes these fixtures exist to carry (STU-524). The fixture must
    represent a publisher's file, not ebooklib's serializer output.

    Layout matches what book_paths_from_epub expects:
    <series>/books/<slug>.epub → outputs under <series>/processing_output/<slug>/.
    """
    names = [f"ch{i:02d}" for i in range(1, len(CHAPTER_TITLES) + 1)]
    ids = [f"chapter_{i}" for i in range(len(CHAPTER_TITLES))]

    opf = _OPF.format(
        title=BOOK_TITLE,
        author=BOOK_AUTHOR,
        manifest="\n".join(
            f'    <item id="{i}" href="{n}.xhtml" media-type="application/xhtml+xml"/>'
            for i, n in zip(ids, names)
        ),
        spine="\n".join(f'    <itemref idref="{i}"/>' for i in ids),
    )
    ncx = _NCX.format(
        title=BOOK_TITLE,
        nav_points="\n".join(
            f'    <navPoint id="np_{k}" playOrder="{k + 1}">'
            f"<navLabel><text>{t}</text></navLabel>"
            f'<content src="{n}.xhtml"/></navPoint>'
            for k, (t, n) in enumerate(zip(CHAPTER_TITLES, names))
        ),
    )

    books_dir = tmp_path / "smoke-series" / "books"
    books_dir.mkdir(parents=True)
    epub_path = books_dir / "smoke-novella.epub"
    with zipfile.ZipFile(epub_path, "w", zipfile.ZIP_DEFLATED) as z:
        # The mimetype entry must be first and stored uncompressed.
        z.writestr(
            zipfile.ZipInfo("mimetype"), "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        z.writestr("META-INF/container.xml", _CONTAINER)
        z.writestr("EPUB/content.opf", opf)
        z.writestr("EPUB/toc.ncx", ncx)
        for name in names:
            z.writestr(
                f"EPUB/{name}.xhtml",
                (FIXTURE_DIR / f"{name}.xhtml").read_bytes(),
            )
    return epub_path


def _run_stage(script: str, payload: dict) -> dict:
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        timeout=300,
    )
    assert result.returncode == 0, (
        f"{script} failed (rc={result.returncode}):\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def smoke_epub(tmp_path_factory) -> Path:
    return _build_smoke_epub(tmp_path_factory.mktemp("e2e"))


@pytest.fixture(scope="module")
def parse_result(smoke_epub: Path) -> dict:
    ctx = yaml.safe_dump({"file_path": str(smoke_epub), "language": "en"})
    return _run_stage("parse_epub.py", {"additional_context": ctx})


def test_parse_epub_extracts_all_chapters(parse_result):
    assert parse_result["title"] == "The Salt Guild Ledger"
    assert parse_result["author"] == "Wiki Creator Fixtures"
    contents = [ch["content"] for ch in parse_result["chapters"]]
    assert len(contents) == len(CHAPTER_TITLES)
    assert any("Elias Thorn" in c for c in contents)
    assert any("Port Saffron" in c for c in contents)


def test_parse_epub_survives_publisher_markup(parse_result):
    """Each shape the fixture chapters carry, asserted on the parsed text.

    The goldens already cover this, but a golden diff is a wall of JSON; these
    name the shape that broke. Every one is drawn from the real library and was
    (or would have been) mis-parsed before STU-519 — see fixtures/e2e/*.xhtml.
    """
    text = " ".join(ch["content"] for ch in parse_result["chapters"])
    assert "Captain Elias Thorn stood" in text          # dropcap sibling spans
    assert "North The Heron slipped" in text            # small-caps opener
    assert "the 9th pier" in text                       # superscript ordinal
    assert '"There," Mira Vale said' in text            # inline tag before punctuation
    assert "coast—harbor masters, tax men & brokers" in text  # &mdash; &amp;
    assert "came out an hour later" in text             # &nbsp;
    assert "the fish market" in text                    # ﬁ ligature
    assert "in the café" in text                        # NFD → NFC
    assert unicodedata.is_normalized("NFC", text)


def test_parse_epub_reports_language_and_pov(parse_result):
    assert parse_result["language"] == "en"
    pov = parse_result["pov_detection"]
    # Third-person narration with 'she/he ... thought/knew' style markers.
    assert pov["pov"] in {"third_limited", "omniscient"}
    assert pov["total_tokens"] > 0


def test_parse_epub_writes_epub_data_json(parse_result, smoke_epub):
    data_file = (
        smoke_epub.parent.parent / "processing_output" / "smoke-novella" / "epub_data.json"
    )
    assert data_file.exists()
    on_disk = json.loads(data_file.read_text(encoding="utf-8"))
    assert on_disk["title"] == parse_result["title"]


@requires_en_sm
def test_entity_extraction_finds_fixture_entities(parse_result, smoke_epub):
    ctx = yaml.safe_dump({
        "file_path": str(smoke_epub),
        "spacy_model": "en_core_web_sm",
        "min_mentions_absolute": 2,
    })
    extraction = _run_stage("entity_extraction.py", {
        "additional_context": ctx,
        "previous_outputs": {"epub-parse": parse_result},
    })
    # entities_for_resolution: dict keyed by entity_id, each entity carrying
    # {type, raw_mentions, first_seen, mention_count} (no mentions_by_chapter).
    entities = extraction["entities_for_resolution"]
    assert entities, "no entities extracted from the smoke novella"

    def mentions(type_filter: str | None = None) -> set[str]:
        return {
            m
            for e in entities.values()
            if type_filter is None or e.get("type") == type_filter
            for m in e.get("raw_mentions", [])
        }

    persons = mentions("PERSON")
    # The two protagonists are each mentioned 4+ times with full names and
    # person cues (title, dialogue verbs) — the fixture prose is written to
    # cooperate with _retag_entity_type_from_context, whose place-cue
    # scoring can retag PERSON entities in place-heavy sentences.
    registry_dump = {
        eid: {"type": e.get("type"), "raw_mentions": e.get("raw_mentions")}
        for eid, e in entities.items()
    }
    assert any("Thorn" in m for m in persons), f"registry: {registry_dump}"
    assert any("Vale" in m for m in persons), f"registry: {registry_dump}"
    assert any("Saffron" in m for m in mentions()), f"registry: {registry_dump}"

    # Per-type registries and chapters.json land in processing_output/<slug>/
    processing = smoke_epub.parent.parent / "processing_output" / "smoke-novella"
    assert (processing / "persons_full.json").exists()
    assert (processing / "chapters.json").exists()
    persons_full = json.loads((processing / "persons_full.json").read_text(encoding="utf-8"))
    assert persons_full["persons_full"], "persons_full.json is empty"
    # Mentions must be keyed by chapter id (repo gotcha: id, not title)
    chapter_ids = {ch["id"] for ch in parse_result["chapters"]}
    for entity in persons_full["persons_full"].values():
        assert set(entity.get("mentions_by_chapter", {})) <= chapter_ids
