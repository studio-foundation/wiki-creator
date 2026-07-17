# death-circumstance-eval (STU-565)

| decides | for |
|---|---|
| whether the STU-552 death circumstance (`agent`/`place` on the entity-status verdict) renders a **false fact** on Eragon's verified `deceased` verdicts | shipping it unmeasured — STU-552 shipped on the *claim* that every failure path drops the field; this buys the number |

STU-488 earned the `death` **chapter** slot its removal by measuring it: 3 of 4
derived chapters wrong on Eragon's verified verdicts. STU-552's replacement — the
in-universe circumstance — shipped unmeasured. This clears it against the same
bar, on the same four verdicts (no new gold).

## The two numbers (STU-565's split)

* **False circumstance rate** — a rendered `agent`/`place` that is *not what the
  novel says*. The one that matters: a false killer reaches a page nobody
  rereads. **Result: 0.**
* **Recall** — verdicts where the text *does* state a killer/place but the gates
  dropped it. Non-zero by design (the quote/type gates are strict), cheap, worth
  the size not the fix. **Result: low** (see `results.md`).

## Why there is no live run here

STU-552's correctness is entirely in the *deterministic gate*
(`wiki_creator.entity_status.parse_status_verdict`). The model only proposes a
circumstance; the gate decides what renders. So the measurement feeds the gate
the novel's real death sentences and the model's **best case** — it proposes the
true killer/place — and any dropped field is charged to the gate, not the model.
No EPUB, no API key, byte-for-byte reproducible. An adversarial arm feeds the
gate *false* circumstances (including the exact one the ticket believed) to prove
the 0 is the gate rejecting them, not the harness only offering truths.

## Run

    cd research/death-circumstance-eval && PYTHONPATH=../.. python measure.py
    cd research/death-circumstance-eval && PYTHONPATH=../.. python -m pytest tests/ -q

No extra dependencies — reuses `wiki_creator/` (per the `research/` rule: measure
the real code, never a restatement of it). `corpus.py` holds the verdicts and the
roster typing; `measure.py` runs the gate and computes the metrics; `results.md`
is the report.
