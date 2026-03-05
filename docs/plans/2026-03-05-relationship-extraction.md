# Relationship Extraction Implementation Plan (STU-229)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `relationship-extraction` stage to the wiki pipeline that builds a weighted co-occurrence graph between resolved PERSON entities, with optional LLM-based relationship classification.

**Architecture:** Single Python script (`scripts/relationship_extraction.py`) following the same pattern as `entity_clustering.py`: reads Studio JSON from stdin, outputs JSON to stdout; `--test` mode for standalone validation; `--classify` flag activates Haiku LLM classification for pairs above a configurable threshold.

**Tech Stack:** Python 3.11+, standard library only for cooccurrence (no new deps), `anthropic` SDK for classification (already used by Studio runtime, add to pyproject.toml).

---

## Task 1: Worktree + branch setup

**Files:**
- No code files

**Step 1: Create worktree**

```bash
git worktree add .worktrees/stu-229-relationship-extraction -b feat/stu-229-relationship-extraction
cd .worktrees/stu-229-relationship-extraction
```

**Step 2: Verify clean state**

```bash
git status
```
Expected: `nothing to commit, working tree clean`

---

## Task 2: Add `ExtractedRelationship` type

**Files:**
- Modify: `wiki_creator/types.py`

**Step 1: Write a failing test**

Create `tests/test_types.py`:
```python
from wiki_creator.types import ExtractedRelationship

def test_extracted_relationship_fields():
    rel = ExtractedRelationship(
        entity_a="David Martín",
        entity_b="Pedro Vidal",
        cooccurrence_count=45,
        chapters=["ch01", "ch03"],
        sample_contexts=["Vidal tendit le manuscrit à Martín..."],
    )
    assert rel.entity_a == "David Martín"
    assert rel.cooccurrence_count == 45
    assert rel.relationship_type is None
    assert rel.direction is None
    assert rel.evolution is None
    assert rel.key_moments == []
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_types.py -v
```
Expected: FAIL with `ImportError: cannot import name 'ExtractedRelationship'`

**Step 3: Add the type to `wiki_creator/types.py`**

Append after the `EntityRegistry` class:
```python
@dataclass
class ExtractedRelationship:
    entity_a: str
    entity_b: str
    cooccurrence_count: int
    chapters: list[str] = field(default_factory=list)
    sample_contexts: list[str] = field(default_factory=list)
    # LLM-filled fields (None if --classify not used)
    relationship_type: str | None = None
    direction: str | None = None
    evolution: str | None = None
    key_moments: list[str] = field(default_factory=list)
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_types.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add wiki_creator/types.py tests/test_types.py
git commit -m "feat(stu-229): add ExtractedRelationship type"
```

---

## Task 3: Implement cooccurrence core

**Files:**
- Create: `scripts/relationship_extraction.py`

**Step 1: Write the failing --test mode first**

Create `scripts/relationship_extraction.py` with just the test harness and a stub:

