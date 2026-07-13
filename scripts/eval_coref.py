#!/usr/bin/env python3
"""Coref evaluation harness (STU-427).

Runs relationship extraction in three variants on one book and reports the
impact of fastcoref coreference resolution:

    baseline    coref off
    coref-8k    coref on, current 8000-char per-chapter cap
    coref-full  coref on, no cap (max_chars=0)

Each variant runs in its own subprocess (under /usr/bin/time -v when
available) for isolated wall-time and peak-RSS measurement. The harness is
read-only with respect to pipeline state: it imports functions from
scripts.relationship_extraction and writes only under
<processing>/coref_eval/.

Usage (from repo root):
    python scripts/eval_coref.py --book library/.../01-throne-of-glass.yaml --workers 4
    python scripts/eval_coref.py --book <book.yaml> --sample 30 --seed 42

Outputs, under <processing_output>/<slug>/coref_eval/:
    <variant>/mentions.json, relationships.json, stats.json
    report.md                metrics tables per variant
    sample_for_review.md     random sample of new attributions for manual ✓/✗
"""
from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

VARIANTS = ("baseline", "coref-8k", "coref-full")
VARIANT_MAX_CHARS = {"coref-8k": 8000, "coref-full": 0}


# ---------------------------------------------------------------- pure core

def count_sentences(mentions: dict) -> int:
    """Total number of mention sentences across all entities and chapters."""
    return sum(len(sents) for by_ch in mentions.values() for sents in by_ch.values())


def compute_mention_deltas(baseline: dict, variant: dict) -> dict:
    """Per-entity count of sentences present in variant but not in baseline."""
    per_entity: list[tuple[str, int]] = []
    total = 0
    for entity, by_ch in variant.items():
        base_by_ch = baseline.get(entity, {})
        added = 0
        for chapter_id, sentences in by_ch.items():
            base_set = set(base_by_ch.get(chapter_id, []))
            added += sum(1 for s in sentences if s not in base_set)
        if added:
            per_entity.append((entity, added))
            total += added
    per_entity.sort(key=lambda t: (-t[1], t[0]))
    return {"total_added": total, "per_entity": per_entity}


def relationship_key(rel: dict) -> tuple[str, str]:
    """Order-insensitive identity of an edge."""
    return tuple(sorted((rel["entity_a"], rel["entity_b"])))  # type: ignore[return-value]


def compute_relationship_deltas(baseline: list[dict], variant: list[dict]) -> dict:
    """Edges added / removed / re-weighted in variant relative to baseline."""
    base_by_key = {relationship_key(r): r for r in baseline}
    var_by_key = {relationship_key(r): r for r in variant}
    added = [var_by_key[k] for k in sorted(var_by_key.keys() - base_by_key.keys())]
    removed = [base_by_key[k] for k in sorted(base_by_key.keys() - var_by_key.keys())]
    reweighted = []
    for k in sorted(base_by_key.keys() & var_by_key.keys()):
        before = base_by_key[k].get("cooccurrence_count", 0)
        after = var_by_key[k].get("cooccurrence_count", 0)
        if before != after:
            reweighted.append({"pair": k, "before": before, "after": after})
    return {"added": added, "removed": removed, "reweighted": reweighted}


def new_sentences(baseline: dict, variant: dict) -> list[dict]:
    """All (entity, chapter_id, sentence) attributions present only in variant."""
    out: list[dict] = []
    for entity in sorted(variant):
        base_by_ch = baseline.get(entity, {})
        for chapter_id in sorted(variant[entity]):
            base_set = set(base_by_ch.get(chapter_id, []))
            for sentence in variant[entity][chapter_id]:
                if sentence not in base_set:
                    out.append({"entity": entity, "chapter_id": chapter_id, "sentence": sentence})
    return out


def sample_new_sentences(baseline: dict, variant: dict, n: int = 30, seed: int = 42) -> list[dict]:
    """Reproducible random sample of the new attributions."""
    pool = new_sentences(baseline, variant)
    if len(pool) <= n:
        return pool
    return random.Random(seed).sample(pool, n)


def extract_context(chapter_text: str, sentence: str, radius: int = 200) -> str:
    """±radius characters around the sentence; the sentence alone if not found."""
    idx = chapter_text.find(sentence)
    if idx < 0:
        return sentence
    start = max(0, idx - radius)
    end = min(len(chapter_text), idx + len(sentence) + radius)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(chapter_text) else ""
    return f"{prefix}{chapter_text[start:end]}{suffix}"


