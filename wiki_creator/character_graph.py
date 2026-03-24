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
