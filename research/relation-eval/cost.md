# What schema-guided discovery costs (STU-603)

Confirmed against the shipped stage, not priced in advance. The pre-ship estimate
this replaces (STU-540) parsed all 16 EPUBs for a chunk census and sampled
throne-of-glass classifier inputs for a token-per-call figure. It was never run.

## The bill was never actually run library-wide

Discovery has a live cache on **1 of the 15 books**: Narnia
(`relationships_discovered_votes.json`). Every other book's `processing_output/`
carries only the co-occurrence `relationships.json` (5 books) or no relationship
artifact at all. So the pre-ship "15 books, 2 986 chunks, 17.8M → 32.6M tokens"
table was a fresh-parse projection over EPUBs, not a measurement of anything that
ran. What follows is Narnia's actual cache plus a census of the 6 books whose
`epub_data.json` is on disk today.

## Actual call count — cold vs cached

One `studio run relationship-discovery-item` per chunk. The votes cache is keyed on
roster + prompt fingerprint, so once every chunk is cached a re-run costs **zero**
calls until the roster or the discovery prompt changes.

| book (live `epub_data`) | narrative ch. | chars | chunks @6k = cold calls | cached |
|---|---:|---:|---:|---:|
| the_way_of_kings | 97 | 2 200 670 | 97 | — |
| le-jeu-de-lange | 93 | 937 202 | 93 | — |
| eragon | 67 | 904 595 | 67 | — |
| the_hobbit | 20 | 506 616 | 20 | — |
| **narnia** | 17 | 198 199 | 45 | **40** |
| throne-of-glass | 1 | 1 125 | 1 | — |

Narnia is the only measured row: **40 chunks cached** (45 by today's census — the
5-chunk gap is a re-parse of `epub_data` since the run shifted paragraph packing),
9 of them returning no pair. A steady-state re-run of Narnia is **0 discovery
calls**. The recurring cost the ticket worried about is a one-time cost **per
(book, roster)**, amortized to zero by the cache — a roster change (re-extraction,
alias edit) is what re-bills it, not a plain re-run.

## `DEFAULT_CHUNK_CHARS = 6000` binds only on paragraphed text

`chunk_chapters` packs paragraphs split on `\n\n` and never splits one. On 4 of the
6 live books — the_way_of_kings, le-jeu-de-lange, eragon, the_hobbit — `epub_data`
content holds **zero** `\n\n` (their artifacts predate STU-523 paragraph
structure), so the whole chapter is one paragraph and each chapter becomes **one
chunk of 13k–25k chars regardless of the 6 000 limit**. The constant is inert
there. It binds only where the text carries paragraphs: Narnia (849 blank lines)
chunks 17 chapters into 45, ~4 400 effective chars each.

A fresh run re-extracts and would produce STU-523 paragraphs, so in production the
constant does bind — Eragon's 904k paragraphed chars are the ~174 chunks the old
estimate assumed. But **no measurement ties 6 000 to a cost or a quality number**:
it was not swept against detection F1 the way NER labels are
(`research/ner-eval/sweep_labels.py`), and nothing shows 6 000 beats 4 000 or
8 000 on either axis. Per the norms — *a threshold nobody can set without reading
our source is a default we have not chosen yet* — 6 000 is undefensible as shipped.
It should either be swept against the relation gold, or documented as an arbitrary
packing target with the two regimes above named so a reader knows it is inert on
unparagraphed input.

## Discovery vs the classifier it feeds (Narnia, measured)

Token counts are `tiktoken` `cl100k_base` over the reconstructed stage inputs
(passage + roster + type defs + auto-injected system prompt = agent yaml +
`invariants.md`).

| stage | calls | input tokens (cold) | per call |
|---|---:|---:|---:|
| discovery | 40–45 | ~177k | 3 927 |
| classify (prose pass, PERSON×PERSON) | 32 | ≥137k | ≥4 267 |

Discovery **feeds** the classifier, it does not replace it (the schema pass emits
`relationship_type`/`direction`/`evidence` but not the `evolution`/`key_moments`
that `generate_wiki_pages`/`event_layer`/`build_character_graph`/`spoiler_blocks`
read). So the new bill on Narnia is discovery **plus** classify — 40 chunk calls
added on top of the 32 pair calls the pipeline already made — i.e. **+40 cold, +0
cached**. All 32 discovered pairs are PERSON×PERSON, so the classify count did not
shrink; discovery's job here is typing quality (STU-575), not call reduction.

## Where the cost is

The Studio system prompt is **53% of a discovery call** (2 096 of 3 927 tokens),
measured — close to the pre-ship "60%" guess but on the right numbers (the old doc
cited a 9 547-char agent yaml; the discovery yaml is 2 186 chars, `invariants.md`
5 727). The classifier pays **more** fixed overhead per call: its agent yaml is
11 486 chars → a 4 124-token system prompt against a ~140-token pair body, so
nearly all of a classify call is scaffolding. If either stage needs to get cheaper,
the injected system prompt is the lever, not the discovery architecture.

## Reproduce

`census.py` (chunk counts, paragraph audit) and `tok.py` (Narnia token model) under
this directory — no LLM, no network; they read the cached artifacts under
`library/`. Numbers above are from those two scripts against the on-disk state on
2026-07-20.
