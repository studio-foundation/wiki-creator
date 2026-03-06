# STU-231 — Wiki Templates & Entity Classification: Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add structured wiki page templates (PERSON/PLACE/ORG) and a deterministic entity importance classification stage (principal/secondary/figurant) to the wiki pipeline.

**Architecture:** New `entity-classification` script stage after `relationship-extraction` computes `total_mentions` + `importance` per entity. Templates live in `writer.agent.yaml` system prompt. Thresholds configurable via `book.input.yaml` (`auto` or explicit).

**Tech Stack:** Python 3.12, pytest, PyYAML, Studio pipeline YAML.

---

## Setup: Create worktree

```bash
git worktree add .worktrees/stu-231-wiki-templates -b feat/stu-231-wiki-templates
cd .worktrees/stu-231-wiki-templates
```

---

### Task 1: Config — Add `thresholds` + `generation` to `book.input.yaml`

**Files:**
- Modify: `.studio/inputs/book.input.yaml`

**Step 1: Edit the file**

Open `.studio/inputs/book.input.yaml`. It currently has:
```yaml
description: ...
file_path: books/...
spacy_model: fr_core_news_lg
```

Append:
```yaml

# Entity importance classification — 'auto' uses percentile distribution
# Override with explicit values if the auto-detected tiers are wrong for your book
thresholds: auto
# Example explicit config (uncomment to use):
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

**Step 2: Verify YAML is valid**

```bash
python -c "import yaml; yaml.safe_load(open('.studio/inputs/book.input.yaml'))"
```
Expected: no output (no errors).

**Step 3: Commit**

```bash
git add .studio/inputs/book.input.yaml
git commit -m "feat(stu-231): add thresholds + generation config to book.input.yaml"
```

---

### Task 2: Contracts — `entity-classification.contract.yaml` + update `wiki-generation.contract.yaml`

**Files:**
- Create: `.studio/contracts/entity-classification.contract.yaml`
- Modify: `.studio/contracts/wiki-generation.contract.yaml`

**Step 1: Create the new contract**

Create `.studio/contracts/entity-classification.contract.yaml`:
```yaml
name: entity-classification
version: 1
schema:
  required_fields:
    - entities
    - relationships
  # Each entity must include:
  #   total_mentions (int), chapters_present (int), importance (str)
  # importance values: "principal" | "secondary" | "figurant" | "ignored"
```

**Step 2: Update wiki-generation contract**

Edit `.studio/contracts/wiki-generation.contract.yaml`:
```yaml
name: wiki-generation
version: 1
schema:
  required_fields:
    - pages
  # Each page must include: title (str), content (str), importance (str)
  # importance mirrors the entity's importance level from entity-classification