```python
#!/usr/bin/env python3
"""
Stage: Relationship Extraction (STU-229)
Builds a weighted co-occurrence graph between resolved PERSON entities.

Pipeline position:
  epub-parse → entity-extraction → entity-clustering → entity-resolution
  → relationship-extraction → wiki-generation

Input (via Studio context):
  previous_outputs.entity-resolution: { "entities": [{canonical_name, type, aliases, source_ids, relevant}] }
  Files read from repo root: persons_full.json

Output (stdout):
  {
    "relationships": [
      {
        "entity_a": "David Martín",
        "entity_b": "Pedro Vidal",
        "cooccurrence_count": 45,
        "chapters": ["ch01", "ch03"],
        "sample_contexts": ["Vidal tendit le manuscrit à Martín..."],
        "relationship_type": null,
        "direction": null,
        "evolution": null,
        "key_moments": []
      }
    ],
    "stats": {
      "total_pairs_checked": 120,
      "pairs_above_threshold": 18,
      "classified": 0,
      "window_size": 5,
      "threshold": 5
    }
  }

Standalone test:
  python scripts/relationship_extraction.py --test
  python scripts/relationship_extraction.py --test --classify
  python scripts/relationship_extraction.py --test --window 3 --threshold 2
"""

import json
import sys


DEFAULT_WINDOW = 5
DEFAULT_THRESHOLD = 5


def build_cooccurrence_graph(
    entities: list[dict],
    mentions_by_entity: dict[str, dict[str, list[str]]],
    window_size: int = DEFAULT_WINDOW,
    threshold: int = DEFAULT_THRESHOLD,
) -> tuple[list[dict], dict]:
    """
    Build weighted co-occurrence graph between PERSON entities.

    Args:
        entities: resolved entities with canonical_name, aliases, relevant, type
        mentions_by_entity: {canonical_name: {chapter_id: [sentence, ...]}}
        window_size: sliding window of N sentences
        threshold: minimum co-occurrence count to include in output

    Returns:
        (relationships list, stats dict)
    """
    raise NotImplementedError


def run_test_mode(window_size: int, threshold: int) -> None:
    """Run with hardcoded Le Jeu de l'Ange data."""
    # Simulated resolved entities (PERSON only, relevant: true)
    entities = [
        {"canonical_name": "David Martín", "type": "PERSON", "aliases": ["Martín", "David"], "relevant": True},
        {"canonical_name": "Pedro Vidal", "type": "PERSON", "aliases": ["Vidal"], "relevant": True},
        {"canonical_name": "Andreas Corelli", "type": "PERSON", "aliases": ["Corelli"], "relevant": True},
        {"canonical_name": "Isabella", "type": "PERSON", "aliases": ["Isa"], "relevant": True},
        {"canonical_name": "Cristina", "type": "PERSON", "aliases": [], "relevant": True},
    ]

    # Simulated mentions_by_chapter (sentences containing each entity)
    # In production, this comes from persons_full.json
    mentions_by_entity = {
        "David Martín": {
            "ch01": [
                "Vidal tendit le manuscrit à Martín en souriant.",
                "Martín retrouva Vidal au café de la rue Fernando.",
                "Martín écrivit toute la nuit.",
                "Vidal encouragea Martín à continuer son roman.",
                "Martín pensait souvent à Isabella.",
            ],
            "ch02": [
                "Martín reçut une lettre de Corelli.",
                "Corelli proposa un contrat à Martín.",
                "Martín hésita longtemps avant d'accepter.",
                "Cristina observait Martín depuis le couloir.",
                "Martín ne remarqua pas Cristina.",
            ],
            "ch03": [
                "Isabella retrouva Martín dans le parc.",
                "Martín et Isabella parlèrent des heures.",
                "Vidal arriva et interrompit leur conversation.",
                "Martín regarda Vidal avec méfiance.",
                "Corelli attendait Martín dans son bureau.",
            ],
        },
        "Pedro Vidal": {
            "ch01": [
                "Vidal tendit le manuscrit à Martín en souriant.",
                "Martín retrouva Vidal au café de la rue Fernando.",
                "Vidal encouragea Martín à continuer son roman.",
                "Vidal rentra chez lui à minuit.",
            ],
            "ch03": [
                "Vidal arriva et interrompit leur conversation.",
                "Martín regarda Vidal avec méfiance.",
            ],
        },
        "Andreas Corelli": {
            "ch02": [
                "Martín reçut une lettre de Corelli.",
                "Corelli proposa un contrat à Martín.",
                "Martín hésita longtemps avant d'accepter.",
                "Corelli attendait Martín dans son bureau.",
            ],
            "ch03": [
                "Corelli attendait Martín dans son bureau.",
            ],
        },
        "Isabella": {
            "ch01": [
                "Martín pensait souvent à Isabella.",
            ],
            "ch03": [
                "Isabella retrouva Martín dans le parc.",
                "Martín et Isabella parlèrent des heures.",
                "Vidal arriva et interrompit leur conversation.",
            ],
        },
        "Cristina": {
            "ch02": [
                "Cristina observait Martín depuis le couloir.",
                "Martín ne remarqua pas Cristina.",
            ],
        },
    }

    relationships, stats = build_cooccurrence_graph(
        entities, mentions_by_entity, window_size, threshold
    )

    print(f"=== TEST MODE — relationship-extraction ===\n")
    print(f"Window size: {window_size}  |  Threshold: {threshold}\n")
    print(f"Top relationships (cooccurrence_count desc):\n")
    for rel in relationships[:20]:
        classified = f"  → {rel['relationship_type']}" if rel.get("relationship_type") else ""
        print(f"  {rel['entity_a']} ↔ {rel['entity_b']}")
        print(f"    count={rel['cooccurrence_count']}  chapters={rel['chapters']}{classified}")
        if rel.get("sample_contexts"):
            print(f"    sample: {rel['sample_contexts'][0][:80]}...")
        print()

    print(f"=== STATS ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    # Validation
    top_pairs = {
        (r["entity_a"], r["entity_b"]) for r in relationships
    } | {
        (r["entity_b"], r["entity_a"]) for r in relationships
    }
    expected = [
        ("David Martín", "Pedro Vidal"),
        ("David Martín", "Andreas Corelli"),
        ("David Martín", "Isabella"),
        ("David Martín", "Cristina"),
    ]
    print("\n=== VALIDATION ===")
    all_ok = True
    for a, b in expected:
        found = (a, b) in top_pairs or (b, a) in top_pairs
        status = "✓" if found else "✗ MISSING"
        print(f"  {status}  {a} ↔ {b}")
        if not found:
            all_ok = False
    print(f"\n{'All expected pairs found.' if all_ok else 'SOME PAIRS MISSING — check algorithm.'}")


def main() -> None:
    args = sys.argv[1:]

    window_size = DEFAULT_WINDOW
    threshold = DEFAULT_THRESHOLD

    if "--window" in args:
        idx = args.index("--window")
        window_size = int(args[idx + 1])

    if "--threshold" in args:
        idx = args.index("--threshold")
        threshold = int(args[idx + 1])

    if "--test" in args:
        run_test_mode(window_size, threshold)
        return

    payload = json.load(sys.stdin)
    # TODO: implement Studio mode after test mode is validated
    json.dump({"error": "Studio mode not yet implemented"}, sys.stdout)


if __name__ == "__main__":
    main()
```

