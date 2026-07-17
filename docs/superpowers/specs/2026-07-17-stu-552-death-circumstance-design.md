# STU-552 — In-universe death circumstance as grounded prose

## The gap

STU-488 filled the `status` infobox slot (`alive | deceased | missing | unknown |
undead`) from one `studio run entity-status-item` per book over the PERSON roster.
It also shipped a `death` slot rendering the **chapter** the verdict quotes, and
removed it: measured on Eragon's 4 verified verdicts, 3 of 4 derived chapters were
wrong. Brom dies around chapter 37; his death slot read "Chapter 61", the chapter
where a character later *says* he was killed. Morzan and Marian died before the book
begins and have no death chapter at all. **The place where the text states a fact is
not the place where the fact happens**, so deriving a chapter from the quoting
snippet does not work, and no refinement of that derivation fixes it.

What a fandom wiki's `<data source="death">` renders is an in-world circumstance —
"Killed by Durza at Farthen Dûr" — not a chapter number. That is the gap this closes.

STU-552's framing proposed the STU-481 `## Déroulement` shape: a writer LLM authoring
free prose over evidence it was shown. **That is not what this ships**, and the ticket
names the reason itself:

> Free prose in an infobox slot is the only non-grounded field of the infobox.
> `_extracted_fact_value` exists to avoid exactly that.

An infobox that takes prose stops being an infobox. So the circumstance is
**structured** — the LLM judges, the code formats, the same split as `status` and
every other `extracted-fact` slot. Prose was considered and rejected; a `## Mort`
body section was too (it buys a paragraph nobody asked for, and the infobox row is
what a reader scans).

## Shape: two fields on the verdict STU-488 already has

**No new stage, no new LLM call, no new roster.** `entity-status-item` already asks
one question per book over the PERSON roster, already returns a quote, and already
has to prove that quote verbatim. The circumstance is two optional fields on that
same verdict:

```json
{"name": "Brom", "status": "deceased",
 "quote": "Durza's blade took Brom in the side at Farthen Dûr",
 "agent": "Durza", "place": "Farthen Dûr"}
```

`agent` — who killed them. `place` — where they died. Both optional, both dropped
independently.

**No `cause` vocabulary.** An enum (`killed | illness | sacrificed | …`) was
considered and rejected: every value is a claim the classifier can get wrong, a cause
outside the enum renders nothing, and the phrasing the two fields already support
cannot lie about a cause the text does not state. An `agent` means someone killed
them; a `place` means they died there. A death by illness has no agent and renders
"Mort à Terím", which stays true.

## Grounding: three gates, per field

`parse_status_verdict` keeps `agent` / `place` only when **all** hold:

1. **`status == "deceased"`.** A living character has no death circumstance.
   `missing` and `undead` are deliberately out of scope — "disparu à X" is a
   different claim, and undeath is not a death the text narrates as one.
2. **The name is on the roster**, canonical or alias — `agent` against PERSON,
   `place` against PLACE. It renders **canonicalized**: `Captain Westfall` →
   `Chaol Westfall`. A name off the roster is one we cannot verify names a
   character at all, which is the STU-529/STU-539 hallucinated-id path.
3. **The name occurs verbatim in that verdict's own quote**, under the same
   `_normalize` folding `_is_quoted` already applies (typographic folding,
   whitespace collapse, casefold).

Gate 3 is the load-bearing one and it is deliberately stricter than "somewhere in
the entity's snippets". The slot asserts a *link between two facts* — this person
died, and this other person killed them. Sourcing the two halves from two different
snippets is the model inferring that link, and "they rode to Farthen Dûr" one
sentence away from "Durza's blade took Brom" would render a place that is where they
rode, not where they died. The quote is the evidence; the slot may claim only what
the evidence says.

**A field failing any gate is dropped; the verdict survives.** A wrong `agent` costs
the circumstance, never the `status`. This is STU-488's forgiving direction held:
every failure path renders less, never a false fact.

These novels are in the model's training data, so gate 3 is also what separates a
circumstance sourced from this run's text from one sourced from the model's memory of
the plot. Without it the two are indistinguishable afterwards.

## Rendering

`death` becomes an `OPT extracted-fact` infobox slot on PERSON — `OPT`, so it needs
no `fallback` (`validate_template` requires one only for `MIN` extracted-facts) and an
absent circumstance renders nothing.

