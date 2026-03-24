# Character Graph Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat relationship list with a series-level NetworkX graph model that enables indirect relationship traversal in wiki generation.

**Architecture:** A new `CharacterGraph` class wraps `nx.DiGraph` and is built by a new `build-character-graph` stage in wiki-resolution. The graph is persisted as `character_graph.json` at the series level and loaded by wiki-preparation to enrich entity bundles with 2-hop indirect relationships.

**Tech Stack:** NetworkX ≥3.0 (`nx.DiGraph`), existing Studio stdin/stdout script convention, Python dataclasses, pytest.

**Spec:** `docs/superpowers/specs/2026-03-23-character-graph-model-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `wiki_creator/character_graph.py` | Create | `IndirectRelationship` dataclass + `CharacterGraph` wrapper |
| `wiki_creator/paths.py` | Modify | +2 path properties on `BookPaths` |
| `pyproject.toml` | Modify | Add `networkx>=3.0` dependency |
| `scripts/build_character_graph.py` | Create | Studio script: entities + relationships → graph |
| `scripts/wiki_preparation.py` | Modify | Load graph from disk, enrich bundle with indirect_relationships |
| `scripts/generate_wiki_pages.py` | Modify | Optional indirect relationships block in LLM prompt |
| `.studio/pipelines/wiki-resolution.pipeline.yaml` | Modify | +stage `build-character-graph` |
| `tests/fixtures/character_graph/minimal_graph.json` | Create | Shared test fixture: 4 nodes, 3 edges |
| `tests/fixtures/character_graph/book1_delta.json` | Create | Book 1 delta fixture |
| `tests/fixtures/character_graph/book2_delta.json` | Create | Book 2 delta fixture (new chapters on same edges) |
| `tests/test_character_graph.py` | Create | Unit tests for `CharacterGraph` |
| `tests/test_build_character_graph.py` | Create | Unit tests for `build_character_graph.py` |
| `tests/test_character_graph_pipeline.py` | Create | Integration tests (merge, wiki-prep) |

---

## Task 1: Add networkx dependency and create test fixtures

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/fixtures/character_graph/minimal_graph.json`
- Create: `tests/fixtures/character_graph/book1_delta.json`
- Create: `tests/fixtures/character_graph/book2_delta.json`

- [ ] **Step 1: Add networkx to pyproject.toml**

In `pyproject.toml`, add to the `dependencies` list:
```toml
"networkx>=3.0",
```

- [ ] **Step 2: Install and verify**

```bash
pip install -e ".[dev]"
python -c "import networkx; assert tuple(int(x) for x in networkx.__version__.split('.')[:2]) >= (3, 0); print('OK', networkx.__version__)"
```
Expected: `OK 3.x.x` printed.

- [ ] **Step 3: Create fixture directory**

```bash
mkdir -p tests/fixtures/character_graph
```

- [ ] **Step 4: Create minimal_graph.json fixture**

Create `tests/fixtures/character_graph/minimal_graph.json`:
```json
{
  "directed": true,
  "multigraph": false,
  "graph": {},
  "nodes": [
    {"id": "Celaena", "type": "CHARACTER", "importance": "major", "aliases": [], "books": ["01-tog"]},
    {"id": "Chaol",   "type": "CHARACTER", "importance": "major", "aliases": [], "books": ["01-tog"]},
    {"id": "Nehemia", "type": "CHARACTER", "importance": "major", "aliases": [], "books": ["01-tog"]},
    {"id": "Cain",    "type": "CHARACTER", "importance": "supporting", "aliases": [], "books": ["01-tog"]}
  ],
  "links": [
    {
      "source": "Celaena", "target": "Chaol",
      "edge_type": "INTERACTION", "relationship_type": "allié",
      "direction": "symétrique", "cooccurrence_count": 45,
      "chapter_weights": {"01-tog/C01.xhtml": 10, "01-tog/C05.xhtml": 35},
      "sample_contexts": ["Celaena et Chaol traversèrent la salle."],
      "evolution": "", "books": ["01-tog"]
    },
    {
      "source": "Celaena", "target": "Nehemia",
      "edge_type": "INTERACTION", "relationship_type": "amie",
      "direction": "symétrique", "cooccurrence_count": 30,
      "chapter_weights": {"01-tog/C03.xhtml": 30},
      "sample_contexts": ["Nehemia sourit à Celaena."],
      "evolution": "", "books": ["01-tog"]
    },
    {
      "source": "Celaena", "target": "Cain",
      "edge_type": "INTERACTION", "relationship_type": "antagoniste",
      "direction": "asymétrique", "cooccurrence_count": 20,
      "chapter_weights": {"01-tog/C10.xhtml": 20},
      "sample_contexts": ["Cain défia Celaena du regard."],
      "evolution": "", "books": ["01-tog"]
    }
  ]
}
```

This gives: Nehemia → Cain (via Celaena) as a testable 2-hop indirect relationship.

- [ ] **Step 5: Create book1_delta.json fixture**

Create `tests/fixtures/character_graph/book1_delta.json`:
```json
{
  "directed": true,
  "multigraph": false,
  "graph": {},
  "nodes": [
    {"id": "Celaena", "type": "CHARACTER", "importance": "major", "aliases": [], "books": ["01-tog"]},
    {"id": "Chaol",   "type": "CHARACTER", "importance": "major", "aliases": [], "books": ["01-tog"]}
  ],
  "links": [
    {
      "source": "Celaena", "target": "Chaol",
      "edge_type": "INTERACTION", "relationship_type": "allié",
      "direction": "symétrique", "cooccurrence_count": 20,
      "chapter_weights": {"01-tog/C01.xhtml": 20},
      "sample_contexts": ["Celaena et Chaol s'entraînaient."],
      "evolution": "", "books": ["01-tog"]
    }
  ]
}
```

