"""Export fandom + pipeline data to Alpaca-format JSONL for LoRA fine-tuning."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from wiki_creator.wikitext_cleaner import clean_wikitext, normalize_infobox_fields

VALID_ENTITY_TYPES = {"PERSON", "PLACE", "ORG", "OTHER"}
VALID_IMPORTANCES = {"principal", "secondary", "figurant"}
MIN_CONTENT_LENGTH = 50


def infer_importance(content: str) -> str:
    """Infer entity importance from content length. >2000=principal, >500=secondary, else figurant."""
    length = len(content)
    if length > 2000:
        return "principal"
    if length > 500:
        return "secondary"
    return "figurant"


def validate_output(output: dict) -> bool:
    """Validate output dict: title non-empty, content non-empty, entity_type valid, importance valid, non-figurants need ## header."""
    title = output.get("title", "")
    content = output.get("content", "")
    entity_type = output.get("entity_type", "")
    importance = output.get("importance", "")

    if not title or not content:
        return False
    if entity_type not in VALID_ENTITY_TYPES:
        return False
    if importance not in VALID_IMPORTANCES:
        return False
    if len(content) < MIN_CONTENT_LENGTH:
        return False
    if importance != "figurant" and "## " not in content:
        return False
    return True


def build_fandom_instruction(title: str, entity_type: str, importance: str) -> str:
    """Build synthetic instruction prompt for fandom entry (simplified build_prompt)."""
    return (
        f"Generate a wiki page for the {entity_type.lower()} entity \"{title}\" "
        f"(importance: {importance}). Include an infobox and relevant sections "
        f"in Markdown format."
    )


def process_fandom_entry(entry: dict, known_entities: dict[str, dict]) -> dict | None:
    """Process a fandom JSONL entry: clean wikitext, normalize infobox, validate. Returns Alpaca dict or None."""
    title = entry.get("page_title", "")
    entity_type = entry.get("entity_type", "PERSON")
    raw_content = entry.get("content", "")
    raw_infobox = entry.get("infobox_fields", {})

    content = clean_wikitext(raw_content)
    infobox = normalize_infobox_fields(raw_infobox)

    # Use known entity metadata for importance if available
    known = known_entities.get(title, {})
    importance = known.get("importance") or infer_importance(content)

    output = {
        "title": title,
        "importance": importance,
        "entity_type": entity_type,
        "infobox_fields": infobox,
        "content": content,
    }

    if not validate_output(output):
        return None

    instruction = build_fandom_instruction(title, entity_type, importance)
    return {
        "instruction": instruction,
        "input": "",
        "output": json.dumps(output, ensure_ascii=False),
    }


def load_known_entities(batch_dir: Path) -> dict[str, dict]:
    """Load entity metadata from batch_*.json files for importance lookup."""
    result: dict[str, dict] = {}
    if not batch_dir or not batch_dir.exists():
        return result
    for batch_file in sorted(batch_dir.glob("batch_*.json")):
        with open(batch_file) as f:
            data = json.load(f)
        for entity in data.get("entities", []):
            name = entity.get("canonical_name", "")
            if name:
                result[name] = {
                    "type": entity.get("type", "PERSON"),
                    "importance": entity.get("importance", ""),
                }
    return result


def load_pipeline_outputs(wiki_pages_path: Path, batch_dir: Path) -> list[dict]:
    """Load validated pipeline outputs, reconstruct instruction via build_prompt from generate_wiki_pages.py."""
    if not wiki_pages_path or not wiki_pages_path.exists():
        return []

    from scripts.generate_wiki_pages import build_prompt
    from wiki_creator.page_templates import resolve_template

    with open(wiki_pages_path) as f:
        pages_data = json.load(f)

    known = load_known_entities(batch_dir) if batch_dir else {}

    results = []
    for page in pages_data if isinstance(pages_data, list) else pages_data.get("pages", []):
        title = page.get("title", "")
        content = page.get("content", "")
        entity_type = page.get("entity_type", "PERSON")
        importance = page.get("importance", "") or infer_importance(content)
        infobox = page.get("infobox_fields", {})

        output = {
            "title": title,
            "importance": importance,
            "entity_type": entity_type,
            "infobox_fields": infobox,
            "content": content,
        }

        if not validate_output(output):
            continue

        # Reconstruct entity dict for build_prompt
        entity = known.get(title, {})
        entity.setdefault("canonical_name", title)
        entity.setdefault("type", entity_type)
        entity.setdefault("importance", importance)

        sections = resolve_template(entity_type, importance).section_tokens() or ["infobox", "biography"]

        instruction = build_prompt(entity, "Unknown", sections)

        results.append({
            "instruction": instruction,
            "input": "",
            "output": json.dumps(output, ensure_ascii=False),
        })

    return results


