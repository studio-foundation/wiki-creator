"""Wikilink integrity (STU-725): every ``[[link]]`` in a rendered wiki page set
resolves to a page, or is a declared red link.

Pure, no I/O. It runs over the *rendered* page set — the ``.wiki`` bodies — so
it applies STU-506 title disambiguation for free (a disambiguated title *is* the
page's identity) and catches a link wherever it appears: infobox, prose, the
relationship index. A ``[[target]]`` resolves in the flat MediaWiki namespace via
:func:`export_helpers.page_filename`, the same identity
``page_validators.duplicate_page_titles`` compares. Namespace links
(``[[Category:...]]``, ``[[File:...]]``, the ``[[:Category:...]]`` link form)
target no content page and are excluded.

Reused at both scopes — the caller supplies ``(title, body)`` per page, so book
scope (``output/<book>/``) and series scope (``output/_series/``) differ only in
how the page set is built.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from wiki_creator.export_helpers import page_filename

_LINK_RE = re.compile(r"\[\[([^\[\]]+?)\]\]")

# A namespace-prefixed target points at a namespace, not a content page. The
# canonical namespaces stay English even in a French wiki (export emits
# ``[[Category:...]]`` literally); a leading ``:`` is the category-link form.
_NAMESPACE_RE = re.compile(
    r"^:?\s*(?:category|file|image|media|template|special|help|user|talk)\s*:",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DeadLink:
    source: str  # identity of the page carrying the link
    target: str  # the raw link target that resolves to no page


def _resolve_key(name: str) -> str:
    """Flat-namespace key for a link target or a page title: drop a ``#section``
    anchor, then :func:`page_filename` (spaces → underscores) — the identity the
    exporter writes files under and ``duplicate_page_titles`` compares."""
    return page_filename(name.split("#", 1)[0].strip())


def extract_link_targets(text: str) -> list[str]:
    """Every ``[[target]]`` / ``[[target|label]]`` in ``text`` that points at a
    content page. Namespace links (Category/File/…) and empty or anchor-only
    links are dropped; order is preserved and duplicates are kept."""
    targets: list[str] = []
    for match in _LINK_RE.finditer(text):
        raw = match.group(1).split("|", 1)[0]
        if _NAMESPACE_RE.match(raw.lstrip()):
            continue
        if raw.split("#", 1)[0].strip():
            targets.append(raw.strip())
    return targets


def retarget_links(text: str, resolve: Callable[[str], str | None]) -> str:
    """Rewrite every content wikilink in ``text`` through ``resolve``.

    ``resolve(target)`` returns the page title to link instead, ``""`` to unlink
    (the label survives as plain text — a merged-away target must not become a
    red link), or ``None`` to leave the link untouched. The visible label is
    preserved: ``[[Nick Chopper]]`` retargeted to ``Tin Woodman`` becomes
    ``[[Tin Woodman|Nick Chopper]]``, so the tome's own wording still reads while
    the link resolves (STU-719). Namespace links are never touched.
    """

    def rewrite(match: re.Match) -> str:
        raw = match.group(1)
        if _NAMESPACE_RE.match(raw.lstrip()):
            return match.group(0)
        target, _, label = raw.partition("|")
        anchor = ""
        base = target
        if "#" in target:
            base, _, anchor = target.partition("#")
        base, label = base.strip(), label.strip()
        if not base:
            return match.group(0)
        resolved = resolve(base)
        if resolved is None:
            return match.group(0)
        if not resolved:
            return label or base
        if _resolve_key(resolved) == _resolve_key(base):
            return match.group(0)
        shown = label or base
        suffix = f"#{anchor}" if anchor else ""
        return f"[[{resolved}{suffix}|{shown}]]"

    return _LINK_RE.sub(rewrite, text)


def find_dead_links(
    pages: Iterable[tuple[str, str]], allowlist: Iterable[str] = ()
) -> list[DeadLink]:
    """Every wikilink across ``pages`` that resolves to no existing page.

    ``pages`` is ``(title, body)`` per rendered page — ``title`` is the page's
    identity (already STU-506-disambiguated in a rendered set), ``body`` the
    wikitext scanned for links. ``allowlist`` names the intentional red links (a
    mentioned-but-not-notable entity); a target it names is never reported.

    One :class:`DeadLink` per (page, unresolved target), in page then link
    order, de-duplicated within a page — the same dead target linked twice on
    one page is one finding, on three pages three findings.
    """
    pages = list(pages)
    known = {_resolve_key(title) for title, _ in pages}
    allowed = {_resolve_key(name) for name in allowlist}
    dead: list[DeadLink] = []
    for title, body in pages:
        seen: set[str] = set()
        for target in extract_link_targets(body):
            key = _resolve_key(target)
            if key in known or key in allowed or key in seen:
                continue
            seen.add(key)
            dead.append(DeadLink(source=title, target=target))
    return dead
