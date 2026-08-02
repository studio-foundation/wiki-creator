# Fandom Scrape Corpus — Stats (2026-08-02)

Snapshot of the bulk `fandom.com` scrape (`scripts/scrape_fandom_bulk.py`) used as
LoRA training data. Corpus lives at `processing_output/fandom_corpus/`, one
subdir per wiki (`<slug>/lora_dataset_fandom.jsonl`). Companion to
[fandom-vs-wiki-creator-capability-gap-2026-08-02.md](fandom-vs-wiki-creator-capability-gap-2026-08-02.md)
(structure/capability audit against wiki-creator's own output).

## Run summary

- 39 wikis scraped (`scripts/fandom_wikis.yaml`)
- 24,750 pages total (`wc -l processing_output/fandom_corpus/*/lora_dataset_fandom.jsonl`)
- `harrypotter` was stopped intentionally at 2,815 pages (11% of its 24,616-article
  site) — scraping it to completion would have doubled the whole corpus with one
  wiki, skewing training toward a single fandom's voice/vocabulary.
- Reports regenerated from the jsonl already on disk, no network/LLM calls:
  `write_reports()` in `scrape_fandom_bulk.py` → `field_report.{json,csv}`,
  `wiki_maturity_report.{json,csv}`.

## Per-wiki maturity (sorted richest → stubbiest by avg content length)

`avg_content_chars` = prose richness. `avg_infobox_fields_filled` = structured
density. Full data: `processing_output/fandom_corpus/wiki_maturity_report.csv`.

| wiki | pages sampled | site total | avg chars | avg infobox fields |
|---|---:|---:|---:|---:|
| riordan | 1770 | 4007 | 6882 | 10.1 |
| warriors | 1564 | 5755 | 6774 | 8.3 |
| the-folk-of-the-air | 90 | 149 | 5400 | 9.7 |
| twilightsaga | 317 | 893 | 5082 | 10.1 |
| outlander | 384 | 818 | 3927 | 11.4 |
| dresdenfiles | 287 | 696 | 3808 | 6.2 |
| malazan | 296 | 6424 | 3757 | **1.7** |
| throneofglass | 227 | 368 | 3712 | 12.3 |
| acourtofthornsandroses | 326 | 515 | 3622 | 7.9 |
| mistborn | 63 | 208 | 3563 | 2.5 |
| firstlaw | 331 | 819 | 3561 | 4.3 |
| thelandofstories | 133 | 574 | 3556 | 5.4 |
| shadowhunters | 571 | 1288 | 3549 | 11.6 |
| thehungergames | 409 | 912 | 3518 | 8.8 |
| blackcompany | 680 | 916 | 3493 | 3.2 |
| houseofnight | 108 | 283 | 3267 | 8.8 |
| vampireacademy | 346 | 772 | 2781 | 16.1 |
| discworld | 559 | 1133 | 2734 | **1.5** |
| deltoraquest | 635 | 1172 | 2606 | 10.9 |
| grishaverse | 386 | 705 | 2527 | 7.7 |
| enkidiev | 943 | 1100 | 2368 | 12.1 |
| shadesofmagic | 118 | 193 | 2321 | 8.4 |
| allsoulstrilogy | 86 | 157 | 2294 | 7.6 |
| harrypotter | 2815 | 24616 | 2172 | 9.4 |
| stormlightarchive | 847 | 1726 | 1908 | 6.7 |
| shannara | 72 | 678 | 1777 | 3.7 |
| inheritance | 611 | 1446 | 1771 | 3.3 |
| kingkiller | 255 | 466 | 1743 | 3.0 |
| fablehaven | 471 | 1017 | 1741 | 5.8 |
| sot | 620 | 1380 | 1720 | **1.9** |
| themagicians | 376 | 1496 | 1656 | 7.2 |
| spiderwick | 65 | 195 | 1639 | 3.8 |
| iceandfire | 1812 | 2562 | 1495 | 6.0 |
| wot | 2390 | 6563 | 1489 | 9.5 |
| beyonders | 142 | 217 | 1474 | 5.6 |
| hollowstar | 39 | 77 | 1213 | 10.3 |
| hisdarkmaterials | 639 | 1744 | 1076 | 4.4 |
| darktower | 560 | 988 | 1039 | 4.4 |
| pern | 2407 | 3247 | 916 | 6.4 |

**Anomaly**: `malazan` (1.7), `discworld` (1.5) and `sot` (1.9) have
`avg_infobox_fields_filled` far below every other wiki despite decent page
counts — likely infobox template resolution failed on these (template name not
matched), so pages contribute prose but no structured data. Worth checking
before training if the structured fields matter.

## Global field coverage (`field_report.json`)

| type | pages | distinct infobox fields |
|---|---:|---:|
| PERSON | 21,377 | 832 |
| PLACE | 2,799 | 240 |
| ORG | 574 | 106 |

Most common infobox fields (coverage % of pages of that type):

| PERSON | PLACE | ORG |
|---|---|---|
| gender 64% | location 31% | name 36% |
| name 47% | name 25% | region 23% |
| image 42% | image 21% | overlord 21% |
| status 37% | type 15% | coat of arms 21% |
| species 36% | continent 13% | seat 17% |
| affiliation 28% | residents 9% | current lord 15% |
| occupation 21% | appearance 9% | title 14% |
| nationality 19% | map 7% | status 12% |
| family 18% | color 6% | affiliation 12% |
| hair 18% | country 5% | members 10% |

Compare against our own taxonomy (`.studio/…/base.yaml#entity_types`): `status`,
`species`, `affiliation` already overlap; `gender`, `hair`, `occupation` are not
in our current PERSON infobox slots.

## Typical prose sections

Extracted from `## `/`### ` headings in scraped page bodies, 109,374 headings
across the corpus. Top 20:

| Section | Occurrences |
|---|---:|
| Appearances | 9805 |
| History | 6455 |
| References | 6174 |
| Notes and references | 4724 |
| Trivia | 4160 |
| Biography | 3538 |
| Appearance | 2878 |
| Personality | 2596 |
| Activities | 1793 |
| Etymology | 1497 |
| Abilities | 1482 |
| Relationships | 1416 |
| Quotes | 1345 |
| Behind the scenes | 1287 |
| External links | 1228 |
| Description | 1015 |
| Physical description | 860 |
| Gallery | 856 |
| Personality and traits | 828 |
| Members | 818 |

Dominant narrative shape: **Biography/History → Personality → Appearance →
Relationships/Abilities → Trivia/References**. `References`/`External links`/
`Notes and references` are wiki-meta noise, not narrative content — filter
these out for prose-only training.

## Reproducing this report

```bash
python3 -c "
from scripts.scrape_fandom_bulk import write_reports
from pathlib import Path
write_reports(Path('processing_output/fandom_corpus'))
"
```

Regenerates `field_report.{json,csv}` and `wiki_maturity_report.{json,csv}` from
whatever is on disk — safe to re-run any time, no network/LLM cost.
