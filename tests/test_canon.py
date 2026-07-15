"""Tests for the series canon policy (STU-512)."""
import pytest
import yaml

from wiki_creator.canon import load_canon, resolve_book_source
from wiki_creator.studio_io import PROJECT_ROOT


def _write_canon(series_dir, block: dict):
    series_dir.mkdir(parents=True, exist_ok=True)
    path = series_dir / "canon.yaml"
    path.write_text(yaml.safe_dump({"canon": block}), encoding="utf-8")
    return path


def _epub_source(**overrides) -> dict:
    source = {
        "id": "epub_en_01",
        "type": "epub",
        "path": "books/01-book.epub",
        "authority": 100,
    }
    source.update(overrides)
    return source


def _single_epub_policy() -> dict:
    return {
        "primary_source": "epub",
        "sources": [_epub_source()],
        "conflict_resolution": {"strategy": "highest_authority", "on_unresolved": "flag"},
        "cross_tome": {"later_tome_overrides": False},
    }


def test_absent_canon_yaml_is_none(tmp_path) -> None:
    assert load_canon(tmp_path / "canon.yaml") is None


@pytest.mark.parametrize(
    "text",
    ["", "# just a placeholder\n", "canon:\n"],
    ids=["empty", "comments_only", "no_block"],
)
def test_declaring_no_policy_degrades_like_an_absent_file(tmp_path, text) -> None:
    """A placeholder must not be harder to survive than no file at all."""
    path = tmp_path / "canon.yaml"
    path.write_text(text, encoding="utf-8")
    assert load_canon(path) is None


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("canon:\n  primary_source: epub\n   bad: indent\n", "not valid YAML"),
        ("- a\n- b\n", "must be a mapping"),
        (
            "canon:\n  primary_source: epub\n  sources:\n    - books/a.epub\n",
            "must be a mapping",
        ),
        (
            "canon:\n  primary_source: epub\n  sources:\n    - {id: a, type: epub}\n",
            "declares no path",
        ),
        (
            "canon:\n  primary_source: epub\n  sources:\n"
            "    - {id: a, type: epub, path: books/a.epub, authority: abc}\n",
            "must be an integer",
        ),
        (
            "canon:\n  primary_source: epub\n  sources:\n"
            "    - {id: a, type: epub, path: books/a.epub, authority: null}\n",
            "must be an integer",
        ),
        ("canon:\n  primary_source: epub\n  sources: []\n", "declares no sources"),
        (
            "canon:\n  primary_source: epub\n  sources:\n"
            "    - {id: dup, type: epub, path: books/a.epub}\n"
            "    - {id: dup, type: epub, path: books/b.epub}\n",
            "duplicate source id",
        ),
    ],
    ids=[
        "broken_yaml", "not_a_mapping", "source_not_a_mapping", "source_without_path",
        "authority_not_int", "authority_null", "no_sources", "duplicate_ids",
    ],
)
def test_a_declared_but_malformed_policy_raises_a_canon_error(tmp_path, text, match) -> None:
    """Never a raw AttributeError/TypeError leak — a broken policy must say so."""
    path = tmp_path / "canon.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        load_canon(path)


def test_loads_declared_policy(tmp_path) -> None:
    canon = load_canon(_write_canon(tmp_path, _single_epub_policy()))
    assert canon.primary_source == "epub"
    assert canon.strategy == "highest_authority"
    assert canon.on_unresolved == "flag"
    assert canon.later_tome_overrides is False
    assert [s.id for s in canon.sources] == ["epub_en_01"]
    assert canon.sources[0].authority == 100


def test_primary_source_matching_no_declared_source_type_raises(tmp_path) -> None:
    policy = _single_epub_policy()
    policy["primary_source"] = "fandom"
    with pytest.raises(ValueError, match="primary_source 'fandom'"):
        load_canon(_write_canon(tmp_path, policy))


def test_source_path_resolves_against_series_dir(tmp_path) -> None:
    canon = load_canon(_write_canon(tmp_path, _single_epub_policy()))
    source = canon.resolve_source("01-book")
    assert canon.source_path(source) == tmp_path / "books" / "01-book.epub"


def test_undeclared_book_resolves_to_none(tmp_path) -> None:
    canon = load_canon(_write_canon(tmp_path, _single_epub_policy()))
    assert canon.resolve_source("02-book") is None


def test_highest_authority_picks_the_epub_over_a_scraped_source(tmp_path) -> None:
    policy = _single_epub_policy()
    policy["sources"].append(
        _epub_source(id="fandom_01", type="fandom", path="books/01-book.fandom", authority=50)
    )
    canon = load_canon(_write_canon(tmp_path, policy))
    assert canon.resolve_source("01-book").id == "epub_en_01"


