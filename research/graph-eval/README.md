# Graph-reasoning spike (STU-469)

Does the pipeline gain from GraphRAG's reasoning layer — community detection,
faction/group pages, multi-hop traversal — on top of the entity+relationship
graph it already builds? Research only; nothing here runs in the pipeline.

Verdict up front: **all three deliverables bottleneck on the same missing input —
typed, sparsified relationship edges — which STU-540 decided to buy but has not
implemented.** On the raw co-occurrence graph the pipeline ships today, community
detection is noise and faction pages duplicate an existing entity type; multi-hop
is already built and merely starved. Full writeup: [findings.md](findings.md).

## Reproduce

`detect_communities.py` runs `networkx.community.louvain_communities` on a book's
`relationships.json` (weighted by `cooccurrence_count`, relevant PERSON nodes).
`library/` is gitignored, so pass an absolute path:

```
python detect_communities.py <abs>/processing_output/<slug>/relationships.json
python detect_communities.py <...>/01_eragon/relationships.json --resolution 2.0
```

The community-to-narrative-group judgement is a human read of the member lists,
not a number the script computes.