**Step 2: Run --test to verify it fails**

```bash
python scripts/relationship_extraction.py --test
```
Expected: `NotImplementedError`

**Step 3: Implement `build_cooccurrence_graph`**

Replace the `raise NotImplementedError` with the actual implementation:

```python
def build_cooccurrence_graph(
    entities: list[dict],
    mentions_by_entity: dict[str, dict[str, list[str]]],
    window_size: int = DEFAULT_WINDOW,
    threshold: int = DEFAULT_THRESHOLD,
) -> tuple[list[dict], dict]:
    # Filter to PERSON entities that are relevant
    persons = [e for e in entities if e.get("type") == "PERSON" and e.get("relevant", True)]

    # Build lookup: all known names (canonical + aliases ≥4 chars) → canonical_name
    name_to_canonical: dict[str, str] = {}
    for entity in persons:
        canonical = entity["canonical_name"]
        name_to_canonical[canonical.lower()] = canonical
        for alias in entity.get("aliases", []):
            if len(alias) >= 4:
                name_to_canonical[alias.lower()] = canonical

    # Co-occurrence matrix: {(canonical_a, canonical_b): {"count": int, "chapters": set, "contexts": list}}
    cooc: dict[tuple[str, str], dict] = {}

    total_pairs_checked = len(persons) * (len(persons) - 1) // 2

    for canonical, chapters in mentions_by_entity.items():
        if canonical not in {e["canonical_name"] for e in persons}:
            continue
        for chapter_id, sentences in chapters.items():
            # Sliding window over sentences
            for i in range(len(sentences)):
                window = sentences[i : i + window_size]
                window_text = " ".join(window)

                # Find which entities appear in this window
                present: set[str] = set()
                for name, canon in name_to_canonical.items():
                    if name in window_text.lower():
                        present.add(canon)

                # Record all pairs in this window
                present_list = sorted(present)
                for idx_a in range(len(present_list)):
                    for idx_b in range(idx_a + 1, len(present_list)):
                        a, b = present_list[idx_a], present_list[idx_b]
                        key = (a, b)
                        if key not in cooc:
                            cooc[key] = {"count": 0, "chapters": set(), "contexts": []}
                        cooc[key]["count"] += 1
                        cooc[key]["chapters"].add(chapter_id)
                        if len(cooc[key]["contexts"]) < 3:
                            cooc[key]["contexts"].append(window[0])

    # Build output: filter by threshold, sort by count desc
    relationships = []
    for (a, b), data in cooc.items():
        if data["count"] >= threshold:
            relationships.append({
                "entity_a": a,
                "entity_b": b,
                "cooccurrence_count": data["count"],
                "chapters": sorted(data["chapters"]),
                "sample_contexts": data["contexts"],
                "relationship_type": None,
                "direction": None,
                "evolution": None,
                "key_moments": [],
            })

    relationships.sort(key=lambda r: r["cooccurrence_count"], reverse=True)

    pairs_above = len(relationships)
    stats = {
        "total_pairs_checked": total_pairs_checked,
        "pairs_above_threshold": pairs_above,
        "classified": 0,
        "window_size": window_size,
        "threshold": threshold,
    }

    return relationships, stats
```

