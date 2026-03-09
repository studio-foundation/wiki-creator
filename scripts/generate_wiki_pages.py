#!/usr/bin/env python3
"""
Standalone pre-processing script: generate wiki pages via Ollama.

Run this BEFORE the wiki-generation Studio pipeline.
Results are saved to <book processing dir>/wiki_pages.json and loaded
by load_wiki_pages.py inside the pipeline.

Usage:
    python scripts/generate_wiki_pages.py --book library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml
    python scripts/generate_wiki_pages.py --book library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml --model llama3:8b
    python scripts/generate_wiki_pages.py --book library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml --importance principal secondary
    python scripts/generate_wiki_pages.py --book library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml --dry-run
"""

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

import yaml

# Ensure project root is importable when running as `python scripts/<file>.py`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wiki_creator.paths import book_paths_from_yaml

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DEFAULT_NUM_PREDICT = 1024

_DEFAULT_SECTIONS_BY_IMPORTANCE = {
    "principal": ["infobox", "biography", "personality", "physical", "powers", "relationships", "trivia", "references"],
    "secondary": ["infobox", "biography", "relationships", "references"],
    "figurant": ["infobox", "biography"],
}
_SECTION_TITLES = {
    "infobox": "Infobox",
    "biography": "Biographie",
    "personality": "Personnalité",
    "physical": "Description physique",
    "powers": "Pouvoirs",
    "relationships": "Relations",
    "trivia": "Anecdotes",
    "references": "Références",
}
_PLACEHOLDER_PATTERNS = (
    re.compile(r"<[^>\n]{1,80}>"),
    re.compile(r"\bsi connu\b", re.IGNORECASE),
    re.compile(r"contenu en fran[çc]ais bas[ée] uniquement sur les extraits", re.IGNORECASE),
)


def call_ollama(prompt: str, model: str, timeout: int, num_predict: int = DEFAULT_NUM_PREDICT) -> str:
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.3, "num_predict": num_predict},
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


def _content_template_for_sections(sections: list[str]) -> str:
    blocks = []
    for section in sections:
        title = _SECTION_TITLES.get(section, section.replace("_", " ").title())
        if section == "infobox":
            blocks.append(
                f"## {title}\\n\\n"
                "- Nom: Inconnu\\n"
                "- Rôle: Inconnu\\n"
                "- Affiliation: Inconnue"
            )
        else:
            blocks.append(f"## {title}\\n\\nInformations non disponibles dans les extraits fournis.")
    return "\\n\\n".join(blocks)


