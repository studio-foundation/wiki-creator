"""Convert fandom wikitext to clean Markdown."""

from __future__ import annotations

import re


def clean_wikitext(text: str) -> str:
    """Transform wikitext into pipeline-compatible Markdown."""
    # Strip metadata
    text = re.sub(r"\[\[Category:[^\]]*\]\]\n?", "", text)
    text = re.sub(r"<gallery[^>]*>.*?</gallery>\n?", "", text, flags=re.DOTALL)
    text = re.sub(r"\{\{[^}]*\}\}", "", text)
    text = re.sub(r"\n?<references\s*/?>\n?", "\n", text)
    text = re.sub(r"<references>.*?</references>", "", text, flags=re.DOTALL)
    text = re.sub(r"\[\[(?:File|Image):[^\]]*\]\]\n?", "", text)

    # Convert wiki syntax
    text = re.sub(r"'''(.*?)'''", r"**\1**", text)
    text = re.sub(r"''(.*?)''", r"*\1*", text)
    text = re.sub(r"\[\[[^\]|]+\|([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)

    # Remove empty sections
    text = re.sub(
        r"(?m)^(#{2,})\s+[^\n]+\n+(?=#{1,}\s|\Z)",
        "",
        text,
    )

    # Normalize whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    return text


# Synonym folding only (STU-734). This used to map every scraped fandom key onto a
# French target (`nom`, `statut`, `couleur des yeux`, …) — a hardcoded French
# vocabulary in code, which scripts/CLAUDE.md forbids. The consumer is the LoRA
# dataset export, i.e. training-data prep and not the wiki, so the keys stay in the
# source's own words and only genuine synonyms collapse onto one key.
_INFOBOX_KEY_MAP: dict[str, str] = {
    "AKA": "alias",
    "allegiance": "affiliation",
    "occupation": "role",
}

_INFOBOX_DROP_KEYS: set[str] = {
    "image", "caption", "affcollapse", "statcollapse",
    "appearances", "gallery",
}


def _strip_wiki_links(value: str) -> str:
    value = re.sub(r"\[\[[^\]|]+\|([^\]]+)\]\]", r"\1", value)
    value = re.sub(r"\[\[([^\]]+)\]\]", r"\1", value)
    return value


def normalize_infobox_fields(fields: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in fields.items():
        if key.lower() in _INFOBOX_DROP_KEYS or key.lower().endswith("collapse"):
            continue
        new_key = _INFOBOX_KEY_MAP.get(key, key)
        new_value = _strip_wiki_links(str(value)) if isinstance(value, str) else str(value)
        result[new_key] = new_value
    return result
