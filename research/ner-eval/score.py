"""Scorer for the NER bake-off. Pure, stdlib-only.

Two independent axes, because they answer different questions:

  detection  span found, label ignored. Convention-free: a zero-shot model that
             finds "the Varden" but calls it something we did not ask for is
             still detecting it. This is the fair axis across architectures.
  typing     span found AND label equal. Conventions matter here, which favours
             any model trained on the same annotator's conventions as the gold.

Each axis is measured overlap-lenient (primary) and exact (secondary); the gap
between them is boundary drift.

Matching is any-overlap in both directions, not a strict one-to-one alignment:
one prediction covering two gold spans counts as a hit for both. Standard for
lenient NER eval, and it cannot silently favour one model over another.
"""
import json


def overlaps(a: dict, b: dict) -> bool:
    return a["start"] < b["end"] and b["start"] < a["end"]


def exact(a: dict, b: dict) -> bool:
    return a["start"] == b["start"] and a["end"] == b["end"]


def load_jsonl(path: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rec = json.loads(line)
                out[rec["id"]] = rec
    return out


def _prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f, 4),
            "tp": tp, "fp": fp, "fn": fn}


def _matched(span: dict, others: list[dict], span_match, typed: bool) -> bool:
    return any(
        span_match(span, o) and (not typed or span.get("label") == o.get("label"))
        for o in others
    )


def _axis(gold_cases: dict, pred_cases: dict, span_match, typed: bool) -> dict:
    """One (detection|typing) x (overlap|exact) cell: global + per-type P/R/F1."""
    per_type: dict[str, dict[str, int]] = {}

    def slot(label: str) -> dict:
        return per_type.setdefault(label, {"tp_g": 0, "fn": 0, "tp_p": 0, "fp": 0})

    g_tp = g_fn = p_tp = p_fp = 0
    for cid, gcase in gold_cases.items():
        preds = pred_cases.get(cid, {}).get("spans", [])
        for gs in gcase["spans"]:
            hit = _matched(gs, preds, span_match, typed)
            g_tp += hit
            g_fn += not hit
            s = slot(gs["label"])
            s["tp_g" if hit else "fn"] += 1
        for ps in preds:
            hit = _matched(ps, gcase["spans"], span_match, typed)
            p_tp += hit
            p_fp += not hit
            s = slot(ps["label"])
            s["tp_p" if hit else "fp"] += 1

    return {
        "global": _prf(p_tp, p_fp, g_fn),
        "per_type": {
            label: _prf(s["tp_p"], s["fp"], s["fn"])
            for label, s in sorted(per_type.items())
        },
        # Recall is gold-anchored; precision is prediction-anchored. With
        # any-overlap matching the two true-positive counts need not agree, so
        # keep the gold-side recall separately rather than reconciling them.
        "recall_global": round(g_tp / (g_tp + g_fn), 4) if g_tp + g_fn else 0.0,
    }


def score(gold_cases: dict, pred_cases: dict) -> dict:
    return {
        "detection_overlap": _axis(gold_cases, pred_cases, overlaps, typed=False),
        "detection_exact": _axis(gold_cases, pred_cases, exact, typed=False),
        "typing_overlap": _axis(gold_cases, pred_cases, overlaps, typed=True),
        "typing_exact": _axis(gold_cases, pred_cases, exact, typed=True),
    }


def gold_support(gold_cases: dict) -> dict[str, int]:
    """Gold span count per type — the denominator behind every recall number."""
    counts: dict[str, int] = {}
    for case in gold_cases.values():
        for s in case["spans"]:
            counts[s["label"]] = counts.get(s["label"], 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))
