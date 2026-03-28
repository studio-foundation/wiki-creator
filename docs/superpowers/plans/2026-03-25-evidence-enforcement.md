# STU-313 Evidence Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Éliminer les 43% de relations sans `evidence` en corrigeant un faux positif du validator, en complétant le message de feedback, en renforçant le prompt agent, et en ajoutant un log de suivi.

**Architecture:** Trois fichiers touchés — le validator script (fix logique + feedback), l'agent YAML (prompt LLM), et le script de classification (logging). Aucune nouvelle abstraction. TDD sur les deux premiers.

**Tech Stack:** Python 3.11, pytest, YAML

---

## File Map

| Fichier | Action |
|---|---|
| `scripts/relationship_classifier_validator.py` | Modifier `check_evolution_not_generic` + `build_feedback` |
| `tests/test_relationship_classifier_validator.py` | Mettre à jour `test_check_evolution_null_fails` + ajouter test feedback |
| `.studio/agents/relationship-classifier.agent.yaml` | Renforcer prompt + réordonner champs JSON |
| `scripts/relationship_extraction.py` | Ajouter warning log post-classification |

---

## Task 1 : Corriger le faux positif `evolution: null`

**Files:**
- Modify: `tests/test_relationship_classifier_validator.py:31-34`
- Modify: `scripts/relationship_classifier_validator.py:85-91`

### Contexte

Le prompt agent dit explicitement : `"evolution": "..., or null if no change is observable"`. Mais le validator traite `None` comme `""` (via `(clf.get("evolution") or "").strip().lower()`), et `""` est dans `_GENERIC_EVOLUTIONS`. Résultat : `evolution: null` génère un retry inutile qui déstabilise le LLM.

- [ ] **Step 1 : Mettre à jour le test existant**

Le test `test_check_evolution_null_fails` affirme que `evolution: None` doit échouer — c'est le comportement bugué qu'on corrige. Le renommer et inverser son assertion :

```python
# Dans tests/test_relationship_classifier_validator.py, remplacer les lignes 31-34 :

def test_check_evolution_null_passes():
    """evolution: null est explicitement autorisé quand aucune évolution n'est observable."""
    clf = {"relationship_type": "ami", "evolution": None}
    assert check_evolution_not_generic(clf) == []
```

- [ ] **Step 2 : Lancer le test pour vérifier qu'il échoue**

```bash
pytest tests/test_relationship_classifier_validator.py::test_check_evolution_null_passes -v
```

Expected : `FAILED` — `check_evolution_not_generic` retourne une erreur pour `None`.

- [ ] **Step 3 : Corriger `check_evolution_not_generic`**

Dans `scripts/relationship_classifier_validator.py`, remplacer les lignes 85-91 :

```python
def check_evolution_not_generic(clf: dict) -> list[str]:
    if clf.get("relationship_type") is None:
        return []  # null type → evolution non requise
    evol = clf.get("evolution")
    if evol is None:
        return []  # null explicite = valide (aucune évolution observable dans les extraits)
    if evol.strip().lower() in {"relation stable dans les extraits fournis", "relation stable"}:
        return ["❌ evolution générique ou nulle — décris comment la relation évolue concrètement"]
    return []
```

Note : `""` est retiré de l'ensemble — une chaîne vide ne peut plus arriver ici puisqu'on intercepte `None` avant.

- [ ] **Step 4 : Lancer le test pour vérifier qu'il passe**

```bash
pytest tests/test_relationship_classifier_validator.py::test_check_evolution_null_passes -v
```

Expected : `PASSED`

- [ ] **Step 5 : Vérifier que les autres tests passent encore**

```bash
pytest tests/test_relationship_classifier_validator.py -v
```

Expected : tous `PASSED` sauf éventuellement `test_validate_classification_valid` (voir Task 2).

- [ ] **Step 6 : Commit**

```bash
git add scripts/relationship_classifier_validator.py tests/test_relationship_classifier_validator.py
git commit -m "fix(validator): accept evolution: null as valid — removes spurious retry loops"
```

---

## Task 2 : Ajouter `evidence` dans le message de feedback

**Files:**
- Modify: `scripts/relationship_classifier_validator.py:106-114`
- Modify: `tests/test_relationship_classifier_validator.py`

### Contexte

`build_feedback` génère le message de retry envoyé au LLM. Il ne mentionne pas `evidence`. Si le LLM corrige une erreur d'evolution mais oublie `evidence`, la prochaine itération peut être retournée sans evidence.

- [ ] **Step 1 : Écrire le test**

Ajouter à la fin de `tests/test_relationship_classifier_validator.py` :

```python
def test_build_feedback_mentions_evidence():
    """Le message de feedback doit rappeler l'obligation de fournir evidence."""
    from scripts.relationship_classifier_validator import build_feedback
    msg = build_feedback(["❌ evolution générique"])
    assert "evidence" in msg.lower()
```

- [ ] **Step 2 : Lancer le test pour vérifier qu'il échoue**

```bash
pytest tests/test_relationship_classifier_validator.py::test_build_feedback_mentions_evidence -v
```

Expected : `FAILED` — le message actuel ne mentionne pas `evidence`.

- [ ] **Step 3 : Mettre à jour `build_feedback`**

Dans `scripts/relationship_classifier_validator.py`, remplacer les lignes 106-114 :

