# Design : Stage `relationship-extraction` (STU-229)

**Date :** 2026-03-05
**Ticket :** [STU-229](https://linear.app/studioag/issue/STU-229)
**Scope :** Cooccurrence pure + classification LLM. Coréférence pronominale hors scope → STU-230.

---

## Contexte

Le pipeline extrait et résout des entités, mais ne capture pas les **relations entre personnages**. Ce stage ajoute un graphe pondéré de relations basé sur la cooccurrence dans des fenêtres glissantes de phrases, avec classification LLM optionnelle.

---

## Position dans le pipeline

```
epub-parse → entity-extraction → entity-clustering → entity-resolution
→ relationship-extraction → wiki-generation
```

---

## Fichiers créés / modifiés

| Fichier | Action |
|---------|--------|
| `scripts/relationship_extraction.py` | Nouveau |
| `.studio/contracts/relationship-extraction.contract.yaml` | Nouveau |
| `.studio/pipelines/wiki-pipeline.pipeline.yaml` | Ajout du stage |
| `wiki_creator/types.py` | Nouveau type `ExtractedRelationship` |
| `.studio/agents/writer.agent.yaml` | Ajout consommation des relations |
| `pyproject.toml` | Ajout `anthropic>=0.40` |

---

## Interface du script

```bash
# Mode Studio (stdin JSON)
echo '{"previous_outputs": {...}, "additional_context": "..."}' | python scripts/relationship_extraction.py

# Mode test standalone
python scripts/relationship_extraction.py --test

# Mode test avec classification LLM
python scripts/relationship_extraction.py --test --classify

# Paramètres configurables (avec valeurs par défaut)
python scripts/relationship_extraction.py --test --window 5 --threshold 5
```

---

## Input

- `previous_outputs.entity-resolution.entities` — liste des entités résolues (`canonical_name`, `type`, `aliases`, `source_ids`, `relevant`)
- Fichiers repo lus via chemin relatif : `persons_full.json`, `places_full.json`, `orgs_full.json`

---

## Output JSON

```json
{
  "relationships": [
    {
      "entity_a": "David Martín",
      "entity_b": "Pedro Vidal",
      "cooccurrence_count": 45,
      "chapters": ["ch01", "ch03", "ch05"],
      "sample_contexts": [
        "Vidal tendit le manuscrit à Martín en souriant...",
        "Martín retrouva Vidal au café..."
      ],
      "relationship_type": "mentor/protégé",
      "direction": "Vidal → Martín",
      "evolution": "Commence comme mentor bienveillant, devient rival",
      "key_moments": ["ch01: Vidal encourage Martín à écrire", "ch15: rupture"]
    }
  ],
  "stats": {
    "total_pairs_checked": 120,
    "pairs_above_threshold": 18,
    "classified": 18,
    "window_size": 5,
    "threshold": 5
  }
}
```

Les champs `relationship_type`, `direction`, `evolution`, `key_moments` sont `null` si `--classify` n'est pas activé.

---

## Algorithme de cooccurrence

1. **Corpus** — pour chaque entité résolue `relevant: true` de type PERSON, récupérer les `mentions_by_chapter` depuis les fichiers full.
2. **Fenêtre glissante** — itérer sur les phrases par chapitre avec une fenêtre de taille N (défaut 5). Pour chaque fenêtre, collecter les entités présentes.
3. **Matching** — via `canonical_name` et `aliases`. Aliases de moins de 4 caractères ignorés (risque de faux positifs).
4. **Matrice** — pour chaque paire dans une fenêtre, incrémenter le compteur. Stocker le chapitre et un sample de contexte.
5. **Filtrage** — paires sous le seuil (défaut 5, configurable) exclues.
6. **Tri** — par `cooccurrence_count` décroissant.

**Complexité :** O(E² × C) — négligeable pour un roman standard (~50 entités PERSON, ~30 chapitres).

---

## Classification LLM

**Déclenchement :** flag `--classify` en mode test, ou `"classify": true` dans `additional_context` en mode Studio.

**Modèle :** Haiku via SDK `anthropic` directement (pas via agent Studio).

**Prompt :** pour chaque paire au-dessus du seuil, envoi des 3 contextes les plus représentatifs. Classification en : `famille | mentor/protégé | amoureux | antagoniste | allié | employeur/employé | ami | connaissance | autre`.

**Résilience :** si l'API échoue pour une paire, les champs LLM restent `null` — le script ne plante pas.

---

## Pipeline YAML

```yaml
- name: relationship-extraction
  kind: analysis
  executor: script
  runtime: python
  script: scripts/relationship_extraction.py
  contract: relationship-extraction
  context:
    include:
      - input
      - previous_stage_output
```

## Contract

```yaml
name: relationship-extraction
version: 1
schema:
  required_fields:
    - relationships
    - stats
```

---

## Intégration wiki-generation

Le writer agent reçoit `relationship-extraction` dans son contexte. Pour chaque page PERSON, si des relations existent pour l'entité, ajouter une section "Relations" listant les personnages liés avec leur type de relation et direction.

---

## Tests

Mode `--test` avec données hardcodées simulant *Le Jeu de l'Ange*. Critères de succès :
- Top 20 inclut les 4 paires attendues : Martín↔Vidal, Martín↔Corelli, Martín↔Isabella, Martín↔Cristina
- Stats cohérentes (total_pairs_checked > 0, seuil respecté)
- Avec `--classify` : les 4 paires ont un `relationship_type` non-null

---

## Hors scope (STU-230)

Résolution pronominale (coréférence) — `coreferee` ou BookNLP-fr. Sera ajoutée comme enrichissement optionnel (`--coref`) dans STU-230, sans modifier l'interface de STU-229.