**Step 4: Run --test to verify it passes**

```bash
python scripts/relationship_extraction.py --test
```
Expected: all 4 expected pairs found with `✓`, stats printed.

Also test with custom parameters:
```bash
python scripts/relationship_extraction.py --test --window 3 --threshold 2
```
Expected: more pairs found (lower threshold), same validation passes.

**Step 5: Commit**

```bash
git add scripts/relationship_extraction.py
git commit -m "feat(stu-229): cooccurrence graph — sliding window algorithm"
```

---

## Task 4: Add LLM classification (--classify)

**Files:**
- Modify: `scripts/relationship_extraction.py`
- Modify: `pyproject.toml`

**Step 1: Add `anthropic` to pyproject.toml**

In `pyproject.toml`, add to `dependencies`:
```toml
"anthropic>=0.40",
```

**Step 2: Write a failing classify integration test**

Add to `run_test_mode()`, after the existing validation block:

```python
    if "--classify" in sys.argv:
        print("\n=== CLASSIFY MODE ===")
        classified = classify_relationships(relationships)
        classified_count = sum(1 for r in classified if r.get("relationship_type"))
        print(f"Classified {classified_count}/{len(classified)} relationships")
        for r in classified[:5]:
            print(f"  {r['entity_a']} ↔ {r['entity_b']}: {r['relationship_type']} ({r['direction']})")
            if r.get("evolution"):
                print(f"    Evolution: {r['evolution']}")
        # Update stats
        stats["classified"] = classified_count
        relationships = classified
```

And add a stub function:
```python
def classify_relationships(relationships: list[dict]) -> list[dict]:
    raise NotImplementedError
```

**Step 3: Run to verify it fails**

```bash
python scripts/relationship_extraction.py --test --classify
```
Expected: `NotImplementedError`

**Step 4: Implement `classify_relationships`**

Replace the stub with:

```python
def classify_relationships(relationships: list[dict]) -> list[dict]:
    """Classify relationships using Haiku LLM. Fails gracefully per pair."""
    import anthropic

    client = anthropic.Anthropic()
    result = []

    for rel in relationships:
        contexts_text = "\n".join(
            f"{i+1}. \"{ctx}\"" for i, ctx in enumerate(rel["sample_contexts"][:3])
        )
        prompt = f"""Voici des extraits d'un roman où deux personnages apparaissent ensemble.
Personnage A : {rel['entity_a']}
Personnage B : {rel['entity_b']}
Cooccurrences : {rel['cooccurrence_count']}

Extraits :
{contexts_text}

Classifie leur relation. Réponds en JSON uniquement, sans markdown :
{{
  "relationship_type": "famille|mentor/protégé|amoureux|antagoniste|allié|employeur/employé|ami|connaissance|autre",
  "direction": "symétrique|A→B|B→A",
  "evolution": "en une phrase, comment la relation évolue",
  "key_moments": ["chXX: description courte"]
}}"""

        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            classification = json.loads(response.content[0].text)
            rel = {**rel, **classification}
        except Exception as e:
            # Fail gracefully — keep null fields
            print(f"  [WARN] classification failed for {rel['entity_a']}↔{rel['entity_b']}: {e}", file=sys.stderr)

        result.append(rel)

    return result
```

**Step 5: Run to verify**

```bash
python scripts/relationship_extraction.py --test --classify
```
Expected: classification output for top pairs. Requires `ANTHROPIC_API_KEY` in environment.

