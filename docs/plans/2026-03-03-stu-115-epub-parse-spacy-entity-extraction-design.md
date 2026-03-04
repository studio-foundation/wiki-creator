# STU-115 — Design : Stage non-LLM epub-parse + entity-extraction via spaCy

**Date :** 2026-03-03
**Ticket :** [STU-115](https://linear.app/studioag/issue/STU-115)
**Branche :** `feat/stu-115-stage-non-llm-parse-epub-extraction-entites-brutes-via-spacy`

---

## Contexte

Avant de passer au LLM, le pipeline doit parser l'EPUB et extraire les entités nommées brutes sans envoyer le texte complet au LLM. Un roman peut représenter des centaines de milliers de tokens — le LLM reçoit uniquement des extraits ciblés autour des entités détectées.

Ce ticket est aussi le premier vrai test du mécanisme `executor: script` du kernel (STU-114).

---

## Décisions de design

| Question | Choix retenu |
|---|---|
| Modèle spaCy | Configurable via `book.input.yaml` (`spacy_model: fr_core_news_lg`) |
| Traitement chapitres | Tout en mémoire, output unique sur stdout |
| Structure pipeline | Remplacer le stage LLM `entity-extraction` par le script spaCy |
| Architecture scripts | Deux scripts séparés (Approche B) |

---

## Nouvelle architecture du pipeline

```
epub-parse (script)          → { title, author, chapters }
entity-extraction (script)   → { entities: { entity_NNN: {...} } }
entity-resolution (LLM)      → entités déduplicées + aliases
wiki-generation (LLM)        → pages Markdown
```

---

## Fichiers à créer / modifier

| Fichier | Action |
|---|---|
| `scripts/parse_epub.py` | Légère amélioration : respect de l'ordre spine EPUB |
| `scripts/entity_extraction.py` | **Nouveau** — stage spaCy |
| `.studio/pipelines/wiki-pipeline.pipeline.yaml` | Ajouter les 2 stages script, retirer le stage LLM entity-extraction |
| `.studio/inputs/book.input.yaml` | Ajouter `spacy_model: fr_core_news_lg` |
| `.studio/contracts/entity-extraction.contract.yaml` | Aucun changement (déjà `required_fields: [entities]`) |
| `wiki_creator/types.py` | Ajouter `EntityRegistryEntry`, `EntityRegistry` |
| `tests/test_entity_extraction.py` | **Nouveau** — tests du script |

---

## Interface `scripts/entity_extraction.py`

### Stdin
```json
{
  "title": "Le Jeu de l'ange",
  "author": "Carlos Ruiz Zafón",
  "chapters": [
    { "id": "ch01", "title": "Chapitre I", "content": "..." }
  ],
  "spacy_model": "fr_core_news_lg"
}
```

### Stdout (registre évolutif)
```json
{
  "entities": {
    "entity_001": {
      "raw_mentions": ["David Martín"],
      "first_seen": "ch01",
      "mentions_by_chapter": {
        "ch01": ["David Martín ouvrit la porte et aperçut la silhouette..."]
      }
    },
    "entity_002": {
      "raw_mentions": ["Barcelona"],
      "first_seen": "ch01",
      "mentions_by_chapter": {
        "ch01": ["Il errait dans les rues de Barcelona au crépuscule..."]
      }
    }
  }
}
```

### Règles
- **Jamais** le texte brut complet d'un chapitre dans le registre
- Types conservés : `PER`, `LOC`, `ORG` (spaCy FR) / `PERSON`, `GPE`, `ORG` (spaCy EN) — `DATE`, `CARDINAL`, `MISC` filtrés
- Clé de grouping = `ent.text.lower().strip()` — même surface form cross-chapitres → même entrée
- La déduplication alias (ex : "David" ≡ "David Martín") reste pour le LLM en stage 3

### Extraction du contexte
Pour chaque entité détectée :
1. Récupérer la phrase contenant l'entité (`span.sent`)
2. Prendre 1 phrase avant + 1 phrase après (si disponible)
3. Concaténer → ~2-3 phrases de contexte

---

## Logique interne du script

```python
def extract_entities(chapters, nlp):
    registry = {}
    entity_counter = 0

    for chapter in chapters:
        doc = nlp(chapter["content"])
        for ent in doc.ents:
            if ent.label_ not in KEPT_LABELS:
                continue
            key = ent.text.lower().strip()
            context = extract_context(doc, ent)

            if key not in registry:
                entity_counter += 1
                registry[key] = {
                    "id": f"entity_{entity_counter:03d}",
                    "raw_mentions": [ent.text],
                    "first_seen": chapter["id"],
                    "mentions_by_chapter": {}
                }
            else:
                if ent.text not in registry[key]["raw_mentions"]:
                    registry[key]["raw_mentions"].append(ent.text)

            registry[key]["mentions_by_chapter"].setdefault(chapter["id"], [])
            registry[key]["mentions_by_chapter"][chapter["id"]].append(context)

    # Restructure: key = entity ID (not normalized text)
    return {"entities": {v["id"]: {k: v[k] for k in v if k != "id"} for v in registry.values()}}
```

---

## Tests

Fichier : `tests/test_entity_extraction.py`

| Test | Description |
|---|---|
| `test_extracts_person_entity` | Extrait une entité PERSON d'un texte simple |
| `test_filters_irrelevant_types` | Filtre DATE, CARDINAL, etc. |
| `test_accumulates_cross_chapter` | Même surface form dans 2 chapitres → 1 entrée, 2 clés dans `mentions_by_chapter` |
| `test_context_max_3_sentences` | Le contexte extrait ne dépasse pas ~3 phrases |
| `test_no_raw_chapter_content` | Aucune valeur dans le registre n'est égale au contenu entier d'un chapitre |

Modèle spaCy pour les tests : `en_core_web_sm` (petit, rapide, pas de download custom en CI).

---

## Pipeline YAML (`.studio/pipelines/wiki-pipeline.pipeline.yaml`)

```yaml
name: wiki-pipeline
description: Generate structured wiki pages from an EPUB book
version: 1

stages:
  - name: epub-parse
    kind: extraction
    executor: script
    command: python scripts/parse_epub.py
    context:
      include:
        - input

  - name: entity-extraction
    kind: extraction
    executor: script
    command: python scripts/entity_extraction.py
    context:
      include:
        - input
        - previous_stage_output

  - name: entity-resolution
    kind: analysis
    agent: resolver
    contract: entity-resolution
    ralph:
      max_attempts: 3
    context:
      include:
        - input
        - previous_stage_output

  - name: wiki-generation
    kind: analysis
    agent: writer
    contract: wiki-generation
    ralph:
      max_attempts: 3
    context:
      include:
        - input
        - previous_stage_output
```

---

## Critères d'acceptation (depuis l'issue)

- [ ] Stage `epub-parse` : découpe un EPUB en chapitres ordonnés, output JSON avec contenu par chapitre
- [ ] Stage `entity-extraction` : détecte entités nommées via spaCy, extrait contexte local (~2-3 phrases), alimente le registre
- [ ] Le registre ne contient jamais le texte brut intégral d'un chapitre
- [ ] Fonctionne sur les 4 livres A Dark and Hollow Star (et le livre FR de test)
- [ ] Les deux stages utilisent `executor: script` (dépend de STU-114)
