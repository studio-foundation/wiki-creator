#!/usr/bin/env python3
"""Stage series-assemble (STU-709): every tome's artifacts, joined into one series model.

Reads each tome's ``{wiki_pages,entity_status,events}.json`` **from disk** — the
tomes ran as separate `studio run` invocations, so nothing about them reaches this
stage through Studio's context (STU-455). The series registry is the identity join
(STU-668/706), the hub is the front page's deterministic frame (STU-707), and its
arc slot is filled by the one generative pass (STU-708, cached).

Writes ``<series>/series_assembly.json``, which `series-export` renders.

Usage:
    python scripts/series_assemble.py --series library/<author>/<series>
    python scripts/series_assemble.py --book library/<author>/<series>/books/01-x.yaml
    python scripts/series_assemble.py --series <series_dir> --no-arc   # skip the LLM pass
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from scripts.generate_series_arc import arc_from_payload, run_for_series
from wiki_creator import studio_io
from wiki_creator.lang import book_language, load_lang_config
from wiki_creator.paths import book_paths_from_yaml
from wiki_creator.registry import Registry
from wiki_creator.series import (
    TomeArtifacts,
    build_series_characters,
    discover_series_books,
    load_tome_artifacts,
    series_title,
)
from wiki_creator.series_hub import SeriesTome, build_series_hub

ASSEMBLY_FILENAME = "series_assembly.json"


def _epub_meta(processing_dir: Path) -> dict:
    try:
        data = json.loads((processing_dir / "epub_data.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load_tomes(books: list[Path]) -> tuple[list[TomeArtifacts], list[SeriesTome], str]:
    """Each tome's artifacts in reading order, its hub entry, and the series author.

    A tome whose page generation failed contributes nothing for that entity — a
    ``_failed`` page has no content to merge into a series page.
    """
    artifacts: list[TomeArtifacts] = []
    entries: list[SeriesTome] = []
    author = ""
    for book in books:
        paths = book_paths_from_yaml(book)
        tome = load_tome_artifacts(paths.processing, book.stem)
        tome.pages = [p for p in tome.pages if not p.get("_failed")]
        meta = _epub_meta(Path(paths.processing))
        author = author or str(meta.get("author") or "")
        artifacts.append(tome)
        entries.append(SeriesTome(book_id=book.stem, title=str(meta.get("title") or book.stem)))
    return artifacts, entries, author


def _determiners(books: list[Path]) -> frozenset[str]:
    """The first tome's language determiners — what the canonical key strips from
    a page title (STU-724). Language is a property of the series, so the first
    tome answers for it, as the arc and the labels already assume."""
    try:
        cfg = yaml.safe_load(books[0].read_text(encoding="utf-8")) or {}
        lang_cfg = load_lang_config(book_language(cfg))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"[series-assemble] warning: no determiners ({exc})", file=sys.stderr)
        return frozenset()
    return frozenset(lang_cfg.get("determiners") or [])


def build_assembly(series_dir: Path | str, *, arc: str | None = None) -> dict:
    series_dir = Path(series_dir)
    books = discover_series_books(series_dir)
    artifacts, entries, author = load_tomes(books)

    registry = Registry.load_from_processing(series_dir)
    if registry is None:
        raise SystemExit(
            f"[series-assemble] no series registry at {series_dir / 'registry.json'} — "
            "run the tomes first"
        )

    characters = build_series_characters(registry, artifacts, _determiners(books))
    hub = build_series_hub(series_title(series_dir), author, entries, characters)
    return {
        "series_dir": str(series_dir),
        "series_title": hub.series_title,
        "arc": arc,
        "hub": studio_io.to_dict(hub),
        "characters": [studio_io.to_dict(c) for c in characters],
    }


def write_assembly(series_dir: Path | str, assembly: dict) -> Path:
    path = Path(series_dir) / ASSEMBLY_FILENAME
    path.write_text(json.dumps(assembly, ensure_ascii=False), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Assemble the series wiki model (STU-709)")
    parser.add_argument("--series", help="Series directory (standalone mode)")
    parser.add_argument("--book", help="Any tome's YAML — its series is assembled (standalone mode)")
    parser.add_argument("--timeout", type=int, default=120, help="Arc LLM timeout (seconds)")
    parser.add_argument("--no-arc", action="store_true", help="Skip the arc pass (no LLM call)")
    args, _ = parser.parse_known_args()

    standalone = bool(args.series or args.book)
    if standalone:
        series_dir = (
            Path(args.series) if args.series else book_paths_from_yaml(args.book).series_dir
        )
        # Standalone: the arc is one nested `studio run` subprocess.
        arc = None if args.no_arc else run_for_series(series_dir, timeout=args.timeout)
    else:
        # Studio stdin mode: the input is any tome's yaml; the tome artifacts come
        # from disk, never from the payload (STU-455). The arc was generated by the
        # native `series-arc-verdict` call, never by a subprocess (STU-720).
        payload = studio_io.read_payload()
        series_dir = studio_io.paths_from_payload(payload).series_dir
        arc = arc_from_payload(payload)

    assembly = build_assembly(series_dir, arc=arc)
    path = write_assembly(series_dir, assembly)
    print(
        f"[series-assemble] {len(assembly['characters'])} entities over "
        f"{len(assembly['hub']['tomes'])} tomes -> {path}",
        file=sys.stderr,
    )
    if not standalone:
        studio_io.write_output({
            "series_dir": assembly["series_dir"],
            "tomes": len(assembly["hub"]["tomes"]),
            "characters": len(assembly["characters"]),
            "arc": bool(assembly["arc"]),
        })


if __name__ == "__main__":
    main()
