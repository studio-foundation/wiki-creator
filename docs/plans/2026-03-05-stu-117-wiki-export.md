# STU-117 : Wiki Export Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ajouter un stage `wiki-export` au pipeline qui convertit l'output Markdown de `wiki-generation` en un dossier `output/wiki/` prêt à importer dans Fandom (wikitext, templates d'infobox, catégories, Main_Page).

**Architecture:** Stage script executor `wiki-export` ajouté en 8e position dans le pipeline. La logique de conversion est dans `wiki_creator/md2wiki.py` (module Python testable). `scripts/wiki_export.py` orchestre la génération des fichiers. `writer.agent.yaml` est modifié pour sortir `infobox_fields` structuré + body séparé.

**Tech Stack:** Python stdlib uniquement (re, pathlib, json, yaml). Pas de dépendance externe pour la conversion.

**Design doc:** `docs/plans/2026-03-05-stu-117-wiki-export-design.md`

---

### Task 1 : Worktree + branch

**Files:**
- (pas de fichier créé)

**Step 1: Créer le worktree**

```bash
git worktree add .worktrees/stu-117-wiki-export -b feat/stu-117-wiki-export
```

**Step 2: Vérifier**

```bash
git worktree list
```

Expected : la nouvelle entrée apparaît.

**Step 3: Ouvrir le worktree dans le terminal pour la suite**

```bash
cd .worktrees/stu-117-wiki-export
```

---

### Task 2 : Module `md2wiki` — `convert()` avec TDD

**Files:**
- Create: `wiki_creator/md2wiki.py`
- Create: `tests/test_md2wiki.py`

**Step 1: Créer le fichier de test**

```python
# tests/test_md2wiki.py
import pytest
from wiki_creator.md2wiki import convert


def test_h2_heading():
    assert convert("## Biographie") == "== Biographie =="


def test_h3_heading():
    assert convert("### Première apparition") == "=== Première apparition ==="


def test_h4_heading():
    assert convert("#### Détail") == "==== Détail ===="


def test_bold():
    assert convert("**texte**") == "'''texte'''"


def test_italic():
    assert convert("*texte*") == "''texte''"


def test_cross_ref_passthrough():
    """[[Nom]] must not be altered."""
    assert convert("[[David Martín]]") == "[[David Martín]]"


def test_category_passthrough():
    assert convert("[[Category:Personnages]]") == "[[Category:Personnages]]"


def test_blockquote_removed():
    """Blockquote lines (spoiler warnings) are stripped."""
    md = "> ⚠️ **Spoilers** — Cette section révèle des événements."
    assert convert(md).strip() == ""


def test_multiline():
    md = "## Biographie\n\n**Pedro Vidal** rencontre [[David Martín]]."
    expected = "== Biographie ==\n\n'''Pedro Vidal''' rencontre [[David Martín]]."
    assert convert(md) == expected


def test_italic_not_bold():
    """Single asterisk = italic, double = bold. No cross-contamination."""
    assert convert("*seul*") == "''seul''"
    assert convert("**double**") == "'''double'''"
```

**Step 2: Lancer les tests pour vérifier l'échec**

```bash
pytest tests/test_md2wiki.py -v
```

Expected : `ImportError` ou `ModuleNotFoundError` — le module n'existe pas encore.

**Step 3: Implémenter `wiki_creator/md2wiki.py` — fonction `convert`**

```python
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
```

**Step 4: Lancer les tests**

```bash
pytest tests/test_md2wiki.py -v
```

Expected : tous les tests PASS.

**Step 5: Commit**

```bash
git add wiki_creator/md2wiki.py tests/test_md2wiki.py
git commit -m "feat(stu-117): add md2wiki.convert() with tests"
```

---

### Task 3 : Module `md2wiki` — `make_infobox_call()` avec TDD

**Files:**
- Modify: `wiki_creator/md2wiki.py`
- Modify: `tests/test_md2wiki.py`

**Step 1: Ajouter les tests dans `tests/test_md2wiki.py`**

