"""Discover fandom.com wikis for a list of book/series titles.

There is no reliable modern API to enumerate "all fandom wikis" — Special:NewWikis
is gone, and the old Wikia-era wkdomains endpoint is dead/unreliable post-migration
to fandom.com. This script instead generates candidate slugs from each title and
VERIFIES them against the documented MediaWiki API (action=query&meta=siteinfo),
same API your existing scrapers already depend on. No fragile HTML scraping,
no undocumented endpoints.

For each title, it also checks whether Characters/Locations/Organizations
categories exist with real members, so a "found" wiki is one you can actually
scrape with scrape_fandom_bulk.py — not just a wiki that resolves.

Usage:
    python discover_fandom_wikis.py --titles-file titles.txt --out wikis.discovered.yaml

titles.txt: one book/series title per line, e.g.:
    Throne of Glass
    A Court of Thorns and Roses
    Le Jeu de l'Ange

Outputs:
    {out}                       — wikis.yaml-compatible file, ready for scrape_fandom_bulk.py
    {out}.not_found.txt         — titles with no verified candidate (needs manual lookup)
    {out}.report.json           — full detail per title: every candidate tried and why it did/didn't match
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import requests
import yaml

RATE_LIMIT_SECONDS = 1
STOPWORDS = {"the", "a", "an", "of", "and", "le", "la", "les", "de", "des", "du"}
DEFAULT_CATEGORIES = {
    "PERSON": "Characters",
    "PLACE": "Locations",
    "ORG": "Organizations",
}
MIN_CATEGORY_MEMBERS = 3  # a wiki with 1-2 character pages isn't worth scraping


def slugify_variants(title: str) -> list[str]:
    """Generate candidate fandom.com slugs from a title, most-likely-first."""
    words = re.findall(r"[A-Za-zÀ-ÿ0-9']+", title.lower())
    if not words:
        return []

    full_squash = "".join(words)
    no_stopwords_squash = "".join(w for w in words if w not in STOPWORDS)
    hyphenated = "-".join(words)
    acronym = "".join(w[0] for w in words if w not in STOPWORDS)

    candidates = [full_squash, no_stopwords_squash, hyphenated]
    # Acronym only worth trying for multi-word titles (avoid 1-letter junk)
    if len(acronym) >= 3:
        candidates.append(acronym)

    # de-dupe, preserve order
    seen = set()
    ordered = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            ordered.append(c)
    return ordered


def check_siteinfo(slug: str) -> dict | None:
    """Verify a candidate slug resolves to a real fandom wiki. Returns siteinfo or None."""
    api_url = f"https://{slug}.fandom.com/api.php"
    try:
        resp = requests.get(
            api_url,
            params={"action": "query", "meta": "siteinfo", "format": "json"},
            timeout=15,
        )
        time.sleep(RATE_LIMIT_SECONDS)
        if resp.status_code != 200:
            return None
        data = resp.json()
        general = data.get("query", {}).get("general")
        if not general:
            return None
        return general
    except (requests.RequestException, json.JSONDecodeError):
        return None


def check_category_counts(slug: str) -> dict:
    """Return {entity_type: member_count} for the standard categories on this wiki."""
    api_url = f"https://{slug}.fandom.com/api.php"
    counts = {}
    for entity_type, category in DEFAULT_CATEGORIES.items():
        try:
            resp = requests.get(
                api_url,
                params={
                    "action": "query",
                    "list": "categorymembers",
                    "cmtitle": f"Category:{category}",
                    "cmlimit": "50",  # just enough to judge viability, not a full fetch
                    "format": "json",
                },
                timeout=15,
            )
            time.sleep(RATE_LIMIT_SECONDS)
            data = resp.json()
            members = data.get("query", {}).get("categorymembers", [])
            counts[entity_type] = len(members)
        except (requests.RequestException, json.JSONDecodeError):
            counts[entity_type] = 0
    return counts


def discover_title(title: str) -> dict:
    """Try every candidate slug for a title, return the best verified match + full trace."""
    candidates = slugify_variants(title)
    trace = []
    best_match = None

    for slug in candidates:
        siteinfo = check_siteinfo(slug)
        if siteinfo is None:
            trace.append({"slug": slug, "resolved": False})
            continue

        counts = check_category_counts(slug)
        total_members = sum(counts.values())
        trace.append({
            "slug": slug,
            "resolved": True,
            "sitename": siteinfo.get("sitename"),
            "lang": siteinfo.get("lang"),
            "category_counts": counts,
            "viable": total_members >= MIN_CATEGORY_MEMBERS,
        })

        if total_members >= MIN_CATEGORY_MEMBERS and best_match is None:
            best_match = {
                "wiki": f"https://{slug}.fandom.com",
                "slug": slug,
                "lang": siteinfo.get("lang", "en"),
                "sitename": siteinfo.get("sitename"),
                "category_counts": counts,
            }
            # Keep going isn't necessary — first viable candidate wins (they're
            # ordered most-likely-first), but we still record remaining trace
            # entries below for the report if you want to sanity-check.

    return {"title": title, "match": best_match, "candidates_tried": trace}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Discover fandom.com wikis for a list of book/series titles.")
    parser.add_argument("--titles-file", required=True, help="Text file, one title per line")
    parser.add_argument("--out", required=True, help="Output wikis.yaml path (compatible with scrape_fandom_bulk.py)")
    args = parser.parse_args(argv)

    titles = [
        line.strip() for line in Path(args.titles_file).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    print(f"Discovering wikis for {len(titles)} titles...")

    results = []
    for title in titles:
        result = discover_title(title)
        results.append(result)
        if result["match"]:
            m = result["match"]
            counts_str = ", ".join(f"{k}={v}" for k, v in m["category_counts"].items())
            print(f"  FOUND  {title} -> {m['wiki']}  ({counts_str})")
        else:
            print(f"  MISS   {title} — no candidate slug resolved to a viable wiki")

    found = [r for r in results if r["match"]]
    missing = [r for r in results if not r["match"]]

    out_path = Path(args.out)
    wikis_yaml = [
        {"wiki": r["match"]["wiki"], "lang": r["match"]["lang"]}
        for r in found
    ]
    with out_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(wikis_yaml, f, allow_unicode=True, sort_keys=False)

    not_found_path = Path(str(out_path) + ".not_found.txt")
    with not_found_path.open("w", encoding="utf-8") as f:
        for r in missing:
            f.write(r["title"] + "\n")

    report_path = Path(str(out_path) + ".report.json")
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n{len(found)}/{len(titles)} titles matched a wiki.")
    print(f"Wikis config: {out_path}")
    print(f"Titles needing manual lookup: {not_found_path}")
    print(f"Full trace (every candidate tried, useful to debug misses): {report_path}")


if __name__ == "__main__":
    main()