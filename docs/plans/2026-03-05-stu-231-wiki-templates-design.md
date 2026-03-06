# STU-231 — Wiki Page Templates: Design

**Date:** 2026-03-05
**Ticket:** [STU-231](https://linear.app/studioag/issue/STU-231)
**Status:** Approved

---

## Problem

The `wiki-generation` stage produces free-form Markdown. Without strict templates, the LLM generates inconsistent page structures across entities. We need typed templates (PERSON, PLACE, ORG) with Infobox, structured sections, and depth scaled to entity importance.

---

## Approach

**Approach A — New classification script + templates in system prompt**

- New deterministic `entity-classification` script stage computes entity importance
- Templates embedded in `writer.agent.yaml` system prompt (replace current informal sections)
- Thresholds configurable in `book.input.yaml` with `auto` mode as default
- Contract updated to validate `importance` field per page

---

## Components

### 1. New stage: `scripts/entity_classification.py`

**Pipeline position:** relationship-extraction → **entity-classification** → wiki-generation

**Input (Studio context):**
- `previous_outputs.relationship-extraction`: `{ entities, relationships, stats, narrator }`
- `additional_context`: YAML string (book.input.yaml) containing `thresholds` and `generation`
- Files: `persons_full.json`, `places_full.json`, `orgs_full.json`

**Logic:**
1. For each resolved entity, aggregate `total_mentions` by summing mention counts across all chapters from the `*_full.json` file matching the entity type
2. Compute `chapters_present` = number of chapters with ≥1 mention
3. Read `thresholds` from `additional_context` YAML
4. If `thresholds: auto` → compute percentiles (10%/40%/90%) on `total_mentions` per type:
   - principal = top 10%
   - secondary = 10–40%
   - figurant = 40–90%
   - ignored = bottom 10%
5. If explicit thresholds → apply `min_mentions` and `min_chapters` per tier
6. Assign `importance: "principal" | "secondary" | "figurant" | "ignored"` to each entity

**Output:**
```json
{
  "entities": [
    {
      "canonical_name": "David Martín",
      "type": "PERSON",
      "aliases": ["Martín", "David"],
      "source_ids": ["entity_001"],
      "relevant": true,
      "total_mentions": 234,
      "chapters_present": 18,
      "importance": "principal"
    }
  ],
  "relationships": [...passthrough from relationship-extraction...],
  "stats": {
    "principal": 3,
    "secondary": 12,
    "figurant": 28,
    "ignored": 8,
    "thresholds_used": "auto"
  },
  "narrator": ...passthrough...
}
```

**Passthrough:** `relationships` and `narrator` are forwarded unchanged so that `wiki-generation` only needs to read `previous_stage_output`.

---

### 2. `book.input.yaml` — `thresholds` and `generation` sections

```yaml
# Existing
description: ...
file_path: books/...
spacy_model: fr_core_news_lg

# New — threshold mode (default: auto)
thresholds: auto
# Or explicit:
# thresholds:
#   characters:
#     principal: { min_mentions: 50, min_chapters: 15 }
#     secondary: { min_mentions: 10, min_chapters: 3 }
#     figurant: { min_mentions: 3 }
#     ignored_below: 3
#   locations:
#     major: { min_mentions: 20, min_chapters: 5 }
#     minor: { min_mentions: 3 }
#   organizations:
#     major: { min_mentions: 10 }
#     minor: { min_mentions: 3 }

generation:
  principal:
    sections: [infobox, biography, personality, physical, powers, relationships, trivia, references]
    max_tokens_per_page: 2000
  secondary:
    sections: [infobox, biography, relationships, references]
    max_tokens_per_page: 800
  figurant:
    sections: [infobox, biography]
    max_tokens_per_page: 200
```

---

### 3. `wiki-pipeline.pipeline.yaml` — insert new stage

```yaml
- name: entity-classification
  kind: extraction
  executor: script
  runtime: python
  script: scripts/entity_classification.py
  contract: entity-classification
  context:
    include:
      - input
      - previous_stage_output
```

Insert between `relationship-extraction` and `wiki-generation`. The `wiki-generation` stage already uses `previous_stage_output`, so no context change needed there.

---

### 4. `writer.agent.yaml` — replace informal sections with typed templates

Replace the current `## Wiki page structure` section with:

#### Templates by entity type

**PERSON template:**
```markdown
# {canonical_name}

## Infobox
| Champ | Valeur |
|-------|--------|
| Nom complet | {full_name} |
| Aussi connu comme | {aliases} |
| Titre(s) | {titles} |
| Statut | Vivant / Décédé / Inconnu |
| Espèce/Race | {species} |
| Occupation | {occupation} |
| Résidence | {residence} |
| Affiliation | {faction/house/organization} |
| Première apparition | {first_seen_chapter} |

## Relations
| Relation | Personnage |
|----------|------------|
| Famille | {family_members} |
| Allié(e)s | {allies} |
| Antagoniste(s) | {antagonists} |
| Romance | {romantic_interests} |

## Biographie
### Première apparition
...

### {Arc}
...

## Personnalité
...

## Description physique
...

## Pouvoirs & Capacités
...

## Anecdotes
...

## Références
...
```

**PLACE template:**
```markdown
# {canonical_name}

## Infobox
| Champ | Valeur |
|-------|--------|
| Type | Ville / Quartier / Bâtiment / Région |
| Localisation | {parent_location} |
| Première mention | {first_seen_chapter} |
| Résidents notables | {characters_associated} |

## Description
...

## Événements
...

## Références
...
```

**ORG template:**
```markdown
# {canonical_name}

## Infobox
| Champ | Valeur |
|-------|--------|
| Type | Faction / Entreprise / Institution / Famille |
| Leader(s) | {characters} |
| Membres notables | {characters} |
| Siège | {location} |
| Première mention | {first_seen_chapter} |

## Description
...

## Membres
...

## Événements
...

## Références
...
```

#### Importance-based section selection

- `principal` → full template (all sections)
- `secondary` → Infobox + short biography + Relations + Références (≤800 tokens)
- `figurant` → Infobox + 1-paragraph biography (≤200 tokens)
- `ignored` → skip, do not generate a page

#### Cross-references

Every mention of an entity that has its own wiki page → format as `[[canonical_name]]`.

#### Spoiler warnings

Before each biography section add: `> ⚠️ **Spoilers** — Cette section révèle des événements de l'intrigue.`

#### Narrator attribution (existing behavior, unchanged)

Keep the existing narrator/reliability logic from the current system prompt.

---

### 5. Contracts

**New: `.studio/contracts/entity-classification.contract.yaml`**
```yaml
name: entity-classification
version: 1
schema:
  required_fields:
    - entities
    - relationships
```

**Updated: `.studio/contracts/wiki-generation.contract.yaml`**
```yaml
name: wiki-generation
version: 1
schema:
  required_fields:
    - pages
  # Each page must include: title (str), content (str), importance (str)
```

---

## Acceptance Criteria (from ticket)

- [ ] Templates defined for PERSON, PLACE, ORG
- [ ] `wiki-generation.contract.yaml` validates output structure (title + content + importance)
- [ ] writer.agent.yaml includes templates as structural instructions
- [ ] Thresholds configurable in YAML (explicit or `auto`)
- [ ] `auto` mode computes percentiles on `total_mentions` post-classification
- [ ] Generated sections vary by importance (principal = full, figurant = paragraph)
- [ ] `[[Nom]]` cross-references generated automatically
- [ ] Spoiler warning included before biography sections
- [ ] On *Le Jeu de l'Ange*: David Martín → full page, figurant → paragraph, Petit Poucet → no page

---

## Files Changed

| File | Change |
|------|--------|
| `scripts/entity_classification.py` | New |
| `.studio/pipelines/wiki-pipeline.pipeline.yaml` | Add `entity-classification` stage |
| `.studio/inputs/book.input.yaml` | Add `thresholds` + `generation` sections |
| `.studio/agents/writer.agent.yaml` | Replace informal sections with typed templates + importance logic |
| `.studio/contracts/entity-classification.contract.yaml` | New |
| `.studio/contracts/wiki-generation.contract.yaml` | Add `importance` field comment |
