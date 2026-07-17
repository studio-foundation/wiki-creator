#!/usr/bin/env python3
"""Pre-step: entity-species — which species/race is each character? (STU-574)

Usage:
    python scripts/entity_species.py --book library/.../book.yaml

Input:  processing_output/<slug>/registry.json
Output: processing_output/<slug>/entity_species.json

Runs before wiki-preparation, which stamps the verdict onto the batch entity so
`generate_wiki_pages.py` can render the `species` infobox slot.

A pre-step and not a wiki-resolution stage, for STU-488's reasons: it changes no
identity, and resolution is chained by `make golden`, which stays LLM-free by
construction.

Genre-gated (the slot is `genre_gated: true`): only a book whose world has
invented species has a species to attribute. A real-world-cast book skips the
stage entirely — the gate is `ner.invented_names`, the same signal that already
distinguishes those worlds, not a new key (STU-537: the property is the book's,
not the pipeline's).

Never fails a run: a book whose verdict cannot be obtained renders no slot at all,
loudly.
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from wiki_creator import studio_io
from wiki_creator.entity_species import (
    CACHE_VERSION,
    parse_species_verdict,
    roster_rows,
)
from wiki_creator.lang import book_language, load_lang_config
from wiki_creator.ner import ner_config
from wiki_creator.paths import book_paths_from_yaml
from wiki_creator.registry import Registry
from wiki_creator.roster import load_cache, render_roster, save_cache

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_TIMEOUT_SECONDS = 600


def contexts_by_entity(registry: Registry) -> dict[str, list[dict]]:
    """Per-PERSON context sentences with the chapter each came from."""
    contexts: dict[str, list[dict]] = {}
    for record in registry.entities:
        if record.entity_type != "PERSON":
            continue
        snippets = [
            {"text": mention.context.strip(), "chapter_id": mention.chapter_id}
            for mention in record.mentions
            if mention.context and mention.context.strip()
        ]
        if snippets:
            contexts[record.canonical_name] = snippets
    return contexts


def resolve_species(rows: list[dict], book_title: str, cache_path: Path) -> dict[str, dict]:
    """Verified species per character, from cache or one `studio run`.

    Never raises. Every failure path returns {} — every character then renders no
    `species` slot, which is what an OPT slot with no value does.
    """
    cached = load_cache(cache_path, rows, CACHE_VERSION)
    if cached is not None:
        return cached
    # A verdict for another roster must not survive a failure below:
    # `wiki_preparation.load_species_verdicts` is roster-blind and would replay a
    # stale artifact.
    Path(cache_path).unlink(missing_ok=True)

    item_input = {"book_title": book_title, "roster": render_roster(rows)}
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".yaml", delete=False) as tmp:
        yaml.safe_dump(item_input, tmp, sort_keys=False, allow_unicode=True)
        input_path = tmp.name

    cmd = ["studio", "run", "entity-species-item", "--input-file", input_path, "--json"]
    try:
        result = subprocess.run(
            cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=_TIMEOUT_SECONDS
        )
    except FileNotFoundError:
        return _give_up("studio_cli_missing", rows)
    except subprocess.TimeoutExpired:
        return _give_up("studio_run_timeout", rows)
    finally:
        Path(input_path).unlink(missing_ok=True)

    if result.returncode != 0:
        return _give_up("studio_run_failed", rows)
    stage_output = studio_io.stage_output_from_stdout(result.stdout or "", "entity-species-item")
    if stage_output is None:
        return _give_up("studio_run_output_missing", rows)

    verdicts = parse_species_verdict(stage_output, rows)
    save_cache(cache_path, rows, verdicts, CACHE_VERSION)
    return verdicts


def _give_up(error: str, rows: list[dict]) -> dict[str, dict]:
    print(
        f"[entity-species] WARNING: {error} — none of the {len(rows)} characters "
        "render a species",
        file=sys.stderr,
    )
    return {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Decide each character's species for this book")
    parser.add_argument("--book", required=True, help="Path to the book YAML")
    args = parser.parse_args()

    book_cfg = yaml.safe_load(Path(args.book).read_text(encoding="utf-8")) or {}
    paths = book_paths_from_yaml(args.book)

    cache_path = paths.processing / "entity_species.json"

    if not ner_config(book_cfg).invented_names:
        print(
            "[entity-species] this book's world has no invented species "
            "(ner.invented_names is false) — no character renders a species",
            file=sys.stderr,
        )
        Path(cache_path).unlink(missing_ok=True)
        return

    registry = Registry.load_from_processing(paths.processing)
    if registry is None:
        print(
            f"[entity-species] registry.json not found in {paths.processing} — "
            "no character renders a species",
            file=sys.stderr,
        )
        Path(cache_path).unlink(missing_ok=True)
        return

    lang_cfg = load_lang_config(book_language(book_cfg))
    markers = list(lang_cfg.get("species_markers", []))
    if not markers:
        print(
            "[entity-species] no `species_markers` in this language's cue_words — "
            "no snippet can be selected, so no character renders a species",
            file=sys.stderr,
        )
        Path(cache_path).unlink(missing_ok=True)
        return

    contexts = contexts_by_entity(registry)
    persons = [
        {"canonical_name": record.canonical_name, "aliases": record.aliases}
        for record in registry.entities
        if record.entity_type == "PERSON" and record.canonical_name in contexts
    ]
    if not persons:
        print(
            "[entity-species] no PERSON entity with context — nothing to decide",
            file=sys.stderr,
        )
        Path(cache_path).unlink(missing_ok=True)
        return

    rows = roster_rows(persons, contexts, markers)
    verdicts = resolve_species(
        rows,
        book_title=str(book_cfg.get("title") or paths.processing.name),
        cache_path=cache_path,
    )

    print(
        f"[entity-species] {len(verdicts)}/{len(rows)} characters have a species; "
        "the rest render no slot",
        file=sys.stderr,
    )
    for name, verdict in sorted(verdicts.items()):
        print(f"[entity-species]   {name}: {verdict['species']}", file=sys.stderr)


if __name__ == "__main__":
    main()
