# Fandom Corpus vs wiki-creator — Capability Gap Audit (2026-08-02)

What real Fandom wikis contain — sections, infobox slots, structural features —
compared against what wiki-creator generates today. **Structure and capability
only, not prose quality** (prose is the LoRA track). Companion to
[fandom-corpus-stats-2026-08-02.md](fandom-corpus-stats-2026-08-02.md).

## Method

- Deterministic counting over `processing_output/fandom_corpus/*/lora_dataset_fandom.jsonl`
  (39 wikis, 24,750 pages). No network, no LLM.
- Coverage = % of pages of that entity type containing the section/field, after
  normalization (case, wikitext markup, synonym folding: Physical description →
  Appearance, Notes and references → References, Abilities/Powers/Skills →
  Powers & abilities, numbered fields `spouse2` → `spouse`).
- Two scopes everywhere. **Full** = all 39 wikis. **Mature** = the 10 wikis with
  `avg_content_chars ≥ 3500` and `avg_infobox_fields_filled ≥ 6`
  (acourtofthornsandroses, dresdenfiles, outlander, riordan, shadowhunters,
  the-folk-of-the-air, thehungergames, throneofglass, twilightsaga, warriors) —
  what a *good* wiki looks like, undiluted by the 2,400 pern stubs. Mature
  coverage is the number recommendations are ranked on.
- A section counts as a real convention only at **≥ 1% coverage in ≥ 3 wikis**;
  single-wiki headings (`character pixels`, `kin`, `pandava quintet`) are local
  culture, not gaps.
- `malazan`, `discworld`, `sot` are excluded from all infobox stats (template
  resolution failed on these — `avg_infobox_fields_filled < 2`, see the stats doc).
- wiki-creator side = `wiki_creator/templates/base.yaml` (entity types, section
  tokens, infobox slots, tiers) + `lang/en.yaml` labels.

**Corpus limits.** The scraper collects only PERSON / PLACE / ORG pages, so page
types Fandom also has — books/chapters, objects/artifacts, spells, creatures-as-
species, timelines, disambiguation — are absent from the corpus by construction
and *not measurable here*. wiki-creator's EVENT and FACTION pages, synopsis, and
series hub therefore have no Fandom baseline in this audit. ORG mature n=21 is
too small; ORG uses the full set (n=348, iceandfire-heavy — flagged where it
skews).

