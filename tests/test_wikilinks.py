"""Wikilink integrity check (STU-725) — pure logic + the disk-scanning gate.

The real-world case these fixtures distill is the Oz ``_series/`` output on
PR #336: a page titled ``City of Emeralds`` while the prose links
``[[Emerald City]]`` — a dead link canonicalization drift shipped silently.
"""
import os
import subprocess
import sys
from pathlib import Path

from wiki_creator.wikilinks import (
    DeadLink,
    extract_link_targets,
    find_dead_links,
    retarget_links,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_extract_plain_and_piped_targets():
    text = "See [[Emerald City]] and [[Dorothy Gale|Dorothy]] for more."
    assert extract_link_targets(text) == ["Emerald City", "Dorothy Gale"]


def test_extract_excludes_category_and_file_links():
    text = (
        "[[Toto]]\n[[Category:Personnages]]\n[[:Category:Lieux|All]]\n"
        "[[File:map.png]]\n[[Image:x.jpg|thumb]]"
    )
    assert extract_link_targets(text) == ["Toto"]


def test_extract_strips_anchor_and_drops_anchor_only_links():
    text = "[[Emerald City#History]] and [[#Overview|top]]"
    assert extract_link_targets(text) == ["Emerald City#History"]


# --- retargeting (STU-719) -------------------------------------------------

_SERIES = {"Nick Chopper": "Tin Woodman", "Queen": "", "Scarecrow": "Scarecrow"}


def _resolve(target):
    return _SERIES.get(target)


def test_retarget_keeps_the_tome_wording_as_the_label():
    assert retarget_links("Met [[Nick Chopper]].", _resolve) == "Met [[Tin Woodman|Nick Chopper]]."


def test_retarget_preserves_an_existing_label_and_anchor():
    assert retarget_links("[[Nick Chopper|Nick]]", _resolve) == "[[Tin Woodman|Nick]]"
    assert retarget_links("[[Nick Chopper#Death]]", _resolve) == "[[Tin Woodman#Death|Nick Chopper]]"


def test_retarget_unlinks_an_empty_resolution():
    # A merged-away target must not become a red link; the label survives as prose.
    assert retarget_links("Fled the [[Queen]].", _resolve) == "Fled the Queen."
    assert retarget_links("Fled the [[Queen|wicked queen]].", _resolve) == "Fled the wicked queen."


def test_retarget_leaves_an_unknown_or_already_canonical_target_untouched():
    text = "[[Ozma]] and [[Scarecrow]] and [[Category:Personnages]]"
    assert retarget_links(text, _resolve) == text


def test_all_links_resolve_is_clean():
    pages = [
        ("Dorothy", "She met [[Scarecrow]] on the road to [[Emerald City]]."),
        ("Scarecrow", "A friend of [[Dorothy]]."),
        ("Emerald City", "Ruled from afar."),
    ]
    assert find_dead_links(pages) == []


def test_flags_the_dead_link_not_the_allowlisted_red_link():
    """The ticket's acceptance case: one dead link and one intentional red link;
    only the former is reported."""
    pages = [
        # "Emerald City" was renamed to "City of Emeralds" at assembly (STU-719
        # drift), so this link dangles. "Nome King" is a deliberate red link.
        ("Dorothy", "She reached [[Emerald City]] and heard of [[Nome King]]."),
        ("City of Emeralds", "The capital."),
    ]
    dead = find_dead_links(pages, allowlist=["Nome King"])
    assert dead == [DeadLink(source="Dorothy", target="Emerald City")]


def test_resolution_is_namespace_flat_via_page_filename():
    """A link with a space resolves against a title the exporter files with an
    underscore — the same identity duplicate_page_titles compares."""
    pages = [("Home", "Go to [[Emerald City]]."), ("Emerald_City", "Here.")]
    assert find_dead_links(pages) == []


def test_dead_link_deduped_within_page_but_not_across():
    pages = [
        ("A", "[[Ghost]] then [[Ghost]] again."),
        ("B", "Also [[Ghost]]."),
    ]
    dead = find_dead_links(pages)
    assert dead == [DeadLink("A", "Ghost"), DeadLink("B", "Ghost")]


def test_series_scope_shares_the_function():
    """Series scope differs only in how the page set is built — one page per
    canonical character (STU-668), no title disambiguation."""
    pages = [
        ("Aelin_Galathynius", "Bonded to [[Rowan]]; sister of [[Aedion]]."),
        ("Rowan", "A warrior."),
    ]
    assert find_dead_links(pages) == [DeadLink("Aelin_Galathynius", "Aedion")]


def _write(wiki_dir: Path, rel: str, body: str) -> None:
    path = wiki_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_gate_scans_disk_excluding_templates(tmp_path):
    wiki = tmp_path / "output" / "oz"
    _write(wiki, "characters/Dorothy.wiki", "Met [[Scarecrow]] near [[Emerald City]].")
    _write(wiki, "characters/Scarecrow.wiki", "Friend of [[Dorothy]].\n[[Category:Personnages]]")
    _write(wiki, "locations/City_of_Emeralds.wiki", "The capital.")
    # A template is an infobox source, not a page — its placeholders must not be
    # read as a page nor as links.
    _write(wiki, "templates/Infobox_character.wiki", "{{{nom}}}")

    from wiki_creator.wikilinks import find_dead_links as _f
    from scripts.check_wikilinks import load_pages

    pages = load_pages(wiki)
    assert "Infobox_character" not in {t for t, _ in pages}
    assert _f(pages) == [DeadLink("Dorothy", "Emerald City")]


def test_gate_cli_exits_nonzero_on_dead_link(tmp_path):
    book_dir = tmp_path / "library" / "baum" / "oz" / "books"
    book_dir.mkdir(parents=True)
    book_yaml = book_dir / "01-oz.yaml"
    book_yaml.write_text("file_path: library/baum/oz/books/01-oz.yaml\n", encoding="utf-8")

    wiki = tmp_path / "library" / "baum" / "oz" / "output" / "01-oz"
    _write(wiki, "characters/Dorothy.wiki", "To [[Emerald City]].")
    _write(wiki, "locations/City_of_Emeralds.wiki", "The capital.")

    proc = subprocess.run(
        [sys.executable, "scripts/check_wikilinks.py", "--book", str(book_yaml)],
        capture_output=True, text=True, cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
    )
    assert proc.returncode == 1
    assert "Emerald City" in proc.stderr


def test_gate_cli_clean_with_red_link_allowlist(tmp_path):
    book_dir = tmp_path / "library" / "baum" / "oz" / "books"
    book_dir.mkdir(parents=True)
    book_yaml = book_dir / "01-oz.yaml"
    book_yaml.write_text(
        "file_path: library/baum/oz/books/01-oz.yaml\n"
        "export:\n  red_links: [Nome King]\n",
        encoding="utf-8",
    )

    wiki = tmp_path / "library" / "baum" / "oz" / "output" / "01-oz"
    _write(wiki, "characters/Dorothy.wiki", "Heard of the [[Nome King]].")

    proc = subprocess.run(
        [sys.executable, "scripts/check_wikilinks.py", "--book", str(book_yaml)],
        capture_output=True, text=True, cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
    )
    assert proc.returncode == 0, proc.stderr
    assert "0 dead links" in proc.stderr
