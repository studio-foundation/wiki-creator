# Preview app wikitext fixture (STU-645)

Foundational fixture for the **M5.1 — Fandom Preview** app. It reproduces what
`scripts/wiki_export.py` writes for one book, so the preview app (launcher,
parser, shell, skin, wikilinks) can be built and tested in the web sandbox with
no EPUB, GPU, LLM, or full pipeline run.

The book is `01-alice-in-wonderland` (Alice's Adventures in Wonderland), an
English novel — `output_language: en`, so the Main_Page chrome is English while
the infobox row labels stay French (they are hard-coded in `base.yaml`'s
`infobox_source`; the parser must not assume one language per file).

## Not hand-typed — generated from the real exporter

`gen_fixture.py` hand-authors the *pages* (an Alice cast) but produces the
*wikitext* through the real exporter helpers (`render_page`,
`main_page_content`, the infobox-template writer, `_build_categories_wiki`). So
the fixture is byte-identical to a real export. No circularity with the e2e
discipline (STU-524): the exporter and the preview parser are different
components.

Regenerate after an intentional exporter change and commit the diff:

```bash
python tests/fixtures/preview/gen_fixture.py
```

`tests/test_preview_fixture.py` fails if the committed files drift from
`gen_fixture.build()`, or if the fixture stops covering a construct.

## Layout (`output/`)

```
Main_Page.wiki          landing page: nav, showcase lists, stats
categories.wiki         category hierarchy reference page
Synopsis.wiki           SYNOPSIS page — body only, no infobox (renders at root)
Minor_Characters.wiki   COLLATION page — body only, no infobox (renders at root)
templates/Infobox_*.wiki  one MediaWiki template per entity type ({{{param|}}})
characters/*.wiki       PERSON pages (infobox + body + categories)
locations/*.wiki        PLACE pages
organizations/*.wiki    ORG pages
events/*.wiki           EVENT pages
```

## Which file demonstrates which construct

| Construct the parser must handle | Where to see it |
|---|---|
| `== Heading ==` (levels 1–4) | every page body |
| `'''bold'''`, `''italic''` | `characters/Alice.wiki` (`'''Alice'''`, `''enormous''`) |
| `[[Wikilink]]`, `[[Target\|label]]` | throughout; `[[Synopsis\|Book synopsis]]` in `Main_Page.wiki` |
| Cross-subdir wikilink | `characters/Alice.wiki` → `[[Wonderland]]` (a PLACE page) |
| Dangling / red link (no target page) | `characters/Alice.wiki` → `[[Dormouse]]` |
| `[[Category:X]]` | foot of every entity page; `categories.wiki` |
| `{{Infobox <type>\|k=v}}` call | head of every entity page |
| Local template source (`{{{param\|default}}}`, `{\| class="infobox" }`) | `templates/Infobox_character.wiki` |
| `mw-collapsible` spoiler block (section) | `characters/Alice.wiki` — the *Narrative role* section (revealed after the cutoff) |
| Inline gated infobox row (`<span class="mw-collapsible">`) | `characters/Queen_of_Hearts.wiki` — `status` and `death` |
| Body-only page (no infobox/categories) | `Synopsis.wiki`, `Minor_Characters.wiki` |

The spoiler cutoff is `collapse_after_chapter = 6` (`gen_fixture.COLLAPSE_AFTER`):
sections first revealed after chapter 6 collapse, and the PERSON `status`/`death`
rows are gated unconditionally.
