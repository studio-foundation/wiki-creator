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
