# What type + direction at discovery costs (STU-540 step 4, confirmed STU-603)

STU-540 priced this stage before it shipped. STU-603 re-measured it against the
shipped `discover-relationships` and the artifacts on disk. **The chunk census
reproduces exactly** — 2 986 chunks over 15 books at 6 000 chars, the same number
STU-540 wrote down. What the confirmation changes is everything around that
number: what the library has actually paid, what a cached re-run costs, and
whether `DEFAULT_CHUNK_CHARS = 6000` was ever chosen.

Reproduce: parse the library and chunk it (`wiki_creator.relationship_discovery.
chunk_chapters` over `parse_epub` output — no LLM, no network, ~2 min).

## The library has never paid this cost

One book of fifteen has ever run discovery. `relationships_discovered_votes.json`
exists only for `01-the_lion_the_witch_and_the_wardrobe`; the other fourteen have
no vote cache, no `relationships_discovered.json`, and — for eleven of them — no
`registry.json` to build a roster from. So the per-book figures below are a
**projection from one book's measured payloads**, not an observed bill.

That one run is also incomplete. The book chunks to 45 at 6 000 chars; the cache
holds **40**. Five chunks (`bookcontent{10,11,14,17,18}_0`) failed and, per the
STU-562 rule, were correctly left out of the cache so a re-run would retry them —
but no re-run happened, so the shipped graph was built from 89 % of the text, and
the missing chunks are in the book's last third. Nothing downstream said so: a
chunk that contributes no votes is indistinguishable from a chunk that evidenced
no relation. **Cost paid is not coverage bought.**

## Chunk census (15 books, current parser)

| book | chars | n@2000 | n@4000 | n@6000 | n@12000 |
|---|---:|---:|---:|---:|---:|
| 01_a-dark-and-hollow-star | 920 182 | 529 | 266 | 184 | 103 |
| 02_a-cruel-and-fated-light | 1 137 341 | 646 | 321 | 224 | 126 |
| 03_a-grim-and-sunken-vow | 1 066 827 | 604 | 309 | 215 | 127 |
| 04_a-wild-and-ruined-song | 696 515 | 396 | 204 | 144 | 83 |
| 01-the_way_of_kings | 2 217 475 | 1 233 | 622 | 427 | 236 |
| 01-the_lion_the_witch… | 198 954 | 127 | 65 | 48 | 29 |
| 02-le-jeu-de-lange | 942 583 | 569 | 297 | 205 | 121 |
| 01_eragon | 907 007 | 522 | 269 | 182 | 111 |
| 02_eldest | 1 218 317 | 699 | 353 | 246 | 141 |
| 03_brisingr | 1 448 760 | 848 | 419 | 282 | 152 |
| 04.5_tales-of-alagaesia | 227 966 | 133 | 73 | 50 | 34 |
| 04_inheritance | 1 583 958 | 901 | 459 | 316 | 182 |
| 05_murtagh | 1 109 244 | 623 | 321 | 221 | 130 |
| 00-the_hobbit | 509 319 | 302 | 147 | 98 | 54 |
| 01-throne-of-glass | 647 316 | 372 | 196 | 144 | 84 |
| **total** | **14 831 764** | **8 504** | **4 321** | **2 986** | **1 713** |

A cold library pass is **2 986 discovery calls plus one classifier call per
discovered pair**. Per book the spread is 48 (Narnia) to 427 (Way of Kings);
STU-540's "~174 chunks/book" is the right order but is a mid-size book, not a mean.

**Chunking degenerates silently on a pre-STU-523 artifact.** `chunk_chapters`
packs paragraphs split on `\n\n` and never splits one, so a chapter with no
paragraph marks is one chunk at any `size`. Five of the six cached
`epub_data.json` on disk predate STU-523 and hold zero `\n\n`: Way of Kings
chunks to 97 chunks of up to 55 673 chars instead of 427, and `--chunk-chars`
does nothing. The census above is from a fresh parse; a run over a stale
extraction cache silently buys a different (and far worse) stage.

## Two thirds of every call is boilerplate

Measured on Narnia, chars of input per discovery call:

