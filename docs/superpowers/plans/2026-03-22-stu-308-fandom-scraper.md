# STU-308 Fandom Scraper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `scripts/scrape_fandom.py` — a CLI script that scrapes fandom.com wikis via the MediaWiki API and writes an intermediate JSONL dataset of entity pages (PERSON, PLACE, ORG).

**Architecture:** Standalone script with four internal functions (discover, fetch, parse, write) called from a `main()`. Uses `mwparserfromhell` for wikitext parsing. Output is intermediate JSONL (not yet aligned to STU-304 training format).

**Tech Stack:** Python 3.11+, `mwparserfromhell`, `requests`, `argparse`, `pytest` + `unittest.mock`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `scripts/scrape_fandom.py` | Create | CLI entrypoint + all scraper logic |
| `tests/test_scrape_fandom.py` | Create | Unit tests mocking the MediaWiki API |
| `pyproject.toml` | Modify | Add `mwparserfromhell` and `requests` to dependencies |

---

## Task 1: Add dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Check if `requests` is already a dependency**

```bash
grep "requests" pyproject.toml
```

If `requests` is already listed, only add `mwparserfromhell`. Otherwise add both.

- [ ] **Step 2: Add missing dependencies to `pyproject.toml`**

In `pyproject.toml`, find the `dependencies` list and add:
```toml
dependencies = [
    ...existing deps...,
    "mwparserfromhell>=0.6",
    "requests>=2.31",
]
```

- [ ] **Step 3: Install the new dependencies**

```bash
pip install -e ".[dev]"
```

Expected: installs without errors.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "feat(stu-308): add mwparserfromhell and requests dependencies"
```

---

## Task 2: Infobox parsing

**Files:**
- Create: `scripts/scrape_fandom.py` (skeleton + `parse_infobox`)
- Create: `tests/test_scrape_fandom.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_scrape_fandom.py`:

```python
"""Tests for scripts/scrape_fandom.py."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.scrape_fandom import parse_infobox


WIKITEXT_WITH_INFOBOX = """\
{{Infobox character
| name    = Celaena Sardothien
| species = Human
| status  = Alive
| gender  = Female
}}
== Biography ==
Celaena is an assassin.
"""

WIKITEXT_NO_INFOBOX = """\
== Biography ==
A short article with no infobox.
"""


def test_parse_infobox_extracts_fields():
    result = parse_infobox(WIKITEXT_WITH_INFOBOX)
    assert result["name"] == "Celaena Sardothien"
    assert result["species"] == "Human"
    assert result["status"] == "Alive"


def test_parse_infobox_returns_empty_dict_when_absent():
    result = parse_infobox(WIKITEXT_NO_INFOBOX)
    assert result == {}


def test_parse_infobox_strips_wikitext_from_values():
    wikitext = """\
{{Infobox character
| home = [[Rifthold]]
}}
"""
    result = parse_infobox(wikitext)
    assert result["home"] == "Rifthold"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_scrape_fandom.py -v
```

Expected: `ImportError` — `scrape_fandom` does not exist yet.

- [ ] **Step 3: Create `scripts/scrape_fandom.py` with `parse_infobox`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_scrape_fandom.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/scrape_fandom.py tests/test_scrape_fandom.py
git commit -m "feat(stu-308): add parse_infobox with tests"
```

---

## Task 3: Body parsing

**Files:**
- Modify: `scripts/scrape_fandom.py` (add `parse_body`)
- Modify: `tests/test_scrape_fandom.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_scrape_fandom.py`:

```python
from scripts.scrape_fandom import parse_body


WIKITEXT_BODY = """\
{{Infobox character
| name = Celaena
}}
== Biography ==
Celaena Sardothien is a famous assassin.<ref>Source</ref>

She lives in [[Rifthold]].

== Relationships ==
Her mentor is [[Arobynn Hamel]].

