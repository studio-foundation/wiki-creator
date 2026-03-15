# STU-255 Mixed-Type Entity Clustering Design

**Issue:** `STU-255`

**Problem**

`scripts/entity_clustering.py` already performs deterministic pre-resolution clustering, but it blocks clustering when two candidate entities have different extracted types. That prevents legitimate merges such as `Arobynn` and `Arobynn Hamel` when upstream NER assigned conflicting labels like `PERSON` and `PLACE`.

**Approved Scope**

- Allow clustering across any mixed entity types when the existing name-matching rules say the mentions belong together.
- Resolve the final cluster type inside `entity-clustering`.
- Choose the resolved type by dominant evidence within the cluster.

**Design**

1. Matching boundary

Remove the same-type guard from `build_clusters`. Pairwise matching should continue to rely on the existing deterministic rules:

- token subset / overlap checks
- Jaro-Winkler similarity
- gender-title conflict blocking
- surname/first-name conflict splitting

This keeps name matching logic in one place and avoids introducing a second reconciliation stage later in the pipeline.

2. Type resolution

After union-find has formed a cluster, compute a dominant type for that cluster by summing evidence for each member type:

- prefer `mention_count` when present
- otherwise fall back to `len(raw_mentions)`

The resolved cluster `type` becomes the type with the highest total weight.

3. Tie handling

Type resolution must stay deterministic. If two or more types have the same evidence weight, break ties with a fixed precedence order:

`PERSON`, `PLACE`, `ORG`, `EVENT`, `OTHER`

This favors the more semantically specific types already used downstream and prevents unstable output ordering.

4. Pipeline contract

Keep the emitted cluster shape unchanged:

- `cluster_id`
- `type`
- `canonical_candidate`
- `all_mentions`
- `entity_ids`
- `first_seen`
- `entity_count`
- `total_mentions`

Downstream scripts (`verify_entity_types`, `split_clusters`, `resolve_clusters`) should not need structural changes.

**Alternatives Considered**

1. Add a second post-clustering merge pass across typed clusters.
Rejected because it duplicates matching logic and creates another boundary to maintain.

2. Handle type conflicts in `verify_entity_types`.
Rejected because that script is currently a targeted correction pass, not a general-purpose clustering stage.

**Testing**

Add focused tests for:

- mixed-type entities with matching names merging into one cluster
- dominant type chosen by weighted mention totals
- deterministic tie behavior

Retain existing tests for legitimate non-matches and same-name ambiguity protections.
