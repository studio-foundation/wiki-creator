# public_domain invented-world flip (STU-616)

The `public_domain/` example library shipped every book on the spaCy default, so
the GLiNER / `invented_names` path — the bulk of recent NER work (STU-521/535/537)
— was never demoed on distributable content. The invented-world books there have
exactly the spaCy failure mode the flip exists for: invented proper nouns typed
ORG/PERSON wrongly (Odyssey: **217 ORG** out of 648 raw spans; Oz 01: **45 ORG**).

## Method

Identical to STU-535 — `run_arms.py` (spaCy, GLiNER t0.5, GLiNER t0.3) through the
shipped extractor, then `oracle_types.py` (one `claude-opus-4-8` verdict over the
union of the arms at each book's `min_mentions_absolute`, here 3). Not a gold
corpus: it measures *which arm this book should declare*, blind to any entity no
arm found. Driver: `batch_all.sh` → `flip_measure.sh` (per-book parse → 3 arms →
oracle → save roster). Run on CPU (`WIKI_NER_DEVICE=cpu`) — a concurrent worktree
held the GPU.

Caveats carried from STU-535: GLiNER's borderline spans are not deterministic
(±1 entity between runs), and the rubric names no entity under test.

## Result — every invented-world book flips, all at threshold 0.3

`typing` = candidates typed correctly / union size. PERSON/PLACE columns compare
the shipped arm (GLiNER t0.3) against spaCy.

| book | union | spaCy | t0.5 | **t0.3** | Δ | PERSON t0.3 vs spaCy | PLACE t0.3 vs spaCy |
|---|---|---|---|---|---|---|---|
| Alice in Wonderland | 36 | 18 | 15 | **20** | +2 | 19/20 r19 vs 14/16 r14 | 1/1 r1 vs 2/3 r2 |
| The Call of Cthulhu | 33 | 17 | 18 | **20** | +3 | 10/12 r10 vs 8/13 r8 | 8/10 r8 vs 7/8 r7 |
| Oz 1 · Wonderful Wizard | 61 | 22 | 34 | **40** | +18 | 27/29 r27 vs 12/16 r12 | 7/8 r7 vs 8/10 r8 |
| Oz 2 · Marvelous Land | 65 | 21 | 33 | **38** | +17 | 30/38 r30 vs 17/25 r17 | 3/6 r3 vs 2/3 r2 |
| Oz 3 · Ozma of Oz | 59 | 28 | 33 | **36** | +8 | 27/34 r27 vs 23/30 r23 | 6/9 r6 vs 2/2 r2 |
| Oz 4 · Dorothy & the Wizard | 63 | 26 | 36 | **43** | +17 | 28/31 r28 vs 20/27 r20 | 12/12 r12 vs 4/7 r4 |
| Oz 5 · The Road to Oz | 88 | 36 | 53 | **60** | +24 | 44/49 r44 vs 28/35 r28 | 11/11 r11 vs 6/7 r6 |
| Oz 6 · Emerald City | 124 | 52 | 68 | **68** | +16 | 45/56 r45 vs 43/65 r43 | 15/24 r15 vs 7/7 r7 |
| The Odyssey | 211 | 94 | 160 | **173** | +79 | 113/116 r113 vs 69/85 r69 | 42/49 r42 vs 23/39 r23 |

Threshold 0.3 beats 0.5 on typing in every book (ties it on Oz 6), matching
STU-535: 0.5 leaves invented types on the table. All nine now declare
`invented_names: true` + `threshold: 0.3`.

## Reading the two soft rows honestly

Alice (+2) and Cthulhu (+3) sit inside the range where a typing delta alone is
near the ±1 nondeterminism. They flip on the **PERSON** column, not the typing
count: Alice's talking-creature cast lifts PERSON recall 14→19 at precision
19/20, and Cthulhu also takes PLACE (8/10 vs 7/8). That is the exact
invented-cast failure the flip targets, so the small typing margin is not the
load-bearing number there.

Oz 1's PLACE is the one cell spaCy edges (8/10 recall 8 vs GLiNER 7/8 recall 7) —
swamped by PERSON 27/29 vs 12/16.

## Left on spaCy — real-world casts, not the failure mode

Not flipped, and deliberately: their proper nouns are names spaCy has read.

- **Dracula** (Harker, Van Helsing, Transylvania, Whitby)
- **Journey to the Centre of the Earth** + **Voyage au centre de la terre** (Verne, en/fr)
- **Notre-Dame de Paris** (Quasimodo, Esmeralda, Paris)

A book of real-world names should not pay GLiNER's runtime, and STU-537's asymmetry
holds: a false GLiNER flip costs precision on names spaCy already types right.

## Reproduce

    # one book (from repo root; book must be parsed or the driver parses it)
    WIKI_NER_DEVICE=cpu bash research/ner-eval/flip_measure.sh \
      public_domain/homer/the_odyssey/books/01-the_odyssey.yaml

    # all nine
    bash research/ner-eval/batch_all.sh   # writes research/ner-eval/stu616/ (gitignored)

Needs the `[models]` + `[gliner]` extras and a `claude` CLI for the oracle. The
per-book oracle rosters land in `research/ner-eval/stu616/oracle_<slug>.json`
(gitignored, regenerable).
