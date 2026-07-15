"""Pure scoring logic for the relationship-classifier eval harness (STU-499).

The relationship classifier is an LLM stage with no golden coverage: it is
excluded from the deterministic e2e goldens (non-deterministic output) and the
only existing test checks structural validity, not typing quality. Five sibling
issues (STU-472/476/477/495/496) all tune the SAME prompt, so a change that
recovers mentor/authority relations can silently re-open the hallucination
surface the current gate closes (Westfall↔Kaltain) with no test to catch it.

This module turns "blind prompt tuning" into "measured change": given a
hand-labelled fixture of pairs (gold typing on Throne of Glass book 1) and a set
of predictions, it computes per-class precision/recall plus the two rates the
classifier's defects live in — the false-null rate (over-nulling real relations,
STU-495) and the hallucination rate (typing pure co-occurrence, the
Westfall↔Kaltain case).

Everything here is pure: no LLM, no I/O beyond fixture loading. The heavy path
(running the classifier per pair) lives in ``scripts/eval_relationship_classifier.py``.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from wiki_creator.relationship_types import usable_relationship_type

NULL_LABEL = "null"


def _label(relationship_type: object) -> str:
    """Display label for a relationship type; the sentinel/None collapse to ``null``."""
    return usable_relationship_type(relationship_type) or NULL_LABEL


def pair_key(entity_a: str, entity_b: str) -> tuple[str, str]:
    """Order-insensitive identity of a pair (matches eval_coref.relationship_key)."""
    return tuple(sorted((entity_a, entity_b)))  # type: ignore[return-value]


@dataclass(frozen=True)
class GoldPair:
    """One hand-labelled pair.

    ``acceptable`` is the set of relationship types a correct classifier may
    return, as display labels (``NULL_LABEL`` for "must stay null"). The first
    entry is the primary label used for the per-class confusion matrix; any other
    entry is an equally-correct answer for a genuinely ambiguous pair (e.g. a
    guard/prisoner bond that reads as ``ami`` or ``allié``).
    """

    entity_a: str
    entity_b: str
    acceptable: tuple[str, ...]
    note: str = ""
    cooccurrence_count: int = 0
    sample_contexts: tuple[str, ...] = ()

    @property
    def key(self) -> tuple[str, str]:
        return pair_key(self.entity_a, self.entity_b)

    @property
    def primary(self) -> str:
        return self.acceptable[0]

    @property
    def expects_null(self) -> bool:
        return set(self.acceptable) == {NULL_LABEL}

    @property
    def expects_relation(self) -> bool:
        return NULL_LABEL not in self.acceptable


@dataclass(frozen=True)
class EvalRow:
    """Per-pair scoring outcome, for the review table."""

    entity_a: str
    entity_b: str
    primary: str
    acceptable: tuple[str, ...]
    predicted: str
    verdict: str  # ok | false_null | hallucination | wrong_type


def load_gold(path: str | Path) -> list[GoldPair]:
    """Parse a gold fixture YAML into ``GoldPair`` records.

    A pair declares ``expected`` as either a single label, a list of acceptable
    labels, or ``null`` / ``[null]`` for the must-stay-null cases. YAML ``null``
    (or the string ``"null"``) becomes ``NULL_LABEL``.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    out: list[GoldPair] = []
    for entry in raw.get("pairs", []):
        expected = entry.get("expected")
        if isinstance(expected, list):
            acceptable = tuple(_label(x) for x in expected)
        else:
            acceptable = (_label(expected),)
        if not acceptable:
            raise ValueError(f"pair {entry.get('entity_a')}↔{entry.get('entity_b')} has no expected label")
        out.append(
            GoldPair(
                entity_a=entry["entity_a"],
                entity_b=entry["entity_b"],
                acceptable=acceptable,
                note=entry.get("note", ""),
                cooccurrence_count=int(entry.get("cooccurrence_count", 0)),
                sample_contexts=tuple(entry.get("sample_contexts", []) or ()),
            )
        )
    return out


def predictions_from_relationships(relationships: list[dict]) -> dict[tuple[str, str], str | None]:
    """Map ``pair_key -> predicted relationship_type`` from a classified bundle.

    Accepts the shape of ``relationships_classified.json`` (a list of relationship
    dicts). The sentinel string ``"null"`` normalizes to ``None`` via
    ``usable_relationship_type``.
    """
    out: dict[tuple[str, str], str | None] = {}
    for rel in relationships:
        a, b = rel.get("entity_a"), rel.get("entity_b")
        if not a or not b:
            continue
        out[pair_key(a, b)] = usable_relationship_type(rel.get("relationship_type"))
    return out


@dataclass
class ClassMetrics:
    precision: float | None
    recall: float | None
    f1: float | None
    tp: int
    fp: int
    fn: int
    support: int


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None or (precision + recall) == 0:
        return None
    return 2 * precision * recall / (precision + recall)


