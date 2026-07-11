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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