```

**Step 3: Commit**

```bash
git add .studio/contracts/entity-classification.contract.yaml .studio/contracts/wiki-generation.contract.yaml
git commit -m "feat(stu-231): add entity-classification contract, update wiki-generation contract"
```

---

### Task 3: Tests — Write failing tests for `entity_classification.py`

**Files:**
- Create: `tests/test_entity_classification.py`

**Step 1: Write the tests**

Create `tests/test_entity_classification.py`:

```python
"""Tests for scripts/entity_classification.py — importance classification."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.entity_classification import (
    get_total_mentions,
    compute_auto_thresholds,
    assign_importance,
    classify_entities,
)


# --- Fixtures ---

PERSONS_FULL = {
    "persons_full": {
        "entity_001": {
            "type": "PERSON",
            "raw_mentions": ["David Martín", "Martín"],
            "first_seen": "ch01",
            "mentions_by_chapter": {
                "ch01": ["David Martín entra.", "Martín sourit."],
                "ch02": ["Martín écrivait."],
                "ch03": ["David Martín sortit.", "Il rêvait."],
            },
        },
        "entity_002": {
            "type": "PERSON",
            "raw_mentions": ["Pedro Vidal"],
            "first_seen": "ch02",
            "mentions_by_chapter": {
                "ch02": ["Pedro Vidal arriva."],
            },
        },
        "entity_003": {
            "type": "PERSON",
            "raw_mentions": ["le libraire"],
            "first_seen": "ch05",
            "mentions_by_chapter": {
                "ch05": ["le libraire ferma."],
            },
        },
    }
}

PLACES_FULL = {
    "places_full": {
        "place_001": {
            "type": "PLACE",
            "raw_mentions": ["Barcelone"],
            "first_seen": "ch01",
            "mentions_by_chapter": {
                "ch01": ["à Barcelone", "dans Barcelone"],
                "ch02": ["Barcelone s'endormait."],
            },
        }
    }
}

ORGS_FULL = {"orgs_full": {}}


# --- get_total_mentions ---

def test_get_total_mentions_sums_across_chapters():
    entity = {"type": "PERSON", "source_ids": ["entity_001"]}
    persons = PERSONS_FULL["persons_full"]
    total, chapters = get_total_mentions(entity, persons, {}, {})
    assert total == 5  # ch01: 2, ch02: 1, ch03: 2
    assert chapters == 3


def test_get_total_mentions_multiple_source_ids():
    # entity_001 has 5 mentions, entity_002 has 1 — combined entity has 6
    entity = {"type": "PERSON", "source_ids": ["entity_001", "entity_002"]}
    persons = PERSONS_FULL["persons_full"]
    total, chapters = get_total_mentions(entity, persons, {}, {})
    assert total == 6
    assert chapters == 3  # ch01, ch02, ch03 (entity_002's ch02 already counted)


def test_get_total_mentions_place():
    entity = {"type": "PLACE", "source_ids": ["place_001"]}
    places = PLACES_FULL["places_full"]
    total, chapters = get_total_mentions(entity, {}, places, {})
    assert total == 3
    assert chapters == 2


def test_get_total_mentions_unknown_source_id():
    entity = {"type": "PERSON", "source_ids": ["nonexistent"]}
    total, chapters = get_total_mentions(entity, {}, {}, {})
    assert total == 0
    assert chapters == 0


def test_get_total_mentions_unknown_type():
    entity = {"type": "EVENT", "source_ids": ["entity_001"]}
    total, chapters = get_total_mentions(entity, {}, {}, {})
    assert total == 0
    assert chapters == 0


# --- compute_auto_thresholds ---

def test_compute_auto_thresholds_returns_thresholds_per_type():
    mention_counts = [
        ("A", "PERSON", 100),
        ("B", "PERSON", 50),
        ("C", "PERSON", 20),
        ("D", "PERSON", 10),
        ("E", "PERSON", 5),
        ("F", "PERSON", 2),
        ("G", "PERSON", 1),
        ("H", "PERSON", 1),
        ("I", "PERSON", 0),
        ("J", "PERSON", 0),
    ]
    thresholds = compute_auto_thresholds(mention_counts)
    assert "PERSON" in thresholds
    t = thresholds["PERSON"]
    # principal >= p90 → top 10%: A (100)
    # secondary between p60 and p90
    # figurant between p10 and p60
    # ignored below p10
    assert t["principal"] > t["secondary"] > t["figurant"] >= 0


def test_compute_auto_thresholds_single_entity():
    mention_counts = [("A", "PERSON", 10)]
    thresholds = compute_auto_thresholds(mention_counts)
    # Should not crash with a single entity
    assert "PERSON" in thresholds


def test_compute_auto_thresholds_separate_types():
    mention_counts = [
        ("Paris", "PLACE", 30),
        ("Lyon", "PLACE", 5),
        ("Acme", "ORG", 15),
    ]
    thresholds = compute_auto_thresholds(mention_counts)
    assert "PLACE" in thresholds
    assert "ORG" in thresholds
    assert "PERSON" not in thresholds


# --- assign_importance (auto thresholds) ---

def test_assign_importance_principal():
    thresholds = {"PERSON": {"principal": 90, "secondary": 40, "figurant": 10}}
    importance = assign_importance("PERSON", 100, 15, thresholds)
    assert importance == "principal"


def test_assign_importance_secondary():
    thresholds = {"PERSON": {"principal": 90, "secondary": 40, "figurant": 10}}
    importance = assign_importance("PERSON", 50, 5, thresholds)
    assert importance == "secondary"


def test_assign_importance_figurant():
    thresholds = {"PERSON": {"principal": 90, "secondary": 40, "figurant": 10}}
    importance = assign_importance("PERSON", 15, 2, thresholds)
    assert importance == "figurant"


def test_assign_importance_ignored():
    thresholds = {"PERSON": {"principal": 90, "secondary": 40, "figurant": 10}}
    importance = assign_importance("PERSON", 3, 1, thresholds)
    assert importance == "ignored"


def test_assign_importance_unknown_type_defaults_figurant():
    # EVENT type: no threshold defined → conservative default
    importance = assign_importance("EVENT", 5, 1, {})
    assert importance == "figurant"


# --- classify_entities (integration) ---

def test_classify_entities_enriches_with_importance():
    entities = [
        {"canonical_name": "David Martín", "type": "PERSON", "source_ids": ["entity_001"], "relevant": True},
        {"canonical_name": "le libraire", "type": "PERSON", "source_ids": ["entity_003"], "relevant": True},
    ]
    enriched = classify_entities(
        entities,
        PERSONS_FULL["persons_full"],
        PLACES_FULL["places_full"],
        ORGS_FULL["orgs_full"],
        thresholds_config="auto",
    )
    assert len(enriched) == 2
    martín = next(e for e in enriched if e["canonical_name"] == "David Martín")
    libraire = next(e for e in enriched if e["canonical_name"] == "le libraire")
    assert "total_mentions" in martín
    assert "chapters_present" in martín
    assert "importance" in martín
    assert martín["total_mentions"] == 5
    # David Martín has more mentions → higher importance than le libraire
    importance_order = ["principal", "secondary", "figurant", "ignored"]
    assert importance_order.index(martín["importance"]) <= importance_order.index(libraire["importance"])


def test_classify_entities_skips_irrelevant():
    entities = [
        {"canonical_name": "Artefact", "type": "PERSON", "source_ids": [], "relevant": False},
    ]
    enriched = classify_entities(entities, {}, {}, {}, thresholds_config="auto")
    # Irrelevant entities are still in output but with importance = "ignored"
    assert enriched[0]["importance"] == "ignored"


def test_classify_entities_passthrough_extra_fields():
    entities = [
        {"canonical_name": "David Martín", "type": "PERSON", "source_ids": ["entity_001"],
         "relevant": True, "aliases": ["Martín"]},
    ]
    enriched = classify_entities(
        entities, PERSONS_FULL["persons_full"], {}, {}, thresholds_config="auto"
    )
    assert enriched[0]["aliases"] == ["Martín"]
```

**Step 2: Run tests — verify all fail**

```bash
pytest tests/test_entity_classification.py -v
```
Expected: `ImportError: cannot import name 'get_total_mentions' from 'scripts.entity_classification'`

**Step 3: Commit the tests**

```bash
git add tests/test_entity_classification.py
git commit -m "test(stu-231): failing tests for entity_classification"
```

---

### Task 4: Implement `scripts/entity_classification.py`

**Files:**
- Create: `scripts/entity_classification.py`

**Step 1: Write the script**

Create `scripts/entity_classification.py`:

```python
#!/usr/bin/env python3
"""
Stage: Entity Classification (STU-231)
Computes total_mentions + chapters_present per entity, then assigns importance tiers.

