# What type + direction at discovery costs (STU-540, step 4)

Measured, not estimated. Chunk counts come from parsing all 16 library EPUBs;
payload sizes from throne-of-glass's real classifier inputs; the pair count from a
post-STU-536/537 run of Eragon (173 pairs, matching the spike's fixed arm at 171).

## The two calls are the same size

| | tokens per call |
|---|---|
| per-pair classifier (today) | 5 972 |
| per-chunk schema pass (proposed) | 6 274 |

Both figures include the 3 775 tokens of Studio system prompt every stage pays
(agent yaml 9 547 chars + `invariants.md` 5 554, auto-injected).

## And there are about as many chunks as pairs

STU-536 cut Eragon from 501 pairs to 173. At 6 000 chars a chunk, Eragon's 60
narrative chapters are 174 chunks. So "one LLM call per chunk" — the phrasing that
made this sound expensive — buys roughly the call count the pipeline already makes.

| Eragon | tokens | ratio |
|---|---|---|
| today | 1 021k | 1.00x |
| schema **replaces** the classifier | 1 092k | 1.07x |
| schema **feeds** the classifier | 1 892k | 1.85x |

Library-wide (15 books, 2 986 chunks): 17.8M → 18.7M (replace) or 32.6M (feed).

## The replace column is not available

The schema pass emits `relationship_type`, `direction` and `evidence`. It does not
emit `evolution` or `key_moments`, and those are read by `generate_wiki_pages`,
`event_layer`, `build_character_graph` and `spoiler_blocks`. Dropping them
regresses the pages, so schema discovery *feeds* the per-pair classifier rather
than replacing it, and the real price is **1.85x, not 1.07x**. Aggregating an
`evolution` arc from chunk-level votes would recover the cheaper column; it is a
separate design, not a flag.

## Where the cost actually is

60% of every call, on both architectures, is the injected system prompt rather
than book text. If this ever needs to get cheaper, that is the lever — the choice
of discovery architecture is not.

Reproduce: `scripts/` in this directory plus `python report.py`. The chunk census
is `chunks.json` (regenerate by parsing the library; no LLM, no network).
