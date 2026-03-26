# Design — STU-313 : Enforcement du champ `evidence` dans relationship-classifier

**Date :** 2026-03-25
**Issue :** STU-313
**Contexte :** Run 13 — 69/159 relations (43%) sans champ `evidence`. Dégradation par rapport au Run 8 (37%).

---

## Problème

Le champ `evidence` (citation verbatim justifiant la relation) est absent pour près de la moitié des relations classifiées. Deux causes identifiées :

1. **Faux positif sur `evolution: null`** — Le validator rejette `evolution: null` (valeur pourtant explicitement autorisée dans le prompt agent), ce qui génère des retries inutiles. Lors de ces retries, le LLM peut omettre `evidence` sans que le feedback le lui rappelle.

2. **`build_feedback` ne mentionne pas `evidence`** — Quand le feedback de retry est généré, il ne rappelle pas l'obligation de fournir un extrait verbatim pour `evidence`. Le LLM peut corriger l'erreur signalée tout en oubliant `evidence`.

---

## Solution retenue : Option B — Fix validator + renforcement prompt agent

### 1. Correction du validator (`scripts/relationship_classifier_validator.py`)

**Fix faux positif `evolution: null` :**
- `check_evolution_not_generic` accepte `None` comme valeur valide
- Seules les chaînes vides et formulations génériques restent rejetées
- `_GENERIC_EVOLUTIONS` retire `""` (qui ne peut plus apparaître après le fix)

**Fix `build_feedback` :**
- Ajouter un rappel explicite : `evidence` doit être un extrait verbatim de `sample_contexts` montrant les deux personnages en interaction directe

### 2. Renforcement du prompt agent (`.studio/agents/relationship-classifier.agent.yaml`)

- Ajouter une ligne `REQUIRED` explicite avant la structure JSON de retour : `evidence` est obligatoire quand `relationship_type` n'est pas null
- Déplacer `evidence` en deuxième position dans la structure JSON de retour (juste après `relationship_type`) pour que le LLM le génère tôt dans sa réponse séquentielle

### 3. Logging post-classification (`scripts/relationship_extraction.py`)

- Warning par paire : `[WARN] evidence absent pour X ↔ Y (type=...)` sur stderr
- Résumé agrégé en fin de run : `[WARN] evidence absent : N/M relations classifiées`
- Permet de mesurer le taux directement dans les logs Studio sans script externe

---

## Fichiers modifiés

| Fichier | Changement |
|---|---|
| `scripts/relationship_classifier_validator.py` | Fix faux positif `evolution: null` + feedback |
| `.studio/agents/relationship-classifier.agent.yaml` | Marquage REQUIRED + ordre champs JSON |
| `scripts/relationship_extraction.py` | Warning log post-classification |

## Fichiers non modifiés

- `.studio/contracts/relationship-classifier-item.contract.yaml` — `evidence` est déjà dans `required_fields`
- `.studio/pipelines/relationship-classifier-item.pipeline.yaml` — pipeline inchangé

---

## Tests

- Les tests existants dans `tests/test_relationship_classifier_validator.py` doivent couvrir les nouveaux cas : `evolution: null` valide, feedback mentionnant `evidence`
- Ajouter des cas de test pour : `evolution=None` avec `relationship_type` non null → `valid: true`