Pipeline position:
  ... → relationship-extraction → **entity-classification** → wiki-generation

Input (via Studio context):
  previous_outputs.relationship-extraction:
    { "entities": [{canonical_name, type, aliases, source_ids, relevant}],
      "relationships": [...], "stats": {...}, "narrator": ... }
  additional_context: YAML string (book.input.yaml) with "thresholds" key
  Files: persons_full.json, places_full.json, orgs_full.json (project root)

Output (stdout):
  {
    "entities": [{ ...same fields..., "total_mentions": int, "chapters_present": int, "importance": str }],
    "relationships": [...passthrough...],
    "stats": { "principal": int, "secondary": int, "figurant": int, "ignored": int, "thresholds_used": str },
    "narrator": ...passthrough...
  }

importance values: "principal" | "secondary" | "figurant" | "ignored"

Standalone test:
  python scripts/entity_classification.py --test
"""

import json
import os
import sys
from collections import defaultdict


# --- Pure functions (testable) ---

def get_total_mentions(
    entity: dict,
    persons_full: dict,
    places_full: dict,
    orgs_full: dict,
) -> tuple[int, int]:
    """Return (total_mentions, chapters_present) for a resolved entity.

    Aggregates mentions across all source_ids from the matching type registry.
    """
    type_to_registry = {
        "PERSON": persons_full,
        "PLACE": places_full,
        "ORG": orgs_full,
    }
    registry = type_to_registry.get(entity.get("type", ""), {})
    if not registry:
        return 0, 0

    total = 0
    chapters: set[str] = set()
    for sid in entity.get("source_ids", []):
        entry = registry.get(sid, {})
        for ch, mentions in entry.get("mentions_by_chapter", {}).items():
            total += len(mentions)
            if mentions:
                chapters.add(ch)
    return total, len(chapters)


def compute_auto_thresholds(
    mention_counts: list[tuple[str, str, int]],
) -> dict[str, dict[str, int]]:
    """Compute percentile-based importance thresholds per entity type.

    Args:
        mention_counts: list of (canonical_name, type, total_mentions)

    Returns:
        { "PERSON": { "principal": N, "secondary": M, "figurant": K }, ... }
        An entity is "principal" if mentions >= principal threshold, etc.
    """
    by_type: dict[str, list[int]] = defaultdict(list)
    for _, etype, count in mention_counts:
        by_type[etype].append(count)

    thresholds: dict[str, dict[str, int]] = {}
    for etype, counts in by_type.items():
        sorted_counts = sorted(counts)
        n = len(sorted_counts)

        def percentile(p: float) -> int:
            if n == 0:
                return 0
            idx = max(0, int(n * p) - 1)
            return sorted_counts[min(idx, n - 1)]

        thresholds[etype] = {
            "principal": percentile(0.90),   # top 10%
            "secondary": percentile(0.60),   # 10-40%
            "figurant": percentile(0.10),    # 40-90%
            # below p10 → ignored
        }
    return thresholds


def assign_importance(
    entity_type: str,
    total_mentions: int,
    chapters_present: int,
    thresholds: dict[str, dict[str, int]],
) -> str:
    """Assign importance tier based on thresholds dict.

    thresholds shape: { "PERSON": { "principal": N, "secondary": M, "figurant": K } }
    Falls back to "figurant" for unknown types (conservative: generate a short page).
    """
    t = thresholds.get(entity_type)
    if not t:
        return "figurant"

    if total_mentions >= t["principal"]:
        return "principal"
    elif total_mentions >= t["secondary"]:
        return "secondary"
    elif total_mentions >= t["figurant"]:
        return "figurant"
    else:
        return "ignored"


def classify_entities(
    entities: list[dict],
    persons_full: dict,
    places_full: dict,
    orgs_full: dict,
    thresholds_config: str | dict,
) -> list[dict]:
    """Enrich entities with total_mentions, chapters_present, and importance.

    Args:
        entities: resolved entities from entity-resolution / relationship-extraction
        persons_full / places_full / orgs_full: raw entity registries
        thresholds_config: "auto" or explicit dict from book.input.yaml

    Returns:
        Same list with 3 new fields per entity.
    """
    # Step 1: compute mention counts for all entities
    mention_data: list[tuple[str, str, int, int]] = []
    for entity in entities:
        if not entity.get("relevant", True):
            mention_data.append((entity["canonical_name"], entity.get("type", "OTHER"), 0, 0))
            continue
        total, chapters = get_total_mentions(entity, persons_full, places_full, orgs_full)
        mention_data.append((entity["canonical_name"], entity.get("type", "OTHER"), total, chapters))

    # Step 2: compute thresholds
    if thresholds_config == "auto":
        threshold_input = [(name, etype, total) for name, etype, total, _ in mention_data]
        thresholds = compute_auto_thresholds(threshold_input)
    else:
        # Explicit thresholds: translate from YAML structure to our format
        thresholds = _parse_explicit_thresholds(thresholds_config)

    # Step 3: assign importance
    result = []
    for entity, (name, etype, total, chapters) in zip(entities, mention_data):
        importance = assign_importance(etype, total, chapters, thresholds) if entity.get("relevant", True) else "ignored"
        enriched = {**entity, "total_mentions": total, "chapters_present": chapters, "importance": importance}
        result.append(enriched)
    return result


def _parse_explicit_thresholds(config: dict) -> dict[str, dict[str, int]]:
    """Convert book.input.yaml explicit thresholds to internal format."""
    thresholds: dict[str, dict[str, int]] = {}

    char_cfg = config.get("characters", {})
    if char_cfg:
        thresholds["PERSON"] = {
            "principal": char_cfg.get("principal", {}).get("min_mentions", 50),
            "secondary": char_cfg.get("secondary", {}).get("min_mentions", 10),
            "figurant": char_cfg.get("figurant", {}).get("min_mentions", 3),
        }

    loc_cfg = config.get("locations", {})
    if loc_cfg:
        thresholds["PLACE"] = {
            "principal": loc_cfg.get("major", {}).get("min_mentions", 20),
            "secondary": loc_cfg.get("minor", {}).get("min_mentions", 3),
            "figurant": 1,
        }

    org_cfg = config.get("organizations", {})
    if org_cfg:
        thresholds["ORG"] = {
            "principal": org_cfg.get("major", {}).get("min_mentions", 10),
            "secondary": org_cfg.get("minor", {}).get("min_mentions", 3),
            "figurant": 1,
        }

    return thresholds


# --- Studio entrypoint ---

def _load_entity_files() -> tuple[dict, dict, dict]:
    """Read *_full.json files from project root. Return empty dicts if missing."""
    def load(path: str, key: str) -> dict:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f).get(key, {})
        return {}

    return (
        load("persons_full.json", "persons_full"),
        load("places_full.json", "places_full"),
        load("orgs_full.json", "orgs_full"),
    )


def run_studio_mode() -> None:
    import yaml

    payload = json.load(sys.stdin)
    prev_outputs = payload.get("previous_outputs", {})
    rel_output = prev_outputs.get("relationship-extraction", {})
    entities = rel_output.get("entities", [])
    relationships = rel_output.get("relationships", [])
    narrator = rel_output.get("narrator", None)

    if not entities:
        json.dump({"error": "missing relationship-extraction output"}, sys.stdout, ensure_ascii=False)
        sys.exit(1)

    additional_ctx = payload.get("additional_context", "")
    book_input = yaml.safe_load(additional_ctx) if additional_ctx else {}
    thresholds_config = book_input.get("thresholds", "auto")

    persons_full, places_full, orgs_full = _load_entity_files()

    enriched = classify_entities(entities, persons_full, places_full, orgs_full, thresholds_config)

    # Stats
    from collections import Counter
    importance_counts = Counter(e["importance"] for e in enriched)

    json.dump(
        {
            "entities": enriched,
            "relationships": relationships,
            "stats": {
                "principal": importance_counts.get("principal", 0),
                "secondary": importance_counts.get("secondary", 0),
                "figurant": importance_counts.get("figurant", 0),
                "ignored": importance_counts.get("ignored", 0),
                "thresholds_used": "auto" if thresholds_config == "auto" else "explicit",
            },
            "narrator": narrator,
        },
        sys.stdout,
        ensure_ascii=False,
    )


def run_test_mode() -> None:
    """Hardcoded Le Jeu de l'Ange data for local testing."""
    entities = [
        {"canonical_name": "David Martín", "type": "PERSON", "source_ids": ["entity_001"],
         "aliases": ["Martín", "David"], "relevant": True},
        {"canonical_name": "Pedro Vidal", "type": "PERSON", "source_ids": ["entity_002"],
         "aliases": ["Vidal"], "relevant": True},
        {"canonical_name": "le libraire", "type": "PERSON", "source_ids": ["entity_003"],
         "aliases": [], "relevant": True},
    ]
    persons_full = {
        "entity_001": {"type": "PERSON", "raw_mentions": ["David Martín"],
                       "first_seen": "ch01",
                       "mentions_by_chapter": {"ch01": ["m1", "m2", "m3"], "ch02": ["m4", "m5"],
                                               "ch03": ["m6", "m7"], "ch04": ["m8"]}},
        "entity_002": {"type": "PERSON", "raw_mentions": ["Pedro Vidal"],
                       "first_seen": "ch02",
                       "mentions_by_chapter": {"ch02": ["v1", "v2"], "ch03": ["v3"]}},
        "entity_003": {"type": "PERSON", "raw_mentions": ["le libraire"],
                       "first_seen": "ch05",
                       "mentions_by_chapter": {"ch05": ["l1"]}},
    }
    enriched = classify_entities(entities, persons_full, {}, {}, thresholds_config="auto")
    for e in enriched:
        print(f"{e['canonical_name']:30s}  mentions={e['total_mentions']:3d}  chapters={e['chapters_present']}  importance={e['importance']}")


