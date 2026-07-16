# Relation-discovery bake-off (STU-467)

Scores the shipped co-occurrence discovery against GLiREL and schema-guided LLM
extraction, on a book none of them was tuned on. Research only — nothing here runs
in the pipeline.

**Status: incomplete.** The diagnostic below is done and reproduces. The bake-off
is not: the gold and the LLM arm need API credit, and GLiREL needs the GPU. See
[Blocked](#blocked).

## Read this before any bake-off number

The ticket charges co-occurrence with *proximity is not relation*. Measuring the
prior question first — whether the mechanism measures proximity at all — changes
what the bake-off is comparing.

    python diagnose_baseline.py \
      --processing-output ../../library/christopher_paolini/inheritance/processing_output/01_eragon

On Eragon, 66 PERSON entities, 60 narrative chapters:

| sentence pairs the window reads as adjacent, across two entities | 370 |
|---|---|
| median real distance between them, in the chapter | **4 151 chars** |
| p90 | 15 345 chars |
| max | 29 200 chars |
| actually adjacent prose (< 300 chars apart) | **7%** |

`build_cooccurrence_graph` slides a 5-sentence window over `chapter_sentences`
and admits a pair as a *direct interaction* when the two names land within
`_MAX_DIRECT_INTERACTION_GAP` (1) sentences. The constant's name promises textual
adjacency. `chapter_sentences` is not the chapter: it is built
(`relationship_extraction.py:208-221`) by iterating `mentions_by_entity`, a dict
keyed by entity, appending each entity's context sentences for that chapter. So

- each entity contributes at most 3 sentences per chapter (the extraction-side
  context cap), making the list a sparse sample rather than the text, and
- **the list is ordered by entity, then by position.** Sentence *i* and *i+1*
  usually belong to different entities and sit pages apart. Position orders
  sentences only inside one entity's block.

The window is therefore adjacent in a list whose order is an artifact of dict
iteration. 173 of the baseline's 501 emitted pairs are never within one sentence
of each other anywhere in the book.

This does not retire the ticket, it re-scopes it. "Co-occurrence is a weak signal"
and "our co-occurrence is not co-occurrence" call for different work, and the
bake-off cannot tell them apart unless it runs a **corrected** co-occurrence arm
— the same idea over real text windows — next to the shipped one. That is why
there are four arms and not three. If the corrected arm closes most of the gap to
GLiREL, the answer to STU-467 is a bug fix, not a model.

## Why Eragon

Held out. `throne-of-glass` is the only book with `ner.backend: gliner`, the only
one with a relation gold (`tests/fixtures/relationship_eval/`, 13 pairs), and the
book the relation vocabulary was tuned against (STU-477). A number measured there
is optimistic on every axis the spike is supposed to decide. Eragon shares the
held-out property that made it the right corpus for the NER bake-off
(`research/ner-eval/`), and its corpus builder is reused here.

## Design

**Entities are frozen; only relation discovery varies.** Every arm is handed the
same roster (`roster.json`) — PERSON + `relevant`, exactly the filter
`build_cooccurrence_graph` applies. Free-naming would fold entity resolution back
into a relation benchmark, and let a stronger NER take credit for a relation win.
GLiREL takes given spans natively, so this costs no arm anything.

The roster is dirty and stays dirty: split-clusters types entities before
entity-classification and the book's `entity_overrides` run, so `Varden` and
`Empire` (ORG) and `Tronjheim`, `Farthen Dûr`, `Du Weldenvarden`, `Leona Lake`
(PLACE) sit in the PERSON roster — 6 of 66. Cleaning it would measure a fix that
is not shipped. Whether an arm declines to relate a character to a valley is part
of what is being measured.

**The gold unit is a book-level pair**, not a chunk-level triple, because the gap
the ticket names lives in the aggregate: "did we ever discover that Eragon is
Garrow's nephew" is not a question any one passage answers. Annotation is still
per chapter — no annotator, model or human, enumerates a 60-chapter novel's
relations in one pass — and `aggregate.py` folds the votes.

**A pair's type is a set.** Relations move inside one book; Eragon and Murtagh are
a `wary_alliance` for twenty chapters and `friend` by the end. `acceptable` is
every type any chapter evidenced, ordered by how many chapters evidenced it, so
the primary is the dominant reading and the alternates are the arc. Same
convention as the STU-499 fixture.

**The implicit/explicit split is computed, never annotated.** It is the axis the
ticket's charge lives on, so it is a property of the text and of nothing else: a
pair is explicit if its surfaces ever land within `--max-sentence-gap` (default 1)
sentences in the raw chapters. The default mirrors `_MAX_DIRECT_INTERACTION_GAP`
on purpose — calibration, not circularity. It puts every pair co-occurrence could
plausibly reach into the explicit stratum, so the implicit stratum holds only
pairs no proximity method reaches at any threshold: a floor on the charge, never
an inflation of it. On Eragon, 382 of 2145 possible pairs are proximate; 1763 are
not.

Asking the annotator instead would make the central axis a model judgment no arm
could be checked against. Reusing the baseline's own admission rule would answer
the question with itself.

**Three axes, reported per stratum** (`score.py`):

- **detection** — pair found, type ignored. The only axis fair across
  architectures: co-occurrence emits no type at all, so scoring it on type scores
  the LLM classifier bolted after it.
- **typing** — reported end-to-end (an undiscovered pair is a typing miss) *and*
  conditional on detection. The conditional number flatters low recall by
  construction — one pair found and typed right scores 1.0 — so it is printed
  next to its *n*. The end-to-end number is the one that decides.
- **direction** — on correctly-typed pairs only. Direction on a wrong type is not
  partial credit, it is a different claim.

`null` and `none` score as no type at all, per STU-501: a type the reader never
sees cannot earn typing credit.

## Arms

| arm | what it tests |
|---|---|
| `cooccurrence_shipped` | production, as it runs today |
| `cooccurrence_fixed` | same idea, real text windows — isolates the bug from the idea |
| `glirel` | zero-shot encoder RE, types + direction at discovery |
| `llm_schema` | one schema-guided pass, entities + relation + type + direction |

## Run

    pip install -r requirements.txt

    # 1. Pipeline artifacts (parse -> roster + the shipped baseline's own output)
    cd ../.. && make run-extraction BOOK=library/christopher_paolini/inheritance/books/01_eragon.yaml \
             && make run-resolution  BOOK=library/christopher_paolini/inheritance/books/01_eragon.yaml

    # 2. Corpus + roster — id_7..id_66 is Eragon's narrative span
    python build_corpus.py \
      --processing-output ../../library/christopher_paolini/inheritance/processing_output/01_eragon \
      --first-chapter id_7 --last-chapter id_66

    # 3. The implicit/explicit split (no model, ~4s)
    python explicit_pairs.py

    # 4. Gold (needs an API key)
    python build_gold.py

    # 5. Arms, then report
    ...

## Blocked

- **Gold and the `llm_schema` arm** need API credit. `build_gold.py` currently
  dies on `Your credit balance is too low to access the Anthropic API`. Nothing
  can be scored until the gold exists.
- **The `glirel` arm** needs the GPU. `jackboyla/glirel-large-v0` loads and works
  — it types Brom/Eragon `mentor` at 0.815 on a toy sentence, with direction —
  but takes 12.5s per short sentence on CPU, which will not cross 60 chapters.

Neither blocks `diagnose_baseline.py`, which is the finding above.

## Tests

    PYTHONPATH=../.. python -m pytest tests/ -q

Covers the scorer and the vote fold — everything except the API and model calls.
Direction flipping has its own tests: `pair_key` sorts the two names and
`direction` is stated against `entity_a`, so a vote naming (Brom, Eragon) and one
naming (Eragon, Brom) mean opposite things by the same token. It is the only place
here where a bug silently inverts a result.
