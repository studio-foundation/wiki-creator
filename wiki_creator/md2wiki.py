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

    # Headings (order matters: h4 before h3 before h2)
    if line.startswith("#### "):
        return "==== " + line[5:] + " ===="
    if line.startswith("### "):
        return "=== " + line[4:] + " ==="
    if line.startswith("## "):
        return "== " + line[3:] + " =="

    # Inline markup
    line = _convert_inline(line)
    return line


def _convert_inline(text: str) -> str:
    # Bold (**text**) → '''text''' — must be done before italic
    text = re.sub(r"\*\*(.+?)\*\*", r"'''\1'''", text)
    # Italic (*text*) → ''text'' — only single asterisks remaining
    text = re.sub(r"\*(.+?)\*", r"''\1''", text)
    return text