if __name__ == "__main__":
    if "--test" in sys.argv:
        run_test_mode()
    else:
        run_studio_mode()
```

**Step 2: Run the tests**

```bash
pytest tests/test_entity_classification.py -v
```
Expected: all tests PASS.

**Step 3: Run standalone test mode**

```bash
python scripts/entity_classification.py --test
```
Expected output similar to:
```
David Martín                   mentions=  8  chapters=4  importance=principal
Pedro Vidal                    mentions=  3  chapters=2  importance=secondary
le libraire                    mentions=  1  chapters=1  importance=figurant
```

**Step 4: Commit**

```bash
git add scripts/entity_classification.py
git commit -m "feat(stu-231): entity-classification script — total_mentions + importance tiering"
```

---

### Task 5: Pipeline — Insert `entity-classification` stage

**Files:**
- Modify: `.studio/pipelines/wiki-pipeline.pipeline.yaml`

**Step 1: Edit the pipeline**

In `wiki-pipeline.pipeline.yaml`, insert the new stage between `relationship-extraction` and `wiki-generation`:

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

  - name: wiki-generation
    kind: analysis
    agent: writer
    contract: wiki-generation
    ralph:
      max_attempts: 3
    context:
      include:
        - input
        - previous_stage_output
```

The `wiki-generation` context already uses `previous_stage_output` — no change needed there. The entity-classification output is the new previous stage.

