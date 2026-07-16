"""Scorer for the relation-discovery bake-off (STU-467). Pure, stdlib-only.

The unit is a book-level pair, not a chunk-level triple, because the gap the
ticket names lives in the aggregate: "did we ever discover that Eragon is
Garrow's nephew" is not a question any single passage answers.

Three axes, because collapsing them hides the finding:

  detection  pair found, type ignored. The only axis that is fair across
             architectures: co-occurrence emits no type at all, so scoring it
             on type would score the LLM classifier bolted after it.
  typing     pair found AND type in the gold's acceptable set. Reported two
             ways — conditional on detection (how good is the typer, given the
             pair reached it) and end-to-end (what the reader actually gets).
             The conditional number flatters any arm with poor recall; the
             end-to-end one is the one that decides.
  direction  on correctly-typed pairs only. Direction on a wrong type is not a
             partial credit, it is a different claim.

`acceptable` is a set, not a scalar: relations evolve inside one book (Eragon
and Murtagh go wary_alliance -> friend), and a gold that forces one token would
score a correct reading as an error. Same convention as the STU-499 fixture.

The implicit/explicit split is the point of the exercise, not a nicety: the
ticket's charge against co-occurrence is that it cannot see a relation whose
two names never share a window. That charge is only measurable if the gold says
which relations those are, so every axis is also reported per stratum.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from wiki_creator.relationship_eval import pair_key  # noqa: E402
from wiki_creator.relationship_types import usable_relationship_type  # noqa: E402

NULL_LABEL = "null"


def _label(value) -> str:
    """A type the reader would never see is scored as no type at all (STU-501)."""
    return usable_relationship_type(value) or NULL_LABEL


def _prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f = 2 * p * r / (p + r) if p and r else None
    return {
        "precision": round(p, 4) if p is not None else None,
        "recall": round(r, 4) if r is not None else None,
        "f1": round(f, 4) if f is not None else None,
        "tp": tp, "fp": fp, "fn": fn,
    }


def index_gold(pairs: list[dict]) -> dict:
    """{pair_key: gold} — gold pairs are the positives; everything else is a negative."""
    return {pair_key(p["entity_a"], p["entity_b"]): p for p in pairs}


def index_predictions(pairs: list[dict]) -> dict:
    return {pair_key(p["entity_a"], p["entity_b"]): p for p in pairs}


def _acceptable_list(gold: dict) -> list[str]:
    """Declaration order is meaningful: the first token is the pair's primary."""
    raw = gold.get("acceptable") or []
    if isinstance(raw, str):
        raw = [raw]
    return [_label(t) for t in raw]


def _acceptable(gold: dict) -> set[str]:
    return set(_acceptable_list(gold))


def _primary(gold: dict) -> str:
    tokens = _acceptable_list(gold)
    return tokens[0] if tokens else NULL_LABEL


def _detection(gold: dict, pred: dict, keys: set) -> dict:
    """Pair found, type ignored. keys = the gold stratum under test."""
    tp = sum(1 for k in keys if k in pred)
    fn = len(keys) - tp
    # A predicted pair outside the gold is a false positive only if the gold is
    # exhaustive over this roster. It is built by a per-chapter sweep of the
    # whole book, so a pair no chapter evidenced is a genuine over-connection —
    # the crowd-scene failure the ticket predicts. Stated in README as a caveat.
    fp = sum(1 for k in pred if k not in gold)
    return _prf(tp, fp, fn)


def _typing(gold: dict, pred: dict, keys: set) -> dict:
    """Per-type P/R/F1, end-to-end: an undiscovered pair is a typing miss too."""
    per_type: dict[str, dict[str, int]] = {}

    def slot(label: str) -> dict:
        return per_type.setdefault(label, {"tp": 0, "fp": 0, "fn": 0})

    hits = 0
    for k in keys:
        g = gold[k]
        acceptable = _acceptable(g)
        primary = _primary(g)
        predicted = _label((pred.get(k) or {}).get("relationship_type"))
        hit = predicted in acceptable
        hits += hit
        if hit:
            # Credit an acceptable alternate to the primary token, so per-type
            # support sums to the gold's own distribution.
            slot(primary)["tp"] += 1
        else:
            slot(primary)["fn"] += 1
            if predicted != NULL_LABEL:
                slot(predicted)["fp"] += 1

    for k in pred:
        if k not in gold:
            predicted = _label(pred[k].get("relationship_type"))
            if predicted != NULL_LABEL:
                slot(predicted)["fp"] += 1

    tp = sum(s["tp"] for s in per_type.values())
    fp = sum(s["fp"] for s in per_type.values())
    fn = sum(s["fn"] for s in per_type.values())
    return {
        "global": _prf(tp, fp, fn),
        "accuracy_end_to_end": round(hits / len(keys), 4) if keys else None,
        "per_type": {label: _prf(s["tp"], s["fp"], s["fn"]) for label, s in sorted(per_type.items())},
    }


def _typing_conditional(gold: dict, pred: dict, keys: set) -> dict | None:
    """Type accuracy over pairs the arm actually discovered.

    Flatters low recall by construction — an arm that emits one pair and types
    it right scores 1.0 here. Reported next to n so the flattery is visible.
    """
    found = [k for k in keys if k in pred]
    if not found:
        return None
    hits = sum(1 for k in found if _label(pred[k].get("relationship_type")) in _acceptable(gold[k]))
    return {"accuracy": round(hits / len(found), 4), "n": len(found)}


def _direction(gold: dict, pred: dict, keys: set) -> dict | None:
    """Direction accuracy over correctly-typed pairs only."""
    typed = [
        k for k in keys
        if k in pred and _label(pred[k].get("relationship_type")) in _acceptable(gold[k])
    ]
    scored = [k for k in typed if gold[k].get("direction")]
    if not scored:
        return None
    hits = sum(1 for k in scored if (pred[k].get("direction") or "") == gold[k]["direction"])
    return {"accuracy": round(hits / len(scored), 4), "n": len(scored)}


def _stratum(gold: dict, pred: dict, keys: set) -> dict:
    return {
        "n_gold": len(keys),
        "detection": _detection(gold, pred, keys),
        "typing": _typing(gold, pred, keys),
        "typing_conditional": _typing_conditional(gold, pred, keys),
        "direction": _direction(gold, pred, keys),
    }


def score(gold_pairs: list[dict], pred_pairs: list[dict]) -> dict:
    gold = index_gold(gold_pairs)
    pred = index_predictions(pred_pairs)
    all_keys = set(gold)
    implicit = {k for k in all_keys if gold[k].get("implicit")}

    return {
        "n_predicted": len(pred),
        "overall": _stratum(gold, pred, all_keys),
        "explicit": _stratum(gold, pred, all_keys - implicit),
        "implicit": _stratum(gold, pred, implicit),
        "missed": sorted(k for k in all_keys if k not in pred),
        "over_connected": sorted(k for k in pred if k not in gold),
    }


def gold_support(gold_pairs: list[dict]) -> dict[str, int]:
    """Gold pair count per primary type — the denominator behind every recall."""
    counts: dict[str, int] = {}
    for p in gold_pairs:
        primary = _primary(p)
        counts[primary] = counts.get(primary, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))
