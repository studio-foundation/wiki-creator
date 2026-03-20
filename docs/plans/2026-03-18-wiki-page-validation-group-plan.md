# Wiki Page Validation Group — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Trois améliorations couplées : (1) ajouter un groupe de validation dans `wiki-page-item.pipeline.yaml` pour détecter et corriger les hallucinations via `group_feedback` ; (2) ajouter le même groupe dans `chapter-summary-item.pipeline.yaml` ; (3) migrer `relationship_extraction.py` pour lire `system_prompt` + `model` depuis l'agent YAML au lieu de les hardcoder.

**Architecture:** Les pipelines `wiki-page-item` et `chapter-summary-item` passent chacun à un `group` Studio (`max_iterations: 3`) avec un stage validator après le stage agent. Le validator Python fait des checks structurels rapides, puis délègue à un agent de grounding LLM pour les entités `principal`/`secondary`. Pour `relationship-extraction`, le script charge l'agent YAML au démarrage et en extrait `system_prompt` + `model` — la boucle Ollama reste dans le script (migration niveau 2 = issue séparée).

**Tech Stack:** Python, YAML (Studio pipeline/agent/contract), pytest, Ollama/mistral

---

## Task 1 : Ajouter `validation` dans le book YAML

Ajoute la section `validation` dans le YAML du livre. Elle définit les keywords cross-série interdits et le titre de série canonique — aucun hardcode dans le script.

**Files:**
- Modify: `library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml`

**Step 1: Ajouter la section validation**

À la fin du fichier, ajouter :

```yaml
validation:
  series: Throne of Glass
  forbidden_series:
    - Kingkiller Chronicle
    - A Court of Thorns and Roses
    - An Ember in the Ashes
    - The Selection
    - Daughter of Smoke and Bone
```

**Step 2: Vérifier que pytest passe toujours**

```bash
pytest -q
```