```python
def build_feedback(errors: list[str]) -> str:
    lines = "\n".join(f"- {e}" for e in errors)
    return (
        "La classification précédente contient les erreurs suivantes. Régénère-la :\n"
        f"{lines}\n\n"
        "Rappels : utilise uniquement les types autorisés "
        "(famille|mentor/protégé|amoureux|antagoniste|allié|employeur/employé|ami|connaissance|autre). "
        "evolution doit décrire une évolution observable dans les extraits, pas une phrase générique. "
        "evidence doit être un extrait verbatim de sample_contexts montrant les deux personnages "
        "en interaction directe — ce champ est obligatoire quand relationship_type n'est pas null."
    )
```

- [ ] **Step 4 : Lancer le test pour vérifier qu'il passe**

```bash
pytest tests/test_relationship_classifier_validator.py::test_build_feedback_mentions_evidence -v
```

Expected : `PASSED`

- [ ] **Step 5 : Lancer la suite complète**

```bash
pytest tests/test_relationship_classifier_validator.py -v
```

Expected : tous `PASSED`.

- [ ] **Step 6 : Commit**

```bash
git add scripts/relationship_classifier_validator.py tests/test_relationship_classifier_validator.py
git commit -m "fix(validator): remind LLM about evidence requirement in retry feedback"
```

---

## Task 3 : Renforcer le prompt agent

**Files:**
- Modify: `.studio/agents/relationship-classifier.agent.yaml`

### Contexte

Le prompt agent mentionne `evidence` en bas de la liste des règles. Deux ajustements : (1) ajouter une ligne `REQUIRED` explicite juste avant la structure JSON, (2) déplacer `evidence` en deuxième position dans le JSON pour que le LLM le génère tôt dans sa réponse séquentielle.

Pas de test unitaire possible sur le YAML — vérification manuelle de la structure.

- [ ] **Step 1 : Modifier le system_prompt**

Dans `.studio/agents/relationship-classifier.agent.yaml`, trouver le bloc `Return exactly:` (ligne 48) et le remplacer par :

```yaml
  REQUIRED when relationship_type is not null: the "evidence" field must be a verbatim sentence
  from sample_contexts showing both entity_a and entity_b in direct interaction. Do NOT omit it.

  Return exactly:
  {
    "relationship_type": "famille|mentor/protégé|amoureux|antagoniste|allié|employeur/employé|ami|connaissance|autre|null",
    "evidence": "verbatim sentence or short passage from sample_contexts that best demonstrates the direct interaction between entity_a and entity_b — must contain both names or clear references to both",
    "direction": "symétrique|A→B|B→A|null",
    "evolution": "one sentence describing HOW the relationship changes across the provided chapters, or null if no change is observable — do NOT write \"relation stable\" or any equivalent filler",
    "key_moments": ["chXX: short description"]
  }
```

Supprimer l'ancienne ligne `"evidence": ...` qui était en cinquième position.

- [ ] **Step 2 : Vérifier la cohérence du fichier YAML**

```bash
python -c "import yaml; yaml.safe_load(open('.studio/agents/relationship-classifier.agent.yaml'))" && echo "YAML valide"
```

Expected : `YAML valide`

- [ ] **Step 3 : Commit**

```bash
git add .studio/agents/relationship-classifier.agent.yaml
git commit -m "feat(agent): mark evidence as REQUIRED and move it early in JSON schema"
```

---

## Task 4 : Ajouter le logging post-classification

**Files:**
- Modify: `scripts/relationship_extraction.py:1024-1041`

### Contexte

Ajouter deux niveaux de log dans `classify_relationships` : un warning par paire (ligne) et un résumé agrégé en fin de fonction. Cela remplace le besoin d'un script externe pour mesurer le taux d'absence.

Pas de test unitaire ajouté — la fonction est testée par intégration. Le logging va sur `stderr` comme les autres warns du fichier.

- [ ] **Step 1 : Mettre à jour `classify_relationships`**

Dans `scripts/relationship_extraction.py`, remplacer les lignes 1024-1041 :

```python
        if classification and not classification.get("error"):
            rel = {
                **rel,
                "relationship_type": classification.get("relationship_type"),
                "direction": classification.get("direction"),
                "evolution": classification.get("evolution"),
                "key_moments": classification.get("key_moments", []),
                "evidence": classification.get("evidence"),
            }
            if rel["relationship_type"] and not rel["evidence"]:
                print(
                    f"  [WARN] evidence absent pour {rel['entity_a']} ↔ {rel['entity_b']} "
                    f"(type={rel['relationship_type']})",
                    file=sys.stderr,
                )
        else:
            print(
                f"  [WARN] Studio classification failed for "
                f"{rel['entity_a']}↔{rel['entity_b']}: "
                f"{classification.get('error', 'unknown')}",
                file=sys.stderr,
            )
        result.append(rel)

    missing = sum(
        1 for r in result
        if r.get("relationship_type") and not r.get("evidence")
    )
    total_typed = sum(1 for r in result if r.get("relationship_type"))
    if missing:
        print(
            f"  [WARN] evidence absent : {missing}/{total_typed} relations classifiées",
            file=sys.stderr,
        )
    return result
```

- [ ] **Step 2 : Lancer les tests**

```bash
pytest -q
```

Expected : `485 passed` (ou plus si les tâches précédentes ont ajouté des tests).

- [ ] **Step 3 : Commit**

```bash
git add scripts/relationship_extraction.py
git commit -m "feat(classify): log missing evidence per pair and as aggregate summary"
```

---

## Vérification finale

- [ ] **Lancer la suite complète**

```bash
pytest -q
```

Expected : tous les tests passent. Le nombre de tests doit avoir augmenté de 2 (Task 1 + Task 2).