[[File:Celaena.png|thumb|Celaena]]
"""


def test_parse_body_removes_templates():
    result = parse_body(WIKITEXT_BODY)
    assert "{{" not in result
    assert "}}" not in result


def test_parse_body_converts_headings():
    result = parse_body(WIKITEXT_BODY)
    assert "## Biography" in result
    assert "## Relationships" in result


def test_parse_body_removes_refs():
    result = parse_body(WIKITEXT_BODY)
    assert "<ref>" not in result
    assert "Source" not in result


def test_parse_body_removes_file_links():
    result = parse_body(WIKITEXT_BODY)
    assert "File:" not in result
    assert "Celaena.png" not in result


def test_parse_body_keeps_plain_text():
    result = parse_body(WIKITEXT_BODY)
    assert "Celaena Sardothien is a famous assassin" in result


def test_parse_body_is_stub_when_short():
    result = parse_body("== Section ==\nShort.")
    assert len(result) < 200
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_scrape_fandom.py::test_parse_body_removes_templates -v
```

Expected: `ImportError` — `parse_body` not defined yet.

- [ ] **Step 3: Implement `parse_body` in `scripts/scrape_fandom.py`**

Add after `parse_infobox`:

```python
import re


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
```

- [ ] **Step 4: Run the body tests**

```bash
pytest tests/test_scrape_fandom.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/scrape_fandom.py tests/test_scrape_fandom.py
git commit -m "feat(stu-308): add parse_body with tests"
```

---

## Task 4: Redirect and stub detection

**Files:**
- Modify: `scripts/scrape_fandom.py` (add `is_redirect`, `is_stub`)
- Modify: `tests/test_scrape_fandom.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_scrape_fandom.py`:

```python
from scripts.scrape_fandom import is_redirect, is_stub


def test_is_redirect_detects_uppercase():
    assert is_redirect("#REDIRECT [[Celaena Sardothien]]") is True


def test_is_redirect_detects_lowercase():
    assert is_redirect("#redirect [[Celaena Sardothien]]") is True


def test_is_redirect_returns_false_for_normal_page():
    assert is_redirect("== Biography ==\nSome content.") is False


def test_is_stub_when_body_short():
    assert is_stub("Too short.") is True


def test_is_stub_when_body_long_enough():
    assert is_stub("x" * 200) is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_scrape_fandom.py::test_is_redirect_detects_uppercase -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement `is_redirect` and `is_stub`**

Add to `scripts/scrape_fandom.py`:

```python
def is_redirect(wikitext: str) -> bool:
    """Return True if the wikitext is a redirect page."""
    return wikitext.strip().lower().startswith("#redirect")


def is_stub(body: str) -> bool:
    """Return True if the cleaned body text is too short (< 200 chars)."""
    return len(body) < 200
```

- [ ] **Step 4: Run all tests**

```bash
pytest tests/test_scrape_fandom.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/scrape_fandom.py tests/test_scrape_fandom.py
git commit -m "feat(stu-308): add is_redirect and is_stub helpers"
```

---

## Task 5: MediaWiki API fetch functions

**Files:**
- Modify: `scripts/scrape_fandom.py` (add `fetch_category_members`, `fetch_wikitext`)
- Modify: `tests/test_scrape_fandom.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_scrape_fandom.py`:

```python
from unittest.mock import patch, MagicMock
from scripts.scrape_fandom import fetch_category_members, fetch_wikitext

API_URL = "https://throneofglass.fandom.com/api.php"


def _mock_response(data: dict) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.json.return_value = data
    mock_resp.raise_for_status.return_value = None
    return mock_resp


def test_fetch_category_members_returns_titles():
    page_data = {
        "query": {
            "categorymembers": [
                {"title": "Celaena Sardothien"},
                {"title": "Dorian Havilliard"},
            ]
        }
    }
    with patch("scripts.scrape_fandom.requests.get", return_value=_mock_response(page_data)) as mock_get:
        with patch("scripts.scrape_fandom.time.sleep"):
            titles = fetch_category_members(API_URL, "Characters")
    assert titles == ["Celaena Sardothien", "Dorian Havilliard"]


def test_fetch_category_members_paginates():
    page1 = {
        "query": {"categorymembers": [{"title": "Page A"}]},
        "continue": {"cmcontinue": "token_abc", "continue": "-||"},
    }
    page2 = {
        "query": {"categorymembers": [{"title": "Page B"}]},
    }
    responses = [_mock_response(page1), _mock_response(page2)]
    with patch("scripts.scrape_fandom.requests.get", side_effect=responses):
        with patch("scripts.scrape_fandom.time.sleep"):
            titles = fetch_category_members(API_URL, "Characters")
    assert titles == ["Page A", "Page B"]


def test_fetch_wikitext_returns_content():
    response_data = {
        "query": {
            "pages": {
                "123": {
                    "revisions": [{"*": "{{Infobox character}}\n== Bio ==\nContent here."}]
                }
            }
        }
    }
    with patch("scripts.scrape_fandom.requests.get", return_value=_mock_response(response_data)):
        with patch("scripts.scrape_fandom.time.sleep"):
            result = fetch_wikitext(API_URL, "Celaena Sardothien")
    assert "Infobox character" in result


def test_fetch_wikitext_returns_none_for_missing_page():
    response_data = {"query": {"pages": {"-1": {}}}}
    with patch("scripts.scrape_fandom.requests.get", return_value=_mock_response(response_data)):
        with patch("scripts.scrape_fandom.time.sleep"):
            result = fetch_wikitext(API_URL, "Nonexistent Page")
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_scrape_fandom.py::test_fetch_category_members_returns_titles -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement `fetch_category_members` and `fetch_wikitext`**

Add to `scripts/scrape_fandom.py`:

```python
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
```

- [ ] **Step 4: Run all tests**

```bash
pytest tests/test_scrape_fandom.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/scrape_fandom.py tests/test_scrape_fandom.py
git commit -m "feat(stu-308): add fetch_category_members and fetch_wikitext"
```

---

## Task 6: `wiki_slug` derivation

**Files:**
- Modify: `scripts/scrape_fandom.py` (add `derive_wiki_slug`)
- Modify: `tests/test_scrape_fandom.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_scrape_fandom.py`:

```python
from scripts.scrape_fandom import derive_wiki_slug


def test_derive_wiki_slug_strips_fandom_suffix():
    assert derive_wiki_slug("https://throneofglass.fandom.com") == "throneofglass"


def test_derive_wiki_slug_with_trailing_slash():
    assert derive_wiki_slug("https://throneofglass.fandom.com/") == "throneofglass"
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_scrape_fandom.py::test_derive_wiki_slug_strips_fandom_suffix -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement `derive_wiki_slug`**

Add to `scripts/scrape_fandom.py`:

```python
def derive_wiki_slug(wiki_url: str) -> str:
    """Derive wiki slug from fandom URL. e.g. https://throneofglass.fandom.com → throneofglass"""
    host = urlparse(wiki_url).hostname or ""
    return host.replace(".fandom.com", "")