| component | chars | per call |
|---|---:|---|
| `relationship-discovery.agent.yaml` system prompt | 2 186 | fixed |
| `.studio/invariants.md` (auto-injected) | 5 727 | fixed |
| `relationship_types` vocabulary + roster | 3 519 | fixed per book |
| passage | ≤6 000 | the payload |
| **fixed share** | **11 432** | **66 %** |

The demoted per-pair classifier is worse, not better: 11 486 chars of agent yaml
+ 5 727 invariants + 3 802 of type/confidence vocabulary = **21 015 fixed chars
against a mean 3 143 chars of actual pair evidence — 87 % boilerplate.** Narnia's
32 pairs cost 222 235 chars of item input for 100 k of evidence.

STU-540 already said "60 % of every call is the injected system prompt rather
than book text" and concluded the discovery architecture is not the lever. That
is confirmed. What it did not name is the lever that *is* one: the call count,
which is `DEFAULT_CHUNK_CHARS`.

## `DEFAULT_CHUNK_CHARS = 6000` is undefended

Total discovery input over the library, holding the book text constant and
scaling the fixed overhead by the call count:

| chunk_chars | calls | overhead | total input | overhead share | vs. 6000 |
|---:|---:|---:|---:|---:|---:|
| 2 000 | 8 504 | 97.2 M | 112.0 M | 87 % | 2.29× |
| 4 000 | 4 321 | 49.4 M | 64.2 M | 77 % | 1.31× |
| **6 000** | **2 986** | **34.1 M** | **49.0 M** | **70 %** | **1.00×** |
| 8 000 | 2 351 | 26.9 M | 41.7 M | 64 % | 0.85× |
| 12 000 | 1 713 | 19.6 M | 34.4 M | 57 % | 0.70× |

Nothing measured picks 6 000 out of that column. The constant is not a context
limit — 6 000 chars is ~1.5 k tokens against a 200 k window, so the model is
nowhere near full at any row here. The only real argument for a small chunk is
**recall per passage**: a longer passage may bury a relation the model would have
found in a shorter one. That is the number nobody has, and it is the number this
decision needs. Per the project norm, a threshold nobody can set without reading
our source is a default we have not chosen yet — `6000` is that default.

Measuring it is cheap and self-contained: Narnia has a human-checkable roster and
a 48-chunk cold run, so re-running discovery at 4 000 / 6 000 / 12 000 and scoring
the pair sets against each other costs ~230 calls on one book. Until that runs,
**do not raise the constant on the cost argument alone** — the 0.70× is real and
the recall cost is unknown, which is the asymmetry STU-538 and STU-539 both
resolved toward the safe side.

## Steady state is cheap, but only until the prompt changes

The per-chunk vote cache means a re-run costs only the uncached chunks, so a
second pass over an unchanged book is ~0. Two things bound that:

- The cache key is `(roster_lines, prompt_fingerprint)`, and the fingerprint
  hashes `relationship-discovery.agent.yaml` **and** the injected type
  definitions. Any prompt edit, or any book gaining a `classification.
  relationship_types` entry, re-runs **every chunk of that book**. Steady state
  is not "paid once", it is "paid once per prompt revision" — 2 986 calls each
  time, library-wide.
- An alias merge upstream changes `roster_lines` without changing a single chunk
  id, and busts the same cache. That is deliberate (a vote made for a different
  roster must not be replayed), and it means resolution changes are re-discovery
  changes.

## The token figures are not dollars

`.studio/config.yaml` sets `defaults.provider: claude-code`, and
`discover_relationships.py` shells `studio run` with no `--provider`. The stage
therefore runs through the Claude Code CLI and consumes subscription usage, not
per-token API billing. The char counts above are exact; a token figure is not —
the STU-540 table's per-call token counts came from a working API key, and the
one in `.studio/config.yaml` now returns 401, so `count_tokens` could not be
re-run. At a nominal 4 chars/token the 49 M chars of a cold library pass is
~12 M input tokens, which at `claude-haiku-4-5` rates ($1/MTok in, $5/MTok out)
would be ~$12 plus output — but that is a **derived estimate for a provider the
pipeline does not use**. The invariants worth tracking are the call count and the
input volume above, not a dollar figure.
