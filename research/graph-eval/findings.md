# STU-469 spike — findings

Three deliverables (community detection, faction/group pages, multi-hop), one
shared bottleneck.

## Part 1 — community detection: Louvain on the co-occurrence graph

Louvain (`networkx`, weighted by `cooccurrence_count`, relevant PERSON nodes) on
three real books:

| book   | nodes | edges | communities | modularity | real groups it surfaced |
| ------ | ----- | ----- | ----------- | ---------- | ----------------------- |
| eragon | 71    | 324   | 12          | **0.110**  | the Varden/dwarves at Farthen Dûr (Ajihad, Arya, Orik, Hrothgar, Nasuada); the Empire/villains (Galbatorix, Morzan, Forsworn, Shruikan); Angela + Solembum |
| tog    | 21    | 125   | 2           | **0.042**  | Celaena's circle vs the royal court (Dorian, King, Perrington, Kaltain) |
| narnia | 17    | 59    | 2           | **0.091**  | Pevensie-home axis vs Witch/battle axis (Aslan misfiled with the Witch) |

Louvain does find 2–3 genuine narrative factions per book. But modularity is
0.04–0.11 — weak to none — because the partition also dumps a third of the roster
into **one protagonist blob** and sheds the low-degree tail as singletons. On
eragon, community 0 is 33 nodes: Eragon, his companions (Saphira, Brom), *and* the
Ra'zac / Shade who hunt him, all in one cluster.

**The blob is a genuine hairball, not a mis-tuned resolution.** Raising the
resolution parameter on eragon only shreds it and destroys the partition:

| resolution | communities | modularity |
| ---------- | ----------- | ---------- |
| 1.0        | 12          | 0.110      |
| 1.5        | 14          | 0.053      |
| 2.0        | 18          | 0.013      |
| 3.0        | 21          | −0.026     |

The protagonist has weighted degree 11895, ~2× the next node (Saphira, 6236). He
co-occurs with allies and pursuers alike, so his ego-network cannot split — the
allies and the enemies chasing him land together because they share his scenes.

This is the STU-467 / STU-536 / STU-540 finding at graph level: raw co-occurrence
edges mean "co-present in a scene", not "related". The hairball is that defect made
visible in the community structure.

## Part 2 — faction/group page value

Two structural facts cap the value on the current graph:

1. **The relationship graph is PERSON-only** (`relationship_extraction.py:203,388,765`,
   STU-551). A community is a cluster of *people*, never a `FACTION`. But `FACTION`
   is a first-order entity type since STU-505, with its own pages. A "Varden's
   people" community page competes with the Varden's own entity page — same subject,
   two surfaces.
2. **Only 2–3 clean communities exist per book**; the rest is blob + singletons.
   That is not enough clean structure to justify a new page class.

Verdict: marginal on the current graph. A community summary adds value only where a
clean cluster exists *and* it is not already a `FACTION` entity — a narrow slice.
Revisit if typed edges sharpen the partition.

## Part 3 — multi-hop traversal: already shipped, starved

`character_graph.indirect_relationships` (STU-528) already does 2-hop typed-path
reasoning, and it is wired into production: `wiki_preparation.py:451` computes it
per entity, `generate_wiki_pages.py:364` feeds it to the page-writer prompt.

But it drops any path with an untyped hop (`character_graph.py:170` — "a path is its
edge types; one hole makes it unreadable"). Every cached book has **0 typed edges**
(the classifier stage did not populate `relationship_type`), so multi-hop currently
returns `[]` on every book. It is built, wired, and starved — not un-designed.

## The shared bottleneck

All three want the same input: **typed, sparsified relationship edges.**

- community detection — types would drop the crowd-scene edges that form the hairball;
- faction pages — need clean communities, which need the above;
- multi-hop — literally returns `[]` without types.

STU-540 decided to *buy* schema-guided typed discovery (0.86 detection / 0.82 type /
0.85 direction) but has not implemented it. On the raw co-occurrence graph the
pipeline ships today, STU-469 builds on sand.

## Recommendation

- **Do not** build community detection or faction pages on the raw co-occurrence
  graph. Modularity 0.01–0.11 means the partition is noise, and faction pages
  duplicate the `FACTION` entity type.
- **Block STU-469 on STU-540's implementation**, not just its decision. When typed
  edges land, re-run `detect_communities.py` on them. Reopen parts 1–2 only if
  modularity clears a real bar (≥0.3 as a starting line) and communities stop
  swallowing the protagonist.
- **Part 3 needs no new work** — multi-hop lights up for free the moment typed
  edges exist.