def parse_time_v(text: str) -> dict:
    """Extract peak RSS from GNU `time -v` stderr output."""
    m = re.search(r"Maximum resident set size \(kbytes\): (\d+)", text)
    return {"peak_rss_kb": int(m.group(1)) if m else None}


def _fmt_rss(kb: int | None) -> str:
    return f"{kb / 1024 / 1024:.1f} GB" if kb else "n/a"


def render_report(book: str, results: dict) -> str:
    """Markdown metrics report; `results` maps variant -> metrics dict."""
    lines = [f"# Coref evaluation — {book}", ""]
    lines += ["| Variant | Wall time (s) | Peak RSS | Pronoun sentences added |",
              "|---|---|---|---|"]
    for variant, r in results.items():
        lines.append(
            f"| {variant} | {r.get('wall_seconds', 0):.1f} | {_fmt_rss(r.get('peak_rss_kb'))} "
            f"| {r.get('pronoun_sentences_added', 0)} |"
        )
    for variant, r in results.items():
        md = r.get("mention_deltas")
        rd = r.get("relationship_deltas")
        if md is None or rd is None:
            continue
        lines += ["", f"## {variant} vs baseline", "",
                  f"Mention sentences added: **{md['total_added']}**", "",
                  "| Entity | Sentences added |", "|---|---|"]
        lines += [f"| {name} | {added} |" for name, added in md["per_entity"][:20]]
        lines += ["", f"Relationship edges — added: {len(rd['added'])}, removed: {len(rd['removed'])}, re-weighted: {len(rd['reweighted'])}", ""]
        if rd["added"]:
            lines += ["| New edge | Co-occurrences |", "|---|---|"]
            lines += [f"| {' ↔ '.join(relationship_key(rel))} | {rel.get('cooccurrence_count', '?')} |" for rel in rd["added"]]
            lines.append("")
        if rd["reweighted"]:
            lines += ["| Re-weighted edge | Before | After |", "|---|---|---|"]
            lines += [f"| {' ↔ '.join(rw['pair'])} | {rw['before']} | {rw['after']} |" for rw in rd["reweighted"]]
            lines.append("")
    return "\n".join(lines) + "\n"


def render_sample(samples: dict, chapters: dict) -> str:
    """Manual-review sheet; `samples` maps variant -> sample_new_sentences() output."""
    lines = ["# Coref attributions — manual review", "",
             "For each row: is the claimed referent the correct antecedent of the",
             "pronoun(s) in the sentence? Mark ✓ or ✗ in the last column.", ""]
    for variant, rows in samples.items():
        lines += [f"## {variant}", "",
                  "| # | Claimed referent | Chapter | Sentence (context) | ✓/✗ |",
                  "|---|---|---|---|---|"]
        for i, row in enumerate(rows, 1):
            ctx = extract_context(chapters.get(row["chapter_id"], ""), row["sentence"])
            ctx = ctx.replace("|", "\\|").replace("\n", " ")
            sent = row["sentence"].replace("|", "\\|")
            lines.append(f"| {i} | {row['entity']} | {row['chapter_id']} | **{sent}** — {ctx} | |")
        lines.append("")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------ orchestration

def variant_dir(processing: Path, variant: str) -> Path:
    return processing / "coref_eval" / variant


def build_child_command(variant: str, book_yaml: str, workers: int) -> list[str]:
    """Child invocation, wrapped in GNU time -v when available."""
    cmd = [sys.executable, str(Path(__file__).resolve()), "--variant-run", variant,
           "--book", str(book_yaml), "--workers", str(workers)]
    gnu_time = shutil.which("time")
    if gnu_time:
        cmd = [gnu_time, "-v"] + cmd
    return cmd


