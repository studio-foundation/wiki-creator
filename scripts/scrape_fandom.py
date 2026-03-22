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
            parsed.remove(link)

    # Remove all templates (infoboxes, navboxes, etc.)
    for template in parsed.filter_templates():
        parsed.remove(template)

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
        "redirects": "0",
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
