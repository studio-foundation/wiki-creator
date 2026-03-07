#!/usr/bin/env python3
"""
Standalone pre-processing script: generate wiki pages via Ollama.

Run this BEFORE the wiki-generation Studio pipeline.
Results are saved to processing_output/wiki_pages.json and loaded
by load_wiki_pages.py inside the pipeline.

Usage:
    python scripts/generate_wiki_pages.py
    python scripts/generate_wiki_pages.py --model llama3:8b
    python scripts/generate_wiki_pages.py --importance principal secondary
    python scripts/generate_wiki_pages.py --dry-run
"""

import argparse
import json
import os
import sys
import urllib.request

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OUTPUT_FILE = "processing_output/wiki_pages.json"
WIKI_INPUTS_DIR = "wiki_inputs"


def call_ollama(prompt: str, model: str, timeout: int) -> str:
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.3, "num_predict": 1024},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    return data.get("response", "")


def build_prompt(entity: dict, book_title: str) -> str:
    name = entity["canonical_name"]
    etype = entity["type"]
    importance = entity["importance"]
    aliases = entity.get("aliases", [])
    context = entity.get("context_by_chapter", {})

    context_lines = []
    for chapter, mentions in list(context.items())[:15]:
        for mention in mentions[:3]:
            context_lines.append(f"  [{chapter}] {mention}")
    context_block = "\n".join(context_lines) if context_lines else "  (no excerpts available)"

    alias_str = ", ".join(a for a in aliases if a != name) or "none"
    length_guide = {
        "principal": "Write 4-6 paragraphs total across all sections.",
        "secondary": "Write 1-2 paragraphs for biography. Keep it short.",
        "figurant": "Write 1 short paragraph only.",
    }.get(importance, "Write 1 short paragraph only.")

    return f"""You are writing a wiki page for a fantasy novel called "{book_title}".
Output ONLY a valid JSON object. No markdown fences. No explanation.

Entity:
  Name: {name}
  Type: {etype}
  Known aliases: {alias_str}

Text excerpts from the book that mention this entity:
{context_block}

RULES:
- Write in encyclopedic French.
- Use ONLY information from the excerpts above. Do NOT use your training knowledge about this book.
- If excerpts are empty or insufficient, write a minimal page.
- {length_guide}
- Do NOT invent plot details, relationships, or facts not in the excerpts.

Output this JSON object:
{{
  "title": "{name}",
  "importance": "{importance}",
  "entity_type": "{etype}",
  "infobox_fields": {{}},
  "content": "## Biographie\\n\\n<write content here in French>"
}}

The "content" field must be a Markdown string. Use \\n for newlines inside the string.
Output ONLY the JSON object, nothing else."""


def make_stub_page(entity: dict) -> dict:
    return {
        "title": entity["canonical_name"],
        "importance": entity["importance"],
        "entity_type": entity["type"],
        "infobox_fields": {},
        "content": "## Biographie\n\n*Informations insuffisantes disponibles pour cette entité.*",
    }


def parse_response(raw: str, entity: dict) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
    try:
        page = json.loads(raw)
        page.setdefault("title", entity["canonical_name"])
        page.setdefault("importance", entity["importance"])
        page.setdefault("entity_type", entity["type"])
        page.setdefault("infobox_fields", {})
        page.setdefault("content", "")
        return page
    except json.JSONDecodeError:
        print(f"    [WARN] JSON parse failed for {entity['canonical_name']}, using stub", file=sys.stderr)
        return make_stub_page(entity)


def load_batch_files(importance_filter: list[str] | None) -> list[tuple[str, dict]]:
    """Load all batch files from wiki_inputs/, optionally filtering by importance."""
    if not os.path.isdir(WIKI_INPUTS_DIR):
        print(f"[ERROR] {WIKI_INPUTS_DIR}/ not found. Run wiki-preparation first.", file=sys.stderr)
        sys.exit(1)

    batch_files = sorted(f for f in os.listdir(WIKI_INPUTS_DIR) if f.endswith(".json"))
    result = []
    for fname in batch_files:
        path = os.path.join(WIKI_INPUTS_DIR, fname)
        with open(path, encoding="utf-8") as f:
            batch = json.load(f)
        if importance_filter:
            batch["entities"] = [e for e in batch.get("entities", []) if e.get("importance") in importance_filter]
        if batch.get("entities"):
            result.append((path, batch))
    return result


def load_book_title() -> str:
    """Try to load book title from processing_output/epub_data.json."""
    try:
        with open("processing_output/epub_data.json", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("title", "the novel")
    except Exception:
        return "the novel"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.environ.get("WIKI_MODEL", "qwen2.5"), help="Ollama model")
    parser.add_argument("--timeout", type=int, default=120, help="Timeout per entity (seconds)")
    parser.add_argument("--importance", nargs="+", choices=["principal", "secondary", "figurant"],
                        help="Only process entities of these importance levels")
    parser.add_argument("--dry-run", action="store_true", help="Skip LLM calls, output stubs only")
    args = parser.parse_args()

    book_title = load_book_title()
    batches = load_batch_files(args.importance)

    if not batches:
        print("[WARN] No batch files found or all batches empty after filter.", file=sys.stderr)
        _save([], args)
        return

    total_entities = sum(len(b["entities"]) for _, b in batches)
    print(f"[generate-wiki-pages] {total_entities} entities across {len(batches)} batches | model={args.model}", file=sys.stderr)

    all_pages = []
    for path, batch in batches:
        batch_id = batch.get("batch_id", os.path.basename(path))
        entities = batch.get("entities", [])
        print(f"\n[{batch_id}] {len(entities)} entities", file=sys.stderr)

        for entity in entities:
            name = entity.get("canonical_name", "?")
            importance = entity.get("importance", "figurant")
            context = entity.get("context_by_chapter", {})

            if not context:
                print(f"  [STUB] {name} (no context)", file=sys.stderr)
                all_pages.append(make_stub_page(entity))
                continue

            if args.dry_run:
                print(f"  [DRY]  {name}", file=sys.stderr)
                all_pages.append(make_stub_page(entity))
                continue

            print(f"  [GEN]  {name} ({importance})", file=sys.stderr, end="", flush=True)
            try:
                prompt = build_prompt(entity, book_title)
                raw = call_ollama(prompt, args.model, args.timeout)
                page = parse_response(raw, entity)
                all_pages.append(page)
                print(" ✓", file=sys.stderr)
            except Exception as e:
                print(f" ✗ {e}", file=sys.stderr)
                all_pages.append(make_stub_page(entity))

    _save(all_pages, args)


def _save(pages: list[dict], args: argparse.Namespace) -> None:
    os.makedirs("processing_output", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump({"pages": pages}, f, ensure_ascii=False, indent=2)
    print(f"\n[generate-wiki-pages] {len(pages)} pages saved to {OUTPUT_FILE}", file=sys.stderr)


if __name__ == "__main__":
    main()