- [ ] **Step 6: Create book2_delta.json fixture**

Create `tests/fixtures/character_graph/book2_delta.json`:
```json
{
  "directed": true,
  "multigraph": false,
  "graph": {},
  "nodes": [
    {"id": "Celaena", "type": "CHARACTER", "importance": "major", "aliases": [], "books": ["02-com"]},
    {"id": "Chaol",   "type": "CHARACTER", "importance": "major", "aliases": [], "books": ["02-com"]},
    {"id": "Aedion",  "type": "CHARACTER", "importance": "supporting", "aliases": [], "books": ["02-com"]}
  ],
  "links": [
    {
      "source": "Celaena", "target": "Chaol",
      "edge_type": "INTERACTION", "relationship_type": "allié",
      "direction": "symétrique", "cooccurrence_count": 25,
      "chapter_weights": {"02-com/C02.xhtml": 25},
      "sample_contexts": ["Celaena regarda Chaol avec méfiance."],
      "evolution": "", "books": ["02-com"]
    },
    {
      "source": "Celaena", "target": "Aedion",
      "edge_type": "INTERACTION", "relationship_type": "allié",
      "direction": "symétrique", "cooccurrence_count": 15,
      "chapter_weights": {"02-com/C04.xhtml": 15},
      "sample_contexts": ["Aedion se battit aux côtés de Celaena."],
      "evolution": "", "books": ["02-com"]
    }
  ]
}
```

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml tests/fixtures/character_graph/
git commit -m "chore: add networkx dependency and character graph test fixtures"
```

---

## Task 2: IndirectRelationship dataclass + CharacterGraph skeleton

**Files:**
- Create: `wiki_creator/character_graph.py`
- Create: `tests/test_character_graph.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_character_graph.py`:
```python
import json
import pytest
from pathlib import Path
from wiki_creator.character_graph import CharacterGraph, IndirectRelationship

FIXTURES = Path(__file__).parent / "fixtures" / "character_graph"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_from_json_raises_on_incompatible_format():
    with pytest.raises(ValueError, match="incompatible"):
        CharacterGraph.from_json({"nodes": [], "links": []})


def test_from_json_roundtrip_empty():
    g = CharacterGraph()
    data = g.to_json()
    g2 = CharacterGraph.from_json(data)
    assert g2.to_json() == data
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_character_graph.py -v
```
Expected: `ImportError` — module does not exist yet.

- [ ] **Step 3: Create wiki_creator/character_graph.py skeleton**

```python
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

import networkx as nx


@dataclass
class IndirectRelationship:
    entity_a: str
    entity_b: str
    via: list[str]
    path_edge_types: list[str]
    strength: float
    inferred: bool = True