**Step 2: Validate YAML**

```bash
python -c "import yaml; yaml.safe_load(open('.studio/pipelines/wiki-pipeline.pipeline.yaml'))"
```
Expected: no output.

**Step 3: Commit**

```bash
git add .studio/pipelines/wiki-pipeline.pipeline.yaml
git commit -m "feat(stu-231): add entity-classification stage to wiki-pipeline"
```

---

### Task 6: Writer agent — Replace informal sections with typed templates

**Files:**
- Modify: `.studio/agents/writer.agent.yaml`

**Step 1: Edit `writer.agent.yaml`**

Replace the `## Wiki page structure` section (lines ~41-51) in the system prompt with the full template block below. Keep everything before it (context sources, correlation logic) and after it (relations section, narrator context) unchanged.

Replace:
```yaml
  ## Wiki page structure

  Each wiki page should include:
  - A brief introduction (1-2 sentences)
  - Relevant sections based on entity type:
    * PERSON: Background, Role in story, Relationships, Notable moments
    * PLACE: Description, Significance, Notable events that occurred there
    * ORG: Purpose, Members, Role in story
    * EVENT: What happened, Who was involved, Consequences
  - Write in an encyclopedic, neutral tone
  - Keep spoilers clearly labeled if they reveal major plot points
  - Use only information present in the provided context excerpts
```