```

- [ ] **Step 4: Run all tests**

```bash
pytest tests/test_scrape_fandom.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/scrape_fandom.py tests/test_scrape_fandom.py
git commit -m "feat(stu-308): add derive_wiki_slug"
```

---

## Task 7: `main()` and CLI wiring

**Files:**
- Modify: `scripts/scrape_fandom.py` (add `scrape_page`, `main`)

- [ ] **Step 1: Write the integration test**

Add to `tests/test_scrape_fandom.py`:

```python
import tempfile
from pathlib import Path
from scripts.scrape_fandom import main


FAKE_CATEGORY_RESPONSE = {
    "query": {
        "categorymembers": [
            {"title": "Celaena Sardothien"},
        ]
    }
}

FAKE_PAGE_RESPONSE = {
    "query": {
        "pages": {
            "1": {
                "revisions": [{
                    "*": (
                        "{{Infobox character\n"
                        "| species = Human\n"
                        "| status  = Alive\n"
                        "}}\n"
                        "== Biography ==\n"
                        + "Celaena Sardothien is a world-famous assassin. " * 10
                    )
                }]
            }
        }
    }
}


def test_main_writes_jsonl(tmp_path):
    out_file = tmp_path / "output.jsonl"
    responses = [
        _mock_response(FAKE_CATEGORY_RESPONSE),  # discover PERSON
        _mock_response(FAKE_PAGE_RESPONSE),       # fetch page
    ]
    with patch("scripts.scrape_fandom.requests.get", side_effect=responses):
        with patch("scripts.scrape_fandom.time.sleep"):
            main([
                "--wiki", "https://throneofglass.fandom.com",
                "--types", "PERSON",
                "--lang", "en",
                "--out", str(out_file),
            ])
    assert out_file.exists()
    lines = out_file.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["source"] == "fandom"
    assert record["wiki_slug"] == "throneofglass"
    assert record["page_title"] == "Celaena Sardothien"
    assert record["entity_type"] == "PERSON"
    assert record["infobox_fields"]["species"] == "Human"
    assert record["content_lang"] == "en"
    assert "scraped_at" in record


def test_main_skips_redirects(tmp_path):
    out_file = tmp_path / "output.jsonl"
    redirect_response = {
        "query": {
            "pages": {"1": {"revisions": [{"*": "#REDIRECT [[Celaena Sardothien]]"}]}}
        }
    }
    responses = [
        _mock_response(FAKE_CATEGORY_RESPONSE),
        _mock_response(redirect_response),
    ]
    with patch("scripts.scrape_fandom.requests.get", side_effect=responses):
        with patch("scripts.scrape_fandom.time.sleep"):
            main([
                "--wiki", "https://throneofglass.fandom.com",
                "--types", "PERSON",
                "--out", str(out_file),
            ])
    # File may not exist or be empty — either is correct
    if out_file.exists():
        assert out_file.read_text().strip() == ""


def test_main_skips_stubs(tmp_path):
    out_file = tmp_path / "output.jsonl"
    stub_response = {
        "query": {
            "pages": {"1": {"revisions": [{"*": "{{Infobox character}}\n== Bio ==\nToo short."}]}}
        }
    }
    responses = [
        _mock_response(FAKE_CATEGORY_RESPONSE),
        _mock_response(stub_response),
    ]
    with patch("scripts.scrape_fandom.requests.get", side_effect=responses):
        with patch("scripts.scrape_fandom.time.sleep"):
            main([
                "--wiki", "https://throneofglass.fandom.com",
                "--types", "PERSON",
                "--out", str(out_file),
            ])
    if out_file.exists():
        assert out_file.read_text().strip() == ""