class CharacterGraph:
    def __init__(self) -> None:
        self._g: nx.DiGraph = nx.DiGraph()

    # ── Serialization ──────────────────────────────────────────────────────

    def to_json(self) -> dict:
        """Return NetworkX node_link_data dict (directed=True)."""
        return nx.node_link_data(self._g, edges="links")

    @classmethod
    def from_json(cls, data: dict) -> "CharacterGraph":
        """Load from node_link_data dict. Raises ValueError on incompatible format."""
        if "directed" not in data:
            raise ValueError(
                f"character_graph.json format incompatible: missing 'directed' key "
                f"(got keys: {set(data.keys())})"
            )
        g = cls()
        g._g = nx.node_link_graph(data, edges="links")
        return g

    # ── Mutations ──────────────────────────────────────────────────────────

    def add_character(self, name: str, metadata: dict) -> None:
        """Add or update a CHARACTER node."""
        self._g.add_node(name, type="CHARACTER", **metadata)

    def add_interaction(self, a: str, b: str, edge_data: dict) -> None:
        """Add or update an INTERACTION edge between two characters."""
        self._g.add_edge(a, b, edge_type="INTERACTION", **edge_data)

    def merge_book(self, other: "CharacterGraph") -> None:
        """Accumulate another book's graph into this series graph."""
        # Merge nodes
        for node, attrs in other._g.nodes(data=True):
            if node in self._g:
                existing = self._g.nodes[node]
                # Extend books list
                existing_books = existing.get("books", [])
                new_books = attrs.get("books", [])
                merged_books = existing_books + [b for b in new_books if b not in existing_books]
                self._g.nodes[node]["books"] = merged_books
                # Merge aliases
                existing_aliases = set(existing.get("aliases", []))
                new_aliases = set(attrs.get("aliases", []))
                self._g.nodes[node]["aliases"] = list(existing_aliases | new_aliases)
            else:
                self._g.add_node(node, **attrs)

        # Merge edges
        for a, b, attrs in other._g.edges(data=True):
            if self._g.has_edge(a, b):
                e = self._g.edges[a, b]
                # Sum counts
                e["cooccurrence_count"] = e.get("cooccurrence_count", 0) + attrs.get("cooccurrence_count", 0)
                # Merge chapter_weights (sum same keys)
                cw = dict(e.get("chapter_weights", {}))
                for chapter, count in attrs.get("chapter_weights", {}).items():
                    cw[chapter] = cw.get(chapter, 0) + count
                e["chapter_weights"] = cw
                # Extend books
                existing_books = e.get("books", [])
                new_books = attrs.get("books", [])
                e["books"] = existing_books + [b for b in new_books if b not in existing_books]
                # Enrich sample_contexts (up to 3, truncate at 500 chars)
                existing_ctx = e.get("sample_contexts", [])
                for ctx in attrs.get("sample_contexts", []):
                    if len(existing_ctx) < 3:
                        existing_ctx.append(ctx[:500])
                e["sample_contexts"] = existing_ctx
            else:
                # Truncate new contexts
                new_attrs = dict(attrs)
                new_attrs["sample_contexts"] = [
                    c[:500] for c in new_attrs.get("sample_contexts", [])[:3]
                ]
                self._g.add_edge(a, b, **new_attrs)

    # ── Queries ────────────────────────────────────────────────────────────

    def direct_relationships(self, name: str) -> list[dict]:
        """Return all INTERACTION edges involving this character."""
        if name not in self._g:
            return []
        results = []
        for a, b, data in self._g.edges(data=True):
            if (a == name or b == name) and data.get("edge_type") == "INTERACTION":
                results.append({"entity_a": a, "entity_b": b, **data})
        return results

    def indirect_relationships(
        self, name: str, max_hops: int = 2
    ) -> list[IndirectRelationship]:
        """Return 2-hop (or up to max_hops) indirect relationships not already direct."""
        if name not in self._g:
            return []

        undirected = self._g.to_undirected()
        direct_neighbors = set(self._g.successors(name)) | set(self._g.predecessors(name))

        # Max cooccurrence across all edges for normalization
        all_counts = [
            d.get("cooccurrence_count", 0)
            for _, _, d in self._g.edges(data=True)
            if d.get("edge_type") == "INTERACTION"
        ]
        max_count = max(all_counts) if all_counts else 1
        if max_count == 0:
            max_count = 1

        results: list[IndirectRelationship] = []
        seen_targets: set[str] = set()

        for target in self._g.nodes:
            if target == name or target in direct_neighbors or target in seen_targets:
                continue
            if self._g.nodes[target].get("type") != "CHARACTER":
                continue

            # Find shortest simple path up to max_hops
            for path in nx.all_simple_paths(undirected, name, target, cutoff=max_hops):
                if len(path) < 3:
                    continue  # no intermediate node

                via = path[1:-1]
                edge_types: list[str] = []
                strength = 1.0

                for i in range(len(path) - 1):
                    a, b = path[i], path[i + 1]
                    if self._g.has_edge(a, b):
                        edge_data = dict(self._g.edges[a, b])
                    elif self._g.has_edge(b, a):
                        edge_data = dict(self._g.edges[b, a])
                    else:
                        edge_data = {}
                    edge_types.append(edge_data.get("relationship_type") or "co-occurrence")
                    count = edge_data.get("cooccurrence_count", 0)
                    strength *= count / max_count

                if strength < 0.1:
                    break  # no stronger path will be found for this target via this route

                results.append(
                    IndirectRelationship(
                        entity_a=name,
                        entity_b=target,
                        via=via,
                        path_edge_types=edge_types,
                        strength=round(strength, 4),
                        inferred=True,
                    )
                )
                seen_targets.add(target)
                break  # take first valid path per target

        return sorted(results, key=lambda r: r.strength, reverse=True)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_character_graph.py -v
```
Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add wiki_creator/character_graph.py tests/test_character_graph.py
git commit -m "feat(character-graph): add CharacterGraph skeleton + IndirectRelationship"
```

---

## Task 3: CharacterGraph — full unit tests

**Files:**
- Modify: `tests/test_character_graph.py`

- [ ] **Step 1: Add all unit tests**

Append to `tests/test_character_graph.py` (the imports from Task 2 — `json`, `pytest`, `Path`, `CharacterGraph`, `IndirectRelationship`, `_load_fixture`, `FIXTURES` — are already in the file):

