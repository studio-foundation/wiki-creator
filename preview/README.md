# wiki-preview

The **M5.1 — Fandom Preview** app: render the wikitext that
`scripts/wiki_export.py` produces as browsable, Fandom-styled HTML, so a
generated wiki can be shown to someone who won't open the raw `.wiki` files.

Built up across the milestone:

- **STU-647 (done)** — `src/wikitext/parse.js`: the custom wikitext → HTML
  mini-parser + its vitest suite (this slice).
- STU-646 — the `wiki preview <book>` launcher (Python) that serves a book's
  `output/` and opens the browser.
- STU-648 — the React (Vite) app shell around the parser.
- STU-649 — the frozen Fandom-style skin (CSS).
- STU-650 — navigable wikilinks + red-link resolution.

## The parser (`src/wikitext/parse.js`)

`renderWikitext(source, { templates })` → `{ html, categories }`.

It renders **only** the subset the exporter emits — not arbitrary wikitext.
Core wikitext is a frozen target (unchanged since ~2016) and the input is our
own trusted exporter output, so the parser is coupled to our export code, not
to MediaWiki. When the exporter grows a construct, the STU-645 fixture breaks
and this module changes in the same PR.

Supported constructs:

| Construct | Rendered as |
|---|---|
| `= … =` … `==== … ====` | `<h1>`–`<h4>` |
| `'''bold'''`, `''italic''` | `<strong>`, `<em>` |
| `[[Target]]`, `[[Target\|label]]`, `[[:Category:X\|label]]` | `<a class="wikilink" data-target="…">` (resolution/red-links: STU-650) |
| `[[Category:X]]` tag lines | collected into `categories`, removed from body |
| `{\| class="infobox" … \|}` | `<table>` |
| `{{Infobox <type>\|k=v}}` | expanded against `templates[name]` (`{{{param\|default}}}`), then the table is rendered |
| `<div>` / `<span class="mw-collapsible">` | passed through verbatim; inner wikitext still parsed |

`templates` maps a template name to its source, e.g.
`{ "Infobox character": "<includeonly>{| … |}</includeonly>" }`. The launcher /
app builds it from the `templates/*.wiki` files (filename `_` → space). An
unknown template or unsupported construct degrades gracefully (left verbatim /
escaped) and never throws.

## Develop

```bash
npm install
npm test        # vitest, driven by tests/fixtures/preview/output (STU-645)
```
