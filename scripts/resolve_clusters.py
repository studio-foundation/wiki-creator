#!/usr/bin/env python3
"""
Stage: resolve-clusters (script executor, no LLM)

Converts clustered entities from split-clusters output into resolved entities.
Each cluster is already a group of co-referent mentions (produced by fuzzy matching
in the extraction pipeline). This script just maps them to the resolved entity format.

Singles (entity_count == 1) come pre-resolved in singles_resolved and are included as-is.
Multi-clusters: each cluster → one entity. No splitting, no inventing. Pure mapping.

Input: splits.json on disk, written by the split-clusters stage of the
wiki-extraction pipeline. It is a different `studio run`, so its stage output
never reaches this pipeline's context.

Output (stdout):
  { "entities": [...all resolved...], "narrator": null }
"""

import json
import re
import sys
from pathlib import Path

import yaml


from wiki_creator import studio_io
from wiki_creator.canonicalize import canonical_tokens
from wiki_creator.entity_taxonomy import resolution_types
from wiki_creator.lang import load_lang_config
from wiki_creator.types import Splits


def _default_noise_words() -> frozenset[str]:
    en = frozenset(load_lang_config("en").get("noise_words", []))
    fr = frozenset(load_lang_config("fr").get("noise_words", []))
    return en | fr


def _default_title_prefixes() -> frozenset[str]:
    en = frozenset(load_lang_config("en").get("title_prefixes", []))
    fr = frozenset(load_lang_config("fr").get("title_prefixes", []))
    return en | fr


_NOISE_WORDS = _default_noise_words()
_TITLE_PREFIXES = _default_title_prefixes()
_WORD = re.compile(r"[^\W_]+")


def name_tokens(name: str) -> frozenset[str]:
    """Order- and punctuation-free token set of a name.

    Matches the epub's declared author against the extracted surface however the
    two are written: ``Baum, L. Frank`` (DC creator) vs ``L. FRANK BAUM`` (title
    page).
    """
    return frozenset(_WORD.findall(name.lower()))


def is_relevant(
    name: str,
    noise_words: frozenset[str] = _NOISE_WORDS,
    author_tokens: frozenset[str] = frozenset(),
    author_surname: frozenset[str] = frozenset(),
) -> bool:
    """Heuristic: is this a real proper noun worth keeping?"""
    if not name:
        return False
    cleaned = name.strip()
    if len(cleaned) < 2:
        return False
    if cleaned.lower() in noise_words:
        return False
    # Proper nouns start with uppercase
    if cleaned[0].islower():
        return False
    # The book's own author is title/copyright-page (or foreword) boilerplate,
    # not a character (STU-740/744) — derived from the epub metadata, so no
    # stopword list to curate. A subset match (post title-stripping) catches a
    # bare "Mr. Baum" the STU-740 equality check missed; a one-token subset
    # ("Frank") is only the author, not a coincidentally-named character, when
    # that token is the author's own surname.
    if author_tokens:
        entity_tokens = frozenset(canonical_tokens(cleaned, _TITLE_PREFIXES))
        if entity_tokens and entity_tokens.issubset(author_tokens):
            if len(entity_tokens) > 1 or entity_tokens.issubset(author_surname):
                return False
    return True


def cluster_to_entity(
    cluster: dict,
    noise_words: frozenset[str] = _NOISE_WORDS,
    author_tokens: frozenset[str] = frozenset(),
    author_surname: frozenset[str] = frozenset(),
) -> dict:
    """Map a cluster directly to a resolved entity. No invention."""
    return {
        "canonical_name": cluster.get("canonical_candidate", ""),
        "type": cluster.get("type", "OTHER"),
        "aliases": cluster.get("all_mentions", []),
        "source_ids": cluster.get("entity_ids", []),
        "relevant": is_relevant(
            cluster.get("canonical_candidate", ""), noise_words, author_tokens, author_surname
        ),
    }


def resolve(
    splits: dict,
    noise_words: frozenset[str] = _NOISE_WORDS,
    author_tokens: frozenset[str] = frozenset(),
    author_surname: frozenset[str] = frozenset(),
) -> dict:
    entities: list[dict] = []

    # Singles: already in resolved format, but split-clusters stamps them
    # relevant=True unconditionally — the noise check happens here, or a bare
    # "The" reaches classification and gets a page (STU-740).
    for single in splits.get("singles_resolved", []):
        entities.append({
            **single,
            "relevant": is_relevant(
                single.get("canonical_name", ""), noise_words, author_tokens, author_surname
            ),
        })

    # Multi-clusters: one cluster = one entity, no LLM needed
    by_type = splits.get("by_type") or {}
    for entity_type in resolution_types():
        clusters = by_type.get(entity_type, [])
        if not isinstance(clusters, list):
            print(f"Warning: {entity_type} is not a list, skipping", file=sys.stderr)
            continue
        for cluster in clusters:
            entities.append(cluster_to_entity(cluster, noise_words, author_tokens, author_surname))

    return {"entities": entities, "narrator": None}


def _declared_author(processing: Path) -> str:
    """The epub's own `author` metadata, as written by epub-parse."""
    try:
        data = json.loads((processing / "epub_data.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(data.get("author") or "")


def _declared_author_tokens(processing: Path) -> frozenset[str]:
    return name_tokens(_declared_author(processing))


def _declared_author_surname(processing: Path) -> frozenset[str]:
    """The author's surname tokens, from either DC-creator order (``Baum, L.
    Frank``) or title-page order (``L. Frank Baum``) — the token that, alone,
    still identifies the author rather than a coincidentally-named character."""
    author = _declared_author(processing).strip()
    if not author:
        return frozenset()
    if "," in author:
        return name_tokens(author.split(",", 1)[0])
    parts = author.split()
    return name_tokens(parts[-1]) if parts else frozenset()


def main() -> None:
    payload = studio_io.read_payload()
    paths = studio_io.paths_from_payload(payload)
    splits_path = paths.processing / "splits.json"
    if not splits_path.exists():
        print(
            f"[ERROR] {splits_path} not found. Run wiki-extraction first:\n"
            "  studio run wiki-extraction --input-file <book.yaml>",
            file=sys.stderr,
        )
        sys.exit(1)
    splits = studio_io.to_dict(studio_io.load_artifact(splits_path, Splits))

    noise_words = _NOISE_WORDS
    raw_context = payload.get("additional_context", "")
    if raw_context:
        try:
            ctx = yaml.safe_load(raw_context) or {}
            language = (
                ctx.get("export", {}).get("categories", {}).get("language")
                or ctx.get("language")
                or "en"
            )
            lang_noise = frozenset(load_lang_config(language).get("noise_words", []))
            if lang_noise:
                noise_words = lang_noise
        except Exception:
            pass

    result = resolve(
        splits,
        noise_words=noise_words,
        author_tokens=_declared_author_tokens(splits_path.parent),
        author_surname=_declared_author_surname(splits_path.parent),
    )
    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
