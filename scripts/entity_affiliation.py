#!/usr/bin/env python3
"""Pre-step: entity-affiliation — which faction does each character belong to?

Usage:
    python scripts/entity_affiliation.py --book library/.../book.yaml

Input:  processing_output/<slug>/registry.json
Output: processing_output/<slug>/entity_affiliation.json

Runs before wiki-preparation, which stamps the verdict onto the batch entity so
`generate_wiki_pages.py` can render the `affiliation` infobox slot.

A pre-step and not a wiki-resolution stage, for STU-488's reasons: it changes no
identity, and resolution is chained by `make golden`, which stays LLM-free by
construction.

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
from wiki_creator.entity_affiliation import (
    parse_affiliation_verdict,
    roster_rows,
)
from wiki_creator.roster import load_cache, render_roster, save_cache
from wiki_creator.lang import book_language, load_lang_config
from wiki_creator.paths import book_paths_from_yaml
from wiki_creator.registry import Registry

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_TIMEOUT_SECONDS = 600


def contexts_by_entity(registry: Registry) -> dict[str, list[dict]]:
    """Per-PERSON context sentences with the chapter each came from.

    The chapter rides along because `select_affiliation_snippets` sorts by it.
    """
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


def resolve_affiliation(rows: list[dict], book_title: str, cache_path: Path) -> dict[str, dict]:
    """Verified affiliation per character, from cache or one `studio run`.

    Never raises. Every failure path returns {} — every character then renders no
    `affiliation` slot, which is what an OPT slot with no value does.
    """
    cached = load_cache(cache_path, rows)
    if cached is not None:
        return cached
    # A verdict for another roster must not survive a failure below:
    # `wiki_preparation.load_affiliation_verdicts` is roster-blind and would
    # replay a stale artifact.
    Path(cache_path).unlink(missing_ok=True)

    item_input = {"book_title": book_title, "roster": render_roster(rows)}
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".yaml", delete=False) as tmp:
        yaml.safe_dump(item_input, tmp, sort_keys=False, allow_unicode=True)
        input_path = tmp.name

    cmd = ["studio", "run", "entity-affiliation-item", "--input-file", input_path, "--json"]
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
    run_payload = studio_io.extract_first_json_object(result.stdout or "")
    if run_payload is None:
        return _give_up("studio_output_json_parse_error", rows)

    stage_output = studio_io.extract_stage_output_from_run_payload(
        run_payload, "entity-affiliation-item"
    )
    if stage_output is None:
        run_id = str(run_payload.get("id") or "").strip()
        if run_id:
            stage_output = studio_io.load_studio_stage_output(run_id, "entity-affiliation-item")
    if stage_output is None:
        return _give_up("studio_run_output_missing", rows)

    verdicts = parse_affiliation_verdict(stage_output, rows)
    save_cache(cache_path, rows, verdicts)
    return verdicts


def _give_up(error: str, rows: list[dict]) -> dict[str, dict]:
    print(
        f"[entity-affiliation] WARNING: {error} — none of the {len(rows)} characters "
        "render an affiliation",
        file=sys.stderr,
    )
    return {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Decide each character's faction for this book")
    parser.add_argument("--book", required=True, help="Path to the book YAML")
    args = parser.parse_args()

    book_cfg = yaml.safe_load(Path(args.book).read_text(encoding="utf-8")) or {}
    paths = book_paths_from_yaml(args.book)

    cache_path = paths.processing / "entity_affiliation.json"

    registry = Registry.load_from_processing(paths.processing)
    if registry is None:
        print(
            f"[entity-affiliation] registry.json not found in {paths.processing} — "
            "no character renders an affiliation",
            file=sys.stderr,
        )
        Path(cache_path).unlink(missing_ok=True)
        return

    lang_cfg = load_lang_config(book_language(book_cfg))
    markers = list(lang_cfg.get("affiliation_markers", []))
    if not markers:
        print(
            "[entity-affiliation] no `affiliation_markers` in this language's cue_words — "
            "no snippet can be selected, so no character renders an affiliation",
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
            "[entity-affiliation] no PERSON entity with context — nothing to decide",
            file=sys.stderr,
        )
        Path(cache_path).unlink(missing_ok=True)
        return

    rows = roster_rows(persons, contexts, markers)
    verdicts = resolve_affiliation(
        rows,
        book_title=str(book_cfg.get("title") or paths.processing.name),
        cache_path=cache_path,
    )

    print(
        f"[entity-affiliation] {len(verdicts)}/{len(rows)} characters have a faction; "
        "the rest render no slot",
        file=sys.stderr,
    )
    for name, verdict in sorted(verdicts.items()):
        print(f"[entity-affiliation]   {name}: {verdict['affiliation']}", file=sys.stderr)


if __name__ == "__main__":
    main()
