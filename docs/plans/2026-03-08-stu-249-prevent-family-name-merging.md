# STU-249: Prevent Distinct Characters with Shared Surname from Merging

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add pre-filter rules and post-processing to `entity_clustering.py` that block two kinds of wrong merges: (1) gender-title conflicts like "Mme Vidal" + "M. Vidal", and (2) transitive merges through bare surnames like Cristina Sagnier + Sagnier + Manuel Sagnier.

**Architecture:** Two independent fixes. Rule 1 (gender titles) is a pre-filter applied in `should_cluster()` before any similarity check. Rule 2 (distinct first names) is a post-processing step applied after Union-Find builds raw clusters, splitting clusters where full-name entities have incompatible first names. Bare-surname entities that acted as bridges go into an ambiguous sub-cluster with a logged warning.

**Tech Stack:** Pure Python, no new dependencies. `scripts/entity_clustering.py` + `tests/test_entity_clustering.py`.

---

## Diagnosis (read before implementing)

Run this to understand the current bug:

```bash
python3 -c "
from scripts.entity_clustering import should_cluster, tokenize_name
pairs = [
    ('Cristina Sagnier', 'Manuel Sagnier'),
    ('Cristina Sagnier', 'Sagnier'),
    ('Manuel Sagnier', 'Sagnier'),
    ('Mme Vidal', 'M. Vidal'),
    ('Mme Vidal', 'Pedro Vidal'),
]
for a, b in pairs:
    print(f'{a!r} vs {b!r}: {should_cluster(a, b)}')"
```

