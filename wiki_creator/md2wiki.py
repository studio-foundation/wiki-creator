# wiki_creator/md2wiki.py
"""Markdown → MediaWiki wikitext conversion for wiki export."""
import re

from wiki_creator import entity_taxonomy


def convert(markdown: str) -> str:
    """Convert markdown body text to wikitext.

    Cross-refs ([[Name]]) and category tags ([[Category:X]]) pass through unchanged.
    Blockquote lines (spoiler warnings) are removed.
    """
    lines = markdown.split("\n")
    result = []
    for line in lines:
        line = _convert_line(line)
        result.append(line)
    return "\n".join(result)


def _convert_line(line: str) -> str:
    # Remove blockquotes entirely
    if line.startswith(">"):
        return ""

    # Headings (order matters: most specific prefix first)
    if line.startswith("#### "):
        return "==== " + _convert_inline(line[5:]) + " ===="
    if line.startswith("### "):
        return "=== " + _convert_inline(line[4:]) + " ==="
    if line.startswith("## "):
        return "== " + _convert_inline(line[3:]) + " =="
    if line.startswith("# "):
        return "= " + _convert_inline(line[2:]) + " ="

    # Inline markup
    line = _convert_inline(line)
    return line


def _convert_inline(text: str) -> str:
    # Bold (**text**) → '''text''' — must be done before italic
    text = re.sub(r"\*\*(.+?)\*\*", r"'''\1'''", text)
    # Italic (*text*) → ''text'' — only single asterisks remaining
    text = re.sub(r"\*(.+?)\*", r"''\1''", text)
    return text


def make_infobox_call(entity_type: str, fields: dict) -> str:
    """Return the wikitext template call for the given entity type
    (base.yaml#entity_types.export.infobox_template, STU-505).

    A type without a declared template (OTHER, SYNOPSIS) falls through to the
    generic "Infobox" — though SYNOPSIS/COLLATION render body-only and never call
    this. Empty/None values are omitted. Each field on its own line.
    """
    template = entity_taxonomy.infobox_template_name(entity_type) or "Infobox"
    lines = ["{{" + template]
    for key, value in fields.items():
        if value is not None and value != "":
            lines.append(f"|{key}={value}")
    lines.append("}}")
    return "\n".join(lines)