def main_with_args(
    fandom_jsonl: Path | None,
    batch_dir: Path | None,
    wiki_pages: Path | None,
    gold_jsonl: Path | None,
    output_dir: Path,
) -> None:
    """Core logic, callable from tests."""
    output_dir.mkdir(parents=True, exist_ok=True)

    known_entities = load_known_entities(batch_dir) if batch_dir else {}

    train_records: list[dict] = []
    eval_records: list[dict] = []
    rejected_pages: list[str] = []
    by_type: dict[str, int] = {}
    by_importance: dict[str, int] = {}

    fandom_total = 0
    fandom_accepted = 0
    fandom_rejected = 0
    pipeline_accepted = 0
    gold_accepted = 0

    def _route(record: dict) -> None:
        out = json.loads(record["output"])
        imp = out["importance"]
        etype = out["entity_type"]
        title = out.get("title", "")
        by_type[etype] = by_type.get(etype, 0) + 1
        by_importance[imp] = by_importance.get(imp, 0) + 1
        # Only route to eval if the entity is known as principal from batch files
        known_imp = known_entities.get(title, {}).get("importance")
        if known_imp == "principal":
            eval_records.append(record)
        else:
            train_records.append(record)

    # Fandom
    if fandom_jsonl and fandom_jsonl.exists():
        with open(fandom_jsonl) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                fandom_total += 1
                entry = json.loads(line)
                record = process_fandom_entry(entry, known_entities)
                if record is None:
                    fandom_rejected += 1
                    rejected_pages.append(entry.get("page_title", "unknown"))
                else:
                    fandom_accepted += 1
                    _route(record)

    # Pipeline
    if wiki_pages:
        pipeline_records = load_pipeline_outputs(wiki_pages, batch_dir)
        pipeline_accepted = len(pipeline_records)
        for r in pipeline_records:
            _route(r)

    # Gold examples
    if gold_jsonl and gold_jsonl.exists():
        with open(gold_jsonl) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                # Validate the output field
                try:
                    out = json.loads(record["output"])
                    if validate_output(out):
                        gold_accepted += 1
                        _route(record)
                except (json.JSONDecodeError, KeyError):
                    pass

    # Write outputs
    with open(output_dir / "train.jsonl", "w") as f:
        for r in train_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    with open(output_dir / "eval.jsonl", "w") as f:
        for r in eval_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    report = {
        "fandom_total": fandom_total,
        "fandom_accepted": fandom_accepted,
        "fandom_rejected": fandom_rejected,
        "pipeline_accepted": pipeline_accepted,
        "gold_accepted": gold_accepted,
        "rejected_pages": rejected_pages,
        "by_type": by_type,
        "by_importance": by_importance,
        "train_count": len(train_records),
        "eval_count": len(eval_records),
    }

    with open(output_dir / "export_report.json", "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)


def main() -> None:
    """CLI entry point with argparse."""
    parser = argparse.ArgumentParser(description="Export LoRA dataset from fandom + pipeline data")
    parser.add_argument("--fandom-jsonl", type=Path, help="Path to fandom JSONL file")
    parser.add_argument("--batch-dir", type=Path, default=None, help="Path to batch directory")
    parser.add_argument("--wiki-pages", type=Path, default=None, help="Path to wiki_pages.json")
    parser.add_argument("--gold-jsonl", type=Path, default=None, help="Path to gold examples JSONL")
    parser.add_argument("--output-dir", type=Path, required=True, help="Output directory")
    args = parser.parse_args()

    main_with_args(
        fandom_jsonl=args.fandom_jsonl,
        batch_dir=args.batch_dir,
        wiki_pages=args.wiki_pages,
        gold_jsonl=args.gold_jsonl,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()