```python
from wiki_creator.md2wiki import make_infobox_call


def test_infobox_person():
    fields = {"name": "David Martín", "status": "Vivant", "occupation": "Écrivain"}
    result = make_infobox_call("PERSON", fields)
    assert result.startswith("{{Infobox character")
    assert "|name=David Martín" in result
    assert "|status=Vivant" in result
    assert "|occupation=Écrivain" in result
    assert result.strip().endswith("}}")


def test_infobox_place():
    fields = {"name": "Barcelone", "type": "Ville"}
    result = make_infobox_call("PLACE", fields)
    assert result.startswith("{{Infobox location")


def test_infobox_org():
    fields = {"name": "La Roseraie"}
    result = make_infobox_call("ORG", fields)
    assert result.startswith("{{Infobox organization")


def test_infobox_empty_fields_omitted():
    """Fields with empty/None values must not appear in the call."""
    fields = {"name": "X", "status": "", "occupation": None}
    result = make_infobox_call("PERSON", fields)
    assert "|status=" not in result
    assert "|occupation=" not in result


def test_infobox_format():
    """Each field on its own line, no trailing whitespace."""
    fields = {"name": "X", "status": "Vivant"}
    result = make_infobox_call("PERSON", fields)
    lines = result.strip().splitlines()
    assert lines[0] == "{{Infobox character"
    assert lines[-1] == "}}"
    # Middle lines are |key=value
    for line in lines[1:-1]:
        assert line.startswith("|")
        assert "=" in line
```

**Step 2: Lancer les tests pour vérifier l'échec**

```bash
pytest tests/test_md2wiki.py::test_infobox_person -v
```

Expected : `ImportError` — `make_infobox_call` n'existe pas encore.

**Step 3: Ajouter `make_infobox_call` dans `wiki_creator/md2wiki.py`**

Ajouter après la fonction `convert` :

```python
_TEMPLATE_NAMES = {
    "PERSON": "Infobox character",
    "PLACE": "Infobox location",
    "ORG": "Infobox organization",
}


def make_infobox_call(entity_type: str, fields: dict) -> str:
    """Return the wikitext template call for the given entity type.

    Empty/None values are omitted. Each field on its own line.
    """
    template = _TEMPLATE_NAMES.get(entity_type, "Infobox")
    lines = ["{{" + template]
    for key, value in fields.items():
        if value:
            lines.append(f"|{key}={value}")
    lines.append("}}")
    return "\n".join(lines)
```

**Step 4: Lancer les tests**

```bash
pytest tests/test_md2wiki.py -v
```

Expected : tous PASS.

**Step 5: Commit**

```bash
git add wiki_creator/md2wiki.py tests/test_md2wiki.py
git commit -m "feat(stu-117): add make_infobox_call() with tests"
```

---

### Task 4 : Modifier `writer.agent.yaml` — output structuré

**Files:**
- Modify: `.studio/agents/writer.agent.yaml`

**Step 1: Localiser la section output dans le system_prompt**

Ouvrir `.studio/agents/writer.agent.yaml`. Trouver la ligne :

```
Output each generated page with: { "title": canonical_name, "content": "...", "importance": entity.importance }
```

(Ligne ~52 du fichier actuel)

**Step 2: Remplacer cette ligne par**

```yaml
  Output each generated page as a JSON object with these fields:
  - "title": canonical_name (string)
  - "importance": entity.importance ("principal" | "secondary" | "figurant")
  - "entity_type": entity.type ("PERSON" | "PLACE" | "ORG")
  - "infobox_fields": dict of infobox key-value pairs (only populated fields, no nulls)
    Keys match the template fields from the entity type template above.
    For PERSON: name, aliases, titles, status, species, occupation, residence, affiliation, first_seen
    For PLACE: name, type, location, first_seen, residents
    For ORG: name, type, leaders, members, headquarters, first_seen
  - "content": the wiki body in Markdown, WITHOUT the infobox section
    (Do NOT include the "## Infobox" table in content — it goes in infobox_fields instead)

  Output one JSON object per relevant entity as a JSON array:
  [{ "title", "importance", "entity_type", "infobox_fields", "content" }]
```

**Step 3: Vérifier que le YAML est syntaxiquement valide**

```bash
python -c "import yaml; yaml.safe_load(open('.studio/agents/writer.agent.yaml'))"
```

Expected : pas d'erreur.

**Step 4: Commit**

```bash
git add .studio/agents/writer.agent.yaml
git commit -m "feat(stu-117): update writer agent — structured infobox_fields output"
```

---

### Task 5 : Mettre à jour `wiki-generation.contract.yaml`

**Files:**
- Modify: `.studio/contracts/wiki-generation.contract.yaml`

**Step 1: Ouvrir le contrat actuel**

