"""Scrape MULTIPLE fandom.com wikis via the MediaWiki API, capturing a
complete-enough record per page to answer questions you haven't thought of
yet — not just what's needed for infobox/enum analysis. Also produces
aggregate reports (field frequency, per-wiki maturity).

Usage:
    python scrape_fandom_bulk.py \\
        --wikis wikis.yaml \\
        --out-dir processing_output/fandom_corpus \\
        --workers 4 \\
        --limit-per-wiki 300

wikis.yaml format (see scripts/fandom_wikis.yaml for the curated list):
    - wiki: https://throneofglass.fandom.com
      lang: en
      types: [PERSON, PLACE, ORG]
    - wiki: https://hisdarkmaterials.fandom.com
      lang: en
      categories: {PERSON: Humans, ORG: Organisations}
    - wiki: https://enkidiev.fandom.com/fr
      lang: fr
      types: [PERSON]
      categories: {PERSON: Personnage}

Only `wiki` is required per entry. `lang` defaults to "en".
`types` defaults to ["PERSON", "PLACE", "ORG"].
`categories` overrides DEFAULT_CATEGORIES per entity type, merged over the
defaults so a partial override is enough. It is per-wiki because a category
name is a property of the wiki, not something derivable: the plain
"Characters"/"Locations"/"Organizations" default holds on barely half the
wikis surveyed. Real names in use include `Personnage` (singular, fr),
`Humans`, `Character`, `Places`, `Geography`, `Groups`, `Factions`, and
`The Shadowhunter Chronicles characters`. A wrong name is silent — the
category returns 0 members and the wiki yields no pages.

`infobox_templates` names the templates that ARE infoboxes but say so nowhere a
test can read — `Charcat` on warriors, whose markup lives one transclusion away.
Everything else is derived: a template is an infobox if its title contains
"infobox", or its source carries Portable Infobox `<infobox>` markup.

Non-English wikis are served under a path, not a subdomain: give the full
`https://enkidiev.fandom.com/fr` as `wiki`. Their Template: namespace is
localized too (`Modèle:`), which is why the namespace name is read from the API
rather than assumed.

Re-parsing the corpus already on disk, without rescraping any page:
    python scrape_fandom_bulk.py --wikis wikis.yaml \\
        --out-dir processing_output/fandom_corpus --reparse

Per-page record schema (one JSON object per line in lora_dataset_fandom.jsonl):
    source, wiki_slug, page_title, entity_type, content_lang, scraped_at
    infobox_fields      — parsed infobox key/value pairs
    all_templates       — every template on the page (navboxes, spoiler
                          warnings, quote boxes, etc.), not just the infobox
    categories          — the page's actual MediaWiki categories (richer
                          than the single entity_type label)
    content             — cleaned Markdown-like body (templates/File links
                          stripped)
    raw_wikitext        — full unparsed wikitext, kept so re-parsing for a
                          different question later doesn't require rescraping
    revision_id, last_edited_at, page_length_bytes — revision metadata

Outputs:
    {out_dir}/{wiki_slug}/lora_dataset_fandom.jsonl   — one per wiki, resumable
    {out_dir}/{wiki_slug}/wiki_stats.json             — one-time per-wiki snapshot:
                                                         total pages/articles/edits/
                                                         users, independent of the
                                                         page sample scraped
    {out_dir}/{wiki_slug}/templates/*.json            — canonical schema source: every
                                                         Template: page identified as an
                                                         infobox, + its /doc
                                                         subpage if present. Shows what
                                                         fields the template SUPPORTS,
                                                         not just what got filled in on
                                                         any given character page.
    {out_dir}/field_report.json/.csv                  — infobox field/enum aggregate
    {out_dir}/wiki_maturity_report.json/.csv          — per-wiki maturity spectrum
    {out_dir}/run_log.jsonl                            — per-wiki success/failure log
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import mwparserfromhell
import requests
import yaml

DEFAULT_CATEGORIES = {
    "PERSON": "Characters",
    "PLACE": "Locations",
    "ORG": "Organizations",
}

RATE_LIMIT_SECONDS = 1
MAX_SAMPLE_VALUES_PER_FIELD = 25  # cap so field_report.json doesn't explode on free-text fields
MAX_TITLES_PER_QUERY = 50  # MediaWiki's ceiling for a multi-title query


# --------------------------------------------------------------------------
# Wikitext parsing (same logic as the single-wiki script)
# --------------------------------------------------------------------------

_PORTABLE_INFOBOX_MARKUP = re.compile(r"<infobox\b", re.IGNORECASE)


def normalize_template_name(name: str) -> str:
    """Fold a template name the way MediaWiki folds a page title: underscores
    are spaces, and only the FIRST letter is case-insensitive.
    """
    normalized = " ".join(name.replace("_", " ").split())
    return normalized[:1].upper() + normalized[1:]


def is_infobox_template(title: str, source: str | None) -> bool:
    """Is this Template: page an infobox? Two independent tests, unioned.

    "infobox" in the title is a convention, not a rule — the template is very
    often just `Character`. Portable Infobox markup (`<infobox>`) is a rule, but
    only for wikis that migrated. Neither test alone reaches even half the
    corpus; the union reaches 4 of the 5 conventions in it. The fifth is
    Warriors' `Charcat`, whose own source is one call to `Charcat/deep`: the
    `<infobox>` is real but one transclusion away, so neither test can see it.

    Following transclusions is what that seems to ask for, and it was measured
    and rejected: transcluding an infobox is not being one. On Warriors' 954
    templates, one level adds 16 names to the 23 the direct tests find, and only
    one is `Charcat`. The wiki's `Image`, `Book` and `Location` are themselves
    portable infoboxes, so the level sweeps in whatever shows a picture or cites
    a tome — `Official Site`, `StaffBox`, `Prey`, `R`. Iterating to a fixpoint
    adds 278, including 79 `Charcat/<cat name>` subpages. Either way the one real
    name arrives indistinguishable from the noise, so `Charcat` is declared
    instead, like `categories` — derive what is derivable, declare the rest.

    Deliberately NOT a param-count test: a well-filled `Dialogue` or `Quote`
    would pass one. Param count measured the size of this hole; it does not
    close it.
    """
    if "infobox" in title.lower():
        return True
    return bool(source) and _PORTABLE_INFOBOX_MARKUP.search(source) is not None


class WikiInfoboxTemplates:
    """The template names that are infoboxes on one wiki, unprefixed — a page
    calls `{{Character}}`, never `{{Template:Character}}`.
    """

    def __init__(self, names: set[str], namespace_prefix: str = "Template:"):
        self.names = {normalize_template_name(n) for n in names}
        self.namespace_prefix = namespace_prefix

    def titles(self) -> list[str]:
        return sorted(self.namespace_prefix + name for name in self.names)

    def is_infobox(self, template_name: str) -> bool:
        return normalize_template_name(template_name) in self.names


def zero_infobox_reason(templates: WikiInfoboxTemplates) -> str:
    """Why a wiki produced no infobox_fields at all. The two causes are opposite
    — we failed to identify the template, or the pages really carry none — and a
    wiki sitting at 0.0 must say which one it is rather than go quiet.
    """
    if not templates.names:
        return ("no infobox template found on this wiki: no title says 'infobox', no "
                "source carries <infobox> markup, and the wiki declares no "
                "'infobox_templates'")
    return (f"{len(templates.names)} infobox templates identified on this wiki, but no "
            "scraped page calls one — the pages sampled carry no infobox")


def parse_infobox(wikitext: str, templates: WikiInfoboxTemplates) -> dict:
    parsed = mwparserfromhell.parse(wikitext)
    for template in parsed.filter_templates():
        if templates.is_infobox(str(template.name)):
            return {
                str(param.name).strip(): param.value.strip_code().strip()
                for param in template.params
            }
    return {}


def parse_all_templates(wikitext: str) -> list[dict]:
    """Capture every template on the page (navboxes, spoiler warnings, quote
    boxes, etc.), not just the infobox — "complete dataset for any question"
    means not deciding in advance which templates matter.
    """
    parsed = mwparserfromhell.parse(wikitext)
    templates = []
    for template in parsed.filter_templates():
        templates.append({
            "name": str(template.name).strip(),
            "params": {
                str(param.name).strip(): param.value.strip_code().strip()
                for param in template.params
            },
        })
    return templates


def parse_body(wikitext: str) -> str:
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", wikitext, flags=re.DOTALL)
    text = re.sub(r"<ref[^>]*/?>", "", text)

    parsed = mwparserfromhell.parse(text)

    for link in parsed.filter_wikilinks():
        if str(link.title).strip().startswith(("File:", "Image:")):
            try:
                parsed.remove(link)
            except ValueError:
                pass

    for template in parsed.filter_templates():
        try:
            parsed.remove(template)
        except ValueError:
            pass

    lines = []
    for node in parsed.nodes:
        node_str = str(node)
        heading_match = re.match(r"^(={2,6})\s*(.+?)\s*\1\s*$", node_str.strip())
        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2)
            lines.append("#" * level + " " + title)
        else:
            lines.append(node_str)

    return "".join(lines).strip()


def is_redirect(wikitext: str) -> bool:
    return wikitext.strip().lower().startswith("#redirect")


def is_stub(body: str) -> bool:
    return len(body) < 200


# --------------------------------------------------------------------------
# MediaWiki API
# --------------------------------------------------------------------------

def fetch_category_members(api_url: str, category: str) -> list[str]:
    titles = []
    params: dict = {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": f"Category:{category}",
        "cmlimit": "500",
        "format": "json",
    }
    while True:
        resp = requests.get(api_url, params=params, timeout=30)
        resp.raise_for_status()
        time.sleep(RATE_LIMIT_SECONDS)
        data = resp.json()
        members = data.get("query", {}).get("categorymembers", [])
        titles.extend(m["title"] for m in members)
        if "continue" not in data:
            break
        params["cmcontinue"] = data["continue"]["cmcontinue"]
    return titles


def fetch_page_full(api_url: str, title: str) -> dict | None:
    """Fetch wikitext + categories + revision/length metadata in one call.

    Returns None if the page doesn't exist. Otherwise:
    {
        "wikitext": str,
        "categories": [str, ...],
        "revision_id": int | None,
        "last_edited_at": str | None,   # ISO timestamp of the fetched revision
        "page_length_bytes": int | None,
    }
    """
    params = {
        "action": "query",
        "prop": "revisions|categories|info",
        "rvprop": "content|timestamp|ids",
        "cllimit": "500",
        "titles": title,
        "format": "json",
    }
    resp = requests.get(api_url, params=params, timeout=30)
    resp.raise_for_status()
    time.sleep(RATE_LIMIT_SECONDS)
    data = resp.json()
    pages = data.get("query", {}).get("pages", {})
    for page in pages.values():
        revisions = page.get("revisions")
        if not revisions:
            return None
        rev = revisions[0]
        categories = [
            c.get("title", "").removeprefix("Category:")
            for c in page.get("categories", [])
        ]
        return {
            "wikitext": rev.get("*"),
            "categories": categories,
            "revision_id": rev.get("revid"),
            "last_edited_at": rev.get("timestamp"),
            "page_length_bytes": page.get("length"),
        }
    return None


def fetch_wiki_statistics(api_url: str) -> dict | None:
    """One-time per-wiki snapshot: total pages/articles/edits/users. Independent
    of whatever sample of pages we scrape — answers "how big is this
    community really" without needing the full page sample.
    """
    params = {
        "action": "query",
        "meta": "siteinfo",
        "siprop": "statistics|general",
        "format": "json",
    }
    try:
        resp = requests.get(api_url, params=params, timeout=30)
        resp.raise_for_status()
        time.sleep(RATE_LIMIT_SECONDS)
        data = resp.json()
        query = data.get("query", {})
        stats = query.get("statistics", {})
        general = query.get("general", {})
        return {
            "sitename": general.get("sitename"),
            "lang": general.get("lang"),
            "pages": stats.get("pages"),
            "articles": stats.get("articles"),
            "edits": stats.get("edits"),
            "users": stats.get("users"),
            "activeusers": stats.get("activeusers"),
            "images": stats.get("images"),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
    except (requests.RequestException, json.JSONDecodeError):
        return None


def derive_wiki_slug(wiki_url: str) -> str:
    host = urlparse(wiki_url).hostname or ""
    return host.replace(".fandom.com", "")


def scrape_page(
    api_url: str,
    title: str,
    entity_type: str,
    wiki_slug: str,
    lang: str,
    templates: WikiInfoboxTemplates,
) -> dict | None:
    page_data = fetch_page_full(api_url, title)
    if page_data is None:
        return None
    wikitext = page_data["wikitext"]
    if wikitext is None or is_redirect(wikitext):
        return None
    infobox = parse_infobox(wikitext, templates)
    all_templates = parse_all_templates(wikitext)
    body = parse_body(wikitext)
    if is_stub(body):
        return None
    return {
        "source": "fandom",
        "wiki_slug": wiki_slug,
        "page_title": title,
        "entity_type": entity_type,
        "infobox_fields": infobox,
        "all_templates": all_templates,
        "categories": page_data["categories"],
        "content": body,
        "raw_wikitext": wikitext,
        "revision_id": page_data["revision_id"],
        "last_edited_at": page_data["last_edited_at"],
        "page_length_bytes": page_data["page_length_bytes"],
        "content_lang": lang,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }


# --------------------------------------------------------------------------
# Per-wiki job (resumable) — this is what runs in a worker thread
# --------------------------------------------------------------------------

def load_already_scraped_titles(out_path: Path) -> set[str]:
    """For resume: read an existing jsonl and return titles already captured."""
    if not out_path.exists():
        return set()
    seen = set()
    with out_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                seen.add(rec.get("page_title"))
            except json.JSONDecodeError:
                continue
    return seen


def fetch_template_namespace_titles(api_url: str) -> list[str]:
    """List every page in the Template: namespace (ns=10). Unfiltered: a
    template's title does not say whether it is an infobox (STU-557), so the
    filtering happens in `resolve_infobox_templates`, against the source.
    """
    titles = []
    params: dict = {
        "action": "query",
        "list": "allpages",
        "apnamespace": "10",  # Template:
        "aplimit": "500",
        "format": "json",
    }
    while True:
        resp = requests.get(api_url, params=params, timeout=30)
        resp.raise_for_status()
        time.sleep(RATE_LIMIT_SECONDS)
        data = resp.json()
        pages = data.get("query", {}).get("allpages", [])
        titles.extend(p["title"] for p in pages)
        if "continue" not in data:
            break
        params["apcontinue"] = data["continue"]["apcontinue"]
    return titles


def fetch_template_namespace_prefix(api_url: str) -> str:
    """The Template: namespace's name on this wiki. It is localized — `Modèle:`
    on a French wiki — so stripping the literal "Template:" drops the whole
    namespace on those wikis. Only the namespace NUMBER (10) is the rule.
    """
    resp = requests.get(api_url, params={
        "action": "query",
        "meta": "siteinfo",
        "siprop": "namespaces",
        "format": "json",
    }, timeout=30)
    resp.raise_for_status()
    time.sleep(RATE_LIMIT_SECONDS)
    namespace = resp.json().get("query", {}).get("namespaces", {}).get("10", {})
    return namespace.get("*") or "Template"


def fetch_pages_batch(api_url: str, titles: list[str]) -> dict[str, str | None]:
    """Fetch many pages' wikitext in as few calls as possible.

    Reading every template's source is what makes the markup test affordable:
    one page per call would cost ~34 min on Harry Potter's 2041 templates; at
    the API's 50-titles-per-call ceiling it costs ~25s.
    """
    sources: dict[str, str | None] = {}
    for i in range(0, len(titles), MAX_TITLES_PER_QUERY):
        chunk = titles[i:i + MAX_TITLES_PER_QUERY]
        resp = requests.get(api_url, params={
            "action": "query",
            "prop": "revisions",
            "rvprop": "content",
            "titles": "|".join(chunk),
            "format": "json",
        }, timeout=60)
        resp.raise_for_status()
        time.sleep(RATE_LIMIT_SECONDS)
        for page in resp.json().get("query", {}).get("pages", {}).values():
            revisions = page.get("revisions")
            sources[page["title"]] = revisions[0].get("*") if revisions else None
    return sources


def resolve_infobox_templates(api_url: str, declared: list[str] | None = None) -> WikiInfoboxTemplates:
    """Which template names are infoboxes on this wiki: read the whole Template:
    namespace and test each one's title AND source, then add whatever the wiki
    declares (the templates neither test can see).
    """
    prefix = fetch_template_namespace_prefix(api_url) + ":"
    titles = fetch_template_namespace_titles(api_url)
    sources = fetch_pages_batch(api_url, titles)
    names = {
        title.removeprefix(prefix)
        for title in titles
        if is_infobox_template(title, sources.get(title))
    }
    names.update(declared or [])
    return WikiInfoboxTemplates(names, namespace_prefix=prefix)


def sanitize_filename(name: str) -> str:
    """Turn a template title into a safe filename."""
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "template"


def scrape_infobox_templates(api_url: str, wiki_out_dir: Path, templates: WikiInfoboxTemplates) -> dict:
    """Fetch every infobox Template: page (+ its /doc subpage if any) and write
    each as its own JSON file under {wiki_out_dir}/templates/. This is the
    canonical schema source — what fields the template *supports* — as opposed
    to lora_dataset_fandom.jsonl, which only shows what fields got *filled in*
    on any given character page.

    Returns a summary dict for the run log. Never raises.
    """
    templates_dir = wiki_out_dir / "templates"
    summary = {"templates_found": 0, "templates_written": 0, "errors": []}
    try:
        titles = templates.titles()
        summary["templates_found"] = len(titles)
        if not titles:
            return summary
        templates_dir.mkdir(parents=True, exist_ok=True)
        for title in titles:
            out_file = templates_dir / f"{sanitize_filename(title)}.json"
            if out_file.exists():
                continue  # resume: don't re-fetch templates we already have
            try:
                page_data = fetch_page_full(api_url, title)
            except requests.RequestException as e:
                summary["errors"].append(f"template '{title}' fetch failed: {e}")
                continue
            if page_data is None:
                continue

            doc_title = title + "/doc"
            doc_wikitext = None
            try:
                doc_data = fetch_page_full(api_url, doc_title)
                if doc_data is not None:
                    doc_wikitext = doc_data["wikitext"]
            except requests.RequestException:
                pass  # /doc subpage is optional; absence is not an error

            record = {
                "source": "fandom",
                "template_title": title,
                "wikitext": page_data["wikitext"],
                "params_declared": sorted({
                    str(arg.name).strip()
                    for arg in mwparserfromhell.parse(page_data["wikitext"] or "").filter_arguments()
                }),
                "doc_wikitext": doc_wikitext,
                "revision_id": page_data["revision_id"],
                "last_edited_at": page_data["last_edited_at"],
                "scraped_at": datetime.now(timezone.utc).isoformat(),
            }
            with out_file.open("w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, indent=2)
            summary["templates_written"] += 1
    except Exception as e:  # noqa: BLE001 — one wiki's templates must not kill the run
        summary["errors"].append(f"fatal in template scraping: {e}")
    return summary


def scrape_one_wiki(entry: dict, out_dir: Path, limit_per_wiki: int | None) -> dict:
    """Scrape a single wiki entirely. Returns a summary dict for the run log.

    Never raises — any failure is captured in the summary so one bad wiki
    doesn't kill the whole bulk run.
    """
    wiki_url = entry["wiki"]
    lang = entry.get("lang", "en")
    types = entry.get("types", list(DEFAULT_CATEGORIES.keys()))
    categories = {**DEFAULT_CATEGORIES, **entry.get("categories", {})}
    slug = entry.get("slug") or derive_wiki_slug(wiki_url)

    api_url = wiki_url.rstrip("/") + "/api.php"
    wiki_out_dir = out_dir / slug
    wiki_out_dir.mkdir(parents=True, exist_ok=True)
    out_path = wiki_out_dir / "lora_dataset_fandom.jsonl"

    stats_path = wiki_out_dir / "wiki_stats.json"
    if not stats_path.exists():
        wiki_stats = fetch_wiki_statistics(api_url)
        if wiki_stats is not None:
            with stats_path.open("w", encoding="utf-8") as f:
                json.dump(wiki_stats, f, ensure_ascii=False, indent=2)

    try:
        templates = resolve_infobox_templates(api_url, entry.get("infobox_templates"))
    except requests.RequestException as e:
        return {
            "wiki": wiki_url,
            "slug": slug,
            "written_this_run": 0,
            "total_written": len(load_already_scraped_titles(out_path)),
            "errors": [f"fatal: infobox template resolution failed: {e}"],
            "out_path": str(out_path),
        }

    template_summary = scrape_infobox_templates(api_url, wiki_out_dir, templates)

    already_scraped = load_already_scraped_titles(out_path)
    written_this_run = 0
    total_written = len(already_scraped)
    errors: list[str] = []

    written_with_infobox = 0

    try:
        with out_path.open("a", encoding="utf-8") as out_file:
            for entity_type in types:
                if limit_per_wiki is not None and total_written >= limit_per_wiki:
                    break
                category = categories.get(entity_type, entity_type)
                try:
                    titles = fetch_category_members(api_url, category)
                except requests.RequestException as e:
                    errors.append(f"category '{category}' fetch failed: {e}")
                    continue

                if not titles:
                    errors.append(f"category '{category}' returned 0 results for type {entity_type}")
                    continue

                for title in titles:
                    if limit_per_wiki is not None and total_written >= limit_per_wiki:
                        break
                    if title in already_scraped:
                        continue
                    try:
                        record = scrape_page(api_url, title, entity_type, slug, lang, templates)
                    except requests.RequestException as e:
                        errors.append(f"page '{title}' fetch failed: {e}")
                        continue
                    if record is None:
                        continue
                    out_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                    out_file.flush()
                    already_scraped.add(title)
                    written_this_run += 1
                    total_written += 1
                    written_with_infobox += 1 if record["infobox_fields"] else 0
    except Exception as e:  # noqa: BLE001 — last-resort guard, one wiki must not kill the run
        errors.append(f"fatal: {e}")

    if written_this_run and not written_with_infobox:
        errors.append(zero_infobox_reason(templates))
    errors.extend(template_summary.get("errors", []))

    return {
        "wiki": wiki_url,
        "slug": slug,
        "written_this_run": written_this_run,
        "total_written": total_written,
        "templates_found": template_summary.get("templates_found", 0),
        "templates_written": template_summary.get("templates_written", 0),
        "errors": errors,
        "out_path": str(out_path),
    }


def reparse_one_wiki(entry: dict, out_dir: Path) -> dict:
    """Re-derive infobox_fields from the raw_wikitext already on disk.

    `raw_wikitext` is captured precisely so a better answer to "which template is
    the infobox" can be applied without rescraping any page. Only the template
    sources are fetched. Never raises.
    """
    slug = entry.get("slug") or derive_wiki_slug(entry["wiki"])
    out_path = out_dir / slug / "lora_dataset_fandom.jsonl"
    summary = {"wiki": entry["wiki"], "slug": slug, "errors": [], "out_path": str(out_path)}
    if not out_path.exists():
        summary["errors"].append("nothing on disk to reparse")
        return summary

    try:
        templates = resolve_infobox_templates(
            entry["wiki"].rstrip("/") + "/api.php", entry.get("infobox_templates")
        )
    except requests.RequestException as e:
        summary["errors"].append(f"fatal: infobox template resolution failed: {e}")
        return summary

    pages = filled_before = filled_after = 0
    tmp_path = out_path.with_suffix(".jsonl.tmp")
    try:
        with out_path.open("r", encoding="utf-8") as src, tmp_path.open("w", encoding="utf-8") as dst:
            for line in src:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                pages += 1
                filled_before += 1 if rec.get("infobox_fields") else 0
                wikitext = rec.get("raw_wikitext")
                if wikitext is not None:
                    rec["infobox_fields"] = parse_infobox(wikitext, templates)
                filled_after += 1 if rec.get("infobox_fields") else 0
                dst.write(json.dumps(rec, ensure_ascii=False) + "\n")
        tmp_path.replace(out_path)
    except Exception as e:  # noqa: BLE001 — one wiki must not kill the run
        tmp_path.unlink(missing_ok=True)
        summary["errors"].append(f"fatal: {e}")
        return summary

    if pages and not filled_after:
        summary["errors"].append(zero_infobox_reason(templates))
    summary.update(pages=pages, pages_with_infobox_before=filled_before,
                   pages_with_infobox_after=filled_after, infobox_templates=len(templates.names))
    return summary


# --------------------------------------------------------------------------
# Aggregate field/enum report
# --------------------------------------------------------------------------

def build_field_report(out_dir: Path) -> dict:
    """Walk every lora_dataset_fandom.jsonl under out_dir and aggregate infobox
    field usage per entity_type: how often each field appears, and a sample of
    the distinct values seen (capped) — this is the enum-discovery output.
    """
    # entity_type -> field_name -> Counter(value -> count)
    field_values: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    # entity_type -> total page count
    page_counts: Counter = Counter()
    # entity_type -> wiki_slug set (to show which wikis contributed)
    field_wikis: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))

    for jsonl_path in out_dir.glob("*/lora_dataset_fandom.jsonl"):
        with jsonl_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                etype = rec.get("entity_type", "UNKNOWN")
                slug = rec.get("wiki_slug", "unknown")
                page_counts[etype] += 1
                for field_name, value in rec.get("infobox_fields", {}).items():
                    norm_field = field_name.strip().lower()
                    norm_value = value.strip()
                    if not norm_value:
                        continue
                    field_values[etype][norm_field][norm_value] += 1
                    field_wikis[etype][norm_field].add(slug)

    report: dict = {"generated_at": datetime.now(timezone.utc).isoformat(), "entity_types": {}}

    for etype, fields in field_values.items():
        total_pages = page_counts[etype]
        field_summaries = {}
        for field_name, value_counts in fields.items():
            occurrence_count = sum(value_counts.values())
            distinct_values = len(value_counts)
            top_values = value_counts.most_common(MAX_SAMPLE_VALUES_PER_FIELD)
            field_summaries[field_name] = {
                "pages_with_field": occurrence_count,
                "coverage_pct": round(100 * occurrence_count / total_pages, 1) if total_pages else 0.0,
                "distinct_values_seen": distinct_values,
                "sample_values": [{"value": v, "count": c} for v, c in top_values],
                "seen_in_wikis": sorted(field_wikis[etype][field_name]),
                # Heuristic flag: looks enum-like if few distinct values relative to occurrences
                "looks_enum_like": distinct_values <= 12 and occurrence_count >= 5,
            }
        # sort fields by coverage descending — most common/useful fields first
        field_summaries = dict(
            sorted(field_summaries.items(), key=lambda kv: kv[1]["pages_with_field"], reverse=True)
        )
        report["entity_types"][etype] = {
            "total_pages": total_pages,
            "fields": field_summaries,
        }

    return report


def write_field_report_csv(report: dict, csv_path: Path) -> None:
    """Flat view: one row per (entity_type, field) for easy spreadsheet review."""
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "entity_type", "field", "coverage_pct", "pages_with_field",
            "total_pages", "distinct_values_seen", "looks_enum_like",
            "top_values",
        ])
        for etype, data in report["entity_types"].items():
            for field_name, stats in data["fields"].items():
                top_values_str = "; ".join(
                    f"{sv['value']} ({sv['count']})" for sv in stats["sample_values"][:8]
                )
                writer.writerow([
                    etype, field_name, stats["coverage_pct"], stats["pages_with_field"],
                    data["total_pages"], stats["distinct_values_seen"], stats["looks_enum_like"],
                    top_values_str,
                ])


def build_wiki_maturity_report(out_dir: Path) -> list[dict]:
    """Per-wiki (not per-field) breakdown: page count, avg content length, avg
    infobox fields filled per page. Content length is a rough maturity proxy —
    a wiki with short stub bodies (Hollow Star) reads very differently from
    one with long, dense entries (ACOTAR, Wheel of Time). Sorted by avg
    content length descending, so the spectrum is visible at a glance.
    """
    # slug -> stats accumulators
    stats: dict[str, dict] = defaultdict(lambda: {
        "page_count": 0,
        "total_content_chars": 0,
        "total_infobox_fields_filled": 0,
        "by_entity_type": Counter(),
    })

    for jsonl_path in out_dir.glob("*/lora_dataset_fandom.jsonl"):
        slug = jsonl_path.parent.name
        with jsonl_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                s = stats[slug]
                s["page_count"] += 1
                s["total_content_chars"] += len(rec.get("content", ""))
                filled = sum(1 for v in rec.get("infobox_fields", {}).values() if v.strip())
                s["total_infobox_fields_filled"] += filled
                s["by_entity_type"][rec.get("entity_type", "UNKNOWN")] += 1

    rows = []
    for slug, s in stats.items():
        page_count = s["page_count"]
        if page_count == 0:
            continue
        row = {
            "wiki_slug": slug,
            "page_count_sampled": page_count,
            "avg_content_chars": round(s["total_content_chars"] / page_count, 1),
            "avg_infobox_fields_filled": round(s["total_infobox_fields_filled"] / page_count, 2),
            "by_entity_type": dict(s["by_entity_type"]),
        }
        stats_path = out_dir / slug / "wiki_stats.json"
        if stats_path.exists():
            try:
                with stats_path.open("r", encoding="utf-8") as f:
                    wiki_stats = json.load(f)
                row["wiki_total_articles"] = wiki_stats.get("articles")
                row["wiki_total_edits"] = wiki_stats.get("edits")
                row["wiki_total_users"] = wiki_stats.get("users")
            except (json.JSONDecodeError, OSError):
                pass
        rows.append(row)

    rows.sort(key=lambda r: r["avg_content_chars"], reverse=True)
    return rows


def write_wiki_maturity_csv(rows: list[dict], csv_path: Path) -> None:
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "wiki_slug", "page_count_sampled", "wiki_total_articles", "wiki_total_edits",
            "wiki_total_users", "avg_content_chars", "avg_infobox_fields_filled",
            "by_entity_type",
        ])
        for row in rows:
            by_type_str = "; ".join(f"{k}={v}" for k, v in row["by_entity_type"].items())
            writer.writerow([
                row["wiki_slug"], row["page_count_sampled"],
                row.get("wiki_total_articles", ""), row.get("wiki_total_edits", ""),
                row.get("wiki_total_users", ""),
                row["avg_content_chars"], row["avg_infobox_fields_filled"], by_type_str,
            ])


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def load_wikis_config(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, list):
        raise ValueError("wikis config must be a YAML list of {wiki, lang?, types?, slug?} entries")
    for entry in data:
        if "wiki" not in entry:
            raise ValueError(f"entry missing required 'wiki' key: {entry}")
    return data


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Bulk-scrape many fandom.com wikis + aggregate field report.")
    parser.add_argument("--wikis", required=True, help="Path to YAML file listing wikis to scrape")
    parser.add_argument("--out-dir", required=True, help="Directory to write per-wiki jsonl + reports")
    parser.add_argument("--limit-per-wiki", type=int, default=None, help="Max pages to scrape per wiki")
    parser.add_argument("--workers", type=int, default=3, help="Number of wikis to scrape in parallel")
    parser.add_argument("--reparse", action="store_true",
                        help="Re-derive infobox_fields from the raw_wikitext already on disk "
                             "and rebuild the reports. Fetches template sources only; no page "
                             "is rescraped.")
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    wikis = load_wikis_config(Path(args.wikis))
    print(f"Loaded {len(wikis)} wikis from {args.wikis}")

    if args.reparse:
        reparse_corpus(wikis, out_dir, args.workers)
        write_reports(out_dir)
        return

    run_log_path = out_dir / "run_log.jsonl"
    summaries = []

    with ThreadPoolExecutor(max_workers=args.workers) as executor, \
            run_log_path.open("a", encoding="utf-8") as run_log:
        futures = {
            executor.submit(scrape_one_wiki, entry, out_dir, args.limit_per_wiki): entry
            for entry in wikis
        }
        for future in as_completed(futures):
            entry = futures[future]
            try:
                summary = future.result()
            except Exception as e:  # noqa: BLE001 — guard against unexpected worker crash
                summary = {"wiki": entry.get("wiki"), "errors": [f"unhandled: {e}"]}
            summaries.append(summary)
            run_log.write(json.dumps(summary, ensure_ascii=False) + "\n")
            run_log.flush()
            status = "OK" if not summary.get("errors") else f"OK w/ {len(summary['errors'])} warning(s)"
            print(f"[{status}] {summary.get('wiki')} — {summary.get('written_this_run', 0)} new pages "
                  f"(total {summary.get('total_written', 0)}), "
                  f"{summary.get('templates_written', 0)} infobox templates captured "
                  f"(of {summary.get('templates_found', 0)} found)")
            for err in summary.get("errors", [])[:5]:
                print(f"    ! {err}")

    total_new = sum(s.get("written_this_run", 0) for s in summaries)
    total_all = sum(s.get("total_written", 0) for s in summaries)
    total_templates = sum(s.get("templates_written", 0) for s in summaries)
    print(f"\nDone scraping. {total_new} new pages this run, {total_all} total across all wikis, "
          f"{total_templates} infobox template definitions captured.")

    write_reports(out_dir)


def reparse_corpus(wikis: list[dict], out_dir: Path, workers: int) -> None:
    """Apply the current infobox identification to the corpus already on disk."""
    summaries = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(reparse_one_wiki, entry, out_dir): entry for entry in wikis}
        for future in as_completed(futures):
            entry = futures[future]
            try:
                summary = future.result()
            except Exception as e:  # noqa: BLE001 — guard against unexpected worker crash
                summary = {"wiki": entry.get("wiki"), "errors": [f"unhandled: {e}"]}
            summaries.append(summary)
            before = summary.get("pages_with_infobox_before", 0)
            after = summary.get("pages_with_infobox_after", 0)
            print(f"[{summary.get('slug')}] {summary.get('pages', 0)} pages, "
                  f"infobox parsed {before} -> {after} "
                  f"({summary.get('infobox_templates', 0)} infobox templates on wiki)")
            for err in summary.get("errors", [])[:5]:
                print(f"    ! {err}")

    pages = sum(s.get("pages", 0) for s in summaries)
    before = sum(s.get("pages_with_infobox_before", 0) for s in summaries)
    after = sum(s.get("pages_with_infobox_after", 0) for s in summaries)
    print(f"\nReparsed {pages} pages across {len(summaries)} wikis. "
          f"Pages with a parsed infobox: {before} -> {after}"
          + (f" ({100 * before / pages:.0f}% -> {100 * after / pages:.0f}%)" if pages else ""))


def write_reports(out_dir: Path) -> None:
    print("Building aggregate field report...")
    report = build_field_report(out_dir)
    report_json_path = out_dir / "field_report.json"
    report_csv_path = out_dir / "field_report.csv"
    with report_json_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    write_field_report_csv(report, report_csv_path)

    print(f"Field report written to {report_json_path} and {report_csv_path}")
    for etype, data in report["entity_types"].items():
        print(f"  {etype}: {data['total_pages']} pages, {len(data['fields'])} distinct infobox fields")

    print("\nBuilding per-wiki maturity report (Hollow Star <-> ACOTAR spectrum)...")
    maturity_rows = build_wiki_maturity_report(out_dir)
    maturity_json_path = out_dir / "wiki_maturity_report.json"
    maturity_csv_path = out_dir / "wiki_maturity_report.csv"
    with maturity_json_path.open("w", encoding="utf-8") as f:
        json.dump(maturity_rows, f, ensure_ascii=False, indent=2)
    write_wiki_maturity_csv(maturity_rows, maturity_csv_path)

    print(f"Maturity report written to {maturity_json_path} and {maturity_csv_path}")
    print("  (sorted richest -> stubbiest by avg content length per page)")
    for row in maturity_rows[:5]:
        print(f"  {row['wiki_slug']}: {row['page_count_sampled']} pages, "
              f"avg {row['avg_content_chars']:.0f} chars, "
              f"avg {row['avg_infobox_fields_filled']:.1f} infobox fields filled")
    if len(maturity_rows) > 5:
        print("  ...")
        for row in maturity_rows[-3:]:
            print(f"  {row['wiki_slug']}: {row['page_count_sampled']} pages, "
                  f"avg {row['avg_content_chars']:.0f} chars, "
                  f"avg {row['avg_infobox_fields_filled']:.1f} infobox fields filled")


if __name__ == "__main__":
    main()