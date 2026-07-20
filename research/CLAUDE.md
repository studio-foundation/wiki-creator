# research/ — working rules

Read `README.md` first: it covers what lives here, why each eval runs in its own
process, and the namespace collision that follows from the hyphenated dirs. This
file is the rules an agent keeps breaking.

## A `tests/` directory is a CI contract, not a convenience

The CI step is a loop over `research/*-eval` that skips any eval with no `tests/`
and otherwise runs `pytest tests/ -q` under `bash -e`. So **creating `tests/`
opts the eval into CI**, and from that moment the job is red unless at least one
test actually runs there.

CI installs the repo's `[dev]` extra and **nothing else** — no torch, no GLiNER,
no GPU, no sentence-transformers, no `library/` EPUBs, no gold corpus, no API
key. None of it is installable there.

Two traps, both of which have shipped:

- **`pytest.importorskip("torch")` at module level skips the whole file.** With no
  other test file, pytest collects zero tests and exits **5**, which `bash -e`
  turns into a failed job. "All my tests skip" is not a green CI, it is a red one
  (STU-576).
- **A suite that only runs locally proves nothing in CI.** If every test needs the
  heavy dep, the eval has no regression protection at all — and the PR body will
  still say "N passed", because it did, on the machine with the GPU.

The shape that works: put the **protocol** — how a pair is built, masked, scored,
split — in a module with no heavy import, and test that unconditionally. Gate only
the tests that genuinely need the heavy dep, in their own file, and let the
protocol file carry CI.

    pairs.py          # numpy only          -> tests/test_pairs.py       (always runs)
    train_head.py     # imports torch       -> tests/test_train_head.py  (importorskip)

Verify before pushing, by actually hiding the dep rather than assuming:

    cd research/<name> && PYTHONPATH=../.. python -m pytest tests/ -q   # local
    # then re-run with the heavy import blocked and check the exit code is 0, not 5

## Test the protocol, never the measured number

A test that asserts `margin == -0.019` pins a result, and a result is not an
invariant — it moves with the model, the corpus and the seed. What is testable is
the *definition*: that a `same` pair is drawn from disjoint chapters, that the mask
is a constant so it carries no signal, that a negative margin means no single
threshold separates. Numbers live in `results*.md`, under the run that produced
them.

## `results*.md` is the deliverable; a negative is a result

The evals here exist to write down what was measured, especially when the answer
was no. Four spikes falsified embedding disambiguation; that record is the reason
nobody opens a fifth. **Deleting an eval's code must never delete its results**,
and a ticket that retires a feature keeps the `results*.md` that justified
retiring it.

## Never measure a premise on a subset artifact

The recurring project-wide error (STU-497 / STU-539 / STU-543): a 5-chapter
extraction cache, a fixture chosen for hermeticity, a 3-entity roster. Each
answers a *different question* than the full artifact, and a design built on the
subset's answer is built on nothing. STU-539's premise and STU-576's blocking
prerequisite were both measured false the moment someone looked at a real run.
Before designing around "there is no data for X", check the artifacts on disk.

## Production does not stay alive to serve an eval

If the last consumer of a `wiki_creator/` module is a script in here, the module
moves here — the code follows its consumer out of production, never the reverse
(STU-601). Conversely, an eval must not restate logic it is measuring: import it
from `wiki_creator/`, or a benchmark measures its own reimplementation.

## Outputs are gitignored and regenerable

Per-eval artifacts (arm extractions, verdicts, corpora, encodings) never get
committed — `research/*/arms/` is already ignored, add a line for anything new.
Every ignored path must be reproducible by a committed script, and the README
must name the command. What is committed: the code, the README, the results, and
any hand-written gold small enough to review.