`wiki_preparation` stamps two flat scalars beside `status` on the batch entity dict
(`wiki_preparation.py:403`); `_extracted_fact_value` formats them via a new
`death_label(agent, place, lang)` in `wiki_creator/entity_status.py`, reading
`base.yaml#chrome`:

| fields present | chrome key | renders (fr) |
|---|---|---|
| agent + place | `death_by_at` | `Tué par Durza à Farthen Dûr` |
| agent only | `death_by` | `Tué par Durza` |
| place only | `death_at` | `Mort à Farthen Dûr` |
| neither | — | `None` → `_bind_batch_fields`'s `if value:` drops the slot |

**Plain names, no wikilinks.** `event_infobox_fields` sets that precedent —
`participants` renders `", ".join(names)`, unlinked. It also keeps two problems out
entirely: a collated or figurant entity has no dedicated page, so a wikilink would be
a red link; and no edge is drawn, so the STU-501 rule (an untyped relation never
renders) never engages. The killer is a fact about the dead character, not a typed
relation between them.

## The cache

`load_cached_status` returns verdicts only when `cached["roster"] == rows`. **The
rows do not change here** — the roster is the same PERSON list with the same
snippets; only the question changed. So an `entity_status.json` written before this
ships would validate, replay a verdict that answers the *old* question, and render no
circumstance forever, silently.

The cache payload gains `"version": 2` and `load_cached_status` requires it to match
`CACHE_VERSION`. Roster-keying answers "was this verdict made for a different
roster?"; the version answers "was it made for a different question?".

## Files

| File | Change |
|---|---|
| `wiki_creator/templates/base.yaml` | PERSON `infobox`: `{token: death, group: infobox, provenance: extracted-fact, obligation: OPT, tiers: [figurant, secondary, principal]}`. `infobox_source`: `\| '''Décès''' \|\| {{{death\|}}}` row after `Statut`. `labels.death: {en: Death, fr: Décès}`. `chrome.death_by_at` / `death_by` / `death_at`, `{en, fr}`. |
| `wiki_creator/entity_status.py` | `CACHE_VERSION`; `parse_status_verdict(payload, rows, name_index)` gains the three gates; `death_label(agent, place, lang)`; `load_cached_status` / `save_status_cache` version check. |
| `scripts/entity_status.py` | Build `name_index` (PERSON + PLACE, canonical + alias → canonical) from the registry; pass it to `parse_status_verdict`. |
| `.studio/agents/entity-status.agent.yaml` | Ask for `agent` / `place` when `deceased`; both optional, both must be named in the quote; omit rather than guess. |
| `scripts/wiki_preparation.py` | Stamp `death_agent` / `death_place` beside `status` (`:403`). |
| `scripts/generate_wiki_pages.py` | `_extracted_fact_value`: `death` token → `death_label(...)`. |

## Tests

- `parse_status_verdict`: agent + place both gates pass → both kept; agent absent from
  the quote → dropped, place still renders; agent not on the PERSON roster → dropped;
  a PERSON name returned as `place` → dropped (roster is type-scoped); alias →
  canonical name rendered; `status != "deceased"` → both dropped, status kept;
  a dropped field never drops the verdict.
- `death_label`: the three field combinations + `None` for neither; unknown lang
  falls back through `chrome_label`.
- Cache: a `version: 1` payload with matching rows is **not** replayed.
- `tests/test_entity_status.py:471-472` — the STU-488 guards asserting `death` is
  absent from the slots and `{{{death|}}}` absent from `infobox_source` invert.
- `test_page_templates_schema` stays green: `death` is `OPT`, so the MIN-needs-a-
  fallback rule does not apply to it.
- The ticket's test, end to end: a character killed by a named antagonist at a named
  place renders `Tué par <killer> à <place>`, grounded in a verbatim excerpt; a
  character whose text states only that they died renders no circumstance.

## Out of scope

- **The infobox is not spoiler-gated.** `content_units` skips `infobox` by
  construction, so `Décès : Tué par Durza` leaks the death to a first-time reader
  exactly as STU-488's `Statut : Décédé` already does. Not a new hole; gating the
  infobox is its own ticket.
- **`forbidden_names`** are names from later books. The roster is this tome's, so a
  later-book killer cannot pass gate 2 — no separate check is added.
- **The death chapter** is not resurrected in any form. STU-488 measured that
  derivation wrong 3 times in 4; the circumstance replaces it, it does not restore it.
- **Mention-count / registry propagation**: the circumstance is per-tome, like
  `status`. The series registry carries no status (the wiki is per-tome), so nothing
  accumulates.
