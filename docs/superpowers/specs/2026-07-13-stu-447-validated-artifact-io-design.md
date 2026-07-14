# STU-447 — Wire `types.py` into serialization: validated artifact write/read

- Linear: [STU-447](https://linear.app/studioag/issue/STU-447)
- Milestone: M2 — Package & Schémas
- Blocks: STU-455 (real artifact propagation, remove `load_*.py` stages)

## Problem

`wiki_creator/types.py` (`ExtractedEntity`, `ResolvedEntity`, `EntityRegistry`…) is a **dead schema**: no meaningful import in `scripts/`. Stages read and write raw dicts with defensive `.get(..., default)` calls. Drift is already visible:

- `merge_entities.py` tolerates **three generations** of upstream shapes (alias-resolution / resolve-clusters / entity-resolution-\*).
- The French importance label `secondaire` is re-mapped to English `secondary` by each reader (`_IMPORTANCE_NORMALIZE` in `wiki_preparation.py`).

A schema drift today fails **silently** — a reader falls back to a default and the pipeline produces subtly wrong output.

## Goal

- Reconcile `types.py` with the real artifact shapes (registry stays owned by `registry.py`, the M1 model).
- Add `save_artifact(path, obj, schema)` / `load_artifact(path, schema)` — validation at both frontiers.
- A schema drift breaks **loudly** (raises), not silently.
- Remove the multi-shape compat paths once validation is in place.

Scope: the **main pipeline** artifacts only (extraction → resolution → classify → preparation → generation → export). Off-path scripts (`lora_*`, `eval_coref`, `test_*`) are untouched.

## Mechanism — codec in `wiki_creator/studio_io.py`

`studio_io.py` already centralizes the stdin/stdout artifact boilerplate; the codec lives there.

```python
class ArtifactSchemaError(ValueError): ...

def to_dict(obj) -> JSON            # recursive dataclass -> JSON-ready dict, preserves None
def from_dict(schema, data)         # recursive construct + STRICT validate, raises ArtifactSchemaError
def save_artifact(path, obj, schema)
def load_artifact(path, schema)
```

**Strict validation** — `from_dict` raises `ArtifactSchemaError` (message names the JSON path + field) on:

1. a required field missing,
2. an **unknown key** present (this is what makes drift loud),
3. a leaf value whose type does not match the declared annotation.

Optional fields are those with a default or `X | None` annotation. `Literal[...]` leaves are validated against their allowed values.

**`schema` container forms** — three shapes cover all 10 artifacts:

- a dataclass type → validates a JSON object,
- `list[T]` → validates a JSON array of `T`,
- `dict[str, T]` → validates a JSON object whose values are `T`.

`save_artifact` runs `from_dict(schema, to_dict(obj))` as a roundtrip self-check before writing, so a producer cannot emit an off-schema artifact either.

## Schemas — reconcile `wiki_creator/types.py`

Replace the drifted dataclasses with ones matching real shapes. Field lists below come from the producer/consumer audit (see `docs/flow-audit.md` §data-flow).

| Artifact | `schema` | Producer | Item fields |
|---|---|---|---|
| `{persons,places,orgs,events}_full.json` | `dict[str, EntityFull]` | `entity_extraction.py` | `type`, `raw_mentions`, `first_seen`, `mention_count`, `mentions_by_chapter`, `mention_spans_by_chapter` |
| `splits.json` | `Splits` | `split_clusters.py` | `singles_resolved`, per-type cluster lists, `stats`, optional `pov_detection` |
| `entities_classified.json` | `ClassifiedBundle` | `entity_classification.py` | `entities: list[ClassifiedEntity]`, `relationships`, `stats`, `narrator` |
| `relationships.json` / `relationships_classified.json` | `RelationshipBundle` | `save_relationships.py` / `classify_relationships.py` | base co-occurrence fields; `relationship_type`/`direction`/`evolution`/`key_moments` Optional |
| `chapter_summaries.json` | `dict[str, ChapterSummary]` | `chapter_summary.py` | `chapter_id`, `chapter_title`, `summary_bullets`, `summary_method`, `quality_flags`, `temporal_context`, `flashback_anchor`, enumerated `pov_*` |
| `wiki_pages.json` | `list[WikiPage]` | `generate_wiki_pages.py` | `title`, `importance`, `entity_type`, `books`, `infobox_fields`, `content`, optional `_failed`, `_insufficient_data` |
| `events.json` | `EventBundle` | `build_event_layer.py` | `events: list[Event]` (`chapter`, `description`, `participants`, `places`, `outcome`, `salience`, `source_bullets`, `event_id`) |
| `registry.json` | **unchanged** — `registry.py` `to_dict`/`from_dict` | `write_registry.py` | (M1 model, out of codec scope) |

The wrapper key of the `*_full` files (`persons_full`, `places_full`, …) is unwrapped/wrapped by the caller (as `write_registry.py` already does); the codec validates the inner `dict[str, EntityFull]`.

Delete the dead `EntityRegistry` / `EntityRegistryEntry` / `ExtractedEntity` / `ResolvedEntity` dataclasses that no longer match reality.

## Behavior changes (require `make golden-update` + diff review in this PR)

1. **Importance canonicalized to English at the producer.** `entity_classification.py` writes `principal | secondary | figurant | ignored` directly (`ClassifiedEntity.importance` is a `Literal` of those). Delete `_IMPORTANCE_NORMALIZE` and its call site in `wiki_preparation.py`. One canonical form, no per-reader remap.
2. **Drop `merge_entities.py` gen-2 / gen-3 compat.** Keep only the current alias-resolution input shape; validated load replaces the shape-sniffing. Update/remove the compat tests that exercised the older shapes.

## Plan (4 phases)

1. **Reconcile `types.py`** — define the dataclasses above; delete the dead ones.
2. **Codec** — `to_dict` / `from_dict` / `save_artifact` / `load_artifact` + `ArtifactSchemaError` in `studio_io.py`, with unit tests (roundtrip, each raise condition, all three container forms).
3. **Wire producers + consumers** — one artifact at a time: producer switches to `save_artifact`, every consumer switches to `load_artifact`, and that artifact's defensive `.get(..., default)` reads are deleted.
4. **Remove compat + canonicalize** — `merge_entities` shape-sniffing and `_IMPORTANCE_NORMALIZE`; `make golden-update`, review the golden diff.

## Testing

- Unit tests for the codec (phase 2): roundtrip fidelity, each of the three raise conditions, list / dict / dataclass container forms.
- Per-artifact: existing stage tests must pass unchanged through phase 3 (additive plumbing, no behavior change).
- Phase 4: `tests/test_e2e_golden.py` goldens regenerated via `make golden-update`; the golden diff is reviewed in the same PR (importance labels flip `secondaire`→`secondary` at the classification stage output; merged-entity output loses the legacy-shape branches).
- `pytest -q` and `mypy wiki_creator/` green before ship.

## Non-goals

- No new runtime dependency (stdlib dataclasses only).
- Registry serialization is not reworked (already validated by `registry.py`).
- Off-pipeline scripts (`lora_*`, `eval_coref`, `test_*`) are out of scope.
