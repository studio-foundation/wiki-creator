# Design : Détection narrateur + biais POV (STU-235)

## Contexte

Certains romans utilisent un narrateur à la première personne subjectif (ex: *Le Jeu de l'Ange* — David Martín). Le wiki doit distinguer les faits observables des descriptions filtrées par le prisme du narrateur, et signaler la non-fiabilité quand elle est détectable.

**Dépend de :** STU-229 (coréférence pronominale — déjà mergé)

---

## Architecture : deux couches

| Couche | Où | Quoi |
|--------|----|------|
| Déterministe | `parse_epub.py` | Comptage de pronoms → POV détecté |
| LLM | `resolver.agent.yaml` | Identification narrateur + fiabilité |

---

## Section 1 — `parse_epub.py` : détection POV

Après extraction des chapitres, comptage des pronoms de première personne (`je/me/moi/m'/mon/ma/mes`) sur le texte brut concaténé.

**Seuils :**
- `first_person_count / total_tokens > 0.01` → `first_person`, `confidence: "high"`
- `0.005 – 0.01` → `first_person`, `confidence: "medium"`
- `< 0.005` → analyse troisième personne (patterns `il pensait que`, `elle savait que`)
  - Si un seul personnage → `third_limited`
  - Sinon → `omniscient`

**Champ ajouté à l'output existant :**
```json
{
  "title": "...",
  "author": "...",
  "chapters": [...],
  "pov_detection": {
    "pov": "first_person",
    "first_person_count": 847,
    "total_tokens": 98420,
    "confidence": "high"
  }
}
```

---

## Section 2 — `entity-resolution` : identification du narrateur (LLM)

### Pipeline YAML

Ajouter `epub-parse` au `context.include` du stage `entity-resolution` pour que le resolver reçoive `pov_detection`.

```yaml
- name: entity-resolution
  context:
    include:
      - input
      - epub-parse          # nouveau
      - previous_stage_output
```

### `resolver.agent.yaml`

Ajout au prompt : si `pov: "first_person"`, identifier l'entité PERSON dont les contextes de mention contiennent le plus de `je/me/moi` comme sujet/objet. Évaluer la fiabilité à partir des contradictions et hallucinations visibles dans les excerpts.

**Output — champ `narrator` ajouté au top-level :**
```json
{
  "entities": [...],
  "narrator": {
    "entity": "David Martín",
    "pov": "first_person",
    "reliability": "unreliable",
    "evidence": ["ch20: hallucinations décrites explicitement", "ch25: contradiction avec ch8 sur Corelli"]
  }
}
```

`reliability` : `"reliable"` | `"unreliable"` | `"partial"`. Null si POV omniscient ou troisième personne.

### `entity-resolution.contract.yaml`

Ajouter `narrator` aux champs du schema (nullable).

---

## Section 3 — `relationship_extraction.py` : pass-through

Lire `narrator` depuis `previous_outputs["entity-resolution"]` et l'inclure dans l'output sans modification.

```python
output["narrator"] = entity_resolution_output.get("narrator")
```

**Contract `relationship-extraction`** : ajouter `narrator` (nullable).

---

## Section 4 — `writer.agent.yaml` : adaptation du ton

Le writer lit `previous_stage_output["narrator"]`.

**Si `narrator` non-null et `reliability` = `"unreliable"` ou `"partial"` :**
- Descriptions de personnages via le narrateur → préfixer avec `"Selon [narrator.entity], ..."` ou `"D'après le récit de [narrator.entity], ..."`
- Faits observables (dialogue, actions physiques, dates, lieux) → affirmation directe
- Contradictions entre chapitres → noter les deux versions
- Pages de personnages décrits presque exclusivement via le narrateur → note éditoriale en tête de page :
  > "Note : les informations sur ce personnage proviennent principalement du récit de [narrator.entity], dont la fiabilité est contestée ([premier item d'evidence])."

**Si `narrator` null ou `reliability` = `"reliable"` :**
- Ton encyclopédique standard, aucune attribution nécessaire.

**Distinction observable vs subjectif** : le LLM distingue dialogue/actions (objectif) des descriptions internes (`il semblait`, `je le voyais comme`) qui sont subjectives.

---

## Fichiers modifiés

| Fichier | Changement |
|---------|------------|
| `scripts/parse_epub.py` | Ajouter `pov_detection` à l'output |
| `.studio/pipelines/wiki-pipeline.pipeline.yaml` | Ajouter `epub-parse` au context de `entity-resolution` |
| `.studio/agents/resolver.agent.yaml` | Étendre le prompt pour identifier narrateur + fiabilité |
| `.studio/contracts/entity-resolution.contract.yaml` | Ajouter `narrator` (nullable) |
| `scripts/relationship_extraction.py` | Pass-through du champ `narrator` |
| `.studio/contracts/relationship-extraction.contract.yaml` | Ajouter `narrator` (nullable) |
| `.studio/agents/writer.agent.yaml` | Étendre le prompt pour adapter le ton |