```python
def test_add_and_retrieve_character():
    g = CharacterGraph()
    g.add_character("Celaena", {"importance": "major", "aliases": [], "books": ["01-tog"]})
    assert "Celaena" in g._g.nodes
    assert g._g.nodes["Celaena"]["importance"] == "major"


def test_add_interaction_stored_as_edge():
    g = CharacterGraph()
    g.add_character("Celaena", {"importance": "major", "aliases": [], "books": ["01-tog"]})
    g.add_character("Chaol", {"importance": "major", "aliases": [], "books": ["01-tog"]})
    g.add_interaction("Celaena", "Chaol", {
        "relationship_type": "allié", "direction": "symétrique",
        "cooccurrence_count": 45,
        "chapter_weights": {"01-tog/C01.xhtml": 10},
        "sample_contexts": ["ils marchèrent ensemble."],
        "evolution": "", "books": ["01-tog"],
    })
    assert g._g.has_edge("Celaena", "Chaol")
    assert g._g.edges["Celaena", "Chaol"]["cooccurrence_count"] == 45


def test_direct_relationships_returns_both_directions():
    g = CharacterGraph.from_json(_load_fixture("minimal_graph.json"))
    rels = g.direct_relationships("Celaena")
    names = {r["entity_b"] for r in rels} | {r["entity_a"] for r in rels}
    assert "Chaol" in names
    assert "Nehemia" in names
    assert "Cain" in names


def test_indirect_relationships_two_hop():
    g = CharacterGraph.from_json(_load_fixture("minimal_graph.json"))
    # Nehemia and Cain are not directly connected; both connect via Celaena
    indirect = g.indirect_relationships("Nehemia")
    targets = [r.entity_b for r in indirect]
    assert "Cain" in targets
    r = next(r for r in indirect if r.entity_b == "Cain")
    assert r.via == ["Celaena"]
    assert r.inferred is True


def test_indirect_relationships_excludes_direct_neighbors():
    g = CharacterGraph.from_json(_load_fixture("minimal_graph.json"))
    indirect = g.indirect_relationships("Celaena")
    # All nodes are direct neighbors of Celaena — no indirect results
    assert indirect == []


def test_indirect_relationships_strength_below_threshold_filtered():
    g = CharacterGraph()
    g.add_character("A", {"importance": "major", "aliases": [], "books": ["b"]})
    g.add_character("B", {"importance": "major", "aliases": [], "books": ["b"]})
    g.add_character("C", {"importance": "major", "aliases": [], "books": ["b"]})
    # Very low counts → strength will be near 0
    g.add_interaction("A", "B", {"relationship_type": "allié", "cooccurrence_count": 1,
                                  "chapter_weights": {}, "sample_contexts": [],
                                  "evolution": "", "books": ["b"]})
    g.add_interaction("B", "C", {"relationship_type": "allié", "cooccurrence_count": 1,
                                  "chapter_weights": {}, "sample_contexts": [],
                                  "evolution": "", "books": ["b"]})
    # max_count=1, strength = 1/1 * 1/1 = 1.0 — should NOT be filtered
    # (only filtered if < 0.1)
    indirect = g.indirect_relationships("A")
    assert len(indirect) == 1  # A→C via B, strength=1.0


def test_indirect_relationships_max_hops_respected():
    g = CharacterGraph()
    for name in ["A", "B", "C", "D"]:
        g.add_character(name, {"importance": "major", "aliases": [], "books": ["b"]})
    for a, b in [("A", "B"), ("B", "C"), ("C", "D")]:
        g.add_interaction(a, b, {"relationship_type": "allié", "cooccurrence_count": 50,
                                  "chapter_weights": {}, "sample_contexts": [],
                                  "evolution": "", "books": ["b"]})
    # A→D requires 3 hops; with max_hops=2 it should not appear
    indirect = g.indirect_relationships("A", max_hops=2)
    assert not any(r.entity_b == "D" for r in indirect)
    # With max_hops=3 it should appear
    indirect3 = g.indirect_relationships("A", max_hops=3)
    assert any(r.entity_b == "D" for r in indirect3)


def test_merge_book_accumulates_cooccurrence_counts():
    g1 = CharacterGraph.from_json(_load_fixture("book1_delta.json"))
    g2 = CharacterGraph.from_json(_load_fixture("book2_delta.json"))
    g1.merge_book(g2)
    assert g1._g.edges["Celaena", "Chaol"]["cooccurrence_count"] == 45  # 20 + 25


def test_merge_book_merges_chapter_weights():
    g1 = CharacterGraph.from_json(_load_fixture("book1_delta.json"))
    g2 = CharacterGraph.from_json(_load_fixture("book2_delta.json"))
    g1.merge_book(g2)
    cw = g1._g.edges["Celaena", "Chaol"]["chapter_weights"]
    assert "01-tog/C01.xhtml" in cw
    assert "02-com/C02.xhtml" in cw


def test_merge_book_adds_new_nodes():
    g1 = CharacterGraph.from_json(_load_fixture("book1_delta.json"))
    g2 = CharacterGraph.from_json(_load_fixture("book2_delta.json"))
    g1.merge_book(g2)
    assert "Aedion" in g1._g.nodes


def test_merge_book_extends_books_list():
    g1 = CharacterGraph.from_json(_load_fixture("book1_delta.json"))
    g2 = CharacterGraph.from_json(_load_fixture("book2_delta.json"))
    g1.merge_book(g2)
    books = g1._g.nodes["Celaena"]["books"]
    assert "01-tog" in books
    assert "02-com" in books


def test_serialization_roundtrip():
    g = CharacterGraph.from_json(_load_fixture("minimal_graph.json"))
    data = g.to_json()
    g2 = CharacterGraph.from_json(data)
    assert set(g2._g.nodes) == set(g._g.nodes)
    assert set(g2._g.edges) == set(g._g.edges)
```

- [ ] **Step 2: Run all tests**

```bash
pytest tests/test_character_graph.py -v
```
Expected: all tests PASS. If any fail, fix the implementation in `character_graph.py` before continuing.

- [ ] **Step 3: Run full suite to confirm no regressions**

```bash
pytest -q
```
Expected: 485+ passed, 0 failed.

- [ ] **Step 4: Commit**

```bash
git add tests/test_character_graph.py wiki_creator/character_graph.py
git commit -m "test(character-graph): full unit test suite for CharacterGraph"
```

---

## Task 4: paths.py — series_character_graph + book_graph_delta

**Files:**
- Modify: `wiki_creator/paths.py`
- Modify: `tests/test_character_graph.py` (add path tests)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_character_graph.py`:

```python
from wiki_creator.paths import book_paths_from_yaml
from pathlib import Path


def test_series_character_graph_path():
    # Use the real book yaml from the library
    yaml = "library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml"
    paths = book_paths_from_yaml(yaml)
    sgp = paths.series_character_graph
    # Should be: library/sarah_j_maas/throne-of-glass/character_graph.json
    assert sgp.name == "character_graph.json"
    assert "throne-of-glass" in str(sgp)
    assert "processing_output" not in str(sgp)


