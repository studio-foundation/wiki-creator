# wiki_creator/md2wiki.py
"""Markdown → MediaWiki wikitext conversion for wiki export."""
import re


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


# OTHER is intentionally absent: the pipeline does not generate wiki pages for
# it, so it falls through to the generic "Infobox" fallback in
# make_infobox_call(). SYNOPSIS renders body-only (no infobox).
_TEMPLATE_NAMES = {
    "PERSON": "Infobox character",
    "PLACE": "Infobox location",
    "ORG": "Infobox organization",
    "EVENT": "Infobox event",
}


def make_infobox_call(entity_type: str, fields: dict) -> str:
    """Return the wikitext template call for the given entity type.

    Empty/None values are omitted. Each field on its own line.
    """
    template = _TEMPLATE_NAMES.get(entity_type, "Infobox")
    lines = ["{{" + template]
    for key, value in fields.items():
        if value is not None and value != "":
            lines.append(f"|{key}={value}")
    lines.append("}}")
    return "\n".join(lines)