Expected: tous les tests passent (aucun test ne lit cette section pour l'instant).

**Step 3: Commit**

```bash
git add library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml
git commit -m "feat(validation): add validation.forbidden_series to throne-of-glass book YAML"
```

---

## Task 2 : Créer le contract `wiki-page-validator`

Le contract définit la forme attendue de la sortie du validator. Studio vérifie cette forme avant d'injecter dans `group_feedback`.

**Files:**
- Create: `.studio/contracts/wiki-page-validator.contract.yaml`

**Step 1: Créer le contract**

```yaml
name: wiki-page-validator
version: 1
schema:
  required_fields:
    - valid
    - errors
    - feedback
```

**Step 2: Vérifier que le pipeline config test passe**

```bash
pytest tests/test_pipeline_configs.py -v
```

Expected: PASS (le test lit les contracts, le nouveau doit être valide YAML).

**Step 3: Commit**

```bash
git add .studio/contracts/wiki-page-validator.contract.yaml
git commit -m "feat(validation): add wiki-page-validator contract"
```

---

## Task 3 : Créer le script `wiki_page_validator.py` — squelette + lecture payload

Le script lit stdin (payload Studio), extrait la page générée et les métadonnées d'entrée, et retourne un JSON valide.

**Files:**
- Create: `scripts/wiki_page_validator.py`
- Test: `tests/test_wiki_page_validator.py`

**Step 1: Écrire le test de lecture du payload**

```python
# tests/test_wiki_page_validator.py
import json
import pytest
from scripts.wiki_page_validator import parse_payload

def test_parse_payload_extracts_page_and_input():
    payload = {
        "previous_outputs": {
            "wiki-page-item": {
                "title": "Celaena",
                "importance": "principal",
                "entity_type": "PERSON",
                "infobox_fields": {"Statut": "Assassine"},
                "content": "Celaena est une assassine."
            }
        },
        "additional_context": "file_path: library/foo/books/01.yaml\nseries: Throne of Glass"
    }
    page, meta = parse_payload(payload)
    assert page["title"] == "Celaena"
    assert meta["series"] == "Throne of Glass"
```

**Step 2: Vérifier que le test échoue**

```bash
pytest tests/test_wiki_page_validator.py::test_parse_payload_extracts_page_and_input -v
```

Expected: FAIL — `ModuleNotFoundError` ou `ImportError`.

**Step 3: Implémenter `parse_payload`**

```python
#!/usr/bin/env python3
"""Stage: wiki-page-validator (script executor)

Valide la page générée par wiki-page-item.
Checks structurels (toutes importances) + grounding LLM (principal/secondary).

Input (Studio stdin):
  previous_outputs["wiki-page-item"]: page générée
  additional_context: YAML avec file_path, series, forbidden_series

Output (stdout):
  { "valid": bool, "errors": [...], "feedback": str }
"""
import json
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def parse_payload(payload: dict) -> tuple[dict, dict]:
    """Extract (page, meta) from Studio payload."""
    prev = payload.get("previous_outputs", {})
    page = prev.get("wiki-page-item", {})
    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    return page, ctx


if __name__ == "__main__":
    payload = json.load(sys.stdin)
    page, meta = parse_payload(payload)
    result = {"valid": True, "errors": [], "feedback": ""}
    print(json.dumps(result))
```

**Step 4: Vérifier que le test passe**

```bash
pytest tests/test_wiki_page_validator.py::test_parse_payload_extracts_page_and_input -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add scripts/wiki_page_validator.py tests/test_wiki_page_validator.py
git commit -m "feat(validation): add wiki_page_validator skeleton with parse_payload"
```

---

## Task 4 : Checks structurels — langue FR

**Files:**
- Modify: `scripts/wiki_page_validator.py`
- Modify: `tests/test_wiki_page_validator.py`

**Step 1: Écrire les tests**

```python
from scripts.wiki_page_validator import check_language_fr

def test_check_language_fr_passes_french():
    page = {"content": "Celaena est une assassine connue dans tout le royaume."}
    errors = check_language_fr(page)
    assert errors == []

def test_check_language_fr_detects_english():
    page = {"content": "Celaena is the best assassin in the kingdom. She was known as Laena."}
    errors = check_language_fr(page)
    assert any("anglais" in e for e in errors)

def test_check_language_fr_passes_mixed_names():
    # Les noms propres ne doivent pas déclencher le check
    page = {"content": "Celaena Sardothien est une assassine du royaume d'Adarlan."}
    errors = check_language_fr(page)
    assert errors == []
```

**Step 2: Vérifier que les tests échouent**

```bash
pytest tests/test_wiki_page_validator.py::test_check_language_fr_passes_french tests/test_wiki_page_validator.py::test_check_language_fr_detects_english -v
```

Expected: FAIL.

**Step 3: Implémenter `check_language_fr`**

```python
_EN_MARKERS = [
    "is the", "was a", "was the", "known as", "also known",
    "she was", "he is", "he was", "they are", "is an", "is a",
]

def check_language_fr(page: dict) -> list[str]:
    content = page.get("content", "").lower()
    hits = [m for m in _EN_MARKERS if m in content]
    if hits:
        return [f"❌ Contenu en anglais détecté (marqueurs : {', '.join(hits[:3])})"]
    return []
```

**Step 4: Vérifier que les tests passent**

```bash
pytest tests/test_wiki_page_validator.py -k "language" -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add scripts/wiki_page_validator.py tests/test_wiki_page_validator.py
git commit -m "feat(validation): add check_language_fr structural check"
```

---

## Task 5 : Checks structurels — EPUB IDs, clés infobox, série

**Files:**
- Modify: `scripts/wiki_page_validator.py`
- Modify: `tests/test_wiki_page_validator.py`

**Step 1: Écrire les tests**

```python
from scripts.wiki_page_validator import check_epub_ids, check_infobox_keys, check_series_anchor

def test_check_epub_ids_detects_xhtml():
    page = {"content": "mentionné dans C07.xhtml pour la première fois."}
    assert check_epub_ids(page) != []

def test_check_epub_ids_passes_clean():
    page = {"content": "Celaena est introduite au chapitre 7."}
    assert check_epub_ids(page) == []

def test_check_infobox_keys_detects_prefixed():
    page = {"infobox_fields": {"- Statut": "Assassine", "Titre": "Champion"}}
    assert check_infobox_keys(page) != []

def test_check_infobox_keys_passes_clean():
    page = {"infobox_fields": {"Statut": "Assassine"}}
    assert check_infobox_keys(page) == []

def test_check_series_anchor_detects_missing():
    page = {"content": "Celaena est une assassine redoutable."}
    meta = {"series": "Throne of Glass"}
    errors = check_series_anchor(page, meta)
    assert any("série" in e.lower() for e in errors)

def test_check_series_anchor_passes_present():
    page = {"content": "Celaena Sardothien est un personnage principal de Throne of Glass."}
    meta = {"series": "Throne of Glass"}
    assert check_series_anchor(page, meta) == []
```

**Step 2: Vérifier que les tests échouent**

```bash
pytest tests/test_wiki_page_validator.py -k "epub or infobox or series_anchor" -v
```

Expected: FAIL.

**Step 3: Implémenter les trois fonctions**

```python
def check_epub_ids(page: dict) -> list[str]:
    content = page.get("content", "")
    if ".xhtml" in content:
        return ["❌ ID EPUB dans le contenu (ex: C07.xhtml)"]
    return []


def check_infobox_keys(page: dict) -> list[str]:
    ib = page.get("infobox_fields", {})
    bad = [k for k in ib if k.startswith("- ")]
    if bad:
        return [f"❌ Clé infobox préfixée par '- ' : {bad[0]}"]
    return []


def check_series_anchor(page: dict, meta: dict) -> list[str]:
    series = meta.get("series", "")
    if not series:
        return []
    first_para = (page.get("content", "") + "\n").split("\n")[0]
    if series.lower() not in first_para.lower():
        return [f"❌ Le titre de série '{series}' est absent du premier paragraphe"]
    return []
```

**Step 4: Vérifier que les tests passent**

```bash
pytest tests/test_wiki_page_validator.py -k "epub or infobox or series_anchor" -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add scripts/wiki_page_validator.py tests/test_wiki_page_validator.py
git commit -m "feat(validation): add check_epub_ids, check_infobox_keys, check_series_anchor"
```

---

## Task 6 : Check cross-série (forbidden_series)

**Files:**
- Modify: `scripts/wiki_page_validator.py`
- Modify: `tests/test_wiki_page_validator.py`

**Step 1: Écrire les tests**

```python
from scripts.wiki_page_validator import check_forbidden_series

def test_check_forbidden_series_detects_keyword():
    page = {"content": "Celaena est un personnage de Kingkiller Chronicle.", "infobox_fields": {}}
    meta = {"forbidden_series": ["Kingkiller Chronicle", "The Selection"]}
    errors = check_forbidden_series(page, meta)
    assert any("Kingkiller" in e for e in errors)

def test_check_forbidden_series_checks_infobox_too():
    page = {"content": "Texte propre.", "infobox_fields": {"Série": "The Selection"}}
    meta = {"forbidden_series": ["The Selection"]}
    errors = check_forbidden_series(page, meta)
    assert errors != []

def test_check_forbidden_series_passes_clean():
    page = {"content": "Celaena est une assassine de Throne of Glass.", "infobox_fields": {}}
    meta = {"forbidden_series": ["Kingkiller Chronicle"]}
    assert check_forbidden_series(page, meta) == []

def test_check_forbidden_series_empty_list():
    page = {"content": "N'importe quel contenu.", "infobox_fields": {}}
    meta = {}
    assert check_forbidden_series(page, meta) == []
```

**Step 2: Vérifier que les tests échouent**

```bash
pytest tests/test_wiki_page_validator.py -k "forbidden" -v
```

Expected: FAIL.

**Step 3: Implémenter**

```python
def check_forbidden_series(page: dict, meta: dict) -> list[str]:
    forbidden = meta.get("forbidden_series", [])
    if not forbidden:
        return []
    haystack = page.get("content", "") + str(page.get("infobox_fields", {}))
    hits = [kw for kw in forbidden if kw.lower() in haystack.lower()]
    if hits:
        return [f"❌ Hallucination cross-série détectée : {hits[0]}"]
    return []
```

**Step 4: Vérifier que les tests passent**

```bash
pytest tests/test_wiki_page_validator.py -k "forbidden" -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add scripts/wiki_page_validator.py tests/test_wiki_page_validator.py
git commit -m "feat(validation): add check_forbidden_series from book YAML config"
```

---

## Task 7 : Assemblage — `validate_page` et `build_feedback`

Assemble tous les checks dans une fonction principale et génère le message `feedback` formaté pour `group_feedback`.

**Files:**
- Modify: `scripts/wiki_page_validator.py`
- Modify: `tests/test_wiki_page_validator.py`

**Step 1: Écrire les tests**

```python
from scripts.wiki_page_validator import validate_page, build_feedback

def test_validate_page_returns_valid_when_clean():
    page = {
        "title": "Celaena",
        "importance": "principal",
        "entity_type": "PERSON",
        "infobox_fields": {"Statut": "Assassine"},
        "content": "Celaena Sardothien est l'héroïne de Throne of Glass.",
    }
    meta = {"series": "Throne of Glass", "forbidden_series": []}
    result = validate_page(page, meta)
    assert result["valid"] is True
    assert result["errors"] == []

def test_validate_page_aggregates_all_errors():
    page = {
        "title": "Elena",
        "importance": "secondary",
        "entity_type": "PERSON",
        "infobox_fields": {},
        "content": "Elena was the queen. She is also known as Philippa. C07.xhtml.",
    }
    meta = {"series": "Throne of Glass", "forbidden_series": ["Kingkiller"]}
    result = validate_page(page, meta)
    assert result["valid"] is False
    assert len(result["errors"]) >= 2

def test_build_feedback_formats_instructions():
    errors = ["❌ Langue anglaise", "❌ ID EPUB"]
    feedback = build_feedback(errors)
    assert "Langue anglaise" in feedback
    assert "corrige" in feedback.lower() or "régénère" in feedback.lower()
```

**Step 2: Vérifier que les tests échouent**

```bash
pytest tests/test_wiki_page_validator.py -k "validate_page or build_feedback" -v
```

Expected: FAIL.

**Step 3: Implémenter**

```python
def validate_page(page: dict, meta: dict) -> dict:
    errors: list[str] = []
    errors += check_language_fr(page)
    errors += check_epub_ids(page)
    errors += check_infobox_keys(page)
    errors += check_series_anchor(page, meta)
    errors += check_forbidden_series(page, meta)
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "feedback": build_feedback(errors) if errors else "",
    }


def build_feedback(errors: list[str]) -> str:
    lines = "\n".join(f"- {e}" for e in errors)
    return (
        "La page précédente contient les erreurs suivantes. "
        "Régénère-la en les corrigeant toutes :\n"
        f"{lines}\n\n"
        "Rappels : écris entièrement en français, appuie chaque affirmation "
        "sur les extraits fournis, ne mentionne aucune série sauf celle du livre."
    )
```

**Step 4: Mettre à jour `__main__` pour utiliser `validate_page`**

```python
if __name__ == "__main__":
    payload = json.load(sys.stdin)
    page, meta = parse_payload(payload)
    result = validate_page(page, meta)
    print(json.dumps(result))
```

**Step 5: Vérifier que tous les tests passent**

```bash
pytest tests/test_wiki_page_validator.py -v
```

Expected: tous PASS.

**Step 6: Commit**

```bash
git add scripts/wiki_page_validator.py tests/test_wiki_page_validator.py
git commit -m "feat(validation): add validate_page and build_feedback assembly"
```

---

## Task 8 : Créer l'agent de grounding LLM

**Files:**
- Create: `.studio/agents/wiki-page-validator.agent.yaml`

**Step 1: Créer l'agent**

```yaml
name: wiki-page-validator
provider: ollama
model: mistral
system_prompt: |
  Respond with ONLY a valid JSON object. No markdown fences, no explanation.

  Tu es un validateur de pages wiki pour un roman fantasy.

  Tu reçois :
  - input["prompt"] : les extraits source du roman — la seule vérité autorisée
  - input["page_content"] : la page wiki générée à vérifier

  Pour chaque affirmation factuelle dans page_content (noms, rôles, relations,
  alias, événements), vérifie qu'elle est directement ancrée dans les extraits source.

  Retourne exactement :
  {
    "grounded": true,
    "ungrounded_claims": []
  }

  Ou si des affirmations ne sont pas ancrées :
  {
    "grounded": false,
    "ungrounded_claims": [
      "description courte de l'affirmation non supportée",
      ...
    ]
  }

  Règles strictes :
  - N'utilise aucune connaissance externe sur le livre ou l'auteur.
  - Une affirmation est valide uniquement si tu peux pointer un extrait précis.
  - Les noms propres seuls ne sont pas des affirmations — ignore-les.
  - Retourne au maximum 5 claims non ancrées.
```

**Step 2: Vérifier que le pipeline config test passe**

```bash
pytest tests/test_pipeline_configs.py -v
```

Expected: PASS.

**Step 3: Commit**

```bash
git add .studio/agents/wiki-page-validator.agent.yaml
git commit -m "feat(validation): add wiki-page-validator grounding agent"
```

---

## Task 9 : Modifier `wiki-page-item.pipeline.yaml` — wrap dans le group

**Files:**
- Modify: `.studio/pipelines/wiki-page-item.pipeline.yaml`

**Step 1: Remplacer le contenu**

```yaml
name: wiki-page-item
description: Generate one wiki page item with validation loop
version: 2

stages:
  - group: generation-validation
    max_iterations: 3
    stages:
      - name: wiki-page-item
        kind: analysis
        agent: wiki-page-item
        contract: wiki-page-item
        ralph:
          max_attempts: 3
        context:
          include:
            - input
            - group_feedback

      - name: wiki-page-validator
        kind: validation
        executor: script
        runtime: python
        script: scripts/wiki_page_validator.py
        contract: wiki-page-validator
        context:
          include:
            - input
            - previous_stage_output
```

**Step 2: Vérifier que le pipeline config test passe**

```bash
pytest tests/test_pipeline_configs.py -v
```

Expected: PASS.

**Step 3: Commit**

```bash
git add .studio/pipelines/wiki-page-item.pipeline.yaml
git commit -m "feat(validation): wrap wiki-page-item in generation-validation group (max_iterations=3)"
```

---

## Task 10 : Vérification globale + run smoke test

**Step 1: Lancer la suite complète**

```bash
pytest -q
```

Expected: tous les tests passent (baseline : 485+N passed).

**Step 2: Smoke test sur une page**

Construire un payload minimal et vérifier la sortie du script :

```bash
echo '{
  "previous_outputs": {
    "wiki-page-item": {
      "title": "Celaena",
      "importance": "principal",
      "entity_type": "PERSON",
      "infobox_fields": {"Statut": "Assassine"},
      "content": "Celaena Sardothien est un personnage de Throne of Glass."
    }
  },
  "additional_context": "file_path: library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml\nseries: Throne of Glass\nforbidden_series:\n  - Kingkiller Chronicle"
}' | python scripts/wiki_page_validator.py
```

Expected: `{"valid": true, "errors": [], "feedback": ""}`.

**Step 3: Smoke test page invalide**

```bash
echo '{
  "previous_outputs": {
    "wiki-page-item": {
      "title": "Elena",
      "importance": "secondary",
      "entity_type": "PERSON",
      "infobox_fields": {},
      "content": "Elena was the queen of Terrasen. She is also known as Philippa. See C07.xhtml."
    }
  },
  "additional_context": "series: Throne of Glass\nforbidden_series:\n  - Kingkiller Chronicle"
}' | python scripts/wiki_page_validator.py
```

Expected: `{"valid": false, "errors": [...], "feedback": "..."}` avec au moins 2 erreurs.

**Step 4: Commit final**

```bash
git add -A
git commit -m "feat(validation): wiki-page-validator complete — structural checks + group pipeline"
```

---

## Task 11 : Ajouter le groupe de validation dans `chapter-summary-item.pipeline.yaml`

Le `chapter-summary-item` génère un résumé de chapitre. Les critères de validation sont différents : `temporal_context` renseigné, bullets non vides, pas de langue mixte.

**Files:**
- Modify: `.studio/pipelines/chapter-summary-item.pipeline.yaml`
- Create: `.studio/contracts/chapter-summary-validator.contract.yaml`
- Create: `.studio/agents/chapter-summary-validator.agent.yaml`
- Create: `scripts/chapter_summary_validator.py`
- Modify: `tests/test_chapter_summary.py` (ou créer `tests/test_chapter_summary_validator.py`)

**Step 1: Créer le contract**

```yaml
# .studio/contracts/chapter-summary-validator.contract.yaml
name: chapter-summary-validator
version: 1
schema:
  required_fields:
    - valid
    - errors
    - feedback
```

**Step 2: Créer l'agent de grounding**

```yaml
# .studio/agents/chapter-summary-validator.agent.yaml
name: chapter-summary-validator
provider: ollama
model: mistral
system_prompt: |
  Respond with ONLY a valid JSON object. No markdown fences, no explanation.

  Tu valides un résumé de chapitre de roman fantasy.

  Tu reçois :
  - input["chapter_text"] : le texte brut du chapitre source
  - input["summary_bullets"] : la liste de bullets générés

  Pour chaque bullet, vérifie qu'il est ancré dans le texte du chapitre.

  Retourne :
  {
    "grounded": true,
    "ungrounded_bullets": []
  }

  Ou :
  {
    "grounded": false,
    "ungrounded_bullets": ["bullet non supporté par le texte", ...]
  }

  Règles :
  - N'utilise aucune connaissance externe.
  - Maximum 3 bullets non ancrés reportés.
```

**Step 3: Écrire les tests du validator script**

```python
# tests/test_chapter_summary_validator.py
from scripts.chapter_summary_validator import check_temporal_context, check_bullets_not_empty, validate_summary

def test_check_temporal_context_missing():
    summary = {"temporal_context": None, "summary_bullets": ["Bullet 1"]}
    errors = check_temporal_context(summary)
    assert errors != []

def test_check_temporal_context_present():
    summary = {"temporal_context": "present", "summary_bullets": ["Bullet 1"]}
    assert check_temporal_context(summary) == []

def test_check_bullets_not_empty():
    summary = {"summary_bullets": []}
    errors = check_bullets_not_empty(summary)
    assert errors != []

def test_check_bullets_not_empty_passes():
    summary = {"summary_bullets": ["Celaena sort des mines."]}
    assert check_bullets_not_empty(summary) == []

def test_validate_summary_valid():
    summary = {
        "temporal_context": "present",
        "summary_bullets": ["Celaena est escortée hors d'Endovier."],
    }
    result = validate_summary(summary, meta={})
    assert result["valid"] is True

def test_validate_summary_invalid():
    summary = {"temporal_context": None, "summary_bullets": []}
    result = validate_summary(summary, meta={})
    assert result["valid"] is False
    assert len(result["errors"]) >= 2
```

**Step 4: Vérifier que les tests échouent**

```bash
pytest tests/test_chapter_summary_validator.py -v
```

Expected: FAIL — module manquant.

**Step 5: Implémenter `scripts/chapter_summary_validator.py`**

```python
#!/usr/bin/env python3
"""Stage: chapter-summary-validator (script executor)

Checks structurels sur un résumé de chapitre généré par chapter-summary-item.

Input (Studio stdin):
  previous_outputs["chapter-summary-item"]: résumé généré
  additional_context: YAML book metadata

Output (stdout):
  { "valid": bool, "errors": [...], "feedback": str }
"""
import json
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def parse_payload(payload: dict) -> tuple[dict, dict]:
    prev = payload.get("previous_outputs", {})
    summary = prev.get("chapter-summary-item", {})
    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    return summary, ctx


def check_temporal_context(summary: dict) -> list[str]:
    tc = summary.get("temporal_context")
    if not tc:
        return ["❌ temporal_context absent ou null"]
    return []


def check_bullets_not_empty(summary: dict) -> list[str]:
    bullets = summary.get("summary_bullets", [])
    if not bullets:
        return ["❌ summary_bullets vide"]
    if len(bullets) < 2:
        return ["⚠️ Seulement 1 bullet — résumé trop court"]
    return []


def validate_summary(summary: dict, meta: dict) -> dict:
    errors: list[str] = []
    errors += check_temporal_context(summary)
    errors += check_bullets_not_empty(summary)
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "feedback": build_feedback(errors) if errors else "",
    }


def build_feedback(errors: list[str]) -> str:
    lines = "\n".join(f"- {e}" for e in errors)
    return (
        "Le résumé précédent contient les erreurs suivantes. Régénère-le :\n"
        f"{lines}\n\n"
        "Rappels : renseigne temporal_context (present|flashback), "
        "génère au moins 3 bullets ancrés dans le texte du chapitre."
    )


if __name__ == "__main__":
    payload = json.load(sys.stdin)
    summary, meta = parse_payload(payload)
    result = validate_summary(summary, meta)
    print(json.dumps(result))
```

**Step 6: Vérifier que les tests passent**

```bash
pytest tests/test_chapter_summary_validator.py -v
```

Expected: PASS.

**Step 7: Modifier `chapter-summary-item.pipeline.yaml`**

```yaml
name: chapter-summary-item
description: Generate one chapter summary item with validation loop
version: 2

stages:
  - group: summary-validation
    max_iterations: 3
    stages:
      - name: chapter-summary-item
        kind: analysis
        agent: chapter-summary
        contract: chapter-summary-item
        ralph:
          max_attempts: 3
        context:
          include:
            - input
            - group_feedback

      - name: chapter-summary-validator
        kind: validation
        executor: script
        runtime: python
        script: scripts/chapter_summary_validator.py
        contract: chapter-summary-validator
        context:
          include:
            - input
            - previous_stage_output
```

**Step 8: Vérifier que le pipeline config test passe**

```bash
pytest tests/test_pipeline_configs.py -v && pytest -q
```

Expected: PASS.

**Step 9: Commit**

```bash
git add .studio/pipelines/chapter-summary-item.pipeline.yaml \
        .studio/contracts/chapter-summary-validator.contract.yaml \
        .studio/agents/chapter-summary-validator.agent.yaml \
        scripts/chapter_summary_validator.py \
        tests/test_chapter_summary_validator.py
git commit -m "feat(validation): add validation group to chapter-summary-item pipeline"
```

---

## Task 12 : Créer `relationship-classifier-item.pipeline.yaml` avec groupe de validation

Même pattern que `wiki-page-item` et `chapter-summary-item` : un pipeline Studio per-item avec un groupe de validation. Chaque paire de relations passe par l'agent, puis par un validator.

**Files:**
- Create: `.studio/pipelines/relationship-classifier-item.pipeline.yaml`
- Create: `.studio/contracts/relationship-classifier-item.contract.yaml`
- Create: `.studio/contracts/relationship-classifier-validator.contract.yaml`
- Create: `.studio/agents/relationship-classifier-validator.agent.yaml`
- Create: `scripts/relationship_classifier_validator.py`
- Create: `tests/test_relationship_classifier_validator.py`

**Step 1: Créer le contract du classifier item**

```yaml
# .studio/contracts/relationship-classifier-item.contract.yaml
name: relationship-classifier-item
version: 1
schema:
  required_fields:
    - relationship_type
    - direction
    - evolution
    - key_moments
```

**Step 2: Créer le contract du validator**

```yaml
# .studio/contracts/relationship-classifier-validator.contract.yaml
name: relationship-classifier-validator
version: 1
schema:
  required_fields:
    - valid
    - errors
    - feedback
```

**Step 3: Créer l'agent validator**

```yaml
# .studio/agents/relationship-classifier-validator.agent.yaml
name: relationship-classifier-validator
provider: ollama
model: mistral
system_prompt: |
  Respond with ONLY a valid JSON object. No markdown fences, no explanation.

  Tu valides une classification de relation entre deux personnages de roman fantasy.

  Tu reçois :
  - input["entity_a"], input["entity_b"] : les deux personnages
  - input["sample_contexts"] : extraits où ils apparaissent ensemble
  - input["classification"] : la classification générée (relationship_type, direction, evolution, key_moments)

  Vérifie que :
  1. relationship_type est ancré dans les extraits (pas inventé)
  2. evolution n'est pas la phrase générique "relation stable dans les extraits fournis"
  3. key_moments référencent des événements présents dans les extraits

  Retourne :
  {
    "grounded": true,
    "issues": []
  }
  Ou :
  {
    "grounded": false,
    "issues": ["description courte du problème", ...]
  }
```

**Step 4: Créer le pipeline**

```yaml
# .studio/pipelines/relationship-classifier-item.pipeline.yaml
name: relationship-classifier-item
description: Classify one relationship pair with validation loop
version: 1

stages:
  - group: classification-validation
    max_iterations: 3
    stages:
      - name: relationship-classifier
        kind: analysis
        agent: relationship-classifier
        contract: relationship-classifier-item
        ralph:
          max_attempts: 3
        context:
          include:
            - input
            - group_feedback

      - name: relationship-classifier-validator
        kind: validation
        executor: script
        runtime: python
        script: scripts/relationship_classifier_validator.py
        contract: relationship-classifier-validator
        context:
          include:
            - input
            - previous_stage_output
```

**Step 5: Vérifier que le pipeline config test passe**

```bash
pytest tests/test_pipeline_configs.py -v
```

Expected: PASS.

**Step 6: Commit**

```bash
git add .studio/pipelines/relationship-classifier-item.pipeline.yaml \
        .studio/contracts/relationship-classifier-item.contract.yaml \
        .studio/contracts/relationship-classifier-validator.contract.yaml \
        .studio/agents/relationship-classifier-validator.agent.yaml
git commit -m "feat(relationship-classifier): add relationship-classifier-item pipeline with validation group"
```

---

## Task 13 : Créer `scripts/relationship_classifier_validator.py`

**Files:**
- Create: `scripts/relationship_classifier_validator.py`
- Create: `tests/test_relationship_classifier_validator.py`

**Step 1: Écrire les tests**

```python
# tests/test_relationship_classifier_validator.py
from scripts.relationship_classifier_validator import (
    check_relationship_type_valid,
    check_evolution_not_generic,
    validate_classification,
)

_VALID_TYPES = {
    "famille", "mentor/protégé", "amoureux", "antagoniste",
    "allié", "employeur/employé", "ami", "connaissance", "autre",
}

def test_check_relationship_type_valid_passes():
    clf = {"relationship_type": "ami", "direction": "symétrique", "evolution": "ils se rapprochent.", "key_moments": ["ch01: rencontre"]}
    assert check_relationship_type_valid(clf) == []

def test_check_relationship_type_valid_unknown():
    clf = {"relationship_type": "rival", "direction": "symétrique", "evolution": "x", "key_moments": []}
    errors = check_relationship_type_valid(clf)
    assert errors != []

def test_check_evolution_not_generic_detects_filler():
    clf = {"evolution": "relation stable dans les extraits fournis"}
    errors = check_evolution_not_generic(clf)
    assert errors != []

def test_check_evolution_not_generic_passes():
    clf = {"evolution": "Leur méfiance mutuelle se transforme en respect."}
    assert check_evolution_not_generic(clf) == []

def test_check_evolution_null_fails():
    clf = {"evolution": None}
    errors = check_evolution_not_generic(clf)
    assert errors != []

def test_validate_classification_valid():
    clf = {
        "relationship_type": "ami",
        "direction": "symétrique",
        "evolution": "Leur complicité grandit au fil des chapitres.",
        "key_moments": ["ch03: ils s'entraînent ensemble"],
    }
    result = validate_classification(clf, meta={})
    assert result["valid"] is True

def test_validate_classification_invalid():
    clf = {
        "relationship_type": "rival",
        "direction": "symétrique",
        "evolution": "relation stable dans les extraits fournis",
        "key_moments": [],
    }
    result = validate_classification(clf, meta={})
    assert result["valid"] is False
    assert len(result["errors"]) >= 2
```

**Step 2: Vérifier que les tests échouent**

```bash
pytest tests/test_relationship_classifier_validator.py -v
```

Expected: FAIL.

**Step 3: Implémenter**

```python
#!/usr/bin/env python3
"""Stage: relationship-classifier-validator (script executor)

Valide la classification d'une relation générée par relationship-classifier.

Input (Studio stdin):
  previous_outputs["relationship-classifier"]: classification générée
  input: données originales de la paire (entity_a, entity_b, sample_contexts)

Output (stdout):
  { "valid": bool, "errors": [...], "feedback": str }
"""
import json
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_VALID_TYPES = {
    "famille", "mentor/protégé", "amoureux", "antagoniste",
    "allié", "employeur/employé", "ami", "connaissance", "autre",
}

_GENERIC_EVOLUTIONS = {
    "relation stable dans les extraits fournis",
    "relation stable",
    "",
}


def parse_payload(payload: dict) -> tuple[dict, dict]:
    prev = payload.get("previous_outputs", {})
    clf = prev.get("relationship-classifier", {})
    inp = payload.get("input", {})
    return clf, inp


def check_relationship_type_valid(clf: dict) -> list[str]:
    rt = clf.get("relationship_type", "")
    if rt not in _VALID_TYPES:
        return [f"❌ relationship_type invalide ou hors taxonomie : '{rt}'"]
    return []


def check_evolution_not_generic(clf: dict) -> list[str]:
    evol = (clf.get("evolution") or "").strip().lower()
    if not evol or evol in _GENERIC_EVOLUTIONS:
        return ["❌ evolution générique ou nulle — décris comment la relation évolue concrètement"]
    return []


def validate_classification(clf: dict, meta: dict) -> dict:
    errors: list[str] = []
    errors += check_relationship_type_valid(clf)
    errors += check_evolution_not_generic(clf)
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "feedback": build_feedback(errors) if errors else "",
    }


def build_feedback(errors: list[str]) -> str:
    lines = "\n".join(f"- {e}" for e in errors)
    return (
        "La classification précédente contient les erreurs suivantes. Régénère-la :\n"
        f"{lines}\n\n"
        "Rappels : utilise uniquement les types autorisés "
        "(famille|mentor/protégé|amoureux|antagoniste|allié|employeur/employé|ami|connaissance|autre). "
        "evolution doit décrire une évolution observable dans les extraits, pas une phrase générique."
    )


if __name__ == "__main__":
    payload = json.load(sys.stdin)
    clf, inp = parse_payload(payload)
    result = validate_classification(clf, inp)
    print(json.dumps(result))
```

**Step 4: Vérifier que les tests passent**

```bash
pytest tests/test_relationship_classifier_validator.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add scripts/relationship_classifier_validator.py tests/test_relationship_classifier_validator.py
git commit -m "feat(relationship-classifier): add relationship_classifier_validator script"
```

---

## Task 14 : Migrer `relationship_extraction.py` pour invoquer Studio par paire

Même pattern que `chapter_summary.py` : remplacer la boucle `_call_ollama_classify_json` par `subprocess.run(["studio", "run", "relationship-classifier-item", ...])` pour chaque paire.

**Files:**
- Modify: `scripts/relationship_extraction.py`
- Modify: `tests/test_relationship_extraction.py`

**Step 1: Écrire le test de la fonction d'invocation Studio**

```python
# Dans tests/test_relationship_extraction.py
from unittest.mock import patch, MagicMock
from scripts.relationship_extraction import _run_studio_classifier_item

def test_run_studio_classifier_item_returns_classification_on_success():
    fake_output = json.dumps({
        "stages": {
            "relationship-classifier": {
                "relationship_type": "ami",
                "direction": "symétrique",
                "evolution": "Leur complicité grandit.",
                "key_moments": ["ch03: entraînement commun"],
            }
        }
    })
    mock_result = MagicMock(returncode=0, stdout=fake_output, stderr="")
    with patch("subprocess.run", return_value=mock_result):
        rel = {"entity_a": "Celaena", "entity_b": "Chaol", "sample_contexts": ["ctx1"]}
        result = _run_studio_classifier_item(rel, novel_summary="", additional_context="")
    assert result["relationship_type"] == "ami"

def test_run_studio_classifier_item_degrades_on_studio_missing():
    with patch("subprocess.run", side_effect=FileNotFoundError):
        rel = {"entity_a": "A", "entity_b": "B", "sample_contexts": []}
        result = _run_studio_classifier_item(rel, novel_summary="", additional_context="")
    assert result.get("error") == "studio_cli_missing"
```

**Step 2: Vérifier que les tests échouent**

```bash
pytest tests/test_relationship_extraction.py -k "studio_classifier" -v
```

Expected: FAIL.

**Step 3: Implémenter `_run_studio_classifier_item`**

Ajouter dans `scripts/relationship_extraction.py`, en suivant exactement le pattern de `_run_studio_chapter_summary_item` dans `chapter_summary.py` :

```python
def _run_studio_classifier_item(
    rel: dict,
    *,
    novel_summary: str,
    additional_context: str,
    timeout_seconds: int = 120,
) -> dict:
    """Invoke Studio to classify one relationship pair via relationship-classifier-item pipeline."""
    item_input = {
        "entity_a": rel["entity_a"],
        "entity_b": rel["entity_b"],
        "cooccurrence_count": rel.get("cooccurrence_count", 0),
        "sample_contexts": rel.get("sample_contexts", []),
        "novel_summary": novel_summary or "",
    }

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".yaml", delete=False) as tmp:
        yaml.safe_dump(item_input, tmp, sort_keys=False, allow_unicode=True)
        input_path = tmp.name

    cmd = ["studio", "run", "relationship-classifier-item", "--input-file", input_path, "--json"]
    try:
        result = subprocess.run(
            cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=timeout_seconds
        )
    except FileNotFoundError:
        return {"error": "studio_cli_missing"}
    except subprocess.TimeoutExpired:
        return {"error": "studio_run_timeout"}
    finally:
        Path(input_path).unlink(missing_ok=True)

    if result.returncode != 0:
        return {"error": "studio_run_failed", "stderr": result.stderr}

    try:
        run_payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"error": "studio_output_json_parse_error"}

    # Extract from stages output (same pattern as chapter_summary.py)
    stages = run_payload.get("stages", {})
    clf = stages.get("relationship-classifier") or stages.get("relationship-classifier-item")
    if not clf:
        return {"error": "studio_run_output_missing"}
    return clf
```

**Step 4: Modifier `classify_relationships` pour utiliser Studio**

Remplacer la boucle `_call_ollama_classify_json` dans `classify_relationships()` :

```python
def classify_relationships(
    relationships: list[dict],
    *,
    model: str,
    ollama_url: str = _OLLAMA_URL,
    novel_summary: str | None = None,
    additional_context: str = "",
) -> list[dict]:
    """Classify relationships using Studio relationship-classifier-item pipeline."""
    result = []
    for rel in relationships:
        classification = _run_studio_classifier_item(
            rel,
            novel_summary=novel_summary or "",
            additional_context=additional_context,
        )
        if classification and not classification.get("error"):
            rel = {
                **rel,
                "relationship_type": classification.get("relationship_type"),
                "direction": classification.get("direction"),
                "evolution": classification.get("evolution"),
                "key_moments": classification.get("key_moments", []),
                "evidence": classification.get("evidence"),
            }
        else:
            print(
                f"  [WARN] Studio classification failed for {rel['entity_a']}↔{rel['entity_b']}: "
                f"{classification.get('error', 'unknown')}",
                file=sys.stderr,
            )
        result.append(rel)
    return result
```

Supprimer `_call_ollama_classify_json` et `_check_ollama_available` si elles ne sont plus utilisées ailleurs — vérifier d'abord avec `grep`.

**Step 5: Vérifier que les tests passent**

```bash
pytest tests/test_relationship_extraction.py -v
pytest -q
```

Expected: PASS.

**Step 6: Commit**

```bash
git add scripts/relationship_extraction.py tests/test_relationship_extraction.py
git commit -m "feat(relationship-classifier): migrate to Studio item pipeline per pair (replaces inline Ollama loop)"
```

---

## Task 15 : Vérification globale finale

**Step 1: Suite complète**

```bash
pytest -q
```

Expected: tous les tests passent.

**Step 2: Smoke test du validator**

```bash
echo '{
  "previous_outputs": {
    "relationship-classifier": {
      "relationship_type": "rival",
      "direction": "symétrique",
      "evolution": "relation stable dans les extraits fournis",
      "key_moments": []
    }
  },
  "input": {"entity_a": "Celaena", "entity_b": "Chaol"}
}' | python scripts/relationship_classifier_validator.py
```

Expected: `{"valid": false, "errors": [...], "feedback": "..."}`.

**Step 3: Commit final**

```bash
git add -A
git commit -m "feat(validation): complete — wiki-page-validator, chapter-summary-validator, relationship-classifier Studio migration"
```