def test_book_graph_delta_path():
    yaml = "library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml"
    paths = book_paths_from_yaml(yaml)
    delta = paths.book_graph_delta
    assert delta.name == "character_graph_delta.json"
    assert "processing_output" in str(delta)
    assert "01-throne-of-glass" in str(delta)
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_character_graph.py::test_series_character_graph_path -v
```
Expected: `AttributeError: 'BookPaths' object has no attribute 'series_character_graph'`

- [ ] **Step 3: Add properties to BookPaths in paths.py**

In `wiki_creator/paths.py`, after the `BookPaths` dataclass definition, change it from a plain `@dataclass` to one with properties. Replace the dataclass block:

```python
@dataclass
class BookPaths:
    epub: Path
    processing: Path   # …/processing_output/<slug>/
    wiki_inputs: Path  # …/wiki_inputs/<slug>/
    output: Path       # …/output/<slug>/

    @property
    def series_character_graph(self) -> Path:
        """Series-level graph: library/<author>/<series>/character_graph.json"""
        return self.epub.parent.parent / "character_graph.json"

    @property
    def book_graph_delta(self) -> Path:
        """Per-book delta graph: processing_output/<slug>/character_graph_delta.json"""
        return self.processing / "character_graph_delta.json"
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_character_graph.py::test_series_character_graph_path tests/test_character_graph.py::test_book_graph_delta_path -v
```
Expected: PASS.

- [ ] **Step 5: Run full suite**

```bash
pytest -q
```
Expected: 487+ passed, 0 failed.

- [ ] **Step 6: Commit**

```bash
git add wiki_creator/paths.py tests/test_character_graph.py
git commit -m "feat(paths): add series_character_graph and book_graph_delta to BookPaths"
```

---

## Task 5: build_character_graph.py script

**Files:**
- Create: `scripts/build_character_graph.py`
- Create: `tests/test_build_character_graph.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_build_character_graph.py`:

```python
import json
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from wiki_creator.character_graph import CharacterGraph

# Minimal Studio payload
SAMPLE_ENTITIES = [
    {"canonical_name": "Celaena", "type": "PERSON", "importance": "major",
     "aliases": ["Laena"], "relevant": True},
    {"canonical_name": "Chaol", "type": "PERSON", "importance": "major",
     "aliases": [], "relevant": True},
    {"canonical_name": "Cain", "type": "PERSON", "importance": "supporting",
     "aliases": [], "relevant": True},
]

SAMPLE_RELATIONSHIPS = [
    {
        "entity_a": "Celaena", "entity_b": "Chaol",
        "cooccurrence_count": 45, "chapters": ["C01.xhtml", "C05.xhtml"],
        "chapter_weights": {"01-tog/C01.xhtml": 10, "01-tog/C05.xhtml": 35},
        "sample_contexts": ["Ils marchèrent."],
        "relationship_type": "allié", "direction": "symétrique",
        "evolution": "", "books": ["01-tog"],
    },
    {
        "entity_a": "Celaena", "entity_b": "Cain",
        "cooccurrence_count": 20, "chapters": ["C10.xhtml"],
        "chapter_weights": {"01-tog/C10.xhtml": 20},
        "sample_contexts": ["Cain défia Celaena."],
        "relationship_type": "antagoniste", "direction": "asymétrique",
        "evolution": "", "books": ["01-tog"],
    },
    {
        # Entity not in entity list — should be skipped with warning
        "entity_a": "Ghost", "entity_b": "Chaol",
        "cooccurrence_count": 5, "chapters": ["C01.xhtml"],
        "chapter_weights": {}, "sample_contexts": [],
        "relationship_type": None, "direction": None,
        "evolution": "", "books": ["01-tog"],
    },
]


def _run_script(entities, relationships, book_slug="01-tog", series_graph=None):
    """Run build_character_graph main() with given inputs, return (graph, delta)."""
    import importlib
    import scripts.build_character_graph as bsg

    payload = {
        "all_stage_outputs": {
            "entity-classification": {"entities": entities, "relationships": relationships}
        },
        "additional_context": f"book_slug: {book_slug}\n",
    }
    output = StringIO()
    with patch("sys.stdin", StringIO(json.dumps(payload))), \
         patch("sys.stdout", output):
        bsg.main(series_graph_data=series_graph)

    result = json.loads(output.getvalue())
    return result


def test_builds_character_nodes_from_entities():
    result = _run_script(SAMPLE_ENTITIES, SAMPLE_RELATIONSHIPS)
    graph = CharacterGraph.from_json(result["graph"])
    assert "Celaena" in graph._g.nodes
    assert "Chaol" in graph._g.nodes


def test_builds_interaction_edges():
    result = _run_script(SAMPLE_ENTITIES, SAMPLE_RELATIONSHIPS)
    graph = CharacterGraph.from_json(result["graph"])
    assert graph._g.has_edge("Celaena", "Chaol")
    assert graph._g.edges["Celaena", "Chaol"]["cooccurrence_count"] == 45


def test_skips_edge_with_unknown_entity():
    import io
    result = _run_script(SAMPLE_ENTITIES, SAMPLE_RELATIONSHIPS)
    graph = CharacterGraph.from_json(result["graph"])
    # "Ghost" is not in entities → edge Ghost↔Chaol should not appear
    assert not graph._g.has_edge("Ghost", "Chaol")


def test_chapter_weights_preserved():
    result = _run_script(SAMPLE_ENTITIES, SAMPLE_RELATIONSHIPS)
    graph = CharacterGraph.from_json(result["graph"])
    cw = graph._g.edges["Celaena", "Chaol"]["chapter_weights"]
    assert "01-tog/C01.xhtml" in cw


def test_delta_output_contains_only_current_book():
    result = _run_script(SAMPLE_ENTITIES, SAMPLE_RELATIONSHIPS)
    assert "delta" in result
    delta = CharacterGraph.from_json(result["delta"])
    assert "Celaena" in delta._g.nodes


