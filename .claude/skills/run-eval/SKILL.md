---
name: run-eval
description: Pick and run the right research/ eval for a quality question, and keep its CI contract intact. Use when the user asks "which eval proves X", "run the NER/alias/relation eval", "mesure ça", or when a change to extraction/aliasing/relations/coref needs a number before shipping.
---

# run-eval

The project norm: a load-bearing number is **swept, not guessed** — and almost
every sweep is `claude:local` (GPU, gold corpora, EPUBs, API keys — none of it
exists in a web sandbox). If the evidence needs a live LLM run, **stop and ask
first** (CLAUDE.local.md); this skill's job is picking the right eval and
running only its LLM-free parts.

## Question → eval map

| Question | Where | Needs |
|---|---|---|
| NER recall/precision, label choice, threshold | `research/ner-eval` (gold + `sweep_labels.py`) | GLiNER/torch, gold — local |
| Alias merge precision (who merged wrongly/missed) | `research/alias-eval` | gold — local for full sweep |
| Typed-relation accuracy | `research/relation-eval`; offline scoring: `make eval-relationships PREDICTIONS=<file>` (STU-499 gold fixture, LLM-free) | local for `--run` |
| Character-graph quality | `research/graph-eval` | local |
| Embedding disambiguation | `research/embedding-eval` — **already falsified** (STU-468: topic dominates intra-book; shipped opt-in/OFF). Re-read its README before re-proposing the idea | — |
| Death/status extraction | `research/death-circumstance-eval` | local |
| Coref gain | `make run-coref` path + `scripts/eval_coref.py` | GPU — local |

Read `research/README.md` and `research/CLAUDE.md` first — each eval runs in
its own process (hyphenated-dir namespace collision), and the working rules
there are the ones agents keep breaking.

## CI contract (the part that ships red)

Creating `tests/` inside an eval **opts it into CI**, which installs `[dev]`
and nothing else — no torch, no GLiNER, no gold, no keys:

- `pytest.importorskip("torch")` at module level with no other test file →
  zero tests collected → pytest exit **5** → red job (STU-576). "All my tests
  skip" is a red CI, not a green one.
- The shape that works: the **protocol** (pair building, masking, scoring,
  splitting) in a module with no heavy import, tested unconditionally; the
  heavy-dep tests gated in their own file.
- Verify by actually hiding the dep and checking the exit code is 0, not 5 —
  never by assuming.

## Reporting a number

State: which eval, which gold/fixture, which model/provider produced the
predictions, and the exact command. A number without its provider is
unusable — two runs of the same series can sit on different models, and a
"regression" measured across that boundary measures the model. If the sweep
could not run (web sandbox, no GPU), ship the change with "not verified —
needs <exact local command>" and leave the run to the user; never extrapolate
a number from a subset (STU-497/539).
