# Design — STU-246 : Vérification de cohérence de type NER après clustering

**Date :** 2026-03-08
**Issue :** [STU-246](https://linear.app/studioag/issue/STU-246)
**Statut :** Approuvé

---

## Problème

`fr_core_news_lg` classifie incorrectement certains personnages en PLACE ou ORG. Exemple : `Barrido` (éditeur dans *Le Jeu de l'Ange*) est taggé PLACE à cause de la construction `Barrido & Escobillas` qui ressemble à une raison sociale. Les noms hispaniques peu fréquents en français sont particulièrement vulnérables à ce problème.

Une mauvaise classification de type envoie l'entité dans le mauvais fichier (`places_full.json` au lieu de `persons_full.json`), lui attribue le mauvais template wiki, et l'exclut des relations de co-occurrence PERSON.

---

## Solution retenue : Option B — LLM sur candidats filtrés

Nouveau stage `verify-entity-types` entre `entity-clustering` et `split-clusters` dans `wiki-extraction.pipeline.yaml`. Il identifie les clusters typés PLACE/ORG susceptibles d'être des PERSON, et les soumet à `mistral:7b-instruct` via Ollama avec quelques phrases de contexte.

---

## Architecture

### Placement dans le pipeline

```
epub-parse → entity-extraction → entity-clustering → verify-entity-types → split-clusters
```

Stage script executor standard (stdin/stdout JSON). Quand le flag est désactivé : pass-through pur, zéro overhead.

### Données disponibles

- **Clusters** : via `previous_outputs["entity-clustering"]` (type, canonical_candidate, all_mentions, entity_ids)
- **Contexte textuel** : `places_full.json` et `orgs_full.json` sur disque (écrits par `entity_extraction.py`), indexés par `entity_id`, contiennent `mentions_by_chapter` avec jusqu'à 3 phrases par chapitre

---

## Algorithme

```
Pour chaque cluster typé PLACE ou ORG :

  1. Filtre géographique évident
     Si canonical_candidate contient un mot-clé géographique
     ("rue", "avenue", "église", "quartier", "ville", "boulevard", "place", ...)
     → skip (vrai lieu, pas de vérification LLM nécessaire)

  2. Récupération du contexte
     Lire places_full.json / orgs_full.json, chercher les entity_ids du cluster,
     collecter jusqu'à 3 phrases depuis mentions_by_chapter.
     Si aucun contexte trouvé → skip (pas assez d'info)

  3. Appel Ollama mistral:7b-instruct
     Prompt :
       "Given these sentences from a novel, is '{name}' a person, a place,
        or an organization? Reply with exactly one word: PERSON, PLACE, or ORG.
        Sentences: {context}"

  4. Parse de la réponse
     Chercher PERSON / PLACE / ORG dans le texte retourné (case-insensitive).
     Si PERSON → reclassifier le cluster.
     Sinon → laisser tel quel.

  5. Logging (stderr)
     [VERIFY] Barrido: PLACE → PERSON (context: "Barrido lui tendit la main...")
     [VERIFY] Marlasca: ORG → PERSON (context: "Marlasca dit qu'il reviendrait")
```

**Robustesse :** si Ollama est down ou timeout → warning stderr + pass-through (pas de crash pipeline).

---

## Interface Studio

### Stage YAML (`wiki-extraction.pipeline.yaml`)

```yaml
  - name: verify-entity-types
    kind: extraction
    executor: script
    runtime: python
    script: scripts/verify_entity_types.py
    contract: verify-entity-types
    context:
      include:
        - input
        - previous_stage_output
```

Inséré entre `entity-clustering` et `split-clusters`.

### Input

- `payload["additional_context"]` (YAML) :
  - `verify_entity_types: true` (défaut : false → pass-through)
  - `ollama_model: mistral:7b-instruct` (optionnel, défaut : `mistral:7b-instruct`)
- `payload["previous_outputs"]["entity-clustering"]` : clusters à vérifier

### Output (stdout)

Même structure que la sortie `entity-clustering`, avec un champ additionnel :

```json
{
  "clusters": [...],
  "stats": {...},
  "type_corrections": [
    {"name": "Barrido", "from": "PLACE", "to": "PERSON", "context_snippet": "..."}
  ]
}
```

### Contract (`verify-entity-types.contract.yaml`)

Valide :
- `clusters` est une liste
- `type_corrections` est une liste (peut être vide)

---

## Critères d'acceptation

- [ ] `Barrido` est classifié PERSON dans `entities_classified.json` pour *Le Jeu de l'Ange*
- [ ] Les entités reclassifiées sont loggées avec type original, type corrigé, et snippet de contexte
- [ ] Le stage est activé via `verify_entity_types: true` dans l'input YAML, pass-through sinon
- [ ] Si Ollama est indisponible : warning stderr, pas de crash
- [ ] Pas de régression sur les entités bien classifiées (lieux géographiques filtrés par mots-clés)

---

## Fichiers à créer / modifier

| Fichier | Action |
|---------|--------|
| `scripts/verify_entity_types.py` | Créer |
| `.studio/pipelines/wiki-extraction.pipeline.yaml` | Modifier (insérer stage) |
| `.studio/contracts/verify-entity-types.contract.yaml` | Créer |
