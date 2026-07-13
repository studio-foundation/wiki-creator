# STU-492 · Progression 2/3 — Per-chapter spoiler blocks + dated relationship evolution

Sub-issue of the narrative-progression epic (STU-232). Builds on STU-491
(chapter-of-revelation provenance) and SP1 (STU-479, chapter-ordered PERSON prose).

## Goal

Render the chapter-tagged content produced by 1/3 as **native MediaWiki
collapsible blocks** keyed by chapter, and render relationship lines with their
**dated evolution** (ally ch.5 → antagonist ch.20).

## What 1/3 actually produced (the constraint)

STU-491 emits provenance as a **per-section** parallel field, not per-chapter
within the prose. Each page carries:

```
content_units = [{ "section": "<key>", "revealed_at_chapter": <int|null> }, ...]
```

one `min`-chapter per rendered section. Page `content` stays flattened LLM prose.
So the finest gating granularity available to 2/3 is **whole-section**, keyed by
that section's earliest-source chapter.

**Known limitation (accepted, documented):** because provenance is `min`-chapter,
gating is all-or-nothing per section; later-chapter prose inside a section still
shows once that section is open. A stricter "no info from chapter > X outside its
block" guarantee needs 1/3 to emit sub-section provenance — out of scope here.

## Decisions

| Decision | Choice |
|---|---|
| Collapsible mechanism | **Native `mw-collapsible`** — no template to publish, works on any MediaWiki/Fandom |
| Collapse threshold | **Configurable** `generation.spoiler.collapse_after_chapter: N`; unset ⇒ feature off |
| Relationship rendering | **Hybrid** — keep existing French LLM Relations prose (section-gated) + append a deterministic **dated index** (`[[Nom]] — type (ch.X→ch.Y)`) |
| Index source | **Language-neutral fields only** (names, French type enum, chapters) — English `evolution`/`key_moments` are NOT surfaced |
| Rich per-relation FR subsections | **Follow-up** (needs per-relation LLM generation, out of 2/3 scope) |

## Architecture

### New module — `wiki_creator/spoiler_blocks.py` (pure)

```python
def wrap_collapsible(wikitext_body: str, content_units: list[dict], collapse_after: int) -> str
```

- Split `wikitext_body` into `== Heading ==` blocks.
- Build `{ normalized_title: revealed_at_chapter }` from `content_units`, mapping
  each section key to its heading via `_SECTION_TITLES`.
- For each block whose heading matches a unit with
  `revealed_at_chapter > collapse_after`, wrap it:

  ```
  <div class="mw-collapsible mw-collapsed" data-expandtext="Chapitre 5 — révéler" data-collapsetext="Masquer">
  == Biographie ==
  …prose…
  </div>
  ```

- Blocks with no matching unit, `revealed_at_chapter is None`, or
  `revealed_at_chapter <= collapse_after` are left untouched. This "leave open
  when unmatched" default absorbs LLM heading drift (e.g. the model writes
  `## Pouvoirs et compétences` while the key `powers` maps to `Pouvoirs`) without
  falsely hiding content.

Matching is by **normalized heading title**, not block order, so it is robust to
the single-shot path retaining a `## Infobox` block and to sections being omitted.

### Shared section titles — `wiki_creator/sections.py`

Move `_SECTION_TITLES` out of `scripts/generate_wiki_pages.py` into a new shared
module; import it in both `generate_wiki_pages.py` and `spoiler_blocks.py`. This
is the only cross-cutting refactor and it is required (export must map section
keys to their rendered headings).

### New pure function — `relationship_index_lines(entity) -> list[str]`

(in `wiki_creator/spoiler_blocks.py` or a sibling pure module)

**Language constraint (decisive):** `relationship-classifier` emits `evolution`
and `key_moments` in **English** (verified on the real ToG run — e.g. *"Evolves
from antagonistic training dynamic to mutual understanding…"*, *"ch36: Dorian
shows visible concern…"*). The wiki renders its Relations prose in French. So we
do **not** surface that English text. The index is built from **language-neutral
fields only**: entity names, the French `relationship_type` enum
(`amoureux|antagoniste|allié|famille|…`), and chapter numbers.

For each typed relationship (`relationship_type` set) that carries `chapters`,
emit one dated index line:

```
* [[<Nom>]] — <type> (ch.X→ch.Y)
```

- `X` = min, `Y` = max of `chapter_number(c)` over `rel.chapters`; render `ch.X`
  alone when X == Y.
- `<Nom>` is the *other* entity of the pair (not the page's own entity).
- Lines sorted by first-reveal chapter, **most recent reveal first** (per the
  chosen "du plus récent au plus ancien" ordering).
- Deterministic, no LLM, fully French/language-safe. Empty list when no typed
  relationships.

Attached to the page as `page["relationship_index"]` at generation time (the
3 sites that already attach `content_units`), only when `relationships` is in the
page's sections and typed relationships exist.

The English `evolution`/`key_moments` prose per relation (image-2 style
`=== Nom ===` French subsections) is a **follow-up** (needs per-relation LLM
generation — out of this rendering ticket's scope).

### Rendering — `scripts/wiki_export.py :: render_page`

New order of operations for the body:

1. `body = convert(content)`  *(md2wiki, unchanged)*
2. inject the `relationship_index` lines as a dedicated dated index under the
   `== Relations ==` heading — the existing French LLM prose stays untouched
   above it:
   ```
   == Relations ==
   …prose FR existante (inchangée)…

   ''Évolution :''
   * [[Chaol]] — amoureux (ch.1→ch.55)
   * [[Cain]] — antagoniste (ch.7→ch.54)
   * [[Nehemia]] — ami (ch.13→ch.55)
   ```
   Skipped when there is no Relations block or no lines.
3. `body = wrap_collapsible(body, content_units, collapse_after)` when
   `collapse_after` is configured. Injecting the index **before** wrapping means
   it rides inside the Relations toggle when that section is gated.
4. assemble `infobox + body + categories` as today.

`collapse_after` is read from book YAML `generation.spoiler.collapse_after_chapter`
via the input config already threaded into `render_page`'s caller.

### md2wiki — no change

Collapsible `<div>`s are added on wikitext **after** `convert()`, so md2wiki never
sees them. The old blockquote spoiler-warning removal already covers the deleted
warnings the ticket mentions.

## Config

```yaml
generation:
  spoiler:
    collapse_after_chapter: 3   # sections first revealed after ch.3 collapse; ≤3 stay open
```

Unset (or no `spoiler` block) ⇒ feature off ⇒ **no collapsibles emitted** ⇒ output
byte-identical to today. This keeps every golden / smoke test green without update.

## Testing

- **Unit `wrap_collapsible`**: gates the correct block; respects threshold
  boundary (`==` stays open, `>` collapses); `None` revealed_at untouched;
  unmatched heading untouched; expand/collapse text correct.
- **Unit `relationship_index_lines`**: deterministic output; single-chapter
  renders `ch.X`, multi renders `ch.X→ch.Y`; other-entity name chosen; French
  type preserved; sorted most-recent-reveal first; untyped relationships
  excluded; empty when none; no English text emitted.
- **Integration `render_page`**: with config → collapsibles + dated index present,
  no chapter > X leaks outside its block (at section granularity); without config
  → body byte-identical to current output.

## Out of scope

- Sub-section / per-paragraph provenance (would require changing 1/3).
- Custom published Fandom `{{Spoiler}}` template (native mw-collapsible chosen).
- Per-relation French `=== Nom ===` subsections with LLM-authored progression
  prose (image-2 style) — follow-up ticket; blocked on translating/regenerating
  the English `evolution`/`key_moments` into French.
