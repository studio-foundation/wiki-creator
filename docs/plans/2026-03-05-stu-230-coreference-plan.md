# STU-230 — Résolution pronominale (coréférence) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ajouter un flag `--coref` à `relationship_extraction.py` qui résout les pronoms (il/elle/lui) vers leur entité canonique avant de construire la matrice de co-occurrence, via `coreferee` (extension spaCy).

**Architecture:** `entity_extraction.py` sauvegarde le texte brut des chapitres dans `chapters.json`. En mode `--live --coref`, `relationship_extraction.py` lit ce fichier, passe chaque chapitre dans spaCy+coreferee, et ajoute les phrases à pronoms résolus dans `mentions_by_entity` avant de passer à `build_cooccurrence_graph` (inchangé).

**Tech Stack:** Python 3.11+, spaCy `fr_core_news_lg`, `coreferee` (extension spaCy FR), `anthropic` SDK (déjà présent pour classify).

---

## Task 1 : Worktree + install coreferee

**Files :**
- Modify: `pyproject.toml`

**Step 1 : Créer le worktree**

```bash
git worktree add .worktrees/stu-230-coreference -b feat/stu-230-coreference
cd .worktrees/stu-230-coreference
```

**Step 2 : Installer coreferee + modèle FR**

```bash
pip install coreferee
python -m coreferee install fr
```

Vérifier :
```bash
python -c "import coreferee; print('ok')"
```
Attendu : `ok`

**Step 3 : Ajouter coreferee dans pyproject.toml**

Dans `pyproject.toml`, section `[project] dependencies`, ajouter :
```toml
"coreferee>=1.4",
```

**Step 4 : Commit**

```bash
git add pyproject.toml
git commit -m "feat(stu-230): add coreferee dependency"
```

---

## Task 2 : `entity_extraction.py` — sauvegarde de `chapters.json`

**Files :**
- Modify: `scripts/entity_extraction.py:352-364`
- Test: `tests/test_entity_extraction.py`

**Step 1 : Écrire le test**

Dans `tests/test_entity_extraction.py`, ajouter en fin de fichier :

```python
def test_save_chapters_json_writes_chapter_texts(nlp, tmp_path, monkeypatch):
    """save_chapters_json must write chapter id → content mapping."""
    import json
    from scripts.entity_extraction import save_chapters_json

    chapters = [
        {"id": "ch01", "title": "Ch 1", "content": "Hello world."},
        {"id": "ch02", "title": "Ch 2", "content": "Goodbye world."},
    ]
    out = tmp_path / "chapters.json"
    save_chapters_json(chapters, path=str(out))

    data = json.loads(out.read_text())
    assert data == {"chapters": {"ch01": "Hello world.", "ch02": "Goodbye world."}}
```

**Step 2 : Vérifier que le test échoue**

```bash
pytest tests/test_entity_extraction.py::test_save_chapters_json_writes_chapter_texts -v
```
Attendu : `FAILED` (ImportError: cannot import name 'save_chapters_json')

**Step 3 : Implémenter `save_chapters_json`**

Dans `scripts/entity_extraction.py`, avant la fonction `main()`, ajouter :

```python
def save_chapters_json(chapters: list[dict], path: str = "chapters.json") -> None:
    """Save raw chapter text to chapters.json for downstream coref stage."""
    data = {"chapters": {ch["id"]: ch["content"] for ch in chapters}}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
```

**Step 4 : Appeler `save_chapters_json` dans `main()`**

Dans `scripts/entity_extraction.py`, dans la fonction `main()`, après les lignes qui écrivent les `*_full.json` (autour de la ligne 360), ajouter :

```python
    save_chapters_json(chapters)
```

Note : ne pas appeler `save_chapters_json` dans `run_test_mode()` (cohérent avec le comportement des autres fichiers — le docstring dit "Does not write persons_full.json...").

**Step 5 : Vérifier que le test passe**

```bash
pytest tests/test_entity_extraction.py::test_save_chapters_json_writes_chapter_texts -v
```
Attendu : `PASSED`

**Step 6 : Tous les tests existants passent**

```bash
pytest tests/test_entity_extraction.py -v
```
Attendu : tous verts.

**Step 7 : Commit**

```bash
git add scripts/entity_extraction.py tests/test_entity_extraction.py
git commit -m "feat(stu-230): entity_extraction saves chapters.json"
```

