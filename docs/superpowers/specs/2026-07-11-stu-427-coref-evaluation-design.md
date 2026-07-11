# STU-427 — Coreference Evaluation Design

**Date:** 2026-07-11
**Ticket:** [STU-427](https://linear.app/studioag/issue/STU-427/activerevaluer-la-resolution-de-coreference-par-defaut)
**Branch:** `arianedguay/stu-427-activerevaluer-la-resolution-de-coreference-par-defaut` (worktree off `main`)

## Goal

Produce empirical evidence for whether enabling fastcoref/LingMessCoref coreference
resolution measurably improves relationship and mention completeness on a real EPUB,
and at what RAM/time cost. The enable-by-default decision is a **checkpoint after the
numbers are reviewed** — it is explicitly out of scope for this build.

Book under test: Throne of Glass
(`library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml`). Its existing
`processing_output` (60 chapters, ~643k chars, median chapter ~10k chars) is reused;
no re-extraction.

## Background facts that shaped the design

- `enrich_mentions_with_fastcoref` (`scripts/relationship_extraction.py:619`) runs
  LingMessCoref per chapter and attributes pronoun sentences to known PERSON entities
  *before* the co-occurrence graph is built — so coref feeds both mention counts and
  relationships.
- The function only processes the **first 8,000 characters of each chapter**
  (hardcoded). Median ToG chapter is ~10k chars, max ~20.7k — "coref enabled" today is
  really "coref on chapter openings". Measuring only the as-is behavior risks
  concluding "gain is small" as an artifact of the cap.
- `--live --book <yaml> --coref --workers N` exists as a standalone CLI mode that
  reuses processing output, but it is **console-only**: it prints top-20
  relationships and stats and writes no files (its "validation" pairs are hardcoded
  Zafón characters). The harness therefore cannot shell out to `--live`; it imports
  the module's functions directly and writes its own outputs. Real pipeline files
  are never touched, so no snapshot/restore is needed.
- RAM per the docstring: ~3 GB at 1 worker, ~10 GB at 4 workers. Eval machine:
  38 GB RAM / 16 cores — 4 workers is comfortable.
- `biu-nlp/lingmess-coref` is **English-only**. French books in the library
  (e.g. *Le Jeu de l'Ange*) keep `coref: false` regardless of the outcome; any
  "default" is per-language (English books only). This becomes a documented
  limitation.
- Wrong pronoun attributions silently poison mention counts and can feed identity
  confusion downstream (STU-318 family), so precision matters as much as recall.
- Since the relicense, fastcoref is an extra: `pip install -e ".[coref]"` (pulls
  torch). Base installs fall back silently to the naive heuristic.

## Component 1 — Configurable coref cap (pre-eval code change)

Make the 8,000-char cap configurable, defaulting to current behavior:

- Add `max_chars: int = 8000` to `enrich_mentions_with_fastcoref` and thread it to
  `_coref_worker`; `0` means no cap (full chapter).
- Wire from the book YAML / `additional_context` as `coref_max_chars` (same pattern
  as `workers`, parsed in the executor path around
  `scripts/relationship_extraction.py:1404`).
- Wire from the CLI as `--coref-max-chars` for `--test`/`--live` modes.
- Unit tests cover the wiring (YAML key parsed, CLI flag parsed, default unchanged,
  `0` disables the cap). No other behavior in `relationship_extraction.py` changes.

## Component 2 — Eval harness: `scripts/eval_coref.py` (committed)

CLI: `python scripts/eval_coref.py --book <book.yaml> [--workers 4] [--sample 30]`.

For each variant — `baseline` (coref off), `coref-8k` (as-is cap), `coref-full`
(`max_chars=0`):

1. Spawn **itself** in a per-variant subprocess (internal `--variant-run` mode)
   under `/usr/bin/time -v`, so each variant gets isolated wall-time and peak-RSS
   measurements and models don't accumulate in one process.
2. The child process imports `_load_mentions_from_files`,
   `enrich_mentions_with_fastcoref` (with the variant's `max_chars`/`workers`), and
   `build_cooccurrence_graph` from `scripts/relationship_extraction.py`, runs the
   variant in memory, and writes `mentions.json` + `relationships.json` +
   `stats.json` into `<processing_output>/<slug>/coref_eval/<variant>/`.
3. Real pipeline files are never written — the eval is read-only with respect to
   pipeline state.

Then compute deltas vs baseline:

- pronoun sentences added per entity;
- top mention-count movers;
- relationship edges added / removed / re-weighted, highlighting edges touching
  high-mention entities.

Outputs, written under `<processing_output>/<slug>/coref_eval/`:

- `report.md` — metrics tables per variant (deltas, wall time, peak RSS).
- `sample_for_review.md` — for each coref variant, ~30 randomly sampled
  newly-attributed sentences with surrounding context, the claimed referent, and a
  blank ✓/✗ column for manual review.

Sampling is seeded (fixed default seed, overridable) so reruns are reproducible.

## Component 3 — Quality judgment & decision frame

Ariane reviews `sample_for_review.md` manually; precision = ✓/(✓+✗) per variant.

Decision frame (to be confirmed against actual numbers, not a hard gate):
recommend enabling by default **for English books** if precision ≥ ~90% **and** the
relationship graph gains meaningful edges among relevant entities, at a cost within
~10 GB / a few minutes at 4 workers. Otherwise, document the trade-off and leave
`coref: false`.

## Component 4 — Documentation deliverables (regardless of outcome)

- `docs/coref-evaluation.md` — results write-up: methodology, metrics, precision,
  cost, recommendation.
- `docs/flow-audit.md` gap §2 updated to point at the evaluation results.
- Activation doc: the `pip install -e ".[coref]"` extra, worker/RAM guidance,
  English-only limitation, `coref_max_chars` knob.
- Summary comment on STU-427 with numbers and recommendation.
- Flipping any `coref:` default happens only after the numbers are reviewed
  (separate checkpoint, possibly a follow-up commit on the same branch).

## Testing

- Delta computation, sampling, and report rendering in `eval_coref.py` are pure
  functions with unit tests (fixture JSON in, expected deltas out).
- Cap wiring tests per Component 1.
- Subprocess orchestration stays thin; verified by one smoke run on the real book
  rather than mocked tests.
- `pytest -q` must stay green (735 passed, 31 skipped baseline).

## Out of scope

- Changing any `coref:` default in book YAMLs (checkpoint decision).
- Per-tier (`principal`/`secondary`) coref gating — tiers are assigned by
  `entity-classification`, which runs *after* relationship-extraction (STU-276), so
  they don't exist at coref time. If the eval shows cost is the blocker, a
  pre-tier proxy (raw mention count) can be a follow-up ticket.
- French/multilingual coref models.
- Evaluating additional books (harness is reusable for that later).