Contenu actuel :
```yaml
name: wiki-generation
version: 1
schema:
  required_fields:
    - pages
  # Each page must include: title (str), content (str), importance (str)
  # importance mirrors the entity's importance level from entity-classification
```

**Step 2: Remplacer par**

```yaml
name: wiki-generation
version: 1
schema:
  required_fields:
    - pages
  # Each page must include:
  #   title (str)             — canonical_name
  #   importance (str)        — "principal" | "secondary" | "figurant"
  #   entity_type (str)       — "PERSON" | "PLACE" | "ORG"
  #   infobox_fields (object) — key-value pairs for the infobox template (no nulls)
  #   content (str)           — Markdown body WITHOUT the infobox section
```

**Step 3: Commit**

```bash
git add .studio/contracts/wiki-generation.contract.yaml
git commit -m "feat(stu-117): update wiki-generation contract — add entity_type, infobox_fields"
```

---

### Task 6 : Ajouter config export dans `book.input.yaml`

**Files:**
- Modify: `.studio/inputs/book.input.yaml`

**Step 1: Ajouter la section `export` à la fin du fichier**

```yaml
export:
  wiki_dir: output/wiki
  categories:
    language: fr
    labels:
      persons: Personnages
      principal: Personnages principaux
      secondary: Personnages secondaires
      locations: Lieux
      organizations: Organisations
```

**Step 2: Commit**

```bash
git add .studio/inputs/book.input.yaml
git commit -m "feat(stu-117): add export config to book.input.yaml"
```

---

### Task 7 : Script `wiki_export.py` — helpers testables

Les helpers de génération de fichiers sont extraits dans `wiki_creator/export_helpers.py` pour pouvoir être testés sans simuler le contexte Studio.

**Files:**
- Create: `wiki_creator/export_helpers.py`
- Create: `tests/test_export_helpers.py`

**Step 1: Écrire les tests**

```python
# tests/test_export_helpers.py
import pytest
from wiki_creator.export_helpers import (
    page_filename,
    category_tags,
    infobox_template_content,
    main_page_content,
)


def test_page_filename_replaces_spaces():
    assert page_filename("David Martín") == "David_Martín"


def test_page_filename_preserves_accents():
    assert page_filename("Barcelone") == "Barcelone"


def test_category_tags_principal_person():
    labels = {
        "persons": "Personnages",
        "principal": "Personnages principaux",
        "secondary": "Personnages secondaires",
        "locations": "Lieux",
        "organizations": "Organisations",
    }
    tags = category_tags("PERSON", "principal", labels)
    assert "[[Category:Personnages]]" in tags
    assert "[[Category:Personnages principaux]]" in tags


def test_category_tags_secondary_person():
    labels = {
        "persons": "Personnages",
        "principal": "Personnages principaux",
        "secondary": "Personnages secondaires",
        "locations": "Lieux",
        "organizations": "Organisations",
    }
    tags = category_tags("PERSON", "secondary", labels)
    assert "[[Category:Personnages]]" in tags
    assert "[[Category:Personnages secondaires]]" in tags
    assert "[[Category:Personnages principaux]]" not in tags


def test_category_tags_figurant_person():
    labels = {
        "persons": "Personnages",
        "principal": "Personnages principaux",
        "secondary": "Personnages secondaires",
        "locations": "Lieux",
        "organizations": "Organisations",
    }
    tags = category_tags("PERSON", "figurant", labels)
    assert "[[Category:Personnages]]" in tags
    assert "[[Category:Personnages principaux]]" not in tags


def test_category_tags_place():
    labels = {"persons": "P", "principal": "P", "secondary": "P",
              "locations": "Lieux", "organizations": "O"}
    tags = category_tags("PLACE", "principal", labels)
    assert "[[Category:Lieux]]" in tags


def test_category_tags_org():
    labels = {"persons": "P", "principal": "P", "secondary": "P",
              "locations": "L", "organizations": "Organisations"}
    tags = category_tags("ORG", "principal", labels)
    assert "[[Category:Organisations]]" in tags


def test_infobox_template_person_contains_name_field():
    content = infobox_template_content("PERSON")
    assert "{{{name}}}" in content
    assert "{{{status|}}}" in content


def test_infobox_template_place():
    content = infobox_template_content("PLACE")
    assert "{{{name}}}" in content


def test_main_page_content_contains_title():
    pages = [
        {"title": "David Martín", "importance": "principal", "entity_type": "PERSON"},
        {"title": "Barcelone", "importance": "principal", "entity_type": "PLACE"},
        {"title": "Figurant X", "importance": "figurant", "entity_type": "PERSON"},
    ]
    content = main_page_content(
        book_title="Le Jeu de l'Ange",
        author="Carlos Ruiz Zafón",
        pages=pages,
    )
    assert "Le Jeu de l'Ange" in content
    assert "David Martín" in content
    assert "Barcelone" in content
```

