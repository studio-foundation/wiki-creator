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
