# STU-297 — GT Validator : scoping hallucination_signals + normalisation GT

**Date:** 2026-03-20
**Scope:** Skill `validate-wiki-run` uniquement (audit manuel, pas le pipeline)

## Problème

L'étape 1b du skill applique les `hallucination_signals` globalement à toutes les pages. Un signal défini pour `Gavin` peut déclencher sur la page `Celaena` si le terme y apparaît légitimement. Résultat : faux positifs, bruit dans les rapports d'audit.

Cause secondaire : `elena_and_gavin.json` a une structure imbriquée que le code de chargement actuel ne gère pas — il attend un objet flat avec `entity` à la racine. De plus, `elena_and_gavin.json` n'est pas listé dans la prose de l'étape 1b du SKILL.md.

## Formats GT

Deux formats coexistent :

**Format flat** (`celeana.json`, `chaol.json`, `dorian.json`, `king-of-adarlan.json`, `nehemia.json`, `perrington.json`) :
```json
{
  "entity": "Celaena Sardothien",
  "canonical_aliases_book1": [...],
  "hallucination_signals": [...],
  "forbidden_book1": { "characters": [...], "relationships": [...], ... }
}
```

**Format imbriqué** (`elena_and_gavin.json`) :
```json
{
  "entities": ["Elena Galathynius", "Gavin Havilliard"],
  "note": "...",
  "elena": {
    "canonical_aliases_book1": [...],
    "hallucination_signals": [...],
    "forbidden_book1": { "note": "...", "revelations": [...] }
  },
  "gavin": { ... }
}
```

## Solution — Option A

### 1. Normalisation GT au chargement

Remplacer le bloc de chargement de l'étape 1b par une logique qui produit `gt_entries` — une liste d'objets uniformes :

```python
# Structure uniforme produite pour chaque entité GT
{
    "entity": str,
    "canonical_aliases": list[str],   # mappé depuis canonical_aliases_book1, inclut entity lui-même
    "hallucination_signals": list[str],
    "forbidden": list[tuple[str, str]]  # (term, category) — aplati depuis forbidden_book1
}
```

**Règle de parsing :**

- Si le fichier a une clé `"entity"` → format flat : produire une entrée.
- Si le fichier a une clé `"entities"` → format imbriqué : itérer sur les clés du fichier dont la **valeur est un dict** (exclure `"entities"` qui est une liste et `"note"` qui est une string). Chaque sous-dict (`elena`, `gavin`) produit une entrée ; le nom de l'entité est la première entrée de `canonical_aliases_book1`.

**Aplatissement de `forbidden_book1` → `forbidden` :**

Pour chaque fichier GT (flat ou imbriqué), itérer sur les sous-clés de `forbidden_book1` dont la valeur est une liste, en excluant `"note"`. Pour chaque item de la liste : `(item, category_key)`.

```python
forbidden = []
for cat, items in gt_obj.get("forbidden_book1", {}).items():
    if isinstance(items, list):
        for item in items:
            forbidden.append((item, cat))
```

**Mapping `canonical_aliases_book1` → `canonical_aliases` :** Inclure le nom de l'entité en tête, suivi des alias du fichier.

### 2. Scoping des `hallucination_signals`

Dans la boucle `for p in pages`, les signaux ne s'appliquent qu'à la page de l'entité concernée. Le matching est best-effort via les aliases :

```python
for entry in gt_entries:
    aliases = entry["canonical_aliases"]
    is_entity_page = any(a.lower() in title.lower() for a in aliases)
    if not is_entity_page:
        continue
    for sig in entry["hallucination_signals"]:
        phrases = _extract_match_phrases(sig)
        if any(ph.lower() in full_text.lower() for ph in phrases):
            page_violations.append(f"HALLUC_SIGNAL [{entry['entity']}]: {sig}")
```

Note : le matching titre/alias peut rater des pages avec un titre court (ex: "Elena" seul ne matche pas "la reine Elena"). C'est acceptable — l'audit reste manuel et supervisé.

Les `forbidden` restent **globaux** — appliqués à toutes les pages comme avant.

### 3. Mise à jour de la liste des fichiers GT dans la prose SKILL.md

La prose de l'étape 1b liste actuellement : `celeana.json, chaol.json, dorian.json, king-of-adarlan.json, nehemia.json, perrington.json`. Ajouter `elena_and_gavin.json` à cette liste.

### 4. Ce qui ne change pas

- `_extract_match_phrases` (STU-294, inchangée)
- Vérification des relations (`known_relations_book1`, `forbidden_book1.relationships`)
- Toutes les autres étapes du skill (1, 2, 3, 4, 5, 6)
- Le pipeline — ce fix est exclusivement dans le skill d'audit manuel

## Fichier à modifier

`.claude/skills/validate-wiki-run/SKILL.md` :
- Prose de l'étape 1b : liste des fichiers GT
- Bloc Python de l'étape 1b : chargement + boucle de validation