def _load_book(book_yaml: Path):
    """(paths, cfg, entities, chapters) for one book."""
    import yaml
    from wiki_creator.paths import book_paths_from_yaml

    paths = book_paths_from_yaml(book_yaml)
    with open(book_yaml, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    with open(paths.processing / "entities_classified.json", encoding="utf-8") as f:
        entities = json.load(f)["entities"]
    with open(paths.processing / "chapters.json", encoding="utf-8") as f:
        chapters = json.load(f).get("chapters", {})
    return paths, cfg, entities, chapters


def run_variant(book_yaml: Path, variant: str, workers: int) -> None:
    """Child mode: run one variant in-process and write its outputs."""
    from scripts.relationship_extraction import (
        DEFAULT_MIN_CHAPTERS_TOGETHER,
        DEFAULT_THRESHOLD,
        DEFAULT_WINDOW,
        _load_mentions_from_files,
        build_cooccurrence_graph,
        enrich_mentions_with_fastcoref,
    )

    paths, cfg, entities, chapters = _load_book(book_yaml)
    mentions = _load_mentions_from_files(paths.processing)
    sentences_before = count_sentences(mentions)

    if variant != "baseline":
        mentions = enrich_mentions_with_fastcoref(
            chapters, entities, mentions,
            workers=workers,
            spacy_model=cfg.get("spacy_model", "fr_core_news_lg"),
            max_chars=VARIANT_MAX_CHARS[variant],
        )

    min_cooc = cfg.get("min_cooccurrence")
    relationships, stats = build_cooccurrence_graph(
        entities, mentions,
        int(cfg.get("window", DEFAULT_WINDOW)),
        int(cfg.get("threshold", DEFAULT_THRESHOLD)),
        min_cooccurrence=int(min_cooc) if min_cooc is not None else None,
        min_chapters_together=int(cfg.get("min_chapters_together", DEFAULT_MIN_CHAPTERS_TOGETHER)),
    )
    stats["pronoun_sentences_added"] = count_sentences(mentions) - sentences_before

    out = variant_dir(paths.processing, variant)
    out.mkdir(parents=True, exist_ok=True)
    for name, data in (("mentions.json", mentions), ("relationships.json", relationships), ("stats.json", stats)):
        with open(out / name, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[eval/{variant}] wrote {out} — {stats['pronoun_sentences_added']} pronoun sentences added", file=sys.stderr)


def run_all(book_yaml: Path, workers: int, sample_n: int, seed: int, variants: tuple[str, ...] = VARIANTS) -> Path:
    """Parent mode: run every variant, compute deltas, write report + sample."""
    paths, _cfg, _entities, chapters = _load_book(book_yaml)
    eval_root = paths.processing / "coref_eval"
    results: dict[str, dict] = {}

    for variant in variants:
        print(f"[eval] running {variant}…", file=sys.stderr)
        t0 = time.monotonic()
        proc = subprocess.run(
            build_child_command(variant, str(book_yaml), workers),
            capture_output=True, text=True,
        )
        wall = time.monotonic() - t0
        sys.stderr.write(proc.stderr)
        if proc.returncode != 0:
            raise RuntimeError(f"variant {variant} failed (exit {proc.returncode})")
        with open(variant_dir(paths.processing, variant) / "stats.json", encoding="utf-8") as f:
            stats = json.load(f)
        results[variant] = {
            "wall_seconds": wall,
            "pronoun_sentences_added": stats.get("pronoun_sentences_added", 0),
            **parse_time_v(proc.stderr),
        }

    def _load(variant: str, name: str):
        with open(variant_dir(paths.processing, variant) / name, encoding="utf-8") as f:
            return json.load(f)

    base_mentions = _load("baseline", "mentions.json")
    base_rels = _load("baseline", "relationships.json")
    samples: dict[str, list[dict]] = {}
    for variant in variants:
        if variant == "baseline":
            continue
        var_mentions = _load(variant, "mentions.json")
        results[variant]["mention_deltas"] = compute_mention_deltas(base_mentions, var_mentions)
        results[variant]["relationship_deltas"] = compute_relationship_deltas(base_rels, _load(variant, "relationships.json"))
        samples[variant] = sample_new_sentences(base_mentions, var_mentions, n=sample_n, seed=seed)

    (eval_root / "report.md").write_text(render_report(paths.processing.name, results), encoding="utf-8")
    (eval_root / "sample_for_review.md").write_text(render_sample(samples, chapters), encoding="utf-8")
    print(f"[eval] report: {eval_root / 'report.md'}", file=sys.stderr)
    print(f"[eval] review sheet: {eval_root / 'sample_for_review.md'}", file=sys.stderr)
    return eval_root


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--book", required=True, help="path to the book .yaml")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--sample", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--variants", default=",".join(VARIANTS), help="comma-separated subset of variants")
    parser.add_argument("--variant-run", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.variant_run:
        run_variant(Path(args.book), args.variant_run, args.workers)
        return
    run_all(Path(args.book), args.workers, args.sample, args.seed, tuple(args.variants.split(",")))


if __name__ == "__main__":
    main()
