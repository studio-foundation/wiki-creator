"""Scrape fandom.com wikis via the MediaWiki API.

Usage:
    python scripts/scrape_fandom.py \\
        --wiki https://throneofglass.fandom.com \\
        --types PERSON PLACE ORG \\
        --lang en \\
        --limit 200 \\
        --out processing_output/fandom/throneofglass/lora_dataset_fandom.jsonl
"""
import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import mwparserfromhell
import requests


DEFAULT_CATEGORIES = {
    "PERSON": "Characters",
    "PLACE": "Locations",
    "ORG": "Organizations",
}

RATE_LIMIT_SECONDS = 1


def parse_infobox(wikitext: str) -> dict:
    """Extract infobox fields from wikitext. Returns {} if no infobox found."""
    parsed = mwparserfromhell.parse(wikitext)
    for template in parsed.filter_templates():
        if "infobox" in template.name.strip().lower():
            return {
                str(param.name).strip(): param.value.strip_code().strip()
                for param in template.params
            }
    return {}


def parse_body(wikitext: str) -> str:
    """Convert wikitext body to cleaned Markdown-like text."""
    # Remove <ref>...</ref> and self-closing <ref ... />
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", wikitext, flags=re.DOTALL)
    text = re.sub(r"<ref[^>]*/?>", "", text)

    parsed = mwparserfromhell.parse(text)

    # Remove File/Image links before stripping wikitext
    for link in parsed.filter_wikilinks():
        if str(link.title).strip().startswith(("File:", "Image:")):
            try:
                parsed.remove(link)
            except ValueError:
                pass

    # Remove all templates (infoboxes, navboxes, etc.)
    # Use try/except: filter_templates() is recursive so nested templates may
    # already be gone when we try to remove them individually.
    for template in parsed.filter_templates():
        try:
            parsed.remove(template)
        except ValueError:
            pass

    # Get plain text with section headings preserved
    lines = []
    for node in parsed.nodes:
        node_str = str(node)
        # Convert MediaWiki headings to Markdown
        heading_match = re.match(r"^(={2,6})\s*(.+?)\s*\1\s*$", node_str.strip())
        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2)
            lines.append("#" * level + " " + title)
        else:
            lines.append(node_str)

    return "".join(lines).strip()


def is_redirect(wikitext: str) -> bool:
    """Return True if the wikitext is a redirect page."""
    return wikitext.strip().lower().startswith("#redirect")


def is_stub(body: str) -> bool:
    """Return True if the cleaned body text is too short (< 200 chars)."""
    return len(body) < 200


def fetch_category_members(api_url: str, category: str) -> list[str]:
    """Fetch all page titles in a MediaWiki category. Returns list of titles."""
    titles = []
    params: dict = {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": f"Category:{category}",
        "cmlimit": "500",
        "format": "json",
    }
    while True:
        resp = requests.get(api_url, params=params)
        resp.raise_for_status()
        time.sleep(RATE_LIMIT_SECONDS)
        data = resp.json()
        members = data.get("query", {}).get("categorymembers", [])
        titles.extend(m["title"] for m in members)
        if "continue" not in data:
            break
        params["cmcontinue"] = data["continue"]["cmcontinue"]
    return titles


def fetch_wikitext(api_url: str, title: str) -> str | None:
    """Fetch raw wikitext for a page. Returns None if page not found."""
    params = {
        "action": "query",
        "prop": "revisions",
        "rvprop": "content",
        "titles": title,
        "format": "json",
    }
    resp = requests.get(api_url, params=params)
    resp.raise_for_status()
    time.sleep(RATE_LIMIT_SECONDS)
    data = resp.json()
    pages = data.get("query", {}).get("pages", {})
    for page in pages.values():
        revisions = page.get("revisions")
        if not revisions:
            return None
        return revisions[0].get("*")
    return None


def derive_wiki_slug(wiki_url: str) -> str:
    """Derive wiki slug from fandom URL. e.g. https://throneofglass.fandom.com → throneofglass"""
    host = urlparse(wiki_url).hostname or ""
    return host.replace(".fandom.com", "")


def scrape_page(
    api_url: str,
    title: str,
    entity_type: str,
    wiki_slug: str,
    lang: str,
) -> dict | None:
    """Fetch, parse, and filter a single wiki page. Returns record dict or None."""
    wikitext = fetch_wikitext(api_url, title)
    if wikitext is None:
        return None
    if is_redirect(wikitext):
        return None
    infobox = parse_infobox(wikitext)
    body = parse_body(wikitext)
    if is_stub(body):
        return None
    return {
        "source": "fandom",
        "wiki_slug": wiki_slug,
        "page_title": title,
        "entity_type": entity_type,
        "infobox_fields": infobox,
        "content": body,
        "content_lang": lang,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Scrape a fandom.com wiki via MediaWiki API.")
    parser.add_argument("--wiki", required=True, help="Base URL of the fandom wiki")
    parser.add_argument("--types", nargs="+", default=["PERSON", "PLACE", "ORG"])
    parser.add_argument("--lang", default="en", choices=["en", "fr"])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    api_url = args.wiki.rstrip("/") + "/api.php"
    wiki_slug = derive_wiki_slug(args.wiki)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    with out_path.open("w", encoding="utf-8") as out_file:
        for entity_type in args.types:
            if args.limit is not None and written >= args.limit:
                break
            category = DEFAULT_CATEGORIES.get(entity_type, entity_type)
            titles = fetch_category_members(api_url, category)
            if not titles:
                print(f"WARNING: category '{category}' returned 0 results for type {entity_type}")
                continue
            for title in titles:
                if args.limit is not None and written >= args.limit:
                    break
                record = scrape_page(api_url, title, entity_type, wiki_slug, args.lang)
                if record is None:
                    continue
                out_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                written += 1
                print(f"[{written}] {entity_type} — {title}")

    print(f"Done. {written} pages written to {out_path}")


if __name__ == "__main__":
    main()