**Step 2: Lancer les tests pour vérifier l'échec**

```bash
pytest tests/test_export_helpers.py -v
```

Expected : `ImportError`.

**Step 3: Créer `wiki_creator/export_helpers.py`**

```python
# wiki_creator/export_helpers.py
"""Helper functions for wiki export — pure logic, no I/O."""
from __future__ import annotations


def page_filename(canonical_name: str) -> str:
    """Convert canonical name to wiki filename (spaces → underscores)."""
    return canonical_name.replace(" ", "_")


def category_tags(entity_type: str, importance: str, labels: dict) -> list[str]:
    """Return list of [[Category:X]] tags for a page."""
    tags = []
    if entity_type == "PERSON":
        tags.append(f"[[Category:{labels['persons']}]]")
        if importance == "principal":
            tags.append(f"[[Category:{labels['principal']}]]")
        elif importance == "secondary":
            tags.append(f"[[Category:{labels['secondary']}]]")
    elif entity_type == "PLACE":
        tags.append(f"[[Category:{labels['locations']}]]")
    elif entity_type == "ORG":
        tags.append(f"[[Category:{labels['organizations']}]]")
    return tags


_INFOBOX_TEMPLATES = {
    "PERSON": """\
<includeonly>
{| class="infobox"
|-
! colspan="2" | {{{name}}}
|-
| '''Aussi connu comme''' || {{{aliases|}}}
|-
| '''Titre(s)''' || {{{titles|}}}
|-
| '''Statut''' || {{{status|}}}
|-
| '''Espèce/Race''' || {{{species|}}}
|-
| '''Occupation''' || {{{occupation|}}}
|-
| '''Résidence''' || {{{residence|}}}
|-
| '''Affiliation''' || {{{affiliation|}}}
|-
| '''Première apparition''' || {{{first_seen|}}}
|}
</includeonly>""",
    "PLACE": """\
<includeonly>
{| class="infobox"
|-
! colspan="2" | {{{name}}}
|-
| '''Type''' || {{{type|}}}
|-
| '''Localisation''' || {{{location|}}}
|-
| '''Première mention''' || {{{first_seen|}}}
|-
| '''Résidents notables''' || {{{residents|}}}
|}
</includeonly>""",
    "ORG": """\
<includeonly>
{| class="infobox"
|-
! colspan="2" | {{{name}}}
|-
| '''Type''' || {{{type|}}}
|-
| '''Leader(s)''' || {{{leaders|}}}
|-
| '''Membres notables''' || {{{members|}}}
|-
| '''Siège''' || {{{headquarters|}}}
|-
| '''Première mention''' || {{{first_seen|}}}
|}
</includeonly>""",
}


def infobox_template_content(entity_type: str) -> str:
    """Return the MediaWiki template source for the given entity type."""
    return _INFOBOX_TEMPLATES[entity_type]


def main_page_content(book_title: str, author: str, pages: list[dict]) -> str:
    """Generate Main_Page.wiki content from pipeline data."""
    persons = [p for p in pages if p["entity_type"] == "PERSON"]
    places = [p for p in pages if p["entity_type"] == "PLACE"]
    orgs = [p for p in pages if p["entity_type"] == "ORG"]

    principals = [p for p in persons if p["importance"] == "principal"][:8]
    major_places = [p for p in places if p["importance"] == "principal"][:5]

    lines = [
        f"= {book_title} =",
        f"''{author}''",
        "",
        "== Personnages principaux ==",
    ]
    for p in principals:
        lines.append(f"* [[{p['title']}]]")
    lines += [
        "",
        "== Lieux importants ==",
    ]
    for p in major_places:
        lines.append(f"* [[{p['title']}]]")
    lines += [
        "",
        "== Navigation ==",
        "* [[:Category:Personnages|Tous les personnages]]",
        "* [[:Category:Lieux|Tous les lieux]]",
        "* [[:Category:Organisations|Toutes les organisations]]",
        "",
        "== Statistiques ==",
        f"* {len(pages)} pages wiki",
        f"* {len(persons)} personnages",
        f"* {len(places)} lieux",
        f"* {len(orgs)} organisations",
    ]
    return "\n".join(lines)
```