---

## Task 3 : `relationship_extraction.py` — fonction `enrich_mentions_with_coref`

**Files :**
- Modify: `scripts/relationship_extraction.py`
- Test: `tests/test_relationship_extraction.py` (nouveau fichier)

**Context :** La fonction reçoit les chapitres bruts, les entités connues (canonical_name + aliases), et `mentions_by_entity` (le dict {canonical → {chapter_id → [phrases]}} déjà construit). Elle ajoute les phrases pronominales résolues dans ce dict.

**Step 1 : Créer le fichier de tests**

Créer `tests/test_relationship_extraction.py` :

```python
"""Tests for scripts/relationship_extraction.py — coref enrichment."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.relationship_extraction import enrich_mentions_with_coref


def test_enrich_mentions_adds_pronoun_sentence():
    """Pronoun sentence referring to a known entity must be added to its mentions."""
    # Minimal chapters: 2 sentences, second uses a pronoun
    chapters = {
        "ch01": "David Martín entra dans la pièce. Il s'assit près de la fenêtre.",
    }
    entities = [
        {"canonical_name": "David Martín", "type": "PERSON", "aliases": ["Martín", "David"], "relevant": True},
    ]
    mentions_by_entity = {
        "David Martín": {"ch01": ["David Martín entra dans la pièce."]}
    }

    enriched = enrich_mentions_with_coref(chapters, entities, mentions_by_entity)

    ch01_sentences = enriched.get("David Martín", {}).get("ch01", [])
    # Should now include a sentence with the pronoun "Il"
    pronoun_sentences = [s for s in ch01_sentences if "Il" in s or "il" in s]
    assert len(pronoun_sentences) >= 1, (
        f"Expected at least one pronoun sentence added, got: {ch01_sentences}"
    )


def test_enrich_mentions_no_crash_on_unknown_chapter():
    """If chapters dict is empty, function returns mentions_by_entity unchanged."""
    entities = [
        {"canonical_name": "David Martín", "type": "PERSON", "aliases": [], "relevant": True},
    ]
    mentions_by_entity = {"David Martín": {"ch01": ["David Martín entra."]}}
    result = enrich_mentions_with_coref({}, entities, mentions_by_entity)
    assert result == mentions_by_entity


def test_enrich_mentions_no_duplicate_sentences():
    """Already-present sentences must not be added again."""
    sentence = "David Martín entra dans la pièce."
    chapters = {"ch01": sentence}
    entities = [
        {"canonical_name": "David Martín", "type": "PERSON", "aliases": ["Martín"], "relevant": True},
    ]
    mentions_by_entity = {"David Martín": {"ch01": [sentence]}}

    enriched = enrich_mentions_with_coref(chapters, entities, mentions_by_entity)
    assert enriched["David Martín"]["ch01"].count(sentence) == 1
```

**Step 2 : Vérifier que les tests échouent**

```bash
pytest tests/test_relationship_extraction.py -v
```
Attendu : `FAILED` (ImportError: cannot import name 'enrich_mentions_with_coref')

**Step 3 : Implémenter `enrich_mentions_with_coref`**

Dans `scripts/relationship_extraction.py`, ajouter après les imports en haut du fichier :

```python
import re
```
(déjà présent — ne pas dupliquer)

Ajouter la nouvelle fonction avant `run_test_mode` :

