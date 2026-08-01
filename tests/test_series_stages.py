"""The wiki-series stages (STU-709): assemble reads the tomes from disk, export
renders the series wiki under output/_series/.
"""
import io
import json
import sys

import pytest
import yaml

from scripts import series_assemble as sa
from scripts import series_export as se
from wiki_creator.paths import series_output_dir

RECURRING_ENTITY = {
    "entity_id": "l", "canonical_name": "Cowardly Lion", "entity_type": "PERSON",
    "aliases": ["Cowardly Lion"],
}


def _tome(series_dir, book_id: str, pages: list[dict], events: list[dict] | None = None):
    (series_dir / "books").mkdir(parents=True, exist_ok=True)
    (series_dir / "books" / f"{book_id}.yaml").write_text(
        yaml.safe_dump({"file_path": f"books/{book_id}.epub", "generation": {}}),
        encoding="utf-8",
    )
    processing = series_dir / "processing_output" / book_id
    processing.mkdir(parents=True, exist_ok=True)
    (processing / "wiki_pages.json").write_text(json.dumps({"pages": pages}), encoding="utf-8")
    (processing / "events.json").write_text(json.dumps({"events": events or []}), encoding="utf-8")
    (processing / "epub_data.json").write_text(
        json.dumps({"title": f"Tome {book_id}", "author": "A. Author"}), encoding="utf-8"
    )


def _page(title: str, importance: str = "principal", entity_type: str = "PERSON", **extra) -> dict:
    return {"title": title, "importance": importance, "entity_type": entity_type,
            "content": f"{title} did things.", **extra}


def _registry(series_dir, entities: list[dict]) -> None:
    (series_dir / "registry.json").write_text(
        json.dumps({"version": 1, "entities": entities, "decisions": [], "warnings": []}),
        encoding="utf-8",
    )


def _series(tmp_path, *, entities=None, pages=None) -> "object":
    series_dir = tmp_path / "sarah_j_maas" / "throne-of-glass"
    _tome(series_dir, "01-tome", pages or [_page("Celaena", "secondary")])
    _tome(series_dir, "02-tome", pages or [_page("Celaena", "principal")])
    _registry(series_dir, entities or [
        {"entity_id": "c", "canonical_name": "Celaena", "entity_type": "PERSON", "aliases": ["Celaena"]},
    ])
    return series_dir


def _run_main(module, payload: dict) -> dict:
    stdin_backup, stdout_backup, argv_backup = sys.stdin, sys.stdout, sys.argv
    try:
        sys.stdin = io.StringIO(json.dumps(payload))
        sys.stdout = io.StringIO()
        sys.argv = [module.__name__]
        module.main()
        return json.loads(sys.stdout.getvalue())
    finally:
        sys.stdin, sys.stdout, sys.argv = stdin_backup, stdout_backup, argv_backup


# --- assemble --------------------------------------------------------------

def test_assemble_reads_tome_artifacts_from_disk_not_from_stage_context(monkeypatch, tmp_path):
    """STU-455 at series scope: each tome ran as its own `studio run`, so its
    pages can only come from disk. Feed a contradictory payload and the disk wins
    — otherwise a loader stage could come back unnoticed."""
    series_dir = _series(tmp_path)
    monkeypatch.setattr(sa, "arc_from_payload", lambda *_a, **_k: None)

    out = _run_main(sa, {
        "additional_context": f"file_path: {series_dir}/books/01-tome.epub",
        "previous_outputs": {"pages-export": {"pages": [_page("Nehemia")]}},
        "all_stage_outputs": {"wiki-export": {"pages": [_page("Nehemia")]}},
    })

    assert out["characters"] == 1
    assembly = json.loads((series_dir / "series_assembly.json").read_text(encoding="utf-8"))
    assert [c["canonical_name"] for c in assembly["characters"]] == ["Celaena"]


def test_assemble_writes_hub_and_merged_characters(tmp_path):
    series_dir = _series(tmp_path)

    assembly = sa.build_assembly(series_dir)

    assert assembly["series_title"] == "Throne Of Glass"
    assert assembly["hub"]["author"] == "A. Author"
    assert [t["title"] for t in assembly["hub"]["tomes"]] == ["Tome 01-tome", "Tome 02-tome"]
    assert assembly["hub"]["main_characters"] == ["Celaena"]
    (character,) = assembly["characters"]
    assert [c["book_id"] for c in character["contributions"]] == ["01-tome", "02-tome"]
    assert character["importance"] == "principal"  # latest-wins
    assert assembly["arc"] is None


def test_assemble_drops_failed_pages(tmp_path):
    series_dir = _series(tmp_path, pages=[_page("Celaena", _failed=True)])

    assembly = sa.build_assembly(series_dir)

    assert assembly["characters"] == []


def test_assemble_requires_the_series_registry(tmp_path):
    series_dir = _series(tmp_path)
    (series_dir / "registry.json").unlink()

    with pytest.raises(SystemExit):
        sa.build_assembly(series_dir)


DOROTHY_ENTITY = {
    "entity_id": "d", "canonical_name": "Dorothy", "entity_type": "PERSON", "aliases": ["Dorothy"],
}