def test_main_respects_limit(tmp_path):
    out_file = tmp_path / "output.jsonl"
    category_response = {
        "query": {
            "categorymembers": [
                {"title": "Page A"},
                {"title": "Page B"},
                {"title": "Page C"},
            ]
        }
    }
    long_body = "Some content about a character. " * 20
    page_response = {
        "query": {
            "pages": {
                "1": {"revisions": [{"*": f"{{{{Infobox character}}}}\n== Bio ==\n{long_body}"}]}
            }
        }
    }
    responses = (
        [_mock_response(category_response)]
        + [_mock_response(page_response)] * 3
    )
    with patch("scripts.scrape_fandom.requests.get", side_effect=responses):
        with patch("scripts.scrape_fandom.time.sleep"):
            main([
                "--wiki", "https://throneofglass.fandom.com",
                "--types", "PERSON",
                "--limit", "2",
                "--out", str(out_file),
            ])
    lines = out_file.read_text().strip().splitlines()
    assert len(lines) == 2
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_scrape_fandom.py::test_main_writes_jsonl -v
```

Expected: `ImportError` — `main` not defined.

- [ ] **Step 3: Implement `scrape_page` and `main`**

Add to `scripts/scrape_fandom.py`:

```python
def scrape_page(
    api_url: str,
    title: str,
    entity_type: str,
    wiki_slug: str,
    lang: str,
) -> dict | None:
    """Fetch, parse, and filter a single wiki page. Returns record dict or None."""
    wikitext = fetch_wikitext(api_url, title)
    if wikitext is None:
        return None
    if is_redirect(wikitext):
        return None
    infobox = parse_infobox(wikitext)
    body = parse_body(wikitext)
    if is_stub(body):
        return None
    return {
        "source": "fandom",
        "wiki_slug": wiki_slug,
        "page_title": title,
        "entity_type": entity_type,
        "infobox_fields": infobox,
        "content": body,
        "content_lang": lang,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Scrape a fandom.com wiki via MediaWiki API.")
    parser.add_argument("--wiki", required=True, help="Base URL of the fandom wiki")
    parser.add_argument("--types", nargs="+", default=["PERSON", "PLACE", "ORG"])
    parser.add_argument("--lang", default="en", choices=["en", "fr"])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    api_url = args.wiki.rstrip("/") + "/api.php"
    wiki_slug = derive_wiki_slug(args.wiki)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    with out_path.open("w", encoding="utf-8") as out_file:
        for entity_type in args.types:
            if args.limit is not None and written >= args.limit:
                break
            category = DEFAULT_CATEGORIES.get(entity_type, entity_type)
            titles = fetch_category_members(api_url, category)
            if not titles:
                print(f"WARNING: category '{category}' returned 0 results for type {entity_type}")
                continue
            for title in titles:
                if args.limit is not None and written >= args.limit:
                    break
                record = scrape_page(api_url, title, entity_type, wiki_slug, args.lang)
                if record is None:
                    continue
                out_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                written += 1
                print(f"[{written}] {entity_type} — {title}")

    print(f"Done. {written} pages written to {out_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run all tests**

```bash
pytest tests/test_scrape_fandom.py -v
```

Expected: all PASS.

- [ ] **Step 5: Run the full test suite to check for regressions**

```bash
pytest -q
```

Expected: all existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/scrape_fandom.py tests/test_scrape_fandom.py
git commit -m "feat(stu-308): add main() CLI and integration tests"
```

---

## Task 8: Smoke test against the real API

> This task is manual — it requires a live internet connection and should not be run in CI.

- [ ] **Step 1: Run with a small limit against the real Throne of Glass wiki**

```bash
python scripts/scrape_fandom.py \
    --wiki https://throneofglass.fandom.com \
    --types PERSON \
    --lang en \
    --limit 5 \
    --out /tmp/tog_smoke_test.jsonl
```

Expected:
- 5 lines written to `/tmp/tog_smoke_test.jsonl`
- Each line is valid JSON with `infobox_fields`, `content`, `entity_type`, etc.
- No Python errors or HTTP exceptions

- [ ] **Step 2: Inspect a record**

```bash
python3 -c "
import json
with open('/tmp/tog_smoke_test.jsonl') as f:
    for line in f:
        r = json.loads(line)
        print(r['page_title'], '|', r['entity_type'], '|', len(r['content']), 'chars')
        print('  infobox:', list(r['infobox_fields'].keys())[:5])
        print()
"
```

Expected: readable output with character names, infobox keys (species, status, etc.), and non-empty content.

- [ ] **Step 3: Final commit if any tweaks were needed**

```bash
git add scripts/scrape_fandom.py
git commit -m "fix(stu-308): smoke test corrections" # only if needed
```