def build_prompt(entity: dict, book_title: str, sections: list[str]) -> str:
    name = entity["canonical_name"]
    etype = entity["type"]
    importance = entity["importance"]
    aliases = entity.get("aliases", [])
    context = entity.get("context_by_chapter", {})
    related_context = entity.get("related_context", [])
    chapter_summary_context = entity.get("chapter_summary_context", [])

    context_lines = []
    for chapter, mentions in list(context.items())[:15]:
        for mention in mentions[:3]:
            context_lines.append(f"  [{chapter}] {mention}")
    context_block = "\n".join(context_lines) if context_lines else "  (no excerpts available)"

    related_lines = []
    for rel in related_context[:5]:
        related_name = rel.get("related_name", "").strip()
        if not related_name:
            continue
        related_type = rel.get("related_type") or "unknown"
        related_importance = rel.get("related_importance") or "unknown"
        cooccurrence = rel.get("cooccurrence_count", 0)
        related_lines.append(
            f"  - Name: {related_name} | Type: {related_type} | Importance: {related_importance} | Cooccurrence count: {cooccurrence}"
        )
        for snippet in rel.get("support_snippets", [])[:2]:
            related_lines.append(f"    - Snippet: {snippet}")
    related_block = "\n".join(related_lines) if related_lines else "  (no related entities available)"

    chapter_summary_lines = []
    for chapter in chapter_summary_context[:8]:
        chapter_key = chapter.get("chapter_key", "").strip()
        if not chapter_key:
            continue
        chapter_summary_lines.append(f"  - Chapter: {chapter_key}")
        for bullet in chapter.get("summary_bullets", [])[:3]:
            chapter_summary_lines.append(f"    - {bullet}")
    chapter_summary_block = (
        "\n".join(chapter_summary_lines)
        if chapter_summary_lines
        else "  (no chapter summaries available)"
    )

    alias_str = ", ".join(a for a in aliases if a != name) or "none"
    length_guide = {
        "principal": "Write 4-6 paragraphs total across all sections.",
        "secondary": "Write 1-2 paragraphs for biography. Keep it short.",
        "figurant": "Write 1 short paragraph only.",
    }.get(importance, "Write 1 short paragraph only.")
    sections_str = ", ".join(sections)
    content_template = _content_template_for_sections(sections)

    return f"""You are writing a wiki page for a fantasy novel called "{book_title}".
Output ONLY a valid JSON object. No markdown fences. No explanation.

Entity:
  Name: {name}
  Type: {etype}
  Known aliases: {alias_str}

Text excerpts from the book that mention this entity:
{context_block}

Known related entities (disambiguation context):
{related_block}

Chapter summaries for chapters where this entity appears:
{chapter_summary_block}

RULES:
- Write in encyclopedic French.
- Use ONLY information from the excerpts above. Do NOT use your training knowledge about this book.
- Use this block only to disambiguate likely related entities.
- Direct excerpts have priority over chapter summaries.
- Treat chapter summaries as orientation context, not strong evidence.
- If excerpts are empty or insufficient, write a minimal page.
- {length_guide}
- Use exactly these sections in this order: {sections_str}.
- The "Infobox" section must contain one bullet per field in the format "- Key: Value".
- Do NOT invent plot details, relationships, or facts not in the excerpts.
- If ambiguous, omit rather than infer.
- Do NOT turn cooccurrence into narrative causality.

Output this JSON object:
{{
  "title": "{name}",
  "importance": "{importance}",
  "entity_type": "{etype}",
  "infobox_fields": {{}},
  "content": "{content_template}"
}}

The "content" field must be a Markdown string. Use \\n for newlines inside the string.
Output ONLY the JSON object, nothing else."""


def make_stub_page(entity: dict, failed: bool = False) -> dict:
    page = {
        "title": entity["canonical_name"],
        "importance": entity["importance"],
        "entity_type": entity["type"],
        "infobox_fields": {},
        "content": "## Biographie\n\n*Informations insuffisantes disponibles pour cette entité.*",
    }
    if failed:
        page["_failed"] = True
    return page


def _normalize_infobox_key(key: str) -> str:
    key = key.strip().lower()
    key = re.sub(r"\s+", "_", key)
    return key


def _extract_infobox_fields_from_content(content: str) -> dict[str, str]:
    lines = content.splitlines()
    start_idx = None
    for idx, line in enumerate(lines):
        if re.match(r"^##\s+infobox\s*$", line.strip(), flags=re.IGNORECASE):
            start_idx = idx + 1
            break

    if start_idx is None:
        return {}

    fields: dict[str, str] = {}
    for line in lines[start_idx:]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            break

        if stripped.startswith("- ") or stripped.startswith("* ") or stripped.startswith("+ "):
            stripped = stripped[2:].strip()

        if ":" not in stripped:
            continue

        raw_key, raw_value = stripped.split(":", 1)
        key = _normalize_infobox_key(raw_key)
        value = raw_value.strip()
        if key and value:
            fields[key] = value

    return fields


