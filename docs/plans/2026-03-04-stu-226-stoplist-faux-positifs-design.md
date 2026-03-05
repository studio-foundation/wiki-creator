# STU-226 — Stoplist de faux positifs français : design

**Date :** 2026-03-04
**Ticket :** [STU-226](https://linear.app/studioag/issue/STU-226)
**Fichier concerné :** `scripts/entity_extraction.py`

---

## Problème

spaCy extrait des faux positifs récurrents sur des textes français littéraires :

- `"Cher"` → classifié PLACE (département du Cher), apparaît dans des formules épistolaires
- `"Monsieur"` seul → classifié PERSON
- `"Excusez-moi"`, `"Bonjour"`, etc. → capturés via la majuscule initiale en début de phrase

Ces faux positifs sont déterministes et doivent être filtrés avant le clustering.

---

## Décisions de design

**Filtre contextuel (token suivant) :** non retenu. La stoplist sur le texte complet de l'entité suffit :
- `"Cher"` → clé `"cher"` → bloqué
- `"Le Cher"` → clé `"le cher"` → non dans la stoplist → passe

**Intégration :** dans `_is_valid_mention()` existant (approche A). Centralise toutes les validations de mention au même endroit.

---

## Design

### 1. Constante `FALSE_POSITIVE_WORDS`

Ajoutée au niveau module après `FRONTMATTER_ID_PATTERNS` :

```python
FALSE_POSITIVE_WORDS: frozenset[str] = frozenset({
    # Salutations épistolaires (spaCy → PLACE/PERSON)
    "cher", "chère", "chers", "chères",
    # Titres seuls sans nom propre
    "monsieur", "madame", "mademoiselle",
    # Mots fonctionnels capturés via majuscule initiale
    "excusez", "pardonnez", "intéressant",
    "merci", "bonjour", "bonsoir", "adieu",
})
```

Configurable : ajouter des mots sans toucher à la logique de validation.

### 2. `_is_valid_mention()` étendu

```python
def _is_valid_mention(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 3:
        return False
    if not stripped[0].isupper():
        return False
    if stripped.lower() in FALSE_POSITIVE_WORDS:
        return False
    return True
```

Le check porte sur `stripped.lower()` (texte complet), pas sur la clé du registre — même résultat mais cohérent avec le contrat de la fonction.

---

## Critères d'acceptation

- `"Cher"` → `_is_valid_mention` retourne `False`
- `"Le Cher"` → `True` (multi-mots, non dans la stoplist)
- `"Monsieur"` → `False`
- `"Monsieur Lefebvre"` → `True`
- `"Bonjour"` → `False`
- `python scripts/entity_extraction.py --test` continue de passer (test anglais non affecté)
