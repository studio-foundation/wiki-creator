"""STU-469 spike, part 1: does Louvain on the co-occurrence graph find real
narrative groups?

Read-only. Runs `networkx.community.louvain_communities` on a book's
`relationships.json` (weighted by `cooccurrence_count`), restricted to relevant
PERSON entities, and prints each community with its members ranked by weighted
degree. The verdict — do these clusters map to factions/families/plot lines a
reader would name — is a human read of the output, not a number this script
computes. Nothing here runs in the pipeline.

    python detect_communities.py <relationships.json> [--all-types] [--resolution R]
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict

import networkx as nx


def load_graph(path: str, all_types: bool) -> tuple[nx.Graph, dict[str, str]]:
    data = json.load(open(path))
    types = {e["canonical_name"]: e["type"] for e in data["entities"]}
    keep = {
        e["canonical_name"]
        for e in data["entities"]
        if e.get("relevant") and (all_types or e["type"] == "PERSON")
    }
    g = nx.Graph()
    for name in keep:
        g.add_node(name)
    for r in data["relationships"]:
        a, b = r["entity_a"], r["entity_b"]
        if a in keep and b in keep:
            g.add_edge(a, b, weight=r["cooccurrence_count"])
    return g, types


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("relationships")
    ap.add_argument("--all-types", action="store_true", help="include non-PERSON entities")
    ap.add_argument("--resolution", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    g, types = load_graph(args.relationships, args.all_types)
    print(f"nodes: {g.number_of_nodes()}  edges: {g.number_of_edges()}")
    if g.number_of_edges() == 0:
        print("empty graph")
        return

    communities = nx.community.louvain_communities(
        g, weight="weight", resolution=args.resolution, seed=args.seed
    )
    modularity = nx.community.modularity(g, communities, weight="weight")
    wdeg = dict(g.degree(weight="weight"))

    print(f"communities: {len(communities)}  modularity: {modularity:.3f}")
    for i, comm in enumerate(sorted(communities, key=len, reverse=True)):
        members = sorted(comm, key=lambda n: wdeg[n], reverse=True)
        print(f"\n── community {i} (n={len(comm)}) ──")
        for n in members:
            tag = "" if not args.all_types else f" [{types.get(n, '?')}]"
            print(f"    {wdeg[n]:>6.0f}  {n}{tag}")


if __name__ == "__main__":
    main()
