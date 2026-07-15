#!/usr/bin/env python3
"""Render results.md from gold + per-arm predictions. Pure (stdlib)."""
import json
import sys

from score import gold_support, load_jsonl, score

ARMS = ["tok2vec", "spacy_stock", "gliner"]

CAVEATS = """## What these numbers are not

**Raw NER output.** Production runs six filters after `doc.ents` (`KEPT_LABELS`,
`_truncate_span`, `_is_valid_mention`, `_is_valid_span`, context retagging,
`min_mentions >= 3`), which would clean up much of the stock-spaCy noise counted
here as false positives. That layer sits downstream of the model choice and is
identical for whichever arm wins, so it is out of scope — but it means the
precision column is not page-level precision.

**Gold is LLM-annotated, unadjudicated.** Surfaces come from `claude-opus-4-8`,
offsets are computed in Python (`build_gold.py`). The annotator invented zero
surfaces not present in the passage, but nobody has hand-checked its type calls.
A human adjudication pass over a sample is the missing measurement.

**GLiNER's labels were chosen on this gold.** The sweep scores each candidate
label against the same spans reported here, so GLiNER's numbers are mildly
optimistic. Same posture as STU-401.

**EVENT is not measured.** Two gold spans in 182k characters of prose. Any EVENT
number in this report is noise. Named events are rare in narrative text — this is
a property of the domain, not of the corpus.
"""


def _pct(x: float) -> str:
    return f"{x:.3f}"


def render(gold: dict, preds_by_arm: dict, labels: dict | None) -> str:
    scored = {a: score(gold, p) for a, p in preds_by_arm.items()}
    arms = list(preds_by_arm)
    support = gold_support(gold)

    out = ["# NER bake-off on Eragon — results (STU-470)\n"]
    out.append(
        "One book absent from `ner_dataset/`, so `wiki-ner-en` is scored on text it "
        "was not trained on. 120 chunks, 182k characters, "
        f"{sum(support.values())} gold spans.\n"
    )

    out.append("## Gold support (recall denominators)\n")
    out.append("| type | " + " | ".join(support) + " |")
    out.append("|---|" + "---|" * len(support))
    out.append("| n | " + " | ".join(str(v) for v in support.values()) + " |")
    out.append("")

    out.append("## Detection — was the span found at all (label ignored)\n")
    out.append("The convention-free axis: fair across architectures.\n")
    out.append("| arm | precision | recall | F1 |")
    out.append("|---|---|---|---|")
    for a in arms:
        g = scored[a]["detection_overlap"]["global"]
        out.append(f"| {a} | {_pct(g['precision'])} | {_pct(g['recall'])} | {_pct(g['f1'])} |")
    out.append("")

    out.append("## Typing — span found AND labelled correctly\n")
    out.append("| arm | precision | recall | F1 |")
    out.append("|---|---|---|---|")
    for a in arms:
        g = scored[a]["typing_overlap"]["global"]
        out.append(f"| {a} | {_pct(g['precision'])} | {_pct(g['recall'])} | {_pct(g['f1'])} |")
    out.append("")

    for axis, title in [("detection_overlap", "Detection recall by gold type"),
                        ("typing_overlap", "Typing F1 by type")]:
        key = "recall" if axis.startswith("detection") else "f1"
        out.append(f"## {title}\n")
        out.append("| type | n | " + " | ".join(arms) + " |")
        out.append("|---|---|" + "---|" * len(arms))
        for t in support:
            row = [t, str(support[t])]
            for a in arms:
                cell = scored[a][axis]["per_type"].get(t)
                row.append(_pct(cell[key]) if cell else "—")
            out.append("| " + " | ".join(row) + " |")
        out.append("")

    out.append("## Boundary drift (detection F1: overlap − exact)\n")
    out.append("How often an arm finds the span but cuts it differently than the gold.\n")
    out.append("| arm | overlap | exact | gap |")
    out.append("|---|---|---|---|")
    for a in arms:
        ov = scored[a]["detection_overlap"]["global"]["f1"]
        ex = scored[a]["detection_exact"]["global"]["f1"]
        out.append(f"| {a} | {_pct(ov)} | {_pct(ex)} | {_pct(ov - ex)} |")
    out.append("")

    if labels:
        out.append("## GLiNER labels selected by the sweep\n")
        out.append("| type | winning label |")
        out.append("|---|---|")
        for t, label in labels.items():
            out.append(f"| {t} | `{label}` |")
        out.append("")

    out.append(recommendation())
    out.append(CAVEATS)
    return "\n".join(out)


def recommendation() -> str:
    """The verdict is prose and is written by hand; results.md is regenerated."""
    try:
        with open("recommendation.md", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "## Recommendation\n\n_Write recommendation.md and re-run report.py._\n"


def main() -> None:
    gold = load_jsonl("gold.jsonl")
    preds = {}
    for a in ARMS:
        try:
            preds[a] = load_jsonl(f"predictions.{a}.jsonl")
        except FileNotFoundError:
            print(f"skipping {a}: predictions.{a}.jsonl not found", file=sys.stderr)
    labels = None
    try:
        with open("gliner_labels_selected.json", encoding="utf-8") as f:
            labels = json.load(f)
    except FileNotFoundError:
        pass
    with open("results.md", "w", encoding="utf-8") as f:
        f.write(render(gold, preds, labels))
    print("wrote results.md")


if __name__ == "__main__":
    main()