**Step 4: Lancer les tests**

```bash
pytest tests/test_export_helpers.py -v
```

Expected : tous PASS.

**Step 5: Commit**

```bash
git add wiki_creator/export_helpers.py tests/test_export_helpers.py
git commit -m "feat(stu-117): add export_helpers with tests (categories, templates, main page)"
```

---

### Task 8 : Script `scripts/wiki_export.py`

**Files:**
- Create: `scripts/wiki_export.py`

**Step 1: Créer le script**

Pattern Studio script executor : lit JSON depuis stdin, écrit JSON sur stdout.

```python
#!/usr/bin/env python3
# scripts/wiki_export.py
"""Stage wiki-export — converts wiki-generation Markdown output to wikitext files.

Studio script executor interface:
  Input (stdin): {"additional_context": "<yaml>", "previous_outputs": {...}}
  Output (stdout): {"files_written": N, "wiki_dir": "output/wiki"}
"""
import json
import sys
from pathlib import Path

import yaml

from wiki_creator.md2wiki import convert, make_infobox_call
from wiki_creator.export_helpers import (
    page_filename,
    category_tags,
    infobox_template_content,
    main_page_content,
)

_SUBDIR = {
    "PERSON": "characters",
    "PLACE": "locations",
    "ORG": "organizations",
}


def main() -> None:
    payload = json.load(sys.stdin)
    input_cfg = yaml.safe_load(payload["additional_context"])
    prev = payload["previous_outputs"]

    pages = prev["wiki-generation"]["pages"]
    epub = prev["epub-parse"]
    book_title = epub.get("title", "Wiki")
    author = epub.get("author", "")

    export_cfg = input_cfg.get("export", {})
    wiki_dir = Path(export_cfg.get("wiki_dir", "output/wiki"))
    labels_cfg = export_cfg.get("categories", {}).get("labels", {})
    labels = {
        "persons": labels_cfg.get("persons", "Personnages"),
        "principal": labels_cfg.get("principal", "Personnages principaux"),
        "secondary": labels_cfg.get("secondary", "Personnages secondaires"),
        "locations": labels_cfg.get("locations", "Lieux"),
        "organizations": labels_cfg.get("organizations", "Organisations"),
    }

    # Create directories
    (wiki_dir / "templates").mkdir(parents=True, exist_ok=True)
    for subdir in _SUBDIR.values():
        (wiki_dir / subdir).mkdir(exist_ok=True)

    files_written = 0

    # Write infobox templates
    for entity_type, template_name in [
        ("PERSON", "Infobox_character"),
        ("PLACE", "Infobox_location"),
        ("ORG", "Infobox_organization"),
    ]:
        path = wiki_dir / "templates" / f"{template_name}.wiki"
        path.write_text(infobox_template_content(entity_type), encoding="utf-8")
        files_written += 1

    # Write entity pages
    for page in pages:
        title = page["title"]
        entity_type = page.get("entity_type", "PERSON")
        importance = page.get("importance", "secondary")
        infobox_fields = page.get("infobox_fields", {})
        content_md = page.get("content", "")

        infobox = make_infobox_call(entity_type, infobox_fields)
        body = convert(content_md)
        cats = category_tags(entity_type, importance, labels)

        page_content = infobox + "\n\n" + body
        if cats:
            page_content += "\n\n" + "\n".join(cats)

        subdir = _SUBDIR.get(entity_type, "characters")
        filename = page_filename(title) + ".wiki"
        path = wiki_dir / subdir / filename
        path.write_text(page_content, encoding="utf-8")
        files_written += 1

    # Write categories.wiki
    cats_content = _build_categories_wiki(labels)
    (wiki_dir / "categories.wiki").write_text(cats_content, encoding="utf-8")
    files_written += 1

    # Write Main_Page.wiki
    main_content = main_page_content(book_title, author, pages)
    (wiki_dir / "Main_Page.wiki").write_text(main_content, encoding="utf-8")
    files_written += 1

    json.dump({"files_written": files_written, "wiki_dir": str(wiki_dir)}, sys.stdout)


def _build_categories_wiki(labels: dict) -> str:
    lines = [
        f"[[Category:{labels['principal']}|{labels['persons']}]]",
        f"[[Category:{labels['secondary']}|{labels['persons']}]]",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
```