Verdicts: **HAVE** (capability exists at comparable reach) · **PARTIAL** (exists
but narrower — tier-gated, flatter, or a different mechanism) · **MISSING —
extractible** (absent, but the answer is in the book text) · **OUT-OF-SCOPE**
(needs assets or real-world knowledge an EPUB doesn't carry).

## Sections — PERSON (21,377 pages full / 5,533 mature)

wiki-creator PERSON sections: biography (MIN, all tiers), backstory,
narrative_role, relationships (secondary+), personality, physical, powers
(genre-gated), trivia (principal only), references (MIN, all tiers).

| Fandom section | Mature | Full | Wikis | wiki-creator | Verdict |
|---|---:|---:|---:|---|---|
| References | 65.8% | 45.7% | 34 | `references` — but ours lists chapter mentions, Fandom's are inline `<ref>` citations | PARTIAL |
| Trivia | 49.0% | 17.9% | 35 | `trivia`, principal tier only | PARTIAL (tier) |
| History + Biography | 47.3 + 21.5% | 24.6 + 17.8% | 29/34 | `biography` MIN all tiers, `backstory` | HAVE |
| Appearances (in which books) | 42.5% | 44.2% | 28 | infobox `apparition` + chrome range line; no section listing each book | PARTIAL |
| Appearance (physical) | 41.6% | 24.9% | 38 | `physical`, principal only | PARTIAL (tier) |
| Personality | 30.8% | 16.7% | 35 | `personality`, principal only | PARTIAL (tier) |
| External links | 20.0% | 5.7% | 13 | — | OUT-OF-SCOPE |
| Powers & abilities | 15.9% | 8.6% | 28 | `powers`, genre-gated, principal only | PARTIAL (tier) |
| Quotes | 15.8% | 6.2% | 17 | — | MISSING — extractible (dialogue is in the text) |
| Etymology | 12.2% | 8.2% | 13 | — | MISSING — mostly out-of-scope (real-world name origins; in-book naming lore is rare) |
| Relationships | 11.4% | 6.6% | 28 | `relationships`, extracted-fact | HAVE |
| Gallery / images | 9.4% | 3.7% | 25 | — | OUT-OF-SCOPE (no images in an EPUB) |
| Behind the scenes | — | 6.1% | 13 | — | OUT-OF-SCOPE |
| Family (section) | 5.5% | 1.8% | 20 | `family` infobox slot only, no section/tree | PARTIAL |
| See also | — | 2.9% | 13 | — | MISSING — cheap (related-entity links exist in the graph) |

Two cross-cutting patterns the flat table hides:

- **Per-book breakdown.** 79.7% of mature PERSON pages use `###` subsections,
  overwhelmingly to split History/Appearances by book (`a court of mist and
  fury`, `breaking dawn`, `a feast for crows` — the single-wiki headings in the
  tail are almost all book titles). wiki-creator does this in *series* pages
  (per-tome Biography sections) but a single-tome page is flat, and the per-tome
  wiki has no per-chapter or per-arc splits. PARTIAL.
- **Tier gating is the recurring PARTIAL.** Personality / Appearance / Trivia /
  Powers are principal-only in base.yaml, but on mature wikis they appear on
  30–49% of *all* character pages — i.e. well into our secondary tier. The gap
  is not the section, it's the floor.

## Sections — PLACE (2,799 full / 358 mature)

wiki-creator PLACE sections: biography, physical (principal), events,
relationships (principal), trivia (principal), references.

| Fandom section | Mature | Full | Wikis | wiki-creator | Verdict |
|---|---:|---:|---:|---|---|
| References | 69.6% | 40.9% | 26 | same citation caveat as PERSON | PARTIAL |
| History | 64.2% | 35.3% | 28 | `biography` | HAVE |
| Appearance / Description | 39.9% | 12.9% | 22 | `physical`, principal only | PARTIAL (tier) |
| Trivia | 34.1% | 11.0% | 19 | `trivia`, principal only | PARTIAL (tier) |
| Appearances (in which books) | — | 10.6% | 11 | infobox `apparition` only | PARTIAL |
| Geography | 6.7% | 5.7% | 20 | — | MISSING — extractible |
| Residents / Inhabitants | ~7% | ~4% | 14 | — | MISSING — extractible (residence relations exist in discovery vocab) |
| Culture | 3.1% | 2.0% | 12 | — | MISSING — extractible, low priority |
| Government | — | 1.8% | 10 | — | MISSING — extractible, low priority |

## Sections — ORG (574 full; mature n too small, full-set numbers)

wiki-creator ORG sections: biography, relationships, references — the thinnest
template of the three.

| Fandom section | Full | Wikis | wiki-creator | Verdict |
|---|---:|---:|---|---|
| History | 35.5% | 15 | `biography` | HAVE |
| References | 29.8% | 12 | citation caveat | PARTIAL |
| Members (+ former/current) | 15.9% + 6.4% | 14 | nothing — `leaders` infobox slot only | MISSING — extractible (membership relations already in the graph) |
| Appearances | 11.1% | 6 | infobox `apparition` | PARTIAL |
| Trivia | 5.4% | 9 | `trivia` absent on ORG | MISSING — cheap (token exists for other types) |

Members is the signature ORG section (48.1% on the mature subset despite n=21)
and we have no equivalent at all.

## Infobox — PERSON (mature set, n=5,332 pages with infobox)

wiki-creator slots: nom, alias, apparition, status, death, species, affiliation,
titles, family, romance, friends_allies, enemies.

| Fandom field | Mature % | Wikis (full corpus) | wiki-creator | Verdict |
|---|---:|---:|---|---|
| gender | 69.3% | 33 | — | MISSING — extractible (pronouns; NB series pages already infer gender nowhere — net-new fact type) |
| image | 59.4% | — | — | OUT-OF-SCOPE |
| status | 46.6% | — | `status` | HAVE |
| species | 46.5% | — | `species` (genre-gated) | HAVE |
| appearances / livebooks | 34.2% | — | `apparition` | HAVE |
| family (incl. mother/father/siblings/spouse/children) | 33.0% | 7–11 each | `family` + `romance` flat lists | PARTIAL (no typed kinship slots; typed relations exist in the graph but are not surfaced as infobox rows) |
| residence / home / origin | ~30% combined | 6–9 each | — | MISSING — extractible (residence/origin relations in discovery vocab) |
| hair / eyes / height | 27.6 / 24 / 10.4% | 21 / 15–6 / 17 | — | MISSING — extractible (physical descriptors are classic book facts) |
| age / born / died | 19.4 / — / — | 24 / 13 / 11 | `death` (event only) | PARTIAL |
| occupation | 15.6% | 26 | — | MISSING — extractible |
| titles | 14.4% | 25 | `titles` | HAVE |
| alias / full name | 12.5 / 17.9% | — / 7 | `alias` | HAVE |
| affiliation / allegiance | 24.6 + 7.8% | — | `affiliation` | HAVE |
| nationality | — | 9 | — | MISSING — semi-extractible (≈ origin/kingdom in most fantasy) |
| weapon | — | 2 | — | below threshold, skip |

Wiki-specific fields (pantheon, kit/warrior/apprentice, starclan resident, court)
are local taxonomy — evidence for *per-book custom slots* rather than new base
slots. base.yaml has no book-level slot override today beyond genre gating.

## Infobox — PLACE (mature n=335) and ORG (full n=348)

PLACE slots today: nom, apparition, location. Fandom mature: country 44.8%,
residents 38.2%, type 29.3% (city/kingdom/forest…), ruler(s) 10.7%, population
10.1%, established 8.7%. **Everything but `location` is MISSING**, and
country/type/ruler are extractible — this is the widest per-type infobox gap.

ORG slots today: nom, apparition, leaders. Fandom full: region 38.2%, overlord
35.1%, seat/headquarters 28.2 + 15.8%, current lord 23.9% (≈ leaders — HAVE),
status 19.5%, affiliation 19.3%, members 16.4%, founder 11.5%, founded 10.3%.
Heraldry fields (coat of arms 34.5%, words 8%) are iceandfire skew +
out-of-scope (images). Extractible gaps: headquarters/seat, founder, status,
affiliation, members.

## Structural capabilities (page mechanics, mature % / full %)

| Feature | Fandom | wiki-creator | Verdict |
|---|---|---|---|
| Categories | 100% / 100%, **avg 7 per PERSON page** (status, gender, species, per-book, role facets) | 1 flat category per page (`category_key`) + series hub category listing | PARTIAL — we have the facts (status/species/apparition) but emit one category |
| Infobox image | 56.5% / 40.3% | — | OUT-OF-SCOPE |
| Inline citations `<ref>` | 52.2% / 39.0% | References section = chapter-mention list, no inline anchors | PARTIAL — chapter provenance exists per fact (provenance machinery), not rendered as footnotes |
| Quote template (page-top/pull quotes) | 42.1% / 20.9% | — | MISSING — extractible |
| Spoiler handling | 31.6% / 9.9% (template-based) | spoiler_blocks: chapter-gated reveal, per-tome gating | **HAVE — ours is stronger** (mechanical gating vs a banner) |
| Gallery | 10.3% / 4.5% | — | OUT-OF-SCOPE |
| Navbox | 6.5% / 6.6% | series hub navigation chrome | HAVE (different shape) |
| `###` sub-structure | 79.7% of mature PERSON pages | flat sections; per-tome split only in series pages | PARTIAL |
| Family tree / succession | tree 11.2% but 1 wiki; succession 1.3% | — | below threshold, skip |
| Tables | 1.7% / 0.8% | — | below threshold, skip |

## Gap ranking (by mature coverage × extractibility)

Criteria: mature-set coverage, ≥3-wiki spread, and whether the fact is already
in our pipeline (graph/provenance) vs net-new extraction.

1. **Tier floors for personality / physical / trivia / powers** (30–49% coverage
   vs principal-only today). No new extraction — a base.yaml `tiers:` change +
   prompt budget. Biggest structural convergence per unit of work.
2. **PERSON infobox: gender, residence/origin, occupation, hair/eyes/age**
   (15–69%, 20+ wikis). New extracted-fact slots; same pre/call/post shape as
   the existing entity trio (status/affiliation/species), and gender is nearly
   free (pronoun evidence).
3. **PLACE infobox: country, type, residents, ruler** (10–45%). Widest per-type
   gap; residents/ruler are already relations in the graph.
4. **ORG Members section + ORG infobox (headquarters, founder, members, status)**
   (16–48%). Membership relations exist — rendering gap, not extraction gap.
5. **Multi-facet categories** (universal; avg 7/page vs our 1). Pure export-side:
   status/species/gender/apparition are already known per entity.
6. **Quotes** (section 15.8%, template 42.1%). Extractible dialogue; pairs well
   with the LoRA prose track.
7. **Appearances section (per-book) + per-book `###` splits in single-tome
   pages** (42–44%). Data exists (apparition, per-tome artifacts); mostly
   template/rendering work. Only matters for multi-tome books.
8. **Inline `<ref>` citations from provenance** (52%). Provenance already tracks
   chapter sources per fact; rendering as footnotes would also strengthen the
   grounding validator story.
9. Low priority: Geography/Residents/Culture sections on PLACE (≤7%),
   See also (2.9%), Etymology (mostly out-of-scope), nationality.

Not gaps: External links, Behind the scenes, Gallery, images, coat of arms
(out-of-scope for EPUB-derived wikis); family tree, succession, tables,
weapon (below the ≥1%/≥3-wiki threshold).

## Reproducing

Analysis script is a one-off (deterministic counts, no network):
`fandom_audit.py` — session scratchpad; report JSON alongside. If this needs to
be re-runnable, fold the per-type heading/field coverage into `write_reports()`
in `scripts/scrape_fandom_bulk.py` next to the existing maturity report.