```python
def enrich_mentions_with_coref(
    chapters: dict[str, str],
    entities: list[dict],
    mentions_by_entity: dict[str, dict[str, list[str]]],
) -> dict[str, dict[str, list[str]]]:
    """
    Enrich mentions_by_entity with pronoun sentences resolved via coreferee.

    For each chapter text, run spaCy + coreferee. For each coreference chain
    whose head maps to a known canonical entity, add pronoun sentences to
    mentions_by_entity[canonical][chapter_id] (no duplicates).

    Args:
        chapters: {chapter_id: full_text} from chapters.json
        entities: resolved entities list (canonical_name, aliases, type, relevant)
        mentions_by_entity: existing {canonical → {chapter_id → [sentences]}}

    Returns:
        mentions_by_entity enriched in-place (also returned for convenience)
    """
    import spacy

    # Build name→canonical lookup (same logic as build_cooccurrence_graph)
    persons = [e for e in entities if e.get("type") == "PERSON" and e.get("relevant", True)]
    name_to_canonical: dict[str, str] = {}
    for entity in persons:
        canonical = entity["canonical_name"]
        name_to_canonical[canonical.lower()] = canonical
        for alias in entity.get("aliases", []):
            if len(alias) >= 4:
                name_to_canonical[alias.lower()] = canonical

    if not name_to_canonical:
        return mentions_by_entity

    # Load spaCy + coreferee once
    try:
        nlp = spacy.load("fr_core_news_lg")
        nlp.add_pipe("coreferee")
    except Exception as e:
        print(f"[WARN] coreferee load failed: {e}", file=sys.stderr)
        return mentions_by_entity

    total_added = 0

    for chapter_id, text in chapters.items():
        if not text or not text.strip():
            continue
        try:
            doc = nlp(text)
        except Exception as e:
            print(f"[WARN] spaCy failed on {chapter_id}: {e}", file=sys.stderr)
            continue

        if not doc._.coref_chains:
            continue

        for chain in doc._.coref_chains:
            # Find the canonical entity for this chain (look at all mentions)
            canonical = None
            for mention in chain:
                for token_idx in mention:
                    token_text = doc[token_idx].text
                    canon = name_to_canonical.get(token_text.lower())
                    if canon:
                        canonical = canon
                        break
                if canonical:
                    break

            if not canonical:
                continue

            # Add pronoun sentences to mentions
            for mention in chain:
                for token_idx in mention:
                    token = doc[token_idx]
                    if token.pos_ == "PRON":
                        sentence = token.sent.text.strip()
                        if not sentence:
                            continue
                        if canonical not in mentions_by_entity:
                            mentions_by_entity[canonical] = {}
                        if chapter_id not in mentions_by_entity[canonical]:
                            mentions_by_entity[canonical][chapter_id] = []
                        existing = mentions_by_entity[canonical][chapter_id]
                        if sentence not in existing:
                            existing.append(sentence)
                            total_added += 1

    print(f"[coref] Pronoun sentences added: {total_added}", file=sys.stderr)
    return mentions_by_entity
```

**Step 4 : Vérifier que les tests passent**

```bash
pytest tests/test_relationship_extraction.py -v
```
Attendu : tous verts (note : `test_enrich_mentions_adds_pronoun_sentence` dépend de la qualité de coreferee sur une phrase courte — si coreferee ne résout pas "Il" en contexte ultra-court, ce test peut être ajusté avec une phrase plus longue).

Si le test `test_enrich_mentions_adds_pronoun_sentence` échoue parce que coreferee n'a pas assez de contexte, ajuster la phrase dans le test :
```python
chapters = {
    "ch01": (
        "David Martín était un écrivain qui vivait à Barcelone. "
        "Il travaillait chaque nuit dans son atelier. "
        "Il écrivait des romans sombres et poétiques."
    ),
}
```

**Step 5 : Commit**

```bash
git add scripts/relationship_extraction.py tests/test_relationship_extraction.py
git commit -m "feat(stu-230): enrich_mentions_with_coref — coreferee pronoun resolution"
```

---

## Task 4 : Wiring `--coref` dans les modes live et test

**Files :**
- Modify: `scripts/relationship_extraction.py` — fonctions `run_live_mode`, `run_test_mode`, `main`

**Step 1 : Modifier `run_live_mode`**

Dans `scripts/relationship_extraction.py`, dans `run_live_mode(window_size, threshold)`, ajouter le paramètre `coref: bool = False` et le code d'enrichissement.

Changer la signature :
```python
def run_live_mode(window_size: int, threshold: int, coref: bool = False) -> None:
```

Après la ligne qui construit `mentions_by_entity` (après la boucle `for canonical, member_ids in cluster_members.items():`), ajouter :

```python
    if coref:
        if not os.path.exists("chapters.json"):
            print("[WARN] chapters.json not found — run make test (entity_extraction) first.", file=sys.stderr)
        else:
            with open("chapters.json", encoding="utf-8") as f:
                chapters_data = json.load(f)
            chapters = chapters_data.get("chapters", {})
            mentions_by_entity = enrich_mentions_with_coref(chapters, entities, mentions_by_entity)
```

**Step 2 : Modifier `run_test_mode`**

Changer la signature :
```python
def run_test_mode(window_size: int, threshold: int, coref: bool = False) -> None:
```