**Step 2: Tester manuellement avec un payload minimal**

```bash
echo '{
  "additional_context": "export:\n  wiki_dir: /tmp/test-wiki\n  categories:\n    labels:\n      persons: Personnages\n      principal: Personnages principaux\n      secondary: Personnages secondaires\n      locations: Lieux\n      organizations: Organisations",
  "previous_outputs": {
    "epub-parse": {"title": "Le Jeu de l'\''Ange", "author": "Carlos Ruiz Zafón"},
    "wiki-generation": {
      "pages": [
        {
          "title": "David Martín",
          "importance": "principal",
          "entity_type": "PERSON",
          "infobox_fields": {"name": "David Martín", "status": "Vivant", "occupation": "Écrivain"},
          "content": "## Biographie\n\nDavid Martín est un **écrivain** barcelonais."
        }
      ]
    }
  }
}' | python scripts/wiki_export.py
```

Expected :
```json
{"files_written": 5, "wiki_dir": "/tmp/test-wiki"}
```

**Step 3: Vérifier les fichiers générés**

```bash
find /tmp/test-wiki -type f | sort
cat /tmp/test-wiki/characters/David_Martín.wiki
```

Expected content de la page :
```
{{Infobox character
|name=David Martín
|status=Vivant
|occupation=Écrivain
}}

== Biographie ==

David Martín est un '''écrivain''' barcelonais.

[[Category:Personnages]]
[[Category:Personnages principaux]]
```

**Step 4: Commit**

```bash
git add scripts/wiki_export.py
git commit -m "feat(stu-117): add wiki_export.py stage script"
```

---

### Task 9 : Ajouter le stage dans le pipeline

**Files:**
- Modify: `.studio/pipelines/wiki-pipeline.pipeline.yaml`

**Step 1: Ajouter le stage `wiki-export` à la fin**

```yaml
  - name: wiki-export
    kind: extraction
    executor: script
    runtime: python
    script: scripts/wiki_export.py
    context:
      include:
        - input
        - epub-parse
        - entity-classification
        - previous_stage_output
```

**Step 2: Vérifier que le YAML est syntaxiquement valide**

```bash
python -c "import yaml; yaml.safe_load(open('.studio/pipelines/wiki-pipeline.pipeline.yaml'))"
```

Expected : pas d'erreur.

**Step 3: Commit**

```bash
git add .studio/pipelines/wiki-pipeline.pipeline.yaml
git commit -m "feat(stu-117): add wiki-export stage to pipeline"
```

---

### Task 10 : Lancer la suite de tests complète

**Step 1: Lancer tous les tests**

```bash
pytest tests/ -v
```

Expected : tous les tests PASS. Aucun test ne doit être skipé sans raison.

**Step 2: Vérifier le type checking**

```bash
mypy wiki_creator/md2wiki.py wiki_creator/export_helpers.py
```

Expected : pas d'erreur de type.

**Step 3: Si des erreurs mypy apparaissent**, les corriger avant de continuer.

---

### Task 11 : PR

**Step 1: Push la branche**

```bash
git push -u origin feat/stu-117-wiki-export
```

**Step 2: Créer la PR**

```bash
gh pr create \
  --title "feat(stu-117): wiki export — wikitext, infobox templates, catégories, Main_Page" \
  --body "$(cat <<'EOF'
## Summary

- Nouveau stage `wiki-export` (8e dans le pipeline) qui convertit l'output Markdown de `wiki-generation` en un dossier `output/wiki/` prêt pour Fandom
- `wiki_creator/md2wiki.py` — conversion markdown → wikitext (regex déterministe)
- `wiki_creator/export_helpers.py` — helpers testables : catégories, templates infobox, Main_Page
- `scripts/wiki_export.py` — stage executor qui orchestre la génération des fichiers
- `writer.agent.yaml` modifié pour sortir `infobox_fields` structuré + body séparé
- Catégories configurables en YAML (langue + labels)

## Test plan

- [ ] `pytest tests/test_md2wiki.py` — conversion markdown → wikitext
- [ ] `pytest tests/test_export_helpers.py` — helpers catégories, templates, Main_Page
- [ ] Test manuel `wiki_export.py` avec payload minimal (Task 8)
- [ ] `studio run wiki-pipeline --provider mock` — pipeline complet

Closes STU-117

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)" \
  --base main
```
