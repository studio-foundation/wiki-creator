"""Structural contract validators for Studio stages whose real schema is richer
than `required_fields` can express — nested object shapes, literal enums, and
type vocabularies that must be read at execution time rather than restated.

Each function is pure: it takes a stage's output payload and returns a list of
human-readable error strings (empty list == valid). The thin
`scripts/validate_*.py` wrappers run one against the real stage output and emit
`{valid, errors}` for the kernel, the same shape the `wiki-page` validators use.

The type vocabulary is never restated here — it is read from
`base.yaml#entity_types` via `entity_taxonomy` / `types`, so a taxonomy change
(FACTION shipped in STU-505) can never drift from a copy frozen in a comment."""
from __future__ import annotations

from typing import Any, get_args

from wiki_creator.types import IMPORTANCE

_IMPORTANCE_VALUES = frozenset(get_args(IMPORTANCE))


def _is_list(value: Any) -> bool:
    return isinstance(value, list)


def _is_dict(value: Any) -> bool:
    return isinstance(value, dict)


def _label(obj: dict, *keys: str) -> str:
    for key in keys:
        val = obj.get(key)
        if isinstance(val, str) and val:
            return val
    return "<unnamed>"


def classified_entity_errors(entities: Any, allowed_types: set[str]) -> list[str]:
    """Validate the `entities` list of `entity-classification` against the shape
    the contract used to describe only in prose. `allowed_types` is read from
    `base.yaml` at execution time, so a new entity type never needs an edit
    here."""
    if not _is_list(entities):
        return [f"entities must be a list, got {type(entities).__name__}"]

    errors: list[str] = []
    for i, entity in enumerate(entities):
        if not _is_dict(entity):
            errors.append(f"entity[{i}] must be an object, got {type(entity).__name__}")
            continue
        where = f"entity[{i}] '{_label(entity, 'canonical_name')}'"

        name = entity.get("canonical_name")
        if not isinstance(name, str) or not name:
            errors.append(f"{where}: canonical_name must be a non-empty string")

        etype = entity.get("type")
        if etype not in allowed_types:
            errors.append(
                f"{where}: type {etype!r} is not declared in base.yaml#entity_types "
                f"(allowed: {', '.join(sorted(allowed_types))})"
            )

        if not isinstance(entity.get("total_mentions"), int):
            errors.append(f"{where}: total_mentions must be an int")
        if not isinstance(entity.get("chapters_present"), int):
            errors.append(f"{where}: chapters_present must be an int")

        importance = entity.get("importance")
        if importance not in _IMPORTANCE_VALUES:
            errors.append(
                f"{where}: importance {importance!r} is not one of "
                f"{', '.join(sorted(_IMPORTANCE_VALUES))}"
            )

        if "aliases" in entity and not _is_list(entity["aliases"]):
            errors.append(f"{where}: aliases must be a list")
        if "source_ids" in entity and not _is_list(entity["source_ids"]):
            errors.append(f"{where}: source_ids must be a list")
        if "relevant" in entity and not isinstance(entity["relevant"], bool):
            errors.append(f"{where}: relevant must be a bool")

    return errors


def _graph_errors(graph: Any, name: str) -> list[str]:
    if not _is_dict(graph):
        return [f"{name} must be a node_link_data object, got {type(graph).__name__}"]

    errors: list[str] = []
    nodes = graph.get("nodes")
    if not _is_list(nodes):
        errors.append(f"{name}.nodes must be a list")
    else:
        for i, node in enumerate(nodes):
            if not _is_dict(node):
                errors.append(f"{name}.nodes[{i}] must be an object")
                continue
            where = f"{name}.nodes[{i}] '{_label(node, 'id')}'"
            if not isinstance(node.get("id"), str) or not node.get("id"):
                errors.append(f"{where}: id must be a non-empty string")
            if node.get("type") != "CHARACTER":
                errors.append(f"{where}: type must be 'CHARACTER', got {node.get('type')!r}")
            for key in ("importance",):
                if not isinstance(node.get(key), str):
                    errors.append(f"{where}: {key} must be a string")
            for key in ("aliases", "books"):
                if not _is_list(node.get(key)):
                    errors.append(f"{where}: {key} must be a list")

    links = graph.get("links")
    if not _is_list(links):
        errors.append(f"{name}.links must be a list")
    else:
        for i, link in enumerate(links):
            if not _is_dict(link):
                errors.append(f"{name}.links[{i}] must be an object")
                continue
            where = f"{name}.links[{i}]"
            for key in ("source", "target"):
                if not isinstance(link.get(key), str) or not link.get(key):
                    errors.append(f"{where}: {key} must be a non-empty string")
            if link.get("edge_type") != "INTERACTION":
                errors.append(
                    f"{where}: edge_type must be 'INTERACTION', got {link.get('edge_type')!r}"
                )
            if not isinstance(link.get("cooccurrence_count"), int):
                errors.append(f"{where}: cooccurrence_count must be an int")
            if not _is_dict(link.get("chapter_weights")):
                errors.append(f"{where}: chapter_weights must be an object")
            if not _is_list(link.get("sample_contexts")):
                errors.append(f"{where}: sample_contexts must be a list")
            if not _is_list(link.get("books")):
                errors.append(f"{where}: books must be a list")
    return errors