Expected output shows:
- `Cristina Sagnier` vs `Manuel Sagnier`: **False** (they don't directly match — good)
- `Cristina Sagnier` vs `Sagnier`: **True** — bare surname bridges them
- `Mme Vidal` vs `M. Vidal`: **True** — both strip to `["vidal"]`, title info lost
- `Mme Vidal` vs `Pedro Vidal`: **True** — `["vidal"] ⊂ ["pedro", "vidal"]`

Two bugs, two fixes.

---

## Worktree Setup

```bash
git worktree add .worktrees/stu-249-prevent-surname-merging -b arianedguay/stu-249-empecher-la-fusion-de-personnages-distincts-partageant-un
cd .worktrees/stu-249-prevent-surname-merging
```

---

## Task 1: Rule 1 — Gender Title Pre-filter

**Files:**
- Modify: `scripts/entity_clustering.py`
- Test: `tests/test_entity_clustering.py`

### Step 1: Write the failing tests

Add to `tests/test_entity_clustering.py`:

```python
# Import the new helpers (will fail until implemented)
from scripts.entity_clustering import (
    extract_leading_titles,
    has_conflicting_gender_title,
)


# --- extract_leading_titles ---

def test_extract_leading_titles_mme():
    assert "mme" in extract_leading_titles("Mme Vidal")

def test_extract_leading_titles_monsieur():
    assert "monsieur" in extract_leading_titles("Monsieur Vidal")

def test_extract_leading_titles_no_title():
    assert extract_leading_titles("Pedro Vidal") == frozenset()

def test_extract_leading_titles_stops_at_first_non_title():
    # "Vidal" is not a title prefix — only "M." should be extracted
    assert extract_leading_titles("M. Vidal") == frozenset({"m."})


# --- has_conflicting_gender_title ---

def test_gender_conflict_mme_vs_m():
    assert has_conflicting_gender_title("Mme Vidal", "M. Vidal") is True

def test_gender_conflict_madame_vs_monsieur():
    assert has_conflicting_gender_title("Madame Dupont", "Monsieur Dupont") is True

def test_gender_conflict_senora_vs_senor():
    assert has_conflicting_gender_title("Señora Ramos", "Señor Ramos") is True

def test_gender_conflict_reversed():
    assert has_conflicting_gender_title("M. Vidal", "Mme Vidal") is True

def test_no_gender_conflict_same_title():
    assert has_conflicting_gender_title("Mme Vidal", "Mme Dupont") is False

def test_no_gender_conflict_no_title():
    assert has_conflicting_gender_title("Pedro Vidal", "Vidal") is False

def test_no_gender_conflict_mme_vs_no_title():
    # "Mme" vs no title — can't determine gender → no block
    assert has_conflicting_gender_title("Mme Vidal", "Pedro Vidal") is False


# --- should_cluster with Rule 1 ---

def test_should_cluster_blocks_mme_vs_m():
    assert should_cluster("Mme Vidal", "M. Vidal") is False

def test_should_cluster_blocks_madame_vs_monsieur():
    assert should_cluster("Madame Vidal", "Monsieur Vidal") is False

def test_should_cluster_allows_mme_variants():
    # Two Mme — potentially same person, allow clustering
    assert should_cluster("Mme Vidal", "Mme de Vidal") is True
```

### Step 2: Run to confirm they fail

```bash
pytest tests/test_entity_clustering.py -k "gender_conflict or extract_leading" -v
```

Expected: `ImportError` or `FAILED` — `extract_leading_titles` and `has_conflicting_gender_title` don't exist yet.

### Step 3: Implement the helpers

In `scripts/entity_clustering.py`, after the `TITLE_PREFIXES` set, add:

```python
# Gender-discriminating title sets (subset of TITLE_PREFIXES)
MASCULINE_TITLES = frozenset({"m.", "mr.", "monsieur", "señor", "don"})
FEMININE_TITLES = frozenset({"mme", "mme.", "madame", "señora", "doña"})


def extract_leading_titles(name: str) -> frozenset[str]:
    """Return the set of title prefixes at the START of a name (stops at first non-title)."""
    tokens = name.lower().strip().split()
    result = set()
    for t in tokens:
        if t in TITLE_PREFIXES:
            result.add(t)
        else:
            break
    return frozenset(result)


def has_conflicting_gender_title(name1: str, name2: str) -> bool:
    """Rule 1: block merge if one name has a feminine title and the other a masculine title."""
    t1 = extract_leading_titles(name1)
    t2 = extract_leading_titles(name2)
    masc1, fem1 = bool(t1 & MASCULINE_TITLES), bool(t1 & FEMININE_TITLES)
    masc2, fem2 = bool(t2 & MASCULINE_TITLES), bool(t2 & FEMININE_TITLES)
    return (masc1 and fem2) or (fem1 and masc2)
```

Then modify `should_cluster()`:

```python
def should_cluster(name1: str, name2: str) -> bool:
    """Combined matching with pre-filter rules for obvious wrong merges."""
    # Rule 1: conflicting gender titles → definitely different people
    if has_conflicting_gender_title(name1, name2):
        return False
    return should_cluster_tokens(name1, name2) or should_cluster_jw(name1, name2)
```

### Step 4: Run the tests

```bash
pytest tests/test_entity_clustering.py -k "gender_conflict or extract_leading or blocks_mme or blocks_madame or allows_mme" -v
```

Expected: all pass.

### Step 5: Run full test suite to check for regressions

```bash
pytest tests/test_entity_clustering.py -v
```

Expected: all existing tests still pass.

### Step 6: Commit

```bash
git add scripts/entity_clustering.py tests/test_entity_clustering.py
git commit -m "feat(stu-249): Rule 1 — block merge on conflicting gender titles (Mme vs M.)"
```

---

## Task 2: Rule 2 — Post-processing Split on Distinct First Names

This task fixes the transitive bridge problem: `Cristina Sagnier ← Sagnier → Manuel Sagnier` all ending up in one cluster.

**Files:**
- Modify: `scripts/entity_clustering.py`
- Test: `tests/test_entity_clustering.py`

### Step 1: Write the failing tests

Add to `tests/test_entity_clustering.py`:

```python
from scripts.entity_clustering import (
    extract_surname_and_firstname,
)


# --- extract_surname_and_firstname ---

def test_extract_surname_and_firstname_full_name():
    surname, firsts = extract_surname_and_firstname("Cristina Sagnier")
    assert surname == "sagnier"
    assert firsts == ["cristina"]

def test_extract_surname_and_firstname_no_first():
    surname, firsts = extract_surname_and_firstname("Sagnier")
    assert surname == "sagnier"
    assert firsts == []

def test_extract_surname_and_firstname_with_title():
    # Title stripped before extraction
    surname, firsts = extract_surname_and_firstname("M. Sagnier")
    assert surname == "sagnier"
    assert firsts == []

def test_extract_surname_and_firstname_three_tokens():
    surname, firsts = extract_surname_and_firstname("A. C. Vidal")
    assert surname == "vidal"
    assert firsts == ["a.", "c."]


# --- build_clusters AC tests ---

def test_build_clusters_sagnier_family_separated():
    """AC1: Cristina Sagnier and Manuel Sagnier must be in SEPARATE clusters."""
    entities = {
        "e_cs": {"type": "PERSON", "raw_mentions": ["Cristina Sagnier"], "first_seen": "ch12"},
        "e_ms": {"type": "PERSON", "raw_mentions": ["Manuel Sagnier"], "first_seen": "ch05"},
        "e_s":  {"type": "PERSON", "raw_mentions": ["Sagnier"], "first_seen": "ch04"},
        "e_mlle": {"type": "PERSON", "raw_mentions": ["Mlle Cristina"], "first_seen": "ch13"},
    }
    clusters, unclustered = build_clusters(entities)

    def cluster_of(eid):
        for c in clusters:
            if eid in c["entity_ids"]:
                return c["cluster_id"]
        return None  # unclustered

    cs_cluster = cluster_of("e_cs")
    ms_cluster = cluster_of("e_ms")

    assert cs_cluster is not None, "Cristina Sagnier should be in a cluster"
    assert ms_cluster is not None, "Manuel Sagnier should be in a cluster"
    assert cs_cluster != ms_cluster, (
        f"Cristina Sagnier and Manuel Sagnier must be in different clusters, "
        f"but both are in {cs_cluster}"
    )


def test_build_clusters_mme_vidal_separated_from_pedro_and_m():
    """AC2: Mme Vidal must not be in the same cluster as M. Vidal or Pedro Vidal."""
    entities = {
        "e_mme":   {"type": "PERSON", "raw_mentions": ["Mme Vidal"], "first_seen": "ch10"},
        "e_m":     {"type": "PERSON", "raw_mentions": ["M. Vidal"], "first_seen": "ch01"},
        "e_pedro": {"type": "PERSON", "raw_mentions": ["Pedro Vidal"], "first_seen": "ch01"},
        "e_vidal": {"type": "PERSON", "raw_mentions": ["Vidal"], "first_seen": "ch01"},
        "e_don":   {"type": "PERSON", "raw_mentions": ["Don Pedro"], "first_seen": "ch03"},
    }
    clusters, unclustered = build_clusters(entities)

    all_items = list(clusters) + [
        {"cluster_id": f"unc_{eid}", "entity_ids": [eid]}
        for eid in unclustered
    ]

    def cluster_of(eid):
        for c in all_items:
            if eid in c["entity_ids"]:
                return c["cluster_id"]
        return None

    mme_cluster = cluster_of("e_mme")
    m_cluster = cluster_of("e_m")
    pedro_cluster = cluster_of("e_pedro")

    assert mme_cluster != m_cluster, "Mme Vidal must not be with M. Vidal"
    assert mme_cluster != pedro_cluster, "Mme Vidal must not be with Pedro Vidal"


def test_build_clusters_pedro_vidal_aliases_stay_together():
    """AC3: Pedro Vidal, Don Pedro, Vidal, M. Vidal stay in one cluster (legitimate aliases)."""
    entities = {
        "e_pedro": {"type": "PERSON", "raw_mentions": ["Pedro Vidal"], "first_seen": "ch01"},
        "e_don":   {"type": "PERSON", "raw_mentions": ["Don Pedro"], "first_seen": "ch03"},
        "e_vidal": {"type": "PERSON", "raw_mentions": ["Vidal"], "first_seen": "ch01"},
        "e_m":     {"type": "PERSON", "raw_mentions": ["M. Vidal"], "first_seen": "ch02"},
    }
    clusters, unclustered = build_clusters(entities)
    assert len(clusters) == 1, f"Expected 1 cluster, got {len(clusters)}: {[c['entity_ids'] for c in clusters]}"
    assert set(clusters[0]["entity_ids"]) == {"e_pedro", "e_don", "e_vidal", "e_m"}
```

### Step 2: Run to confirm they fail

```bash
pytest tests/test_entity_clustering.py -k "sagnier_family or mme_vidal_separated or pedro_vidal_aliases" -v
```

Expected: `FAILED` — currently Cristina and Manuel end up in the same cluster via "Sagnier".

### Step 3: Add the `extract_surname_and_firstname` helper

In `scripts/entity_clustering.py`, after `is_single_given_name`:

```python
def extract_surname_and_firstname(name: str) -> tuple[str, list[str]]:
    """
    Extract (surname, first_names) from a name after title stripping.
    Convention: last token = surname, all preceding tokens = first names.
    Returns normalized (lowercase, accent-stripped) tokens.
    """
    tokens = tokenize_name(name)
    if not tokens:
        return "", []
    normalized = [normalize_for_comparison(t) for t in tokens]
    if len(normalized) == 1:
        return normalized[0], []
    return normalized[-1], normalized[:-1]
```

### Step 4: Add the `split_conflicting_first_names` post-processing function

After `build_clusters`, add a new function:

```python
def split_conflicting_first_names(
    clusters: list[dict],
    unclustered: dict,
    entities: dict,
) -> tuple[list[dict], dict]:
    """
    Rule 2 post-processing: split clusters where multiple full-name entities
    share a surname but have incompatible first names.

    A 'full-name entity' is one whose sole raw mention has ≥2 tokens after title stripping
    (i.e., has both a first name and a surname).

    Strategy:
    - For each multi-entity cluster, group full-name entities by (surname, first_name_set).
    - If there are 2+ distinct first-name groups for the same surname → split.
    - Bare-surname entities (no first name) go into the most populated first-name group.
      If ambiguous (tie), log a warning and leave them in the largest group.
    - New sub-clusters get new cluster_ids (e.g., cluster_001a, cluster_001b).
    """
    new_clusters = []
    cluster_counter = [0]  # mutable ref for nested func

    def next_cluster_id():
        cluster_counter[0] += 1
        return f"cluster_{cluster_counter[0]:03d}"

    for cluster in clusters:
        if cluster["entity_count"] < 2:
            new_clusters.append(cluster)
            continue

        # Group full-name members by (surname → set of first_name_sets)
        # key: surname (str), value: list of (frozenset_of_firstnames, eid)
        by_surname: dict[str, list[tuple[frozenset, str]]] = {}
        bare_surname_eids: list[str] = []  # entities with no first name

        for eid in cluster["entity_ids"]:
            mention = entities[eid]["raw_mentions"][0] if entities[eid].get("raw_mentions") else eid
            surname, firsts = extract_surname_and_firstname(mention)
            if not surname:
                bare_surname_eids.append(eid)
                continue
            if not firsts:
                bare_surname_eids.append(eid)
                continue
            by_surname.setdefault(surname, []).append((frozenset(firsts), eid))

        # Check for conflict: same surname, 2+ distinct first-name groups
        split_happened = False
        for surname, entries in by_surname.items():
            distinct_groups: dict[frozenset, list[str]] = {}
            for firsts_set, eid in entries:
                distinct_groups.setdefault(firsts_set, []).append(eid)

            if len(distinct_groups) < 2:
                continue  # no conflict for this surname

            split_happened = True
            sorted_groups = sorted(distinct_groups.items(), key=lambda x: -len(x[1]))

            # Assign bare-surname entities to the largest first-name group
            if bare_surname_eids:
                if len(sorted_groups) >= 2 and len(sorted_groups[0][1]) == len(sorted_groups[1][1]):
                    import sys
                    print(
                        f"Warning: ambiguous bare-surname cluster for '{surname}' "
                        f"— cannot assign to first-name group, logging for LLM resolution",
                        file=sys.stderr,
                    )
                # Assign to largest group regardless
                sorted_groups[0][1].extend(bare_surname_eids)

            for firsts_set, eids in sorted_groups:
                sub_cluster = _make_cluster(next_cluster_id(), eids, entities)
                new_clusters.append(sub_cluster)

            break  # only handle one surname conflict per cluster for simplicity

        if not split_happened:
            new_clusters.append(cluster)

    return new_clusters, unclustered


def _make_cluster(cluster_id: str, eids: list[str], entities: dict) -> dict:
    """Build a cluster dict from a list of entity IDs."""
    all_mentions = []
    first_seen_chapters = []
    total_mentions = 0
    entity_type = entities[eids[0]].get("type", "OTHER") if eids else "OTHER"

    for eid in eids:
        entity = entities[eid]
        all_mentions.extend(entity.get("raw_mentions", []))
        fs = entity.get("first_seen", "")
        if fs:
            first_seen_chapters.append(fs)
        total_mentions += entity.get("mention_count", len(entity.get("raw_mentions", [])))

    def canonical_score(mention):
        tokens = tokenize_name(mention)
        return (len(tokens), len(" ".join(tokens)))

    canonical = max(all_mentions, key=canonical_score) if all_mentions else eids[0]

    return {
        "cluster_id": cluster_id,
        "type": entity_type,
        "canonical_candidate": canonical,
        "all_mentions": sorted(set(all_mentions), key=len, reverse=True),
        "entity_ids": eids,
        "first_seen": min(first_seen_chapters) if first_seen_chapters else "",
        "entity_count": len(eids),
        "total_mentions": total_mentions,
    }
```

### Step 5: Wire `split_conflicting_first_names` into `build_clusters`

In `build_clusters`, after collecting `clusters_list` and `unclustered` (just before `return`), add:

```python
    # Rule 2 post-processing: split clusters with conflicting first names
    clusters_list, unclustered = split_conflicting_first_names(clusters_list, unclustered, entities)

    clusters_list.sort(key=lambda c: c["total_mentions"], reverse=True)
    return clusters_list, unclustered
```

Remove the existing `clusters_list.sort(...)` line that was there before (it's now inside the new return).

### Step 6: Run the new tests

```bash
pytest tests/test_entity_clustering.py -k "sagnier_family or mme_vidal_separated or pedro_vidal_aliases or extract_surname" -v
```

Expected: all pass.

### Step 7: Run full test suite

```bash
pytest tests/test_entity_clustering.py -v
```

Expected: all tests pass. If `test_build_clusters_martin_family` fails (it expects all 5 entities in one cluster), investigate: "David" and "Martín" should NOT be split by Rule 2 because "David" has no surname (single token = bare given name, not bare surname). The `extract_surname_and_firstname` function for "David" → tokens = ["david"] → surname = "david", firsts = []. It goes into `bare_surname_eids`. No conflict. Should be fine.

### Step 8: Run standalone test to visually verify

```bash
python scripts/entity_clustering.py --test 2>&1 | head -40
```

No `Cristina` and `Manuel` should appear in the same cluster.

### Step 9: Commit

```bash
git add scripts/entity_clustering.py tests/test_entity_clustering.py
git commit -m "feat(stu-249): Rule 2 — split clusters with distinct first names sharing surname"
```

---

## Task 3: Rule 3 — JW Score Adjustment for Surname-Dominant Matches

This handles the edge case where Jaro-Winkler gives a high score purely because of a shared long surname, even when first names differ significantly.

**Files:**
- Modify: `scripts/entity_clustering.py`
- Test: `tests/test_entity_clustering.py`

### Step 1: Write the failing tests

Add to `tests/test_entity_clustering.py`:

```python
# --- should_cluster_jw with Rule 3 ---

def test_cluster_jw_same_surname_different_firstname_blocked():
    # "Cristina Sagnier" vs "Manuel Sagnier": JW might be high due to shared "sagnier"
    # but first names differ → should NOT cluster via JW either
    assert should_cluster_jw("Cristina Sagnier", "Manuel Sagnier") is False

def test_cluster_jw_same_full_name_variant_allowed():
    # Legitimate variant: accent difference → should still cluster
    assert should_cluster_jw("David Martín", "David Martin") is True

def test_cluster_jw_different_surname_not_blocked_by_rule3():
    # Rule 3 only applies to shared-surname cases; different surnames use normal JW
    assert should_cluster_jw("Barcelona", "Barcelone") is True
```

### Step 2: Run to confirm they fail (or pass — check)

```bash
pytest tests/test_entity_clustering.py -k "jw_same_surname or jw_same_full_name_variant or jw_different_surname_not_blocked" -v
```

Note: "Cristina Sagnier" vs "Manuel Sagnier" may already fail JW (different string lengths / characters). Run the test and check. If it already passes (JW < 0.92), this task is a no-op for that pair. If there are other real-world cases where JW incorrectly merges, the test will reveal them.

### Step 3: Implement Rule 3 in `should_cluster_jw` (only if tests fail)

If the first test above fails (JW merges them), modify `should_cluster_jw`:

```python
def should_cluster_jw(name1: str, name2: str) -> bool:
    """Jaro-Winkler on normalized full names. Rule 3: penalize surname-dominant matches."""
    t1 = tokenize_name(name1)
    t2 = tokenize_name(name2)
    if is_single_given_name(t1) and is_single_given_name(t2):
        return False
    n1 = normalize_for_comparison(" ".join(t1))
    n2 = normalize_for_comparison(" ".join(t2))
    if not n1 or not n2:
        return False
    if abs(len(n1) - len(n2)) > 3:
        return False

    score = jaro_winkler(n1, n2)
    if score < JW_THRESHOLD:
        return False

    # Rule 3: if both have first names and the first names differ significantly,
    # the high JW score is surname-driven → reject
    surname1, firsts1 = extract_surname_and_firstname(name1)
    surname2, firsts2 = extract_surname_and_firstname(name2)
    if firsts1 and firsts2 and surname1 == surname2:
        # Same surname, different first names → surname is driving the JW score
        first_score = jaro_winkler(
            normalize_for_comparison(" ".join(firsts1)),
            normalize_for_comparison(" ".join(firsts2)),
        )
        if first_score < 0.85:
            return False

    return True
```

### Step 4: Run tests

```bash
pytest tests/test_entity_clustering.py -v
```

Expected: all pass.

### Step 5: Commit

```bash
git add scripts/entity_clustering.py tests/test_entity_clustering.py
git commit -m "feat(stu-249): Rule 3 — penalize JW matches driven by shared surname with different first name"
```

---

## Task 4: Add to TEST_ENTITIES and Validate `--test` Output

Update `TEST_ENTITIES` in `entity_clustering.py` to include the Sagnier/Vidal scenarios from the issue.

**Files:**
- Modify: `scripts/entity_clustering.py`

### Step 1: Add entities to `TEST_ENTITIES`

```python
    # STU-249: Sagnier family — Cristina (romantic interest) and Manuel (her father)
    "entity_080": {"type": "PERSON", "raw_mentions": ["Cristina Sagnier"], "first_seen": "ch12"},
    "entity_081": {"type": "PERSON", "raw_mentions": ["Manuel Sagnier"], "first_seen": "ch05"},
    "entity_082": {"type": "PERSON", "raw_mentions": ["Sagnier"], "first_seen": "ch04"},
    "entity_083": {"type": "PERSON", "raw_mentions": ["Mlle Cristina"], "first_seen": "ch13"},
    # STU-249: Vidal family — Pedro (son) and Mme Vidal (Cristina after marriage, out of scope)
    "entity_090": {"type": "PERSON", "raw_mentions": ["Mme Vidal"], "first_seen": "ch25"},
    "entity_091": {"type": "PERSON", "raw_mentions": ["M. Vidal"], "first_seen": "ch07"},
```

### Step 2: Run `--test` and visually verify

```bash
python scripts/entity_clustering.py --test 2>&1
```

Check:
- `Cristina Sagnier` and `Manuel Sagnier` are in separate clusters
- `Mme Vidal` is NOT grouped with `M. Vidal`
- `Pedro Vidal`, `Monsieur Vidal`, `Vidal` are still in one cluster

### Step 3: Commit

```bash
git add scripts/entity_clustering.py
git commit -m "test(stu-249): add Sagnier and Vidal scenarios to TEST_ENTITIES"
```

---

## Task 5: Warning Logging for Ambiguous Bare-Surname Cases (AC 5)

The warning is already partially implemented in `split_conflicting_first_names` above. This task verifies it works and adds a dedicated test.

**Files:**
- Test: `tests/test_entity_clustering.py`

### Step 1: Write the test

```python
def test_build_clusters_logs_warning_for_ambiguous_bare_surname(capsys):
    """AC5: When a bare-surname entity bridges two distinct first-name clusters of equal size,
    a warning is printed to stderr."""
    entities = {
        "e_cs": {"type": "PERSON", "raw_mentions": ["Cristina Sagnier"], "first_seen": "ch12"},
        "e_ms": {"type": "PERSON", "raw_mentions": ["Manuel Sagnier"], "first_seen": "ch05"},
        "e_s":  {"type": "PERSON", "raw_mentions": ["Sagnier"], "first_seen": "ch04"},
    }
    # Only 3 entities: Cristina (1), Manuel (1), Sagnier (bare, 1) — equal size first-name groups
    clusters, unclustered = build_clusters(entities)
    captured = capsys.readouterr()
    assert "ambiguous" in captured.err.lower() or "warning" in captured.err.lower(), (
        f"Expected an ambiguity warning in stderr. Got: {captured.err!r}"
    )
```

### Step 2: Run the test

```bash
pytest tests/test_entity_clustering.py -k "logs_warning_for_ambiguous" -v
```

Expected: PASS (warning is already emitted in the post-processing function).

### Step 3: Run full suite

```bash
pytest tests/test_entity_clustering.py -v
```

Expected: all tests pass.

### Step 4: Commit

```bash
git add tests/test_entity_clustering.py
git commit -m "test(stu-249): verify warning logged for ambiguous bare-surname bridge"
```

---

## Final Verification

```bash
# Full test suite
pytest tests/test_entity_clustering.py -v

# Visual sanity on test data
python scripts/entity_clustering.py --test 2>&1

# Type check
mypy scripts/entity_clustering.py
```

---

## Notes for the Implementer

- **`_make_cluster` duplication**: The new `_make_cluster` helper duplicates some logic from `build_clusters`. If it becomes a maintenance issue, refactor `build_clusters` to use it too — but YAGNI until then.
- **Transitive bridge limitation**: The post-processing in Task 2 only splits one surname conflict per cluster. If a single cluster has `Dupont` AND `Martin` both conflicting, only the first is split. This is an acceptable limitation for now — the LLM resolution handles remaining ambiguities.
- **`Mme Vidal` + `Pedro Vidal` edge case**: Rule 1 (Task 1) blocks `Mme Vidal` + `M. Vidal`. Rule 2 post-processing (Task 2) cannot split `Mme Vidal` + `Pedro Vidal` because "Mme Vidal" after title-stripping has no first name. This case may still merge via token overlap. The issue marks marriage-name disambiguation as out of scope — document this limitation in the test as a comment.
- **`extract_surname_and_firstname` assumption**: Last token = surname. This holds for `Cristina Sagnier`, `Pedro Vidal`, `A. C. Vidal` but may fail for multi-word surnames like `van der Berg`. Acceptable for current scope.
