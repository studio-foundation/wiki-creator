# STU-468 — Désambiguïsation d'entités sémantique (embeddings)

**Status:** design approuvé (2026-07-12)
**Issue:** [STU-468](https://linear.app/studioag/issue/STU-468)
**Deps:** STU-441/442 (EntityRegistry, Done)

## Problème

La désambiguïsation d'entités est aujourd'hui **purement lexicale** : Jaro-Winkler
([entity_clustering.py](../../../scripts/entity_clustering.py)), apposition/co-occurrence/role-signatures
([alias_resolution.py](../../../scripts/alias_resolution.py)). Deux limites de construction :

1. **Missed merges** — des formes sans recouvrement de caractères (« l'assassine » / « Celaena »)
   ne peuvent *par construction* être fusionnées par du lexical.
2. **Faux merges résiduels** — les paires ambiguës (reveal / role-symmetric) reposent sur un
   confirmateur LLM Ollama ; les confusions survivantes sont ce que STU-318/319 détectent en
   post-génération (ex. Duke Perrington vs Crown Prince Dorian).

## Cadrage (MVP)

**Scope = fusion.** La strategie embedding joue deux rôles, tous deux dans `resolve_aliases`,
tous deux sur la surface *merge* existante (`MergeDecision` est merge-only par construction) :

| Rôle | Quoi | Adresse |
|---|---|---|
| **Proposeur** | Nouveau détecteur, attrape les aliases sans recouvrement char | Missed merges (l'unlock unique des embeddings) |
| **Veto** | Avant un merge ambigu, exige similarité contexte ≥ seuil ; sinon bloque | Faux merges (le pain STU-318/319) |

**Non-goals (YAGNI, explicites) :**
- Séparation d'entités déjà fusionnées upstream → issue de suivi (pas de record `split` dans
  `MergeDecision`, split vit dans le stage extraction en amont, gros blast radius).
- Embeddings pour non-PERSON.
- Représentation hybride centroïde+max.
- Cache disque des vecteurs.
- Remplacement du LLM-confirmer (reste fallback optionnel).

## Décisions de design

| Décision | Choix | Raison |
|---|---|---|
| Modèle | `intfloat/multilingual-e5-small` (118M) | FR+EN, rapide sur 3060, fort en similarité sémantique |
| Préfixe e5 | `passage:` sur chaque contexte | requis par la famille e5 |
| Représentation | **Centroïde mean-pool** L2-normalisé, 1 vec/entité | robuste, cheap, precompute une fois/run |
| Comparaison | cosine(centroïde_A, centroïde_B) | standard |
| Intégration | fonctions dans le ladder `resolve_aliases` | pas de classe `MergeStrategy` dans le repo ; matche l'infra existante |
| Trace | evidence dict → `MergeDecision(strategy="embedding_disambiguation")` | champ `strategy` free-form, zéro changement de schéma |
| Device | idiome `_resolve_coref_device` (cuda si dispo, sinon cpu) | cohérent avec coref |
| Dépendance | extra optionnel `embeddings`, opt-in book YAML | miroir de l'extra `coref`, backward-compat |

## Architecture

### Nouveau module pur : `wiki_creator/embedding_disambiguation.py`

Aucun import pipeline (testable isolément, comme `relationship_fold.py`). Import du module
ne tire **pas** torch (import lazy dans `EmbeddingBackend.__init__`).

```python
DEFAULT_MODEL = "intfloat/multilingual-e5-small"
DEFAULT_PROPOSE_THRESHOLD = 0.86   # tuné sur golden pairs
DEFAULT_VETO_THRESHOLD    = 0.80

@dataclass(frozen=True)
class Verdict:
    decision: str        # "merge" | "abstain"
    score: float
    method: str = "embedding_disambiguation"
    confidence: str = "medium"   # dérivé du score

class EmbeddingBackend:
    def __init__(self, model_name=DEFAULT_MODEL, device=None): ...
    def resolve_device(self, explicit): ...            # mirror _resolve_coref_device
    def encode(self, texts: list[str]) -> np.ndarray:  # prefix "passage:", L2-norm
        ...

def entity_centroid(contexts: list[str], backend) -> "np.ndarray | None": ...  # None si 0 contexte
def cosine(a, b) -> float: ...

class EmbeddingJudge:
    def __init__(self, backend, propose_threshold, veto_threshold): ...
    def build_centroids(self, entities: list[dict]) -> dict[str, "np.ndarray"]: ...
    def propose(self, id_a, id_b, centroids) -> Verdict: ...
    def veto(self, id_a, id_b, centroids) -> bool:  # True = bloque le merge
        ...
```

### Modifs chirurgicales : `scripts/alias_resolution.py`

- `main()` : lit `ctx.get("embedding_disambiguation", {})` ; construit `EmbeddingJudge` seulement
  si `enabled: true` ; `try/except ImportError` → warning + `judge=None` (dégrade, run continue).
- `resolve_aliases(...)` : nouveau param `judge=None`. Si `None`, comportement **bit-identique** à
  aujourd'hui (backward-compat total). Precompute centroïdes une fois. Deux points d'ancrage :
  1. **Veto** enveloppe la branche paires ambiguës (reveal/role-symmetric,
     [alias_resolution.py:762-833](../../../scripts/alias_resolution.py)) : `judge.veto(A,B)` True → SKIP
     immédiat (pas de merge, pas d'appel LLM). False → flux LLM existant inchangé (fallback).
  2. **Proposeur** `_detect_embedding_alias(id_a, id_b, judge, centroids) -> dict | None` ajouté
     **en dernier** dans le ladder (après tous les lexicaux). Même shape de retour que les autres
     `_detect_*` (`{method, confidence, snippet}` ou `None`).
- Contextes réutilisent `_gather_contexts`/`_load_persons_full`
  ([147-180](../../../scripts/alias_resolution.py)) — pas de nouvelle lecture de fichier.

## Flux de données

```
persons_full.json (mentions_by_chapter: contextes phrases)
        │  _gather_contexts (existant)
        ▼
judge.build_centroids(entities)          # 1 seul encode batch, tous contextes
        │  {entity_id: centroid_vec}      # cache mémoire, durée du run
        ▼
pour chaque paire PERSON (A,B):
   ladder lexical ─ pattern/title/pure_title ─► merge si hit
                  └ branche ambiguë (reveal/role_symmetric):
                         judge.veto(A,B)? ──oui──► SKIP (bloque, pas de LLM)
                                          └─non──► flux LLM existant (fallback)
   si aucun hit lexical:
         _detect_embedding_alias ─ cosine ≥ τ_propose ─► merge (embedding_disambiguation)
        ▼
_merge_entities (existant) ─► bloc alias_resolution sur l'entité
        ▼ (write-registry, plus tard)
Registry.from_artifacts ─► MergeDecision(strategy="embedding_disambiguation", evidence, confidence)
```

Le GPU est touché **une fois** par run (batch unique), puis pure algèbre. N (PERSON) ~ dizaines à
centaines → matrice cosine N×N triviale.

## Config

### Book YAML — nouveau bloc (opt-in)

```yaml
embedding_disambiguation:
  enabled: false            # défaut off (backward-compat)
  model: intfloat/multilingual-e5-small
  device: null              # null = auto
  propose_threshold: 0.86
  veto_threshold: 0.80
```

Seuils = numériques (pas du lexique) → OK en YAML/constantes, ne viole pas l'invariant cue_words.

### `pyproject.toml` — extra optionnel

```toml
[project.optional-dependencies]
embeddings = ["sentence-transformers>=3", "numpy>=1.24"]
```

`pip install -e ".[embeddings]"`. Miroir de l'extra `coref`.

## Dégradation gracieuse

| Cas | Comportement |
|---|---|
| deps manquantes, `enabled:true` | warning stderr, `judge=None`, run continue |
| CUDA OOM / device fail | catch, fallback cpu, warning |
| modèle download échoue (offline) | ImportError-like, dégrade |
| entité 0 contexte (centroïde None) | skip paire, jamais merge/veto |
| `enabled:false` (défaut) | chemin actuel intact, sortie bit-identique |

## Éval

### Golden pairs — `tests/fixtures/embedding_golden_pairs.json`

Paires PERSON de throne-of-glass, label + contextes réels extraits des `persons_full.json`
committés (~15-25 paires, mix same/different, incluant les pièges connus) :

```json
[
  {"a": "celaena", "b": "l-assassine", "label": "same", "note": "unlock: zero char commun"},
  {"a": "perrington", "b": "duke", "label": "same"},
  {"a": "dorian", "b": "crown-prince", "label": "same"},
  {"a": "perrington", "b": "dorian", "label": "different", "note": "ex-STU-430, Duke vs Crown Prince"},
  {"a": "celaena", "b": "chaol", "label": "different"}
]
```

### Métrique

Pour chaque paire, `judge` → merge/abstain. Rapport precision/recall/F1 sur `same`.

### Tuning des seuils — `scripts/tune_embedding_thresholds.py` (dev-only, hors pipeline)

Sweep τ sur golden pairs, imprime precision/recall par seuil, choisit τ_propose (haute précision,
évite faux merges) et τ_veto (haute recall du « different »). Les valeurs gagnantes deviennent les
défauts constantes.

### Critère de succès

Sur golden pairs : Celaena/l'assassine mergé (unlock prouvé), Perrington/Dorian jamais mergé (veto
tient), zéro régression Run 16. Bonus non-bloquant : si sortie STU-318/319 dispo sur un run réel,
valider que les confusions flaggées baissent. Golden pairs = la porte.

## Tests

### Unitaires — `tests/test_embedding_disambiguation.py` (backend mocké, CI)

- `entity_centroid` : mean-pool correct, L2-normalisé, `None` sur 0 contexte.
- `cosine` : identiques=1.0, orthogonaux=0, symétrie.
- `EmbeddingJudge.propose` : ≥τ→merge, <τ→abstain, confidence dérivée du score.
- `EmbeddingJudge.veto` : dissimilaire→True (bloque), similaire→False.
- Golden pairs precision/recall (vecteurs mockés déterministes par paire).
- Dégradation : deps absentes→ImportError propre ; centroïde None→pas de verdict.
- Test réel modèle marqué `@requires_embeddings` (skip si extra absent, aligné sur `_markers.py`
  comme `coref`).

### Intégration — `tests/test_alias_resolution.py` (existant)

- `judge=None` → sortie **bit-identique** à aujourd'hui (backward-compat).
- Veto : paire ambiguë + judge dissimilaire → pas de merge, LLM jamais appelé.
- Proposeur : paire sans signal lexical + judge similaire → merge, méthode `embedding_disambiguation`.
- **Run 16 régression** ([test_alias_resolution.py:1280](../../../tests/test_alias_resolution.py)) reste
  vert avec judge actif — Perrington/Dorian pas mergé.

### Registry — `tests/test_registry.py`

- `MergeDecision(strategy="embedding_disambiguation")` round-trip + reconstruit par `from_artifacts`.

## Fichiers touchés

| Fichier | Nature |
|---|---|
| `wiki_creator/embedding_disambiguation.py` | nouveau, module pur |
| `scripts/alias_resolution.py` | modifs chirurgicales (`main`, `resolve_aliases`, `_detect_embedding_alias`) |
| `scripts/tune_embedding_thresholds.py` | nouveau, dev-only |
| `pyproject.toml` | extra `embeddings` |
| `tests/test_embedding_disambiguation.py` | nouveau |
| `tests/test_alias_resolution.py` | +cas veto/proposeur/backward-compat |
| `tests/test_registry.py` | +round-trip strategy |
| `tests/fixtures/embedding_golden_pairs.json` | nouveau |
| book YAML (throne-of-glass) | bloc `embedding_disambiguation` opt-in |