def score(gold: list[GoldPair], predictions: dict[tuple[str, str], str | None]) -> dict:
    """Score predictions against the gold fixture.

    ``predictions`` maps ``pair_key -> relationship_type`` (``None`` = null). A
    gold pair absent from ``predictions`` is scored as ``None`` and flagged in
    ``missing`` — never silently dropped, so a partial run reads as such.

    Returns a metrics dict with the two headline rates (``false_null_rate``,
    ``hallucination_rate``), overall/type accuracy, a per-class confusion, and
    per-pair rows for the report.
    """
    # confusion[true_label][pred_label]; an acceptable-alternate answer is
    # credited to the primary label so ambiguous pairs don't score as errors.
    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    rows: list[EvalRow] = []
    missing: list[GoldPair] = []

    for gp in gold:
        if gp.key in predictions:
            pred = _label(predictions[gp.key])
        else:
            pred = NULL_LABEL
            missing.append(gp)

        correct = pred in gp.acceptable
        y_pred = gp.primary if correct else pred
        confusion[gp.primary][y_pred] += 1

        if correct:
            verdict = "ok"
        elif pred == NULL_LABEL and gp.expects_relation:
            verdict = "false_null"
        elif gp.expects_null and pred != NULL_LABEL:
            verdict = "hallucination"
        else:
            verdict = "wrong_type"
        rows.append(EvalRow(gp.entity_a, gp.entity_b, gp.primary, gp.acceptable, pred, verdict))

    labels = sorted({t for row in confusion.values() for t in row} | set(confusion))
    per_class: dict[str, ClassMetrics] = {}
    for label in labels:
        tp = confusion.get(label, {}).get(label, 0)
        fp = sum(confusion[t].get(label, 0) for t in confusion if t != label)
        fn = sum(v for p, v in confusion.get(label, {}).items() if p != label)
        support = sum(confusion.get(label, {}).values())
        precision = tp / (tp + fp) if (tp + fp) else None
        recall = tp / (tp + fn) if (tp + fn) else None
        per_class[label] = ClassMetrics(precision, recall, _f1(precision, recall), tp, fp, fn, support)

    n_total = len(gold)
    n_relation = sum(1 for gp in gold if gp.expects_relation)
    n_null = sum(1 for gp in gold if gp.expects_null)
    correct_total = sum(1 for r in rows if r.verdict == "ok")
    correct_relation = sum(1 for gp, r in zip(gold, rows) if gp.expects_relation and r.verdict == "ok")
    false_null = sum(1 for r in rows if r.verdict == "false_null")
    hallucination = sum(1 for r in rows if r.verdict == "hallucination")
    wrong_type = sum(1 for r in rows if r.verdict == "wrong_type")

    return {
        "n_total": n_total,
        "n_expects_relation": n_relation,
        "n_expects_null": n_null,
        "overall_accuracy": correct_total / n_total if n_total else None,
        "type_accuracy": correct_relation / n_relation if n_relation else None,
        "false_null_count": false_null,
        "false_null_rate": false_null / n_relation if n_relation else None,
        "hallucination_count": hallucination,
        "hallucination_rate": hallucination / n_null if n_null else None,
        "wrong_type_count": wrong_type,
        "per_class": per_class,
        "confusion": {t: dict(row) for t, row in confusion.items()},
        "rows": rows,
        "missing": missing,
    }


def _pct(x: float | None) -> str:
    return f"{x * 100:.0f}%" if x is not None else "—"


def _num(x: float | None) -> str:
    return f"{x:.2f}" if x is not None else "—"


def render_report(book: str, metrics: dict) -> str:
    """Markdown report: headline rates, per-class table, per-pair verdicts."""
    m = metrics
    lines = [f"# Relationship-classifier eval — {book}", ""]
    lines += [
        "| Metric | Value |",
        "|---|---|",
        f"| Pairs | {m['n_total']} ({m['n_expects_relation']} typed, {m['n_expects_null']} null) |",
        f"| Overall accuracy | {_pct(m['overall_accuracy'])} |",
        f"| Type accuracy (typed pairs) | {_pct(m['type_accuracy'])} |",
        f"| **False-null rate** | {_pct(m['false_null_rate'])} ({m['false_null_count']}/{m['n_expects_relation']}) |",
        f"| **Hallucination rate** | {_pct(m['hallucination_rate'])} ({m['hallucination_count']}/{m['n_expects_null']}) |",
        f"| Wrong-type count | {m['wrong_type_count']} |",
    ]
    if m["missing"]:
        names = ", ".join(f"{gp.entity_a}↔{gp.entity_b}" for gp in m["missing"])
        lines.append(f"| Missing predictions | {len(m['missing'])} ({names}) |")
    lines += ["", "## Per-class", "", "| Class | Precision | Recall | F1 | Support |", "|---|---|---|---|---|"]
    for label, c in sorted(m["per_class"].items()):
        lines.append(f"| {label} | {_pct(c.precision)} | {_pct(c.recall)} | {_num(c.f1)} | {c.support} |")

    lines += ["", "## Per-pair", "", "| Pair | Expected | Predicted | Verdict |", "|---|---|---|---|"]
    order = {"false_null": 0, "hallucination": 1, "wrong_type": 2, "ok": 3}
    for r in sorted(m["rows"], key=lambda r: (order.get(r.verdict, 9), r.entity_a, r.entity_b)):
        expected = " / ".join(r.acceptable)
        mark = "✅" if r.verdict == "ok" else "❌"
        lines.append(f"| {r.entity_a} ↔ {r.entity_b} | {expected} | {r.predicted} | {mark} {r.verdict} |")
    return "\n".join(lines) + "\n"