def parse_response(raw: str, entity: dict) -> dict:
    raw = raw.strip()
    decoder = json.JSONDecoder()
    page = None
    for i, ch in enumerate(raw):
        if ch != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(raw[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            page = candidate
            break
    try:
        if page is None:
            raise json.JSONDecodeError("No JSON object found", raw, 0)
        page.setdefault("title", entity["canonical_name"])
        page.setdefault("importance", entity["importance"])
        page.setdefault("entity_type", entity["type"])
        page.setdefault("infobox_fields", {})
        page.setdefault("content", "")
        if not _is_page_complete(page):
            print(f"    [WARN] Empty content for {entity['canonical_name']}, using failed stub", file=sys.stderr)
            return make_stub_page(entity, failed=True)
        if not page["infobox_fields"] and page["content"]:
            page["infobox_fields"] = _extract_infobox_fields_from_content(page["content"])
        if _contains_template_placeholder(page):
            print(
                f"    [WARN] Placeholder/template leak for {entity['canonical_name']}, using failed stub",
                file=sys.stderr,
            )
            return make_stub_page(entity, failed=True)
        return page
    except json.JSONDecodeError:
        print(f"    [WARN] JSON parse failed for {entity['canonical_name']}, using stub", file=sys.stderr)
        return make_stub_page(entity)


def load_batch_files(wiki_inputs_dir: str, importance_filter: list[str] | None) -> list[tuple[str, dict]]:
    """Load all batch files from wiki_inputs_dir, optionally filtering by importance."""
    if not os.path.isdir(wiki_inputs_dir):
        print(f"[ERROR] {wiki_inputs_dir}/ not found. Run wiki-preparation first.", file=sys.stderr)
        sys.exit(1)

    batch_files = sorted(f for f in os.listdir(wiki_inputs_dir) if f.endswith(".json"))
    result = []
    for fname in batch_files:
        path = os.path.join(wiki_inputs_dir, fname)
        with open(path, encoding="utf-8") as f:
            batch = json.load(f)
        if importance_filter:
            batch["entities"] = [e for e in batch.get("entities", []) if e.get("importance") in importance_filter]
        if batch.get("entities"):
            result.append((path, batch))
    return result


def load_book_title(epub_data_path: str) -> str:
    """Try to load book title from epub_data.json."""
    try:
        with open(epub_data_path, encoding="utf-8") as f:
            data = json.load(f)
            return data.get("title", "the novel")
    except Exception:
        return "the novel"


def load_book_config(book_yaml_path: str) -> dict:
    try:
        with open(book_yaml_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def generation_profile(config: dict, importance: str, entity_type: str | None = None) -> tuple[list[str], int]:
    profile = config.get(importance, {})
    default_sections = _DEFAULT_SECTIONS_BY_IMPORTANCE.get(importance, _DEFAULT_SECTIONS_BY_IMPORTANCE["figurant"])

    sections_by_type = profile.get("sections_by_type", {})
    type_override = None
    if isinstance(sections_by_type, dict) and entity_type:
        type_override = sections_by_type.get(str(entity_type).upper())

    sections = type_override if type_override is not None else profile.get("sections", default_sections)
    if not isinstance(sections, list) or not sections:
        sections = default_sections
    max_tokens = profile.get("max_tokens_per_page", DEFAULT_NUM_PREDICT)
    try:
        max_tokens = int(max_tokens)
    except (TypeError, ValueError):
        max_tokens = DEFAULT_NUM_PREDICT
    if max_tokens < 64:
        max_tokens = 64
    return sections, max_tokens


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--book", required=True,
        help="Path to book yaml, e.g. library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml",
    )
    parser.add_argument("--model", default=os.environ.get("WIKI_MODEL", "qwen2.5"), help="Ollama model")
    parser.add_argument("--timeout", type=int, default=120, help="Timeout per entity (seconds)")
    parser.add_argument("--importance", nargs="+", choices=["principal", "secondary", "figurant"],
                        help="Only process entities of these importance levels")
    parser.add_argument("--dry-run", action="store_true", help="Skip LLM calls, output stubs only")
    args = parser.parse_args()

    book_paths = book_paths_from_yaml(args.book)
    output_file = str(book_paths.processing / "wiki_pages.json")
    wiki_inputs_dir = str(book_paths.wiki_inputs)
    book_cfg = load_book_config(args.book)
    generation_cfg = book_cfg.get("generation", {})

    book_title = load_book_title(str(book_paths.processing / "epub_data.json"))
    batches = load_batch_files(wiki_inputs_dir, args.importance)

    if not batches:
        print("[WARN] No batch files found or all batches empty after filter.", file=sys.stderr)
        _save([], output_file)
        return

    total_entities = sum(len(b["entities"]) for _, b in batches)
    print(f"[generate-wiki-pages] {total_entities} entities across {len(batches)} batches | model={args.model}", file=sys.stderr)

    # Load existing pages to resume interrupted runs
    all_pages = [p for p in _load_existing(output_file) if not p.get("_failed") and _is_page_complete(p)]
    done_titles = {p["title"] for p in all_pages}
    if done_titles:
        print(f"[generate-wiki-pages] Resuming — {len(done_titles)} pages already done", file=sys.stderr)

    try:
        for path, batch in batches:
            batch_id = batch.get("batch_id", os.path.basename(path))
            entities = batch.get("entities", [])
            print(f"\n[{batch_id}] {len(entities)} entities", file=sys.stderr)

            for entity in entities:
                name = entity.get("canonical_name", "?")
                importance = entity.get("importance", "figurant")
                context = entity.get("context_by_chapter", {})

                if name in done_titles:
                    print(f"  [SKIP] {name} (already done)", file=sys.stderr)
                    continue

                if not context:
                    print(f"  [STUB] {name} (no context)", file=sys.stderr)
                    page = make_stub_page(entity)
                    all_pages.append(page)
                    _save(all_pages, output_file)
                    done_titles.add(name)
                    continue

                if args.dry_run:
                    print(f"  [DRY]  {name}", file=sys.stderr)
                    page = make_stub_page(entity)
                    all_pages.append(page)
                    _save(all_pages, output_file)
                    done_titles.add(name)
                    continue

                print(f"  [GEN]  {name} ({importance})", file=sys.stderr, end="", flush=True)
                try:
                    sections, max_tokens = generation_profile(generation_cfg, importance, entity.get("type"))
                    prompt = build_prompt(entity, book_title, sections=sections)
                    raw = call_ollama(prompt, args.model, args.timeout, num_predict=max_tokens)
                    page = parse_response(raw, entity)
                    all_pages.append(page)
                    _save(all_pages, output_file)
                    done_titles.add(name)
                    print(" ✓", file=sys.stderr)
                except Exception as e:
                    print(f" ✗ {e}", file=sys.stderr)
                    page = make_stub_page(entity, failed=True)
                    all_pages.append(page)
                    _save(all_pages, output_file)
                    # Do NOT add to done_titles — will be retried on next run
    except KeyboardInterrupt:
        print(f"\n[generate-wiki-pages] Interrupted — {len(all_pages)} pages saved", file=sys.stderr)


def _save(pages: list[dict], output_file: str) -> None:
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({"pages": pages}, f, ensure_ascii=False, indent=2)


def _load_existing(output_file: str) -> list[dict]:
    if os.path.exists(output_file):
        try:
            with open(output_file, encoding="utf-8") as f:
                return json.load(f).get("pages", [])
        except Exception:
            pass
    return []


def _is_page_complete(page: dict) -> bool:
    content = page.get("content", "")
    return isinstance(content, str) and bool(content.strip())


def _contains_template_placeholder(page: dict) -> bool:
    """Reject responses that leak prompt placeholders into final content."""
    content = str(page.get("content", "") or "")
    for pattern in _PLACEHOLDER_PATTERNS:
        if pattern.search(content):
            return True
    infobox = page.get("infobox_fields", {}) or {}
    for value in infobox.values():
        text = str(value or "")
        for pattern in _PLACEHOLDER_PATTERNS:
            if pattern.search(text):
                return True
    return False


if __name__ == "__main__":
    main()