def test_primary_wins_picks_the_primary_source_type(tmp_path) -> None:
    policy = _single_epub_policy()
    policy["sources"].append(
        _epub_source(id="fandom_01", type="fandom", path="books/01-book.fandom", authority=200)
    )
    policy["conflict_resolution"]["strategy"] = "primary_wins"
    canon = load_canon(_write_canon(tmp_path, policy))
    assert canon.resolve_source("01-book").id == "epub_en_01"


def test_authority_tie_flags_and_falls_back_to_primary(tmp_path, capsys) -> None:
    policy = _single_epub_policy()
    policy["sources"].append(
        _epub_source(id="fandom_01", type="fandom", path="books/01-book.fandom", authority=100)
    )
    canon = load_canon(_write_canon(tmp_path, policy))
    assert canon.resolve_source("01-book").id == "epub_en_01"
    assert "cannot arbitrate" in capsys.readouterr().err


def test_authority_tie_raises_when_on_unresolved_is_fail(tmp_path) -> None:
    policy = _single_epub_policy()
    policy["sources"].append(
        _epub_source(id="fandom_01", type="fandom", path="books/01-book.fandom", authority=100)
    )
    policy["conflict_resolution"]["on_unresolved"] = "fail"
    canon = load_canon(_write_canon(tmp_path, policy))
    with pytest.raises(ValueError, match="cannot arbitrate"):
        canon.resolve_source("01-book")


def test_flag_for_review_never_auto_arbitrates(tmp_path) -> None:
    policy = _single_epub_policy()
    policy["sources"].append(
        _epub_source(id="fandom_01", type="fandom", path="books/01-book.fandom", authority=50)
    )
    policy["conflict_resolution"] = {"strategy": "flag_for_review", "on_unresolved": "fail"}
    canon = load_canon(_write_canon(tmp_path, policy))
    with pytest.raises(ValueError, match="cannot arbitrate"):
        canon.resolve_source("01-book")


def test_unknown_strategy_raises_at_load_not_at_arbitration(tmp_path) -> None:
    """A single-source series must not swallow a typo until a second one appears."""
    policy = _single_epub_policy()
    policy["conflict_resolution"]["strategy"] = "vibes"
    with pytest.raises(ValueError, match="unknown conflict_resolution.strategy 'vibes'"):
        load_canon(_write_canon(tmp_path, policy))


def test_unknown_on_unresolved_raises_at_load(tmp_path) -> None:
    policy = _single_epub_policy()
    policy["conflict_resolution"]["on_unresolved"] = "shrug"
    with pytest.raises(ValueError, match="unknown conflict_resolution.on_unresolved 'shrug'"):
        load_canon(_write_canon(tmp_path, policy))


def test_resolve_book_source_without_canon_reads_file_path(tmp_path) -> None:
    epub = tmp_path / "library" / "a" / "s" / "books" / "01-book.epub"
    epub.parent.mkdir(parents=True)
    epub.touch()
    assert resolve_book_source(epub) == epub


def test_resolve_book_source_uses_the_declared_source(tmp_path) -> None:
    series = tmp_path / "library" / "a" / "s"
    anchor = series / "books" / "01-book.epub"
    anchor.parent.mkdir(parents=True)
    anchor.touch()
    policy = _single_epub_policy()
    policy["sources"] = [_epub_source(book="01-book", path="books/01-book.reference.epub")]
    _write_canon(series, policy)
    assert resolve_book_source(anchor) == series / "books" / "01-book.reference.epub"


def test_resolve_book_source_undeclared_book_warns_and_reads_file_path(tmp_path, capsys) -> None:
    series = tmp_path / "library" / "a" / "s"
    anchor = series / "books" / "02-book.epub"
    anchor.parent.mkdir(parents=True)
    anchor.touch()
    _write_canon(series, _single_epub_policy())
    assert resolve_book_source(anchor) == anchor
    assert "declares no source for '02-book'" in capsys.readouterr().err


def test_shipped_throne_of_glass_canon_agrees_with_its_book_yaml() -> None:
    """The declared canon source and the book YAML's file_path are the same file."""
    series = PROJECT_ROOT / "library" / "sarah_j_maas" / "throne-of-glass"
    canon = load_canon(series / "canon.yaml")
    source = canon.resolve_source("01-throne-of-glass")
    assert canon.primary_source == "epub"
    assert source.type == "epub"

    book = yaml.safe_load((series / "books" / "01-throne-of-glass.yaml").read_text())
    assert canon.source_path(source) == PROJECT_ROOT / book["file_path"]
