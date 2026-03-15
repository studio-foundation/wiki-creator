"""Convert a validated NER JSONL dataset to spaCy DocBin format.

Usage:
    python scripts/convert_to_docbin.py ner_dataset/*.jsonl \\
        --lang en --output-dir . --resolve-overlaps

Produces train.spacy and dev.spacy in the output directory.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from typing import Any

import spacy
from spacy.tokens import DocBin


def examples_to_docbin(
    examples: list[dict[str, Any]],
    nlp: spacy.language.Language,
) -> DocBin:
    """Convert a list of annotated examples to a spaCy DocBin.

    Invalid char spans (e.g. offsets that don't align with token boundaries)
    are silently skipped rather than crashing — spaCy's char_span returns None
    in that case.
    """
    db = DocBin()
    for ex in examples:
        text = ex["text"]
        doc = nlp.make_doc(text)
        ents = []
        for ent in ex.get("entities", []):
            span = doc.char_span(ent["start"], ent["end"], label=ent["label"])
            if span is not None:
                ents.append(span)
        doc.ents = ents
        db.add(doc)
    return db


def split_train_dev(
    examples: list[dict[str, Any]],
    *,
    dev_ratio: float = 0.2,
    seed: int = 42,
) -> tuple[list[dict], list[dict]]:
    """Shuffle and split examples into train / dev sets.

    Returns (train_examples, dev_examples).
    """
    indices = list(range(len(examples)))
    rng = random.Random(seed)
    rng.shuffle(indices)

    n_dev = round(len(examples) * dev_ratio)
    dev_indices = set(indices[:n_dev])

    train = [examples[i] for i in range(len(examples)) if i not in dev_indices]
    dev = [examples[i] for i in range(len(examples)) if i in dev_indices]
    return train, dev


def _load_jsonl(path: Path) -> list[dict]:
    examples = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                examples.append(json.loads(line))
    return examples


def main(
    paths: list[Path],
    *,
    lang: str = "en",
    output_dir: Path = Path("."),
    dev_ratio: float = 0.2,
    seed: int = 42,
    resolve_overlaps: bool = False,
) -> None:
    from scripts.validate_ner_dataset import validate_dataset

    all_examples: list[dict] = []
    for p in paths:
        examples = _load_jsonl(p)
        print(f"{p.name}: {len(examples)} examples loaded")
        all_examples.extend(examples)

    stats = validate_dataset(all_examples, resolve=resolve_overlaps)
    print(
        f"Validation: {stats['valid']}/{stats['total']} valid"
        + (f", {stats['rejected']} rejected" if stats["rejected"] else "")
    )
    valid = stats["valid_examples"]

    train_ex, dev_ex = split_train_dev(valid, dev_ratio=dev_ratio, seed=seed)
    print(f"Split: {len(train_ex)} train / {len(dev_ex)} dev")

    nlp = spacy.blank(lang)
    train_db = examples_to_docbin(train_ex, nlp)
    dev_db = examples_to_docbin(dev_ex, nlp)

    output_dir.mkdir(parents=True, exist_ok=True)
    train_path = output_dir / "train.spacy"
    dev_path = output_dir / "dev.spacy"
    train_db.to_disk(train_path)
    dev_db.to_disk(dev_path)
    print(f"Saved: {train_path}, {dev_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Convert NER JSONL to spaCy DocBin")
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--lang", default="en", help="spaCy blank model language code")
    parser.add_argument("--output-dir", type=Path, default=Path("."))
    parser.add_argument("--dev-ratio", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--resolve-overlaps", action="store_true")
    args = parser.parse_args()
    main(
        args.files,
        lang=args.lang,
        output_dir=args.output_dir,
        dev_ratio=args.dev_ratio,
        seed=args.seed,
        resolve_overlaps=args.resolve_overlaps,
    )