def character_graph_errors(output: Any) -> list[str]:
    """Validate `build-character-graph`'s two node_link_data graphs (`graph` and
    `delta`) — node/link fields and the two literal enums (`type == CHARACTER`,
    `edge_type == INTERACTION`) the contract used to carry only as a comment."""
    if not _is_dict(output):
        return [f"output must be an object, got {type(output).__name__}"]
    errors: list[str] = []
    for name in ("graph", "delta"):
        errors.extend(_graph_errors(output.get(name), name))
    return errors


def batches_errors(output: Any) -> list[str]:
    """Validate `wiki-preparation`'s `batches`: a list of
    {batch_id: str, file: str, entity_count: int}."""
    if not _is_dict(output):
        return [f"output must be an object, got {type(output).__name__}"]
    batches = output.get("batches")
    if not _is_list(batches):
        return [f"batches must be a list, got {type(batches).__name__}"]

    errors: list[str] = []
    for i, batch in enumerate(batches):
        if not _is_dict(batch):
            errors.append(f"batches[{i}] must be an object")
            continue
        where = f"batches[{i}] '{_label(batch, 'batch_id')}'"
        if not isinstance(batch.get("batch_id"), str) or not batch.get("batch_id"):
            errors.append(f"{where}: batch_id must be a non-empty string")
        if not isinstance(batch.get("file"), str) or not batch.get("file"):
            errors.append(f"{where}: file must be a non-empty string")
        if not isinstance(batch.get("entity_count"), int):
            errors.append(f"{where}: entity_count must be an int")
    return errors


def split_clusters_errors(output: Any) -> list[str]:
    """Validate `split-clusters`' shape: `singles_resolved` a list, `by_type` a
    dict of lists. The type *vocabulary* is deliberately not named — STU-505
    moved it into base.yaml and naming the keys here would re-freeze it — only
    the container shape is checked."""
    if not _is_dict(output):
        return [f"output must be an object, got {type(output).__name__}"]
    errors: list[str] = []
    if not _is_list(output.get("singles_resolved")):
        errors.append("singles_resolved must be a list")

    by_type = output.get("by_type")
    if not _is_dict(by_type):
        errors.append("by_type must be an object keyed by resolution type")
    else:
        for key, clusters in by_type.items():
            if not _is_list(clusters):
                errors.append(f"by_type[{key!r}] must be a list of clusters")
    return errors


def sections_complete_errors(output: Any) -> list[str]:
    """Enforce section-filter's load-bearing invariant on its output: sections
    are tagged, never removed, so every chapter must survive with its content
    intact (STU-489 mention offsets index into that content). Output-only, so it
    cannot compare counts against the input; it catches a chapter emitted with
    its id or content stripped."""
    if not _is_dict(output):
        return [f"output must be an object, got {type(output).__name__}"]
    chapters = output.get("chapters")
    if not _is_list(chapters):
        return [f"chapters must be a list, got {type(chapters).__name__}"]
    if not chapters:
        return ["chapters must not be empty — sections are tagged, never removed"]

    errors: list[str] = []
    for i, chapter in enumerate(chapters):
        if not _is_dict(chapter):
            errors.append(f"chapters[{i}] must be an object")
            continue
        where = f"chapters[{i}] '{_label(chapter, 'id', 'title')}'"
        if not isinstance(chapter.get("id"), str) or not chapter.get("id"):
            errors.append(f"{where}: id must be a non-empty string")
        content = chapter.get("content")
        if not isinstance(content, str) or not content:
            errors.append(f"{where}: content must be non-empty — a section may be tagged, never emptied")
    return errors
