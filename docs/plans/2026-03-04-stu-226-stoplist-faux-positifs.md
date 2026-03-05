# STU-226 — Stoplist faux positifs français : Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Filtrer les faux positifs déterministes du français littéraire (salutations, titres seuls, mots fonctionnels) avant qu'ils entrent dans le registre d'entités.

**Architecture:** Ajouter une constante `FALSE_POSITIVE_WORDS` au niveau module dans `entity_extraction.py`, puis l'utiliser dans `_is_valid_mention()` via un check sur le texte complet normalisé (`stripped.lower()`). Multi-mots comme "Le Cher" passent naturellement car leur forme normalisée ne figure pas dans la stoplist.

**Tech Stack:** Python, frozenset, pytest

---

### Task 1: Écrire les tests unitaires pour la stoplist (TDD)

**Files:**
- Modify: `tests/test_entity_extraction.py`

**Step 1: Mettre à jour l'import pour inclure `FALSE_POSITIVE_WORDS`**

À la ligne 8, remplacer :
```python
from scripts.entity_extraction import extract_entities, extract_context, split_entities, split_by_type, KEPT_LABELS, _is_valid_mention, FRONTMATTER_ID_PATTERNS
```
par :
```python
from scripts.entity_extraction import extract_entities, extract_context, split_entities, split_by_type, KEPT_LABELS, _is_valid_mention, FRONTMATTER_ID_PATTERNS, FALSE_POSITIVE_WORDS
```

**Step 2: Corriger le test existant qui va casser**

À la ligne 234, le test actuel attend `True` pour `"Merci"`, ce qui contredira la stoplist. Remplacer :
```python
assert _is_valid_mention("Merci") is True   # ambiguous — left to LLM
```
par :
```python
assert _is_valid_mention("Don Basilio") is True
```
(`"Don Basilio"` reste valide ; on retire `"Merci"` qui sera bloqué par la stoplist.)

**Step 3: Ajouter la section de tests stoplist à la fin du fichier**

Après le dernier test (`test_split_by_type_entities_retain_mentions_by_chapter`), ajouter :

```python
# --- FALSE_POSITIVE_WORDS / stoplist tests ---


def test_false_positive_words_is_frozenset():
    """FALSE_POSITIVE_WORDS doit être un frozenset exportable."""
    assert isinstance(FALSE_POSITIVE_WORDS, frozenset)
    assert len(FALSE_POSITIVE_WORDS) > 0


def test_is_valid_mention_rejects_stoplist_words():
    """Les mots de la stoplist, seuls, doivent être rejetés."""
    assert _is_valid_mention("Cher") is False
    assert _is_valid_mention("Chère") is False
    assert _is_valid_mention("Monsieur") is False
    assert _is_valid_mention("Madame") is False
    assert _is_valid_mention("Bonjour") is False
    assert _is_valid_mention("Merci") is False
    assert _is_valid_mention("Adieu") is False


def test_is_valid_mention_allows_multiword_with_stoplist_root():
    """Les entités multi-mots contenant un mot de la stoplist doivent passer."""
    assert _is_valid_mention("Le Cher") is True
    assert _is_valid_mention("Monsieur Lefebvre") is True
    assert _is_valid_mention("Département du Cher") is True


def test_is_valid_mention_case_insensitive_check():
    """Le check stoplist doit être insensible à la casse."""
    assert _is_valid_mention("CHER") is False
    assert _is_valid_mention("Bonjour") is False
```

**Step 4: Vérifier que les nouveaux tests échouent (attendu — TDD)**

```bash
pytest tests/test_entity_extraction.py::test_false_positive_words_is_frozenset tests/test_entity_extraction.py::test_is_valid_mention_rejects_stoplist_words tests/test_entity_extraction.py::test_is_valid_mention_allows_multiword_with_stoplist_root tests/test_entity_extraction.py::test_is_valid_mention_case_insensitive_check -v
```

Attendu : `ImportError` sur `FALSE_POSITIVE_WORDS` (pas encore défini).

---

### Task 2: Implémenter `FALSE_POSITIVE_WORDS` et étendre `_is_valid_mention()`

**Files:**
- Modify: `scripts/entity_extraction.py:48-74`

**Step 1: Ajouter la constante après `FRONTMATTER_ID_PATTERNS` (ligne 57)**

Insérer après le bloc `FRONTMATTER_ID_PATTERNS = frozenset({...})` :

```python
# Words that are never narrative entities in French literary prose.
# Check is performed on the full normalized entity text (stripped + lowercased),
# so multi-word entities like "Le Cher" or "Monsieur Lefebvre" are not affected.
FALSE_POSITIVE_WORDS: frozenset[str] = frozenset({
    # Epistolary salutations (spaCy classifies "Cher" as PLACE — dept. du Cher)
    "cher", "chère", "chers", "chères",
    # Titles used alone without a proper name
    "monsieur", "madame", "mademoiselle",
    # Functional words captured via sentence-initial uppercase
    "excusez", "pardonnez", "intéressant",
    "merci", "bonjour", "bonsoir", "adieu",
})
```

**Step 2: Étendre `_is_valid_mention()` (ligne 60)**

Remplacer la fonction entière :

```python
def _is_valid_mention(text: str) -> bool:
    """
    Return True if `text` looks like a valid proper-noun mention.

    Rejects:
    - Strings shorter than 3 characters (single letters, "Ah", "II", etc.)
    - Strings whose first non-whitespace character is not an uppercase letter
      (lowercase verbs, dash-prefixed dialog fragments, punctuation artifacts)
    - Single-word strings that match FALSE_POSITIVE_WORDS (French salutations,
      standalone titles, functional words captured via initial uppercase).
      Multi-word entities like "Le Cher" or "Monsieur Lefebvre" are not blocked.
    """
    stripped = text.strip()
    if len(stripped) < 3:
        return False
    if not stripped[0].isupper():
        return False
    if stripped.lower() in FALSE_POSITIVE_WORDS:
        return False
    return True
```

**Step 3: Lancer tous les tests de stoplist**

```bash
pytest tests/test_entity_extraction.py -v -k "stoplist or false_positive or valid_mention"
```

Attendu : tous PASS.

**Step 4: Lancer la suite complète**

```bash
pytest tests/test_entity_extraction.py -v
```

Attendu : tous PASS (y compris `test_is_valid_mention_accepts_valid_names` après la correction du Task 1).

**Step 5: Vérifier le mode --test (régression)**

```bash
python scripts/entity_extraction.py --test
```

Attendu : exit 0, affiche "Total entities extracted:" et "Sample (first 3 entities".

**Step 6: Commit**

```bash
git add scripts/entity_extraction.py tests/test_entity_extraction.py
git commit -m "feat(stu-226): add FALSE_POSITIVE_WORDS stoplist and extend _is_valid_mention()"
```

---

### Checklist finale

- [ ] `FALSE_POSITIVE_WORDS` exportée (frozenset, niveau module)
- [ ] `_is_valid_mention("Cher")` → `False`
- [ ] `_is_valid_mention("Le Cher")` → `True`
- [ ] `_is_valid_mention("Monsieur")` → `False`
- [ ] `_is_valid_mention("Monsieur Lefebvre")` → `True`
- [ ] `pytest tests/test_entity_extraction.py` → tous PASS
- [ ] `python scripts/entity_extraction.py --test` → exit 0