def _oz_series(tmp_path, total_tomes: int, secondary_in: tuple[int, ...]) -> "object":
    """A series where 'Cowardly Lion' is 'secondary' in the given tomes and has
    no page at all in the rest — never 'principal' anywhere (STU-738). Every
    tome also publishes a 'Dorothy' page, so every tome counts as published
    (the recurrence denominator) regardless of whether the Lion has a page in it."""
    series_dir = tmp_path / "l_frank_baum" / "oz"
    for i in range(1, total_tomes + 1):
        pages = [_page("Dorothy", "principal")]
        if i in secondary_in:
            pages.append(_page("Cowardly Lion", "secondary"))
        _tome(series_dir, f"{i:02d}-tome", pages)
    _registry(series_dir, [RECURRING_ENTITY, DOROTHY_ENTITY])
    return series_dir


def test_assemble_includes_a_series_recurring_secondary_character(tmp_path):
    # The real Oz corpus (STU-738): secondary in tomes 01 and 03 of 6 published.
    series_dir = _oz_series(tmp_path, total_tomes=6, secondary_in=(1, 3))

    assembly = sa.build_assembly(series_dir)

    assert "Cowardly Lion" in assembly["hub"]["main_characters"]
    (character,) = (c for c in assembly["characters"] if c["canonical_name"] == "Cowardly Lion")
    assert character["importance"] == "secondary"  # never principal in any tome


def test_assemble_leaves_out_a_character_below_the_recurrence_share(tmp_path):
    series_dir = _oz_series(tmp_path, total_tomes=6, secondary_in=(1,))

    assert "Cowardly Lion" not in sa.build_assembly(series_dir)["hub"]["main_characters"]


def test_assemble_honors_a_canon_recurrence_override(tmp_path):
    series_dir = _oz_series(tmp_path, total_tomes=10, secondary_in=(1, 2, 3))
    assert "Cowardly Lion" not in sa.build_assembly(series_dir)["hub"]["main_characters"]

    (series_dir / "canon.yaml").write_text(yaml.safe_dump({"canon": {
        "primary_source": "epub",
        "sources": [{"id": "e", "type": "epub", "path": "books/01-tome.epub"}],
        "cross_tome": {"main_character_recurrence": {"share": 0.2}},
    }}), encoding="utf-8")

    assert "Cowardly Lion" in sa.build_assembly(series_dir)["hub"]["main_characters"]


# --- export ----------------------------------------------------------------

def test_export_writes_the_hub_and_one_page_per_entity(tmp_path):
    series_dir = _series(tmp_path, entities=[
        {"entity_id": "c", "canonical_name": "Celaena", "entity_type": "PERSON", "aliases": ["Celaena"]},
        {"entity_id": "r", "canonical_name": "Rifthold", "entity_type": "PLACE", "aliases": ["Rifthold"]},
    ], pages=[_page("Celaena"), _page("Rifthold", entity_type="PLACE")])
    sa.write_assembly(series_dir, sa.build_assembly(series_dir))

    result = se.export_series(series_dir)

    wiki_dir = series_output_dir(series_dir)
    assert wiki_dir == tmp_path / "sarah_j_maas" / "throne-of-glass" / "output" / "_series"
    hub = (wiki_dir / "Main_Page.wiki").read_text(encoding="utf-8")
    assert "Throne Of Glass" in hub and "[[Celaena]]" in hub
    assert (wiki_dir / "characters" / "Celaena.wiki").exists()
    assert (wiki_dir / "locations" / "Rifthold.wiki").exists()
    assert result["files_written"] > 3


def test_export_renders_the_arc_into_the_hub(tmp_path):
    series_dir = _series(tmp_path)
    sa.write_assembly(
        series_dir, sa.build_assembly(series_dir, arc="An assassin becomes a queen.")
    )

    se.export_series(series_dir)

    hub = (series_output_dir(series_dir) / "Main_Page.wiki").read_text(encoding="utf-8")
    assert "An assassin becomes a queen." in hub


def test_export_is_a_full_rebuild(tmp_path):
    series_dir = _series(tmp_path)
    sa.write_assembly(series_dir, sa.build_assembly(series_dir))
    se.export_series(series_dir)
    stale = series_output_dir(series_dir) / "characters" / "Gone.wiki"
    stale.write_text("stale", encoding="utf-8")

    se.export_series(series_dir)

    assert not stale.exists()


def test_export_reads_the_assembly_from_disk_not_from_stage_context(tmp_path):
    """The assemble stage output carries counts, never the pages — the export
    reads the artifact (STU-455)."""
    series_dir = _series(tmp_path)
    sa.write_assembly(series_dir, sa.build_assembly(series_dir))

    out = _run_main(se, {
        "additional_context": f"file_path: {series_dir}/books/01-tome.epub",
        "previous_outputs": {"series-assemble": {"characters": 99, "tomes": 99}},
    })

    assert out["files_written"] > 0
    assert (series_output_dir(series_dir) / "characters" / "Celaena.wiki").exists()


def test_export_without_an_assembly_exits(tmp_path):
    series_dir = _series(tmp_path)

    with pytest.raises(SystemExit):
        se.export_series(series_dir)