def test_merges_into_existing_series_graph():
    # First build
    r1 = _run_script(SAMPLE_ENTITIES[:2], SAMPLE_RELATIONSHIPS[:1], book_slug="01-tog")
    # Second build merges into existing
    r2 = _run_script(SAMPLE_ENTITIES, SAMPLE_RELATIONSHIPS, book_slug="02-com",
                     series_graph=r1["graph"])
    graph = CharacterGraph.from_json(r2["graph"])
    # Celaena↔Chaol should have accumulated counts
    count = graph._g.edges["Celaena", "Chaol"]["cooccurrence_count"]
    assert count == 45 + 45  # both runs have 45
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_build_character_graph.py -v
```
Expected: `ModuleNotFoundError: No module named 'scripts.build_character_graph'`

- [ ] **Step 3: Create scripts/build_character_graph.py**

```python
"""build_character_graph.py — Studio script.

Reads from stdin: JSON payload with all_stage_outputs containing entity-classification output.
Writes to stdout: JSON with {"graph": <node_link_data>, "delta": <node_link_data>}

Also writes:
  - series_character_graph (atomic: write-to-temp + rename)
  - book_graph_delta
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

from wiki_creator.character_graph import CharacterGraph
from wiki_creator.paths import book_paths_from_yaml


def _build_book_graph(entities: list[dict], relationships: list[dict], book_slug: str) -> CharacterGraph:
    """Build a CharacterGraph from entity-classification output for one book."""
    g = CharacterGraph()

    known_names: set[str] = set()
    for ent in entities:
        if ent.get("type") != "PERSON":
            continue
        name = ent.get("canonical_name", "")
        if not name:
            continue
        g.add_character(name, {
            "importance": ent.get("importance", "minor"),
            "aliases": ent.get("aliases", []),
            "books": [book_slug],
        })
        known_names.add(name)

    for rel in relationships:
        a = rel.get("entity_a", "")
        b = rel.get("entity_b", "")
        count = rel.get("cooccurrence_count", 0)

        if a not in known_names or b not in known_names:
            print(
                f"build-character-graph: skipping edge {a!r}↔{b!r} — entity not in graph",
                file=sys.stderr,
            )
            continue
        if not count or count <= 0:
            print(
                f"build-character-graph: skipping edge {a!r}↔{b!r} — cooccurrence_count={count}",
                file=sys.stderr,
            )
            continue

        g.add_interaction(a, b, {
            "relationship_type": rel.get("relationship_type"),
            "direction": rel.get("direction"),
            "cooccurrence_count": count,
            "chapter_weights": rel.get("chapter_weights", {}),
            "sample_contexts": [c[:500] for c in rel.get("sample_contexts", [])[:3]],
            "evolution": rel.get("evolution", ""),
            "books": [book_slug],
        })

    return g


def main(series_graph_data: dict | None = None) -> None:
    payload = json.load(sys.stdin)
    all_outputs = payload.get("all_stage_outputs", {})
    classification = all_outputs.get("entity-classification", {})

    entities = classification.get("entities", [])
    relationships = classification.get("relationships", [])

    # Derive book slug from additional_context YAML
    ctx = yaml.safe_load(payload.get("additional_context", "")) or {}
    book_slug = ctx.get("book_slug", "unknown")

    # Build delta for this book
    delta = _build_book_graph(entities, relationships, book_slug)

    # Load existing series graph (if provided or from disk)
    if series_graph_data is not None:
        series_graph = CharacterGraph.from_json(series_graph_data)
    else:
        # Try loading from disk via paths
        try:
            yaml_path = ctx.get("yaml_path", "")
            if yaml_path:
                paths = book_paths_from_yaml(yaml_path)
                sgp = paths.series_character_graph
                if sgp.exists():
                    series_graph = CharacterGraph.from_json(json.loads(sgp.read_text()))
                    # Atomic write after merge
                    series_graph.merge_book(delta)
                    tmp = sgp.with_suffix(".json.tmp")
                    try:
                        tmp.write_text(json.dumps(series_graph.to_json(), ensure_ascii=False))
                        tmp.rename(sgp)
                    except Exception:
                        if tmp.exists():
                            tmp.unlink()
                        raise
                    # Write delta
                    paths.book_graph_delta.parent.mkdir(parents=True, exist_ok=True)
                    paths.book_graph_delta.write_text(
                        json.dumps(delta.to_json(), ensure_ascii=False)
                    )
                    json.dump({"graph": series_graph.to_json(), "delta": delta.to_json()}, sys.stdout, ensure_ascii=False)
                    return
                else:
                    series_graph = CharacterGraph()
            else:
                series_graph = CharacterGraph()
        except Exception as e:
            print(f"build-character-graph: could not load series graph — {e}", file=sys.stderr)
            series_graph = CharacterGraph()

    series_graph.merge_book(delta)
    json.dump(
        {"graph": series_graph.to_json(), "delta": delta.to_json()},
        sys.stdout,
        ensure_ascii=False,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_build_character_graph.py -v
```
Expected: all tests PASS.

- [ ] **Step 5: Run full suite**

```bash
pytest -q
```
Expected: 493+ passed, 0 failed.

- [ ] **Step 6: Commit**

```bash
git add scripts/build_character_graph.py tests/test_build_character_graph.py
git commit -m "feat(character-graph): add build_character_graph Studio script"
```

---

## Task 6: wiki_preparation.py — load graph, enrich bundle

**Files:**
- Modify: `scripts/wiki_preparation.py`
- Create: `tests/test_character_graph_pipeline.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_character_graph_pipeline.py`:

```python
import json
from dataclasses import asdict
from pathlib import Path
from wiki_creator.character_graph import CharacterGraph

FIXTURES = Path(__file__).parent / "fixtures" / "character_graph"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_indirect_relationships_enriched_in_bundle():
    """build_entity_bundle should add indirect_relationships when graph is provided."""
    from scripts.wiki_preparation import build_entity_bundle

    graph = CharacterGraph.from_json(_load_fixture("minimal_graph.json"))

    entity = {
        "canonical_name": "Nehemia",
        "type": "PERSON",
        "importance": "major",
        "aliases": [],
        "total_mentions": 30,
        "chapters_present": 5,
        "mentions_by_chapter": {},
    }
    relationships = []  # direct relationships from flat list (legacy)

    bundle = build_entity_bundle(
        entity=entity,
        relationships=relationships,
        persons={}, places={}, orgs={}, events={},
        entities_by_name={"Nehemia": entity},
        graph=graph,
    )

    assert "indirect_relationships" in bundle
    targets = [r["entity_b"] for r in bundle["indirect_relationships"]]
    assert "Cain" in targets


def test_indirect_relationships_absent_for_minor_character():
    """Minor characters should still get indirect_relationships computed (filtering happens downstream)."""
    from scripts.wiki_preparation import build_entity_bundle

    graph = CharacterGraph.from_json(_load_fixture("minimal_graph.json"))
    entity = {
        "canonical_name": "Cain",
        "type": "PERSON",
        "importance": "supporting",
        "aliases": [],
        "total_mentions": 10,
        "chapters_present": 2,
        "mentions_by_chapter": {},
    }
    bundle = build_entity_bundle(
        entity=entity,
        relationships=[],
        persons={}, places={}, orgs={}, events={},
        entities_by_name={"Cain": entity},
        graph=graph,
    )
    # indirect_relationships key should exist (may be empty for supporting)
    assert "indirect_relationships" in bundle


def test_bundle_graceful_when_no_graph():
    """build_entity_bundle should work without a graph (graph=None)."""
    from scripts.wiki_preparation import build_entity_bundle

    entity = {
        "canonical_name": "Nehemia",
        "type": "PERSON",
        "importance": "major",
        "aliases": [],
        "total_mentions": 10,
        "chapters_present": 3,
        "mentions_by_chapter": {},
    }
    bundle = build_entity_bundle(
        entity=entity,
        relationships=[],
        persons={}, places={}, orgs={}, events={},
        entities_by_name={"Nehemia": entity},
        graph=None,
    )
    assert bundle["indirect_relationships"] == []


def test_series_graph_merged_across_two_books():
    """merge_book correctly accumulates two books."""
    g1 = CharacterGraph.from_json(_load_fixture("book1_delta.json"))
    g2 = CharacterGraph.from_json(_load_fixture("book2_delta.json"))
    g1.merge_book(g2)
    # Celaena↔Chaol: 20 (book1) + 25 (book2) = 45
    assert g1._g.edges["Celaena", "Chaol"]["cooccurrence_count"] == 45
    # Aedion added from book2
    assert "Aedion" in g1._g.nodes
    # Both books listed
    assert "01-tog" in g1._g.nodes["Celaena"]["books"]
    assert "02-com" in g1._g.nodes["Celaena"]["books"]
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_character_graph_pipeline.py -v
```
Expected: `TypeError` — `build_entity_bundle` doesn't accept `graph` parameter yet.

- [ ] **Step 3: Modify build_entity_bundle in wiki_preparation.py**

Find the `build_entity_bundle` function signature (line ~309). Add `graph` parameter and `indirect_relationships` to the returned dict:

**Add `graph` parameter to signature:**
```python
def build_entity_bundle(
    entity: dict,
    relationships: list[dict],
    persons: dict,
    places: dict,
    orgs: dict,
    events: dict,
    entities_by_name: dict[str, dict],
    chapter_summaries: dict[str, dict] | None = None,
    chapter_summary_max: int = DEFAULT_CHAPTER_SUMMARY_MAX,
    chapter_id_to_title: dict[str, str] | None = None,
    graph: "CharacterGraph | None" = None,    # ← add this
) -> dict:
```

**Add import at top of wiki_preparation.py** (after existing imports):
```python
from dataclasses import asdict
from wiki_creator.character_graph import CharacterGraph
```

**In the return dict of build_entity_bundle**, add:
```python
"indirect_relationships": [
    asdict(r) for r in (
        graph.indirect_relationships(canonical_name, max_hops=2)
        if graph is not None else []
    )
],
```

Add it after the `"relationships"` key.

- [ ] **Step 4: Load graph in main() of wiki_preparation.py**

In `main()`, after loading `relationships` from disk (around line 435), add:

```python
# Load series character graph if available
from wiki_creator.character_graph import CharacterGraph as _CG
_series_graph_path = paths.series_character_graph
_series_graph: _CG | None = None
if _series_graph_path.exists():
    try:
        _series_graph = _CG.from_json(json.loads(_series_graph_path.read_text()))
        print(
            f"wiki-preparation: loaded series graph ({len(_series_graph._g.nodes)} nodes, "
            f"{len(_series_graph._g.edges)} edges)",
            file=sys.stderr,
        )
    except Exception as _e:
        print(f"wiki-preparation: could not load series graph — {_e}", file=sys.stderr)
```

Then pass `graph=_series_graph` to every call to `build_entity_bundle`.

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_character_graph_pipeline.py -v
```
Expected: all PASS.

- [ ] **Step 6: Run full suite**

```bash
pytest -q
```
Expected: 497+ passed, 0 failed.

- [ ] **Step 7: Commit**

```bash
git add scripts/wiki_preparation.py tests/test_character_graph_pipeline.py
git commit -m "feat(wiki-preparation): enrich bundles with indirect relationships from CharacterGraph"
```

---

## Task 7: generate_wiki_pages.py — indirect relationships in prompt

**Files:**
- Modify: `scripts/generate_wiki_pages.py`

This task has no new test file — the change is a prompt enhancement guarded by existing conditions. Verify manually via `make generate-pages-dry`.

- [ ] **Step 1: Write a test for the indirect block**

Add to `tests/test_character_graph_pipeline.py`:

```python
def test_indirect_block_injected_for_major_character():
    """_build_entity_prompt should include indirect relationship line for major characters."""
    import scripts.generate_wiki_pages as gwp

    entity_bundle = {
        "canonical_name": "Nehemia",
        "type": "PERSON",
        "importance": "major",
        "aliases": [],
        "total_mentions": 30,
        "chapters_present": 5,
        "relationships": [],
        "indirect_relationships": [
            {"entity_a": "Nehemia", "entity_b": "Cain", "via": ["Celaena"],
             "path_edge_types": ["amie", "antagoniste"], "strength": 0.67, "inferred": True},
            {"entity_a": "Nehemia", "entity_b": "Chaol", "via": ["Celaena"],
             "path_edge_types": ["amie", "allié"], "strength": 0.60, "inferred": True},
        ],
        "related_context": [],
        "context_by_chapter": {},
        "first_seen": None,
        "chapter_summary_context": [],
    }
    prompt = gwp._build_entity_prompt(entity_bundle, sections=["infobox", "biography", "relationships"])
    assert "inferred: true" in prompt
    assert "Cain" in prompt
```

Run: `pytest tests/test_character_graph_pipeline.py::test_indirect_block_injected_for_major_character -v`
Expected: FAIL (function doesn't accept indirect yet).

- [ ] **Step 3: Locate the relationships block in generate_wiki_pages.py**

Find the section around line 211 where `relationships_block` is built.

- [ ] **Step 4: Add indirect relationships block after the direct block**

After the existing `relationships_block = "\n".join(rel_lines) ...` line, add:

```python
# Indirect (inferred) relationships
indirect_rels = entity.get("indirect_relationships", [])
indirect_lines = []
for r in indirect_rels[:5]:  # cap at 5 to avoid prompt bloat
    other = r.get("entity_b", "")
    via = " → ".join(r.get("via", []))
    path = " → ".join(r.get("path_edge_types", []))
    strength = r.get("strength", 0)
    if other and strength >= 0.1:
        indirect_lines.append(
            f"  - related_entity: {other} | via: {via} | path: {path} | inferred: true"
        )
indirect_block = "\n".join(indirect_lines) if indirect_lines else ""
```

- [ ] **Step 5: Inject into prompt template**

Find where `{relationships_block if relationships_block else ...}` appears in the prompt string (around line 318). Add the indirect block beneath it:

```python
Indirect relationships (inferred from graph — do NOT treat as confirmed direct interactions):
{indirect_block if indirect_block else "  (none)"}
```

Only include this line when `entity.get("importance") == "major"` and `len(indirect_rels) >= 2`.

Concretely, wrap the injection in a condition:

```python
indirect_section = ""
if entity.get("importance") == "major" and len(indirect_rels) >= 2 and indirect_block:
    indirect_section = f"\nIndirect relationships (inferred — do NOT treat as confirmed direct interactions):\n{indirect_block}"
```

Then add `{indirect_section}` in the prompt after the relationships block.

- [ ] **Step 6: Run tests**

```bash
pytest tests/test_character_graph_pipeline.py::test_indirect_block_injected_for_major_character -v
```
Expected: PASS.

- [ ] **Step 7: Run full suite**

```bash
pytest -q
```
Expected: 498+ passed, 0 failed.

- [ ] **Step 8: Dry-run smoke test**

```bash
make generate-pages-dry
```
Expected: runs without error. Inspect stderr for any `indirect_relationships` log lines.

- [ ] **Step 9: Commit**

```bash
git add scripts/generate_wiki_pages.py tests/test_character_graph_pipeline.py
git commit -m "feat(generate-wiki-pages): add indirect relationships block to LLM prompt"
```

---

## Task 8: Add build-character-graph stage to wiki-resolution pipeline

**Files:**
- Modify: `.studio/pipelines/wiki-resolution.pipeline.yaml`

- [ ] **Step 1: Add the new stage**

In `.studio/pipelines/wiki-resolution.pipeline.yaml`, append after `entity-classification`:

```yaml
  - name: build-character-graph
    kind: extraction
    executor: script
    runtime: python
    script: scripts/build_character_graph.py
    contract: build-character-graph
    concurrency: 1
    context:
      include:
        - input
        - all_stage_outputs
```

`concurrency: 1` enforces sequential processing per series to prevent graph file corruption.

- [ ] **Step 2: Verify YAML is valid**

```bash
python -c "import yaml; yaml.safe_load(open('.studio/pipelines/wiki-resolution.pipeline.yaml'))"
```
Expected: no error.

- [ ] **Step 3: Run full suite**

```bash
pytest -q
```
Expected: 497+ passed, 0 failed.

- [ ] **Step 4: Commit**

```bash
git add .studio/pipelines/wiki-resolution.pipeline.yaml
git commit -m "feat(pipeline): add build-character-graph stage to wiki-resolution"
```

---

## Task 9: Final verification

- [ ] **Step 1: Full test suite**

```bash
pytest -q
```
Expected: 497+ passed, 0 failed.

- [ ] **Step 2: mypy**

```bash
mypy wiki_creator/character_graph.py wiki_creator/paths.py
```
Expected: no errors.

- [ ] **Step 3: Verify series_character_graph path doesn't exist in wrong location**

```bash
python -c "
from wiki_creator.paths import book_paths_from_yaml
p = book_paths_from_yaml('library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml')
print(p.series_character_graph)
print(p.book_graph_delta)
"
```
Expected output:
```
library/sarah_j_maas/throne-of-glass/character_graph.json
library/sarah_j_maas/throne-of-glass/processing_output/01-throne-of-glass/character_graph_delta.json
```