If no API key available, test graceful failure:
```bash
ANTHROPIC_API_KEY=invalid python scripts/relationship_extraction.py --test --classify 2>&1 | grep -E "(WARN|Classified)"
```
Expected: WARN messages, `Classified 0/N relationships` — script does not crash.

**Step 6: Commit**

```bash
git add scripts/relationship_extraction.py pyproject.toml
git commit -m "feat(stu-229): LLM classification with --classify flag (Haiku)"
```

---

## Task 5: Implement Studio mode (stdin → stdout)

**Files:**
- Modify: `scripts/relationship_extraction.py`

**Step 1: Write a failing test for Studio input parsing**

Add to `tests/test_types.py`:

```python
import json, subprocess, sys

def test_studio_mode_missing_entities():
    """Studio mode with empty previous_outputs returns error JSON, exit 1."""
    payload = json.dumps({"previous_outputs": {}, "additional_context": ""})
    result = subprocess.run(
        [sys.executable, "scripts/relationship_extraction.py"],
        input=payload,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    out = json.loads(result.stdout)
    assert "error" in out
```

**Step 2: Run to verify it fails**

```bash
pytest tests/test_types.py::test_studio_mode_missing_entities -v
```
Expected: FAIL (exit code 0, error message about Studio mode not implemented)

**Step 3: Implement Studio mode in `main()`**

Replace the Studio mode stub in `main()`:

```python
    payload = json.load(sys.stdin)

    prev_outputs = payload.get("previous_outputs", {})
    resolution_output = prev_outputs.get("entity-resolution", {})
    entities = resolution_output.get("entities", [])

    if not entities:
        json.dump({"error": "missing entity-resolution output"}, sys.stdout)
        sys.exit(1)

    # Parse classify flag from additional_context
    import yaml
    additional = {}
    raw_context = payload.get("additional_context", "")
    if raw_context:
        try:
            additional = yaml.safe_load(raw_context) or {}
        except Exception:
            pass
    do_classify = additional.get("classify", False)

    # Load mentions_by_entity from per-type files
    mentions_by_entity = _load_mentions_from_files()

    relationships, stats = build_cooccurrence_graph(
        entities, mentions_by_entity, window_size, threshold
    )

    if do_classify:
        relationships = classify_relationships(relationships)
        stats["classified"] = sum(1 for r in relationships if r.get("relationship_type"))

    json.dump({"relationships": relationships, "stats": stats}, sys.stdout, ensure_ascii=False)
```

Add the file loader helper (reads from current working directory, where Studio runs):

```python
def _load_mentions_from_files() -> dict[str, dict[str, list[str]]]:
    """
    Load mentions_by_chapter from persons_full.json.
    Returns {canonical_name: {chapter_id: [sentences]}}.
    Note: canonical_name matching is done via entity aliases in build_cooccurrence_graph.
    """
    import os
    mentions: dict[str, dict[str, list[str]]] = {}

    type_files = {
        "PERSON": "persons_full.json",
        "PLACE": "places_full.json",
        "ORG": "orgs_full.json",
    }

    for entity_type, filename in type_files.items():
        if not os.path.exists(filename):
            continue
        with open(filename) as f:
            data = json.load(f)
        key = list(data.keys())[0]  # e.g. "persons_full"
        for entity_id, entry in data[key].items():
            # Use first raw_mention as key (will be matched via aliases in graph builder)
            raw = entry.get("raw_mentions", [])
            name = raw[0] if raw else entity_id
            mentions[name] = entry.get("mentions_by_chapter", {})

    return mentions
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_types.py -v
```
Expected: all tests PASS

**Step 5: Commit**

```bash
git add scripts/relationship_extraction.py tests/test_types.py
git commit -m "feat(stu-229): Studio stdin/stdout mode with entity file loading"
```

---

## Task 6: Create contract + update pipeline YAML

**Files:**
- Create: `.studio/contracts/relationship-extraction.contract.yaml`
- Modify: `.studio/pipelines/wiki-pipeline.pipeline.yaml`

**Step 1: Create the contract**

```yaml
name: relationship-extraction
version: 1
schema:
  required_fields:
    - relationships
    - stats
```

