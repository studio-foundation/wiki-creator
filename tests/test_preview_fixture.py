"""Drift guard for the preview-app wikitext fixture (STU-645).

The committed fixture under ``tests/fixtures/preview/output/`` must stay
byte-identical to what ``gen_fixture.build()`` produces from the real exporter
helpers — otherwise the M5.1 preview app would be developed against stale
wikitext. Re-run ``python tests/fixtures/preview/gen_fixture.py`` after an
intentional exporter change and commit the diff.

The second half pins that the fixture keeps *covering* every construct the
preview parser must handle, so trimming the cast can't silently drop a case.
"""
import importlib.util
from pathlib import Path

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "preview"
_OUTPUT_DIR = _FIXTURE_DIR / "output"


def _load_gen():
    spec = importlib.util.spec_from_file_location(
        "preview_gen_fixture", _FIXTURE_DIR / "gen_fixture.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_fixture_matches_exporter():
    """Every committed file equals gen_fixture.build(), and no extra/missing files."""
    expected = _load_gen().build()
    on_disk = {
        str(p.relative_to(_OUTPUT_DIR)).replace("\\", "/"): p.read_text(encoding="utf-8")
        for p in _OUTPUT_DIR.rglob("*.wiki")
    }
    assert set(on_disk) == set(expected), (
        "fixture file set drifted from the exporter — re-run gen_fixture.py"
    )
    for rel_path, content in expected.items():
        assert on_disk[rel_path] == content, (
            f"{rel_path} drifted from the exporter — re-run gen_fixture.py"
        )


def test_fixture_covers_every_construct():
    """The fixture must exercise each wikitext construct the parser handles."""
    files = {
        str(p.relative_to(_OUTPUT_DIR)).replace("\\", "/"): p.read_text(encoding="utf-8")
        for p in _OUTPUT_DIR.rglob("*.wiki")
    }
    corpus = "\n".join(files.values())

    # headings
    assert "== Biography ==" in corpus
    # bold + italic
    assert "'''Alice'''" in corpus and "''enormous''" in corpus
    # infobox template call + local template source with {{{param}}}
    assert "{{Infobox character" in corpus
    assert "{{{name}}}" in files["templates/Infobox_character.wiki"]
    # infobox wikitable
    assert '{| class="infobox"' in files["templates/Infobox_character.wiki"]
    # category tags
    assert "[[Category:Characters]]" in corpus
    # cross-subdir wikilink (a PLACE linked from a character page)
    assert "[[Wonderland]]" in files["characters/Alice.wiki"]
    # dangling / red link (no page named Dormouse exists)
    assert "[[Dormouse]]" in corpus
    assert not any("Dormouse" in name for name in files)
    # mw-collapsible spoiler block (section) and inline gated infobox row (span)
    assert 'class="mw-collapsible' in files["characters/Alice.wiki"]
    assert '<span class="mw-collapsible' in files["characters/Queen_of_Hearts.wiki"]
    # body-only pages (SYNOPSIS + COLLATION render with no infobox)
    assert "{{Infobox" not in files["Synopsis.wiki"]
    assert "{{Infobox" not in files["Minor_Characters.wiki"]


def test_fixture_layout_mirrors_real_export():
    """The directory layout matches paths the exporter writes (subdirs + root pages)."""
    names = {str(p.relative_to(_OUTPUT_DIR)).replace("\\", "/") for p in _OUTPUT_DIR.rglob("*.wiki")}
    assert "Main_Page.wiki" in names
    assert "categories.wiki" in names
    assert "Synopsis.wiki" in names
    assert any(n.startswith("characters/") for n in names)
    assert any(n.startswith("locations/") for n in names)
    assert any(n.startswith("organizations/") for n in names)
    assert any(n.startswith("events/") for n in names)
    assert any(n.startswith("templates/") for n in names)
