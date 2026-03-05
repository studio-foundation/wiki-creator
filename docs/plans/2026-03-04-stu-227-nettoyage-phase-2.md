# STU-227 : Nettoyage phase 2 — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Éliminer trois catégories d'artefacts textuels qui polluent l'extraction d'entités : `\xa0`, espaces cassées dans les mots, et mentions spaCy trop longues.

**Architecture:** Deux fichiers modifiés — `scripts/parse_epub.py` (nettoyage texte, fixes 1 et 2) et `scripts/entity_extraction.py` (post-traitement des spans spaCy, fix 3). Chaque fix suit TDD : test rouge → implémentation → test vert → commit.

**Tech Stack:** Python 3.11+, pytest, spaCy (`en_core_web_sm` pour les tests unitaires, `fr_core_news_lg` pour les tests d'intégration)

---

## Task 1 : Fix `\xa0` dans `parse_epub.py`

**Files:**
- Modify: `tests/test_parse_epub.py`
- Modify: `scripts/parse_epub.py:17-35` (fonction `clean_chapter_text`)

### Step 1 : Mettre à jour le test existant et ajouter un test précis

Le test `test_clean_html_nbsp_handled` (ligne 70) accepte actuellement `\xa0` comme résultat valide. Le modifier pour exiger que `\xa0` soit normalisé. Ajouter aussi un test direct.

Dans `tests/test_parse_epub.py`, remplacer le test existant et ajouter un nouveau :

```python
def test_clean_html_nbsp_handled():
    """&nbsp; est converti en espace standard (pas en \\xa0)."""
    result = clean_chapter_text("hello&nbsp;world")
    assert "&nbsp;" not in result
    assert "\xa0" not in result  # doit être normalisé, pas laissé comme \xa0
    assert result == "hello world"


def test_clean_xa0_normalized_to_space():
    """\\xa0 brut (non-breaking space) est normalisé en espace standard."""
    assert clean_chapter_text("M.\xa0Martín") == "M. Martín"
    assert clean_chapter_text("Mme\xa0Vidal") == "Mme Vidal"
```

### Step 2 : Vérifier que les tests échouent

```bash
pytest tests/test_parse_epub.py::test_clean_html_nbsp_handled tests/test_parse_epub.py::test_clean_xa0_normalized_to_space -v
```

Résultat attendu : FAIL (le `\xa0` n'est pas encore normalisé)

### Step 3 : Implémenter le fix dans `clean_chapter_text`

Dans `scripts/parse_epub.py`, après la ligne `text = html.unescape(text)` (ligne 20), ajouter :

```python
    # 1b. Normaliser \xa0 (non-breaking space) en espace standard
    #     html.unescape() convertit &nbsp; → \xa0, donc ce replace vient après.
    text = text.replace('\xa0', ' ')
```

Le début de `clean_chapter_text` devient :

```python
def clean_chapter_text(text: str) -> str:
    """Normalize chapter text to remove noise before LLM processing."""
    # 1. Unescape HTML entities (&nbsp; → \xa0, &mdash; → —, etc.)
    text = html.unescape(text)

    # 1b. Normaliser \xa0 (non-breaking space) en espace standard
    text = text.replace('\xa0', ' ')

    # 2. Collapse runs of 2+ newlines into exactly \n\n (paragraph break)
    ...
```

### Step 4 : Vérifier que les tests passent

```bash
pytest tests/test_parse_epub.py::test_clean_html_nbsp_handled tests/test_parse_epub.py::test_clean_xa0_normalized_to_space -v
```

Résultat attendu : PASS

### Step 5 : Vérifier que la suite complète passe toujours

```bash
pytest tests/test_parse_epub.py -v
```

Résultat attendu : tous PASS

### Step 6 : Commit

```bash
git add tests/test_parse_epub.py scripts/parse_epub.py
git commit -m "fix(stu-227): normaliser \\xa0 en espace standard dans clean_chapter_text"
```

---

## Task 2 : Fix espaces cassées — lettres capitulaires dans `parse_epub.py`

**Files:**
- Modify: `tests/test_parse_epub.py`
- Modify: `scripts/parse_epub.py:17-35` (fonction `clean_chapter_text`)

### Contexte

HTML source : `<span class="lettrine">P</span>edro`
BeautifulSoup `get_text(separator="\n")` → `"P\nedro"`
Après `clean_chapter_text` étape 3 (single `\n` → space) → `"P edro"`

### Step 1 : Écrire le test

Dans `tests/test_parse_epub.py`, ajouter après les tests existants :

```python
def test_clean_lettrine_space_joined():
    """Une lettre majuscule isolée suivie d'un espace et d'un mot en minuscule
    est joinée (artefact lettrine HTML : 'P edro' → 'Pedro').
    """
    assert clean_chapter_text("P edro Vidal") == "Pedro Vidal"
    assert clean_chapter_text("L orca") == "Lorca"
    assert clean_chapter_text("B arcelone") == "Barcelone"


def test_clean_lettrine_does_not_affect_abbreviations():
    """M. Pedro, Dr. House etc. ne sont pas modifiés (point après la lettre)."""
    assert clean_chapter_text("M. Pedro") == "M. Pedro"
    assert clean_chapter_text("Dr. House") == "Dr. House"
```

### Step 2 : Vérifier que les tests échouent

```bash
pytest tests/test_parse_epub.py::test_clean_lettrine_space_joined tests/test_parse_epub.py::test_clean_lettrine_does_not_affect_abbreviations -v
```

Résultat attendu : `test_clean_lettrine_space_joined` FAIL, `test_clean_lettrine_does_not_affect_abbreviations` PASS (déjà correct)

### Step 3 : Implémenter le fix

Dans `scripts/parse_epub.py`, ajouter une étape dans `clean_chapter_text`, **après** l'étape 1b (`\xa0`) et **avant** l'étape 2 (collapse newlines). L'ordre est important : la regex doit s'appliquer sur le texte après unescape mais avant le collapse des espaces.

Ajouter à la liste des imports en haut du fichier (si pas déjà présent — `re` est déjà importé) : rien à ajouter.

Dans `clean_chapter_text`, après `text = text.replace('\xa0', ' ')` :

```python
    # 1c. Joindre lettre majuscule isolée + mot suivant en minuscule
    #     Artefact lettrine HTML : <span>P</span>edro → "P edro" → "Pedro"
    #     Ne touche pas "M. Pedro" (suivi d'un point) ni les fins de phrase.
    text = re.sub(r'(?<!\w)([A-ZÀÂÇÉÈÊËÎÏÔÙÛÜ]) ([a-záàâçéèêëîïôùûü])', r'\1\2', text)
```

Note sur le pattern : `(?<!\w)` assure que la majuscule n'est pas précédée d'un autre caractère de mot (évite de toucher "ABC edro"). L'espace entre les deux groupes de capture correspond à l'espace parasite. Le remplacement `\1\2` colle les deux parties.

### Step 4 : Vérifier que les tests passent

```bash
pytest tests/test_parse_epub.py::test_clean_lettrine_space_joined tests/test_parse_epub.py::test_clean_lettrine_does_not_affect_abbreviations -v
```

Résultat attendu : PASS

### Step 5 : Vérifier que la suite complète passe toujours

```bash
pytest tests/test_parse_epub.py -v
```

Résultat attendu : tous PASS

### Step 6 : Commit

```bash
git add tests/test_parse_epub.py scripts/parse_epub.py
git commit -m "fix(stu-227): joindre lettre capitulaire isolée au mot suivant (P edro → Pedro)"
```

---

## Task 3 : Truncation des mentions trop longues dans `entity_extraction.py`

**Files:**
- Modify: `tests/test_entity_extraction.py`
- Modify: `scripts/entity_extraction.py`

### Contexte

spaCy étend parfois une entité nommée au-delà du nom propre :
- `"Sempere junior acquiesça"` (PERSON) → seul `"Sempere junior"` est le nom
- `"Barcelone de ténèbres"` (PLACE) → seul `"Barcelone"` est le lieu
- `"Victor Grandes me sourit"` (PERSON) → seul `"Victor Grandes"` est le nom

Stratégie : itérer les tokens du span de droite à gauche, trouver le dernier token dont `is_title` est True ou `pos_ == "PROPN"`, et tronquer là.

### Step 1 : Ajouter `_truncate_mention` à l'import du fichier de test

Dans `tests/test_entity_extraction.py`, ligne 8, ajouter `_truncate_mention` à l'import :

```python
from scripts.entity_extraction import (
    extract_entities, extract_context, split_entities, split_by_type,
    KEPT_LABELS, _is_valid_mention, FRONTMATTER_ID_PATTERNS, _truncate_mention
)
```

### Step 2 : Écrire les tests pour `_truncate_mention`

Dans `tests/test_entity_extraction.py`, ajouter une section après les tests `_is_valid_mention` :

```python
# --- _truncate_mention tests ---


def test_truncate_mention_drops_trailing_lowercase_tokens(nlp):
    """Les tokens en queue tout en minuscule sont supprimés."""
    # "Barcelone de ténèbres" → "Barcelone"
    doc = nlp("Je visite Barcelone de ténèbres demain.")
    # Créer un span factice couvrant "Barcelone de ténèbres"
    start = next(i for i, t in enumerate(doc) if t.text == "Barcelone")
    end = next(i for i, t in enumerate(doc) if t.text == "ténèbres") + 1
    span = doc[start:end]
    result = _truncate_mention(span)
    assert result == "Barcelone", f"Expected 'Barcelone', got {result!r}"


def test_truncate_mention_keeps_multiword_proper_noun(nlp):
    """Un nom propre multi-mots sans queue est retourné intact."""
    doc = nlp("I met Victor Hugo yesterday.")
    start = next(i for i, t in enumerate(doc) if t.text == "Victor")
    end = next(i for i, t in enumerate(doc) if t.text == "Hugo") + 1
    span = doc[start:end]
    result = _truncate_mention(span)
    assert result == "Victor Hugo", f"Expected 'Victor Hugo', got {result!r}"


def test_truncate_mention_single_token(nlp):
    """Un span d'un seul token propre est retourné tel quel."""
    doc = nlp("Alice smiled.")
    span = doc[0:1]  # "Alice"
    result = _truncate_mention(span)
    assert result == "Alice", f"Expected 'Alice', got {result!r}"


def test_truncate_mention_all_lowercase_returns_full(nlp):
    """Si aucun token n'est title/PROPN, retourner le span complet (cas dégénéré)."""
    doc = nlp("the quick brown fox.")
    span = doc[0:4]
    result = _truncate_mention(span)
    # Pas de token propre → retourne tout (comportement de fallback)
    assert result == span.text
```

### Step 3 : Vérifier que les tests échouent

```bash
pytest tests/test_entity_extraction.py::test_truncate_mention_drops_trailing_lowercase_tokens tests/test_entity_extraction.py::test_truncate_mention_keeps_multiword_proper_noun tests/test_entity_extraction.py::test_truncate_mention_single_token tests/test_entity_extraction.py::test_truncate_mention_all_lowercase_returns_full -v
```

Résultat attendu : ImportError (`_truncate_mention` n'existe pas encore)

### Step 4 : Implémenter `_truncate_mention`

Dans `scripts/entity_extraction.py`, ajouter après la fonction `_is_valid_mention` (ligne ~94) :

```python
def _truncate_mention(span) -> str:
    """
    Tronque un span spaCy au dernier token qui ressemble à un nom propre.

    Un token est considéré "propre" si son texte commence par une majuscule
    (is_title) ou si son POS tag est PROPN.

    Si aucun token n'est propre (cas dégénéré), retourne le span complet.

    Exemples :
      "Barcelone de ténèbres" → "Barcelone"
      "Victor Grandes me sourit" → "Victor Grandes"
      "Victor Hugo" → "Victor Hugo" (inchangé)
    """
    tokens = list(span)
    last_proper = 0  # fallback : 0 → on retournera le span complet si aucun propre
    for i in range(len(tokens) - 1, -1, -1):
        if tokens[i].is_title or tokens[i].pos_ == "PROPN":
            last_proper = i + 1
            break
    if last_proper == 0:
        return span.text
    return span.doc[span.start : span.start + last_proper].text
```

### Step 5 : Vérifier que les tests de `_truncate_mention` passent

```bash
pytest tests/test_entity_extraction.py::test_truncate_mention_drops_trailing_lowercase_tokens tests/test_entity_extraction.py::test_truncate_mention_keeps_multiword_proper_noun tests/test_entity_extraction.py::test_truncate_mention_single_token tests/test_entity_extraction.py::test_truncate_mention_all_lowercase_returns_full -v
```

Résultat attendu : PASS

### Step 6 : Intégrer `_truncate_mention` dans `extract_entities`

Dans `scripts/entity_extraction.py`, dans la boucle `for ent in doc.ents:` de `extract_entities` (autour de la ligne 172), remplacer :

```python
            key = ent.text.lower().strip()
            if not key:
                continue
            if not _is_valid_mention(ent.text):
                continue
```

Par :

```python
            mention_text = _truncate_mention(ent)
            key = mention_text.lower().strip()
            if not key:
                continue
            if not _is_valid_mention(mention_text):
                continue
```

Et dans les deux endroits où `ent.text` est utilisé pour stocker les mentions, remplacer par `mention_text` :

```python
            if key not in registry:
                entity_counter += 1
                registry[key] = {
                    "id": f"entity_{entity_counter:03d}",
                    "type": LABEL_TO_TYPE.get(ent.label_, "OTHER"),
                    "raw_mentions": [mention_text],   # <-- was ent.text
                    "first_seen": chapter["id"],
                    "mentions_by_chapter": {},
                    "mention_count": 1,
                }
            else:
                if mention_text not in registry[key]["raw_mentions"]:  # <-- was ent.text
                    registry[key]["raw_mentions"].append(mention_text)  # <-- was ent.text
                registry[key]["mention_count"] += 1
```

### Step 7 : Vérifier que toute la suite de tests passe

```bash
pytest tests/test_entity_extraction.py -v
```

Résultat attendu : tous PASS

### Step 8 : Commit

```bash
git add tests/test_entity_extraction.py scripts/entity_extraction.py
git commit -m "fix(stu-227): tronquer les mentions spaCy au dernier token propre (_truncate_mention)"
```

---

## Task 4 : Validation intégration — `make test`

### Step 1 : Lancer le test d'intégration complet

```bash
make test
```

Ceci exécute `python scripts/test_extraction.py` sur le livre réel (`books/carlos-ruiz-zafon/le-jeu-de-lange.epub`) avec `fr_core_news_lg`, puis `python scripts/entity_clustering.py --live`.

Résultat attendu :
- Pas d'erreur
- Dans le top-20 des clusters : plus de `M.\xa0Martín`, `P edro`, `"Sempere junior acquiesça"`, `"Barcelone de ténèbres"`

### Step 2 : Vérifier les critères d'acceptation

Inspecter la sortie JSONL générée par `test_extraction.py` (fichier `extraction-<ts>.jsonl`) :

```bash
# Chercher des \xa0 résiduels
grep -P '\xa0' extraction-*.jsonl | head -5

# Chercher des espaces dans les mots (lettre seule + espace + minuscule)
grep -P '"[A-Z] [a-z]' extraction-*.jsonl | head -5

# Chercher les mentions longues (> 3 mots)
python -c "
import json, sys
for line in open(sorted(__import__('glob').glob('extraction-*.jsonl'))[-1]):
    e = json.loads(line)
    for m in e.get('raw_mentions', []):
        if len(m.split()) > 3:
            print(m)
" | head -20
```

### Step 3 : Commit final si tout est propre

```bash
git add -p  # vérifier qu'il n'y a rien d'inattendu
git commit -m "fix(stu-227): validation intégration — artefacts nettoyés sur le livre français"
```

---

## Task 5 : PR

### Step 1 : Pousser la branche et créer la PR

```bash
git push -u origin arianedguay/stu-227-nettoyage-phase-2-xa0-espaces-cassees-et-mentions-trop
gh pr create \
  --title "fix(stu-227): nettoyage phase 2 — \xa0, espaces cassées, mentions trop longues" \
  --body "$(cat <<'EOF'
## Summary

- `\xa0` normalisé en espace standard dans `clean_chapter_text` (après `html.unescape`)
- Lettres capitulaires HTML (`P edro` → `Pedro`) corrigées par regex dans `clean_chapter_text`
- Mentions spaCy trop longues tronquées au dernier token propre (`_truncate_mention`)

Closes STU-227

## Test plan

- [ ] `pytest tests/test_parse_epub.py` — tous verts
- [ ] `pytest tests/test_entity_extraction.py` — tous verts
- [ ] `make test` — pas de `\xa0`, pas d'espaces cassées, pas de bouts de phrase dans le top-20

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)" \
  --base main
```