**Step 2: Insert the stage in the pipeline**

In `.studio/pipelines/wiki-pipeline.pipeline.yaml`, insert after `entity-resolution` and before `wiki-generation`:

```yaml
  - name: relationship-extraction
    kind: analysis
    executor: script
    runtime: python
    script: scripts/relationship_extraction.py
    contract: relationship-extraction
    context:
      include:
        - input
        - previous_stage_output
```

**Step 3: Verify YAML is valid**

```bash
python -c "import yaml; yaml.safe_load(open('.studio/pipelines/wiki-pipeline.pipeline.yaml'))" && echo "Valid YAML"
```
Expected: `Valid YAML`

**Step 4: Commit**

```bash
git add .studio/contracts/relationship-extraction.contract.yaml .studio/pipelines/wiki-pipeline.pipeline.yaml
git commit -m "feat(stu-229): add relationship-extraction stage to pipeline"
```

---

## Task 7: Update writer agent to consume relationships

**Files:**
- Modify: `.studio/agents/writer.agent.yaml`

**Step 1: Update the pipeline context for wiki-generation**

In `.studio/pipelines/wiki-pipeline.pipeline.yaml`, update the `wiki-generation` context includes:

```yaml
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

The `previous_stage_output` will now be `relationship-extraction` output. The writer needs to know to also read `entity-resolution` output. Update context to include both:

```yaml
    context:
      include:
        - input
        - previous_outputs.entity-resolution
        - previous_stage_output
```

**Step 2: Add relationship section instructions to writer agent system prompt**

In `.studio/agents/writer.agent.yaml`, add to the system prompt after the existing `## Wiki page structure` section:

```yaml
  ## Relationships data

  You may receive a `previous_stage_output` containing relationship data:
  {"relationships": [{entity_a, entity_b, cooccurrence_count, relationship_type, direction, evolution, key_moments}]}

  For each PERSON wiki page:
  - If relationships exist for this entity (where entity_a or entity_b matches canonical_name):
    * Add a "## Relations" section listing related characters
    * Format: "**Pedro Vidal** (mentor/protégé, Vidal → Martín) — Commence comme mentor bienveillant, devient rival"
  - Only include relationships with relationship_type != null
  - Skip if no relationship data is available (graceful degradation)
```

**Step 3: Verify YAML is valid**

```bash
python -c "import yaml; yaml.safe_load(open('.studio/agents/writer.agent.yaml'))" && echo "Valid YAML"
```
Expected: `Valid YAML`

**Step 4: Commit**

```bash
git add .studio/pipelines/wiki-pipeline.pipeline.yaml .studio/agents/writer.agent.yaml
git commit -m "feat(stu-229): wire relationships into wiki-generation writer agent"
```

---

## Task 8: Final validation & PR

**Step 1: Run all tests**

```bash
pytest tests/ -v
```
Expected: all PASS

**Step 2: Run --test mode end-to-end**

```bash
python scripts/relationship_extraction.py --test
```
Expected: 4 expected pairs found with `✓`

**Step 3: Type check**

```bash
mypy wiki_creator/
```
Expected: no errors

**Step 4: Push branch and open PR**

```bash
git push -u origin feat/stu-229-relationship-extraction
gh pr create \
  --title "feat(stu-229): relationship-extraction stage — cooccurrence graph + LLM classification" \
  --body "$(cat <<'EOF'
## Summary
- New stage `relationship-extraction` inserted between entity-resolution and wiki-generation
- Sliding window co-occurrence graph (default window=5, threshold=5, both configurable)
- Optional LLM classification via `--classify` flag (Haiku, graceful failure)
- Writer agent updated to generate `## Relations` section on PERSON pages
- Coref (STU-230) explicitly out of scope

## Test plan
- [ ] `python scripts/relationship_extraction.py --test` — all 4 expected pairs found
- [ ] `python scripts/relationship_extraction.py --test --window 3 --threshold 2` — more pairs, still valid
- [ ] `python scripts/relationship_extraction.py --test --classify` — relationship_type non-null for top pairs
- [ ] `pytest tests/ -v` — all tests pass
- [ ] `mypy wiki_creator/` — no type errors

Closes STU-229
EOF
)" \
  --base main
```
