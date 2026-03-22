# STU-308 — Fandom Scraper Design

**Date:** 2026-03-22
**Issue:** STU-308 — LoRA dataset : scraper fandom.com pour exemples gold supplémentaires

---

## Objective

Scrape existing fandom.com wikis via the MediaWiki API to produce a rich intermediate JSONL dataset of entity pages (PERSON, PLACE, ORG). This dataset will later be aligned to the STU-304 JSONL training format once that format is finalized.

---

## Architecture

**Script:** `scripts/scrape_fandom.py` — standalone, no new modules in `wiki_creator/`.

**Dependencies added:** `mwparserfromhell` (wikitext parsing)

### CLI

```
python scripts/scrape_fandom.py \
  --wiki https://throneofglass.fandom.com \
  --types PERSON PLACE ORG \
  --lang en \
  --limit 200 \
  --out processing_output/fandom/throneofglass/lora_dataset_fandom.jsonl
```

| Argument | Description |
|----------|-------------|
| `--wiki` | Base URL of the fandom wiki (e.g. `https://throneofglass.fandom.com`) |
| `--types` | Entity types to scrape; defaults to `PERSON PLACE ORG` |
| `--lang` | Language of the wiki content: `en` or `fr`; defaults to `en`. Written as-is into `content_lang` on each output record — no other runtime effect. |
| `--limit` | Max total pages written (across all types combined, counted after filtering); default: unlimited |
| `--out` | Output JSONL path; parent directories created if missing. If the file already exists, it is **overwritten** (not appended) to ensure reproducibility. |

---

## Execution Flow

1. **Discover** — For each requested entity type (processed sequentially in `--types` order), call the MediaWiki API (`action=query&list=categorymembers`) and paginate via `cmcontinue` until all titles for that type are collected. Discovery always runs to completion regardless of `--limit`; the limit is only enforced at write time.
2. **Fetch** — For each title, call `action=query&prop=revisions&rvprop=content&redirects=0` to retrieve raw wikitext. `redirects=0` instructs the API to return the redirect page as-is (preserving the `#redirect` prefix in the wikitext) rather than silently resolving it to the target article.
3. **Parse** — Use `mwparserfromhell` to extract infobox fields and body content.
4. **Filter** — Skip redirects (wikitext starts with `#redirect`, case-insensitive — this is the complement of `redirects=0` set in step 2) and stubs (body content < 200 chars after stripping). Filtered pages do not count against `--limit`.
5. **Write** — Write one JSONL line per valid page to the output file. Stop globally (across all types) once `--limit` written pages is reached. Types are processed in `--types` order, so earlier types fill the limit first.
6. **Rate-limit** — `time.sleep(1)` **after** each API call (applies to both discovery/pagination calls and page content fetches).

---

## Category Mapping

Entity types map to MediaWiki categories via a hardcoded default dict (not overridable via CLI):

```python
DEFAULT_CATEGORIES = {
    "PERSON": "Characters",
    "PLACE":  "Locations",
    "ORG":    "Organizations",
}
```

If a category returns 0 results, the script logs a warning and continues (does not crash). This handles wikis with slightly different category names.

**`wiki_slug` derivation:** strip `.fandom.com` from the host. Example: `throneofglass.fandom.com` → `throneofglass`. The slug matches the subdomain as-is, with no additional transformation.

---

## Parsing Strategy

### Infobox → `infobox_fields`

- Find the first template whose name contains `"infobox"` (case-insensitive)
- Iterate over its params; build `{param_name: value}` dict
- Strip residual wikitext from values via `mwparserfromhell`'s `.strip_code()`
- If no infobox found: `infobox_fields: {}` — page is still included if body is long enough

### Body → `content` (Markdown-like)

- Strip templates (`{{...}}`) via `mwparserfromhell`
- Convert section headings: `== Section ==` → `## Section`
- Keep plain text of paragraphs
- Remove `<ref>` tags, file/image links
- Goal: readable text for style training, not perfect wikitext→Markdown conversion

### Edge Cases

| Case | Behavior |
|------|----------|
| Page is a redirect | Wikitext starts with `#redirect` (case-insensitive); page skipped silently |
| Malformed infobox template | Log warning; `infobox_fields: {}`; continue |
| Category not found (0 results) | Log warning; skip that entity type; continue |
| Body < 200 chars (stub) | Page filtered out; does not count against `--limit` |

---

## Output Format (Intermediate JSONL)

One JSON object per line. This is **not** the STU-304 training format — alignment to that format happens in a later step (STU-305).

```json
{
  "source": "fandom",
  "wiki_slug": "throneofglass",
  "page_title": "Celaena Sardothien",
  "entity_type": "PERSON",
  "infobox_fields": {
    "species": "Human",
    "status": "Alive"
  },
  "content": "## Biography\n\nCelaena Sardothien is...",
  "content_lang": "en",
  "scraped_at": "2026-03-22T14:00:00Z"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `source` | string | Always `"fandom"` |
| `wiki_slug` | string | Subdomain of the wiki, e.g. `throneofglass` |
| `page_title` | string | MediaWiki page title |
| `entity_type` | string | `PERSON`, `PLACE`, or `ORG` |
| `infobox_fields` | dict | Key-value pairs from the infobox template; may be empty |
| `content` | string | Cleaned body text in Markdown-like format |
| `content_lang` | string | Value of `--lang` argument; `"en"` by default |
| `scraped_at` | string | ISO 8601 UTC timestamp |

---

## Output Path

```
processing_output/fandom/<wiki-slug>/lora_dataset_fandom.jsonl
```

Where `<wiki-slug>` is the subdomain (e.g. `throneofglass`). This path is outside the standard book-level path model (`library/.../processing_output/<book-slug>/`) since fandom data is not tied to a specific book.

---

## Compliance

- Uses the MediaWiki API — no HTML scraping, no Cloudflare bypass attempts
- `time.sleep(1)` after every API call (discovery pagination and page content fetches)
- Fandom content is CC-BY-SA licensed — compatible with an open-source training dataset
- French wikis preferred when available; `--lang fr` records the language in `content_lang`

---

## Out of Scope

- Alignment to STU-304 JSONL training format (→ STU-305)
- Deduplication against existing pipeline entities
- Multi-wiki batching (handled by running the script multiple times)
- CLI override of category names (hardcoded default dict)