Dans les données hardcodées de `run_test_mode`, ajouter quelques phrases pronominales dans les mentions existantes (dans `mentions_by_entity["David Martín"]["ch01"]`) pour que la démo soit visible :

```python
# Après les mentions existantes de ch01 pour David Martín, ajouter :
            "ch04": [
                "Il s'assit près de la fenêtre et contempla la nuit.",
                "Elle lui tendit la lettre sans un mot.",
                "Il la prit et la lut lentement.",
            ],
```

Et ajouter à `"Pedro Vidal"` dans les mêmes mentions :
```python
            "ch04": [
                "Il s'assit près de la fenêtre et contempla la nuit.",
            ],
```

Puis, après la construction de `mentions_by_entity` dans `run_test_mode`, avant l'appel à `build_cooccurrence_graph`, ajouter :

```python
    if coref:
        # In test mode, chapters.json is not available.
        # Build minimal chapters dict from existing mentions for demo.
        chapters_demo = {}
        for canonical, by_chapter in mentions_by_entity.items():
            for chapter_id, sentences in by_chapter.items():
                if chapter_id not in chapters_demo:
                    chapters_demo[chapter_id] = " ".join(sentences)
                else:
                    chapters_demo[chapter_id] += " " + " ".join(sentences)
        mentions_by_entity = enrich_mentions_with_coref(chapters_demo, entities, mentions_by_entity)
```

**Step 3 : Modifier `main()`**

Dans `main()`, parser le flag `--coref` :

Après le parsing de `--threshold`, ajouter :
```python
    coref = "--coref" in args
```

Modifier les appels :
```python
    if "--test" in args:
        run_test_mode(window_size, threshold, coref=coref)
        return

    if "--live" in args:
        run_live_mode(window_size, threshold, coref=coref)
        return
```

Pour le mode Studio (stdin), parser `coref` depuis `additional_context` :
```python
        do_coref = bool(additional.get("coref", False))
```
Et appeler `enrich_mentions_with_coref` si `do_coref`, juste avant `build_cooccurrence_graph`.

**Step 4 : Smoke test manuel**

```bash
python scripts/relationship_extraction.py --test --coref
```
Attendu : output normal + `[coref] Pronoun sentences added: N` sur stderr.

```bash
python scripts/relationship_extraction.py --live --coref 2>&1 | head -5
```
Attendu : `[coref] Pronoun sentences added: N` avec N > 0.

**Step 5 : Commit**

```bash
git add scripts/relationship_extraction.py
git commit -m "feat(stu-230): wire --coref flag in run_live_mode, run_test_mode, main"
```

---

## Task 5 : Validation quantitative — comparaison top 20

**Step 1 : Vérifier que chapters.json existe**

```bash
ls -lh chapters.json
```
Si absent, lancer d'abord `make test` (qui appelle `entity_extraction.py`).

**Step 2 : Run baseline**

```bash
python scripts/relationship_extraction.py --live 2>/dev/null
```
Noter le rang de `David Martín ↔ Andreas Corelli` et `David Martín ↔ Isabella`.

Baseline connue : Corelli = #36, Isabella = #35.

**Step 3 : Run avec coref**

```bash
python scripts/relationship_extraction.py --live --coref
```
Vérifier dans la section `=== VALIDATION (top 20) ===` :
- `✓  David Martín ↔ Andreas Corelli`
- `✓  David Martín ↔ Isabella`

Et sur stderr : `[coref] Pronoun sentences added: N` avec N > 0.

**Step 4 : Si les paires restent hors top 20**

Investiguer : `python scripts/relationship_extraction.py --live --coref --threshold 3` pour abaisser le seuil et voir si les paires remontent. Documenter le résultat dans le ticket STU-230 et décider si BookNLP-fr est justifié.

**Step 5 : Tous les tests**

```bash
pytest
```
Attendu : tous verts.

**Step 6 : Commit final + push + PR**

```bash
git add -A
git commit -m "feat(stu-230): validation — --coref enrichit top 20 avec Corelli et Isabella"
git push -u origin feat/stu-230-coreference
gh pr create \
  --title "feat(stu-230): résolution pronominale via coreferee" \
  --body "Adds --coref flag to relationship_extraction.py. Uses coreferee (spaCy extension) to resolve pronouns to canonical entities before co-occurrence graph. entity_extraction.py now saves chapters.json for full chapter text access." \
  --base main
```
