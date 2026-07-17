# STU-553 — Is there an aggregated series page?

Ticket: [STU-553](https://linear.app/studioag/issue/STU-553/decide-whether-an-aggregated-series-page-exists-it-conflicts-with-stu)
Split out of [STU-488](https://linear.app/studioag/issue/STU-488/multi-livres-55-evolution-perso-and-conflits-inter-tomes)
(`2026-07-16-stu-488-entity-status-design.md`).

## Decision

**No aggregated series page.** The per-tome wiki is the product. Series-level state
stays an identity mechanism, never a rendering surface.

This closes the ticket. Nothing to build.

## Why

### 1. Series level is already, consistently, mechanism-only

Three series-level artifacts exist and not one of them renders (`paths.py:25-46`):

| Artifact | Purpose |
|---|---|
| `library/<author>/<series>/registry.json` | cross-tome identity (STU-485) |
| `library/<author>/<series>/character_graph.json` | cross-tome graph accumulation |
| `library/<author>/<series>/canon.yaml` | which source is authoritative (STU-512) |

Every one answers "who is this entity, across tomes" — none answers "what does the
reader see". The wiki is per-tome (`output/<slug>/`) with no exception. A series page
would be the first inversion of that split, and would need a reason of its own; the
sections below are that reason failing.

### 2. The aggregated series page *is* Fandom

It states the end state of every character on one page, per series. That page already
exists, for free, for every book popular enough to have a fandom — we scrape it
(`scripts/scrape_fandom.py`). Rebuilding it is the one deliverable whose value is
provably zero for the books that have one, and unproven for the books that do not.

What this project has that Fandom does not is the **gate**: a page that tells you what
is true at your reading position and nothing beyond it. The aggregate deletes exactly
that. It is not a feature of the product; it is the product's negation, rebuilt at cost.

### 3. The cheap gate is built and nobody has turned it on

STU-232 shipped per-chapter `mw-collapsible` gating (`wiki_creator/spoiler_blocks.py`),
enabled by `generation.spoiler.collapse_after_chapter: N` in the book YAML.

**Zero of the 15 books declare that key.** (`rg -rn collapse_after_chapter library/` →
nothing.)

So the spoiler-free reading surface, in its cheapest shipped form, has never been
exercised on a real book. Building a second gating surface — across tomes, on a new
export root — before the first one has a single user is speculation, not sequencing.
If the reading-position use case is real, the evidence is one YAML key away and costs
nothing to produce. Get that first.

### 4. The tome boundary is already a gate, at the granularity readers actually use

Readers move through a series one tome at a time. Tome N's wiki states the state at the
end of tome N, and earlier tomes are never regenerated — so "tome 1's Brom is alive,
tome 2's Brom is dead" is true **by construction**, not by machinery (STU-488). The
gating stack is already two levels deep and complete:

* **coarse, across tomes** — one wiki per tome, free
* **fine, within a tome** — STU-232's per-chapter collapsible, shipped, unused

An aggregated page would replace level 1 with a page that needs level 1's job done
again, in software, on top of a surface that does not exist yet.

### 5. The cost is a surface, not a slice

An aggregated wiki is not a view over the per-tome pages. It needs, all new:

* an export root above `output/<slug>/`, with its own Main_Page, index and showcase
  lists (`export.index.*`);
* categories, and a tier decision — notability is per-tome and, on `percentile` books,
  deliberately not comparable across tomes (STU-509/STU-513);
* deduplication against the per-tome pages that already exist. MediaWiki's namespace is
  flat, and the STU-506 title disambiguation pass runs **per wiki**
  (`assemble_wiki_pages.py:138`); six tomes of `Eragon` in one namespace is a collision
  problem that pass was never asked to solve;
* collation pages, spoiler blocks and the synopsis, all re-decided at series scope.

That is a second export pipeline. The ticket's framing — "it is not a slice" — is right,
and the price only buys back what Fandom gives away.

## Rejected alternatives

**A series page gated by reading position** (STU-553's option 2). The interesting one,
and still no. It is STU-232's mechanism generalized from the chapter axis to the tome
axis, and its only gain over the per-tome wiki is identity continuity visible in one
place — which is the registry's job, already done, for the pipeline that needs it. If it
is ever wanted, it is **STU-232 work, not STU-233 work**: same gate, coarser axis. It
does not resurrect this ticket.

**A spoiler-full series page as an opt-in** (option 3). The flag is not the cost; the
surface is (§5). An opt-in that nobody can use until a second export pipeline exists is
a decision deferred, not a decision made. And the reader it serves — someone who has
finished the series and wants a reference — has Fandom.

## What would reopen this

One of:

* A book with **no fandom wiki** where a reader asks for a whole-series reference. That
  is the only user §2 does not answer. Nobody has asked.
* `collapse_after_chapter` in production on a real series, with the reading-position use
  case proven and the tome boundary measured as too coarse. Then it is STU-232's ticket
  to widen, per the rejected option above.

Absent either, the series registry stays what it is: how the pipeline knows Brom is
Brom, not a page.
