# STU-230 — Résolution pronominale (coréférence) pour relationship-extraction

**Date :** 2026-03-05
**Ticket :** [STU-230](https://linear.app/studioag/issue/STU-230/resolution-pronominale-coreference-pour-relationship-extraction)
**Dépend de :** STU-229 (co-occurrence pure — fusionné)

---

## Problème

Le stage `relationship-extraction` (STU-229) construit la matrice de co-occurrence en cherchant les noms d'entités explicites dans des fenêtres glissantes. Les interactions pronominales ("il lui tendit la lettre", "elle le rejoignit") sont ignorées, ce qui sous-estime les relations entre personnages.

**Symptôme observé sur *Le Jeu de l'Ange* (`--live`) :**
- `David Martín ↔ Andreas Corelli` → rang #36 (hors top 20)
- `David Martín ↔ Isabella` → rang #35 (hors top 20)

---

## Décisions de design

| Question | Décision |
|----------|----------|
| Outil coref | `coreferee` (extension spaCy, modèle FR) |
| Source texte chapitres | `chapters.json` sauvegardé par `entity_extraction.py` |
| Où tourne coreferee | Dans `relationship_extraction.py` (2ème passage indépendant) |
| Approche d'intégration | Enrichissement de `mentions_by_entity` (Approche A) |

---

## Architecture

```
entity_extraction.py
  ├── persons_full.json      (inchangé)
  ├── places_full.json       (inchangé)
  ├── orgs_full.json         (inchangé)
  └── chapters.json          ← NOUVEAU : {chapters: {chapter_id: full_text}}

relationship_extraction.py
  ├── --live                 (inchangé — baseline)
  └── --live --coref         ← NOUVEAU
        ├── lit chapters.json
        ├── enrich_mentions_with_coref()
        └── build_cooccurrence_graph()  (inchangé)
```

---

## `chapters.json` (format)

Sauvegardé par `entity_extraction.py` au moment du parsing EPUB, en parallèle des fichiers `*_full.json` existants.

```json
{
  "chapters": {
    "x101.xhtml": "Barcelone, 1917. Je m'appelle David Martín...",
    "x102.xhtml": "Le lendemain matin, je retrouvai Vidal..."
  }
}
```

- Clé = `chapter_id` identique à `mentions_by_chapter` dans `*_full.json`
- Taille estimée : ~2–5 MB pour *Le Jeu de l'Ange* (93 chapitres)

---

## `enrich_mentions_with_coref()` — algorithme

```
Entrées : chapters (dict), entities (list), mentions_by_entity (dict)
Sortie  : mentions_by_entity enrichi (in-place)

Pour chaque (chapter_id, texte) dans chapters :
  doc = nlp(texte)   [fr_core_news_lg + coreferee]

  Pour chaque chaîne dans doc._.coref_chains :
    1. Chercher la mention tête dans name_to_canonical
       → si non trouvée : ignorer
    2. Pour chaque mention dans la chaîne :
       - Si token.pos_ == "PRON" :
         phrase = token.sent.text.strip()
         Ajouter à mentions_by_entity[canonical][chapter_id]
         (si pas déjà présente)

  En cas d'exception sur un chapitre → stderr warning, continuer
```

`build_cooccurrence_graph()` est inchangé — il reçoit simplement plus de phrases par entité.

---

## CLI

```bash
# Baseline (comportement STU-229)
python scripts/relationship_extraction.py --live

# Avec coréférence
python scripts/relationship_extraction.py --live --coref
python scripts/relationship_extraction.py --live --coref --window 5 --threshold 3

# Mode test (texte hardcodé + quelques phrases pronominales)
python scripts/relationship_extraction.py --test --coref
```

---

## Dépendances

```bash
pip install coreferee
python -m coreferee install fr
# fr_core_news_lg déjà présent
```

`coreferee` ajouté dans `pyproject.toml → dependencies`.

---

## Critères de succès

| Critère | Mesure |
|---------|--------|
| Coreferee activé | `"Pronoun sentences added: N"` avec N > 0 |
| Martín ↔ Corelli dans top 20 | Rang ≤ 20 avec `--coref` (actuellement #36) |
| Martín ↔ Isabella dans top 20 | Rang ≤ 20 avec `--coref` (actuellement #35) |
| Comportement sans `--coref` inchangé | Output `--live` identique à STU-229 |

Si les deux paires restent hors top 20 → évaluation BookNLP-fr documentée et migration si justifiée.

---

## Hors scope

- Faux positifs d'entités ("Père", "Avez", "Mme") dans le top 20 → ticket séparé
- Modification du pipeline Studio ou du contrat `relationship-extraction`
- Support PLACE/ORG dans la coréférence (PERSON uniquement)