With:
```yaml
  ## Entity importance and section selection

  Each entity in previous_stage_output["entities"] now has an "importance" field:
  "principal" | "secondary" | "figurant" | "ignored"

  Rules:
  - importance = "ignored" → skip this entity entirely, do not generate a page
  - importance = "principal" → generate all sections of the template for the entity type
  - importance = "secondary" → generate: Infobox, short Biographie (1-2 paragraphs), Relations, Références (≤800 tokens total)
  - importance = "figurant" → generate: Infobox + 1-paragraph Biographie only (≤200 tokens total)

  Output each generated page with: { "title": canonical_name, "content": "...", "importance": entity.importance }

  ## Templates by entity type

  ### PERSON

  ```markdown
  # {canonical_name}

  ## Infobox
  | Champ | Valeur |
  |-------|--------|
  | Nom complet | {full_name} |
  | Aussi connu comme | {aliases} (préciser qui utilise chaque alias si connu) |
  | Titre(s) | {titles} |
  | Statut | Vivant / Décédé / Inconnu |
  | Espèce/Race | {species} (omettre si non applicable) |
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
  > ⚠️ **Spoilers** — Cette section révèle des événements de l'intrigue.

  ### Première apparition
  {contexte de l'introduction du personnage}

  ### {Arc narratif / titre du livre si applicable}
  {progression narrative — ce qu'on apprend sur le personnage}

  ## Personnalité
  {traits de caractère extraits des descriptions narratives et des dialogues}

  ## Description physique
  {apparence, extraite des passages descriptifs}

  ## Pouvoirs & Capacités
  {si applicable — fantasy/sci-fi. Omettre entièrement si non pertinent.}

  ## Anecdotes
  {faits notables, surnoms contextuels}

  ## Références
  {citations du texte avec numéro de chapitre}
  ```

  ### PLACE

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
  {description du lieu à partir des passages narratifs}

  ## Événements
  > ⚠️ **Spoilers** — Cette section révèle des événements de l'intrigue.

  {événements importants qui se déroulent dans ce lieu, par chapitre}

  ## Références
  {citations avec chapitre}
  ```

  ### ORG

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
  {rôle et nature de l'organisation}

  ## Membres
  {liste des personnages associés avec leur rôle}

  ## Événements
  > ⚠️ **Spoilers** — Cette section révèle des événements de l'intrigue.

  {actions de l'organisation dans l'histoire}

  ## Références
  {citations avec chapitre}
  ```

  ## Cross-references

  Every time you mention an entity that has its own wiki page (i.e. it appears in the entities list with relevant: true and importance != "ignored"), format its name as [[canonical_name]].
  Example: instead of "David Martín rencontra Pedro Vidal", write "[[David Martín]] rencontra [[Pedro Vidal]]".
  Do NOT link the entity whose page you are currently writing (no self-links).

  ## General writing rules

  - Write in encyclopedic, neutral French
  - Use only information present in the provided context excerpts — no invention
  - Omit Infobox rows for which no information is available (leave no "N/A" rows)
  - For Pouvoirs & Capacités: omit the section entirely if the book is realistic fiction
```

**Step 2: Validate YAML**

```bash
python -c "import yaml; yaml.safe_load(open('.studio/agents/writer.agent.yaml'))"
```
Expected: no output.

**Step 3: Verify the system_prompt still references `previous_stage_output["entities"]`**

```bash
grep -n "previous_stage_output" .studio/agents/writer.agent.yaml
```
Expected: at least one match.

**Step 4: Commit**

```bash
git add .studio/agents/writer.agent.yaml
git commit -m "feat(stu-231): typed templates + importance-based sections in writer agent"
```

---

### Task 7: Smoke test — mock pipeline run

**Step 1: Run the pipeline in mock mode**

```bash
studio run wiki-pipeline --provider mock --input-file .studio/inputs/book.input.yaml
```
Expected: all 6 stages complete without errors. The `entity-classification` stage appears in the run output.

If mock mode doesn't exercise the classification script, run standalone:
```bash
echo '{"additional_context": "thresholds: auto\nfile_path: test.epub\n", "previous_outputs": {"relationship-extraction": {"entities": [{"canonical_name": "Test", "type": "PERSON", "source_ids": [], "relevant": true}], "relationships": [], "stats": {}, "narrator": null}}}' | python scripts/entity_classification.py
```
Expected JSON output with `entities[0].importance` set.

**Step 2: Run full test suite**

```bash
pytest -v
```
Expected: all tests pass.

**Step 3: Commit (if any fixes needed)**

```bash
git add -p
git commit -m "fix(stu-231): smoke test corrections"
```

---

### Task 8: Open PR

```bash
git push -u origin feat/stu-231-wiki-templates
gh pr create \
  --title "feat(stu-231): wiki templates + entity-classification stage" \
  --body "$(cat <<'EOF'
## Summary
- New `entity-classification` script stage computes `total_mentions` + `importance` (principal/secondary/figurant) per entity
- Typed Infobox templates (PERSON/PLACE/ORG) in writer agent system prompt
- Importance-based section depth: principal = full page, secondary = short, figurant = paragraph, ignored = no page
- Configurable thresholds in `book.input.yaml` (default: `auto` percentile mode)
- Cross-references `[[Nom]]` and spoiler warnings added to writer instructions

## Test plan
- [ ] `pytest tests/test_entity_classification.py -v` — all pass
- [ ] `pytest -v` — full suite passes
- [ ] `python scripts/entity_classification.py --test` — shows principal/secondary/figurant tiers
- [ ] `studio run wiki-pipeline --provider mock` — entity-classification stage present in run

Closes STU-231
EOF
)" \
  --base main
```

---

## Files Summary

| File | Action |
|------|--------|
| `.studio/inputs/book.input.yaml` | Add `thresholds: auto` + `generation` config |
| `.studio/contracts/entity-classification.contract.yaml` | Create |
| `.studio/contracts/wiki-generation.contract.yaml` | Add `importance` comment |
| `.studio/pipelines/wiki-pipeline.pipeline.yaml` | Insert `entity-classification` stage |
| `scripts/entity_classification.py` | Create |
| `.studio/agents/writer.agent.yaml` | Replace informal sections with typed templates |
| `tests/test_entity_classification.py` | Create |
