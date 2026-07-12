# STU-442 — EntityRegistry pas 2 : les stratégies de fusion émettent des `MergeDecision`

> Validé le 2026-07-12 avec Ariane. Base : STU-441 (pas 1) mergé dans `main`
> (`wiki_creator/registry.py` en lecture seule + `write-registry` stage).
> Spec programme : `docs/superpowers/specs/2026-07-11-refondation-wiki-creator-design.md`
> §3.5 pas 2, §3.4 (API `merge`), §3.7 (tests), §4 (comparaison canonique du test d'or).
> Linear : [STU-442](https://linear.app/studioag/issue/STU-442) —
> branche `arianedguay/stu-442-entityregistry-pas-2-les-strategies-de-fusion-emettent-des`.

## 1. Objectif

Faire respecter la règle unique du milestone : **plus personne ne fusionne deux
noms sans passer par `registry.merge(a, b, decision)`**. Les mécanismes de fusion
existants deviennent des `MergeStrategy` qui *proposent* des `MergeDecision` au
registre ; le registre trace tout (`audit_log()`).

Bénéfice immédiat : « Pourquoi Crown Prince est chez Perrington ? » devient une
lecture de `registry.json` (stratégie + évidence + confiance) au lieu d'une
session d'archéologie. Les mauvais merges deviennent diffables entre deux runs.

Filet de sécurité : **test d'or** — le registre reconstruit sur les fixtures Run 16
produit une projection identité identique (comparaison canonique : tri +
normalisation, pas diff brut). La suite existante reste verte.

## 2. Décisions de design (validées 2026-07-12)

1. **Émission hybride.** `alias_resolution.py` porte déjà une provenance riche
   (`method`/`confidence`/`snippet`/`merged_from`) → ses décisions portent une
   **évidence réelle**. Le clustering Jaro-Winkler jette tout (`should_cluster_jw`
   ne renvoie qu'un `bool` dans une boucle Union-Find) → `cluster_jw` reste
   **reconstruit** depuis `splits.json`. Faire remonter le score JW hors du hot
   path est coûteux et à faible valeur pour des variantes de surface (M2).
2. **Chemin de production inchangé.** `entities_classified.json` continue d'être
   produit par `entity_classification.py` ; la consommation aval est pas 3
   (STU-435, via `alias_table()`) puis pas 4. En pas 2, rien ne consomme encore
   le registre — c'est une addition.
3. **Politique de conflit = tie-break déterministe.** Quand `merge()` ajoute un
   alias déjà revendiqué par une tierce entité : propriétaire canonique gagne →
   sinon plus grand nombre de mentions → sinon ordre d'apparition. Le perdant
   lâche l'alias + sa décision orpheline ; un `warning` est journalisé. Même règle
   que `_resolve_alias_collisions` aujourd'hui, remontée dans `merge()`.
4. **Pas d'enregistrement des rejets (YAGNI).** Seules les fusions effectivement
   appliquées produisent une `MergeDecision`. Les rejets Ollama restent absents du
   registre (comme aujourd'hui). L'artefact répond « pourquoi X est alias de Y »,
   pas « pourquoi X n'est pas fusionné avec Y ».
5. **Périmètre contenu.** Toute la modif tient dans `wiki_creator/registry.py` +
   le nouveau `wiki_creator/merge_strategies.py` + fixtures/tests. **Aucun script
   de production n'est touché** — cohérent avec « refonte des stages = M2 » (§3.6).

## 3. Architecture : un seul chemin de fusion

Aujourd'hui il existe **deux** implémentations de fusion de facto : les stages
live (clustering + alias-resolution) et la logique de reconstruction ad hoc dans
`from_artifacts` (`_merge_duplicate_canonicals` + `_resolve_alias_collisions` +
synthèse de décision par alias). Pas 2 les réduit à **une** primitive.

```
                    ┌─────────────────────────────────────────────┐
   splits.json ─────▶                                              │
   alias output ────▶  MergeStrategy layer  ──▶ propose            │
   *_full.json ─────▶  (merge_strategies.py)    MergeDecision(s)   │
                    └───────────────────────────────┬─────────────┘
                                                     ▼
                              Registry.merge(a, b, decision)   ◀── SEULE mutation
                                 (registry.py, NOUVEAU)            primitive ; la
                                                     │             politique de
                                                     ▼             conflit vit ici
                                 Registry  ──▶ registry.json (artefact inchangé)
                                           ──▶ to_entities_classified() ──▶ test d'or
```

Le mouvement clé : **`from_artifacts` devient un client de `merge()`**, pas une
implémentation de fusion parallèle. C'est ce qui rend « un seul chemin de fusion »
littéralement vrai, gardé par les 16 tests registry existants + le test d'or.

### Unités nouvelles / modifiées

| Unité | Changement | Rôle |
|---|---|---|
| `registry.py` → `Registry.merge()` | **nouvelle méthode** | primitive de mutation unique ; politique de conflit tie-break déterministe |
| `registry.py` → `from_artifacts` | **refactor** | ne construit plus les fusions à la main ; propose via stratégies, applique chaque décision via `self.merge()` |
| `registry.py` → `to_entities_classified()` | **nouvelle méthode** | projection vers la forme entité identité (test d'or + bascule pas 4 plus tard) |
| `merge_strategies.py` | **nouveau module** | protocole `MergeStrategy` + stratégies concrètes ; possède le vocabulaire de noms de stratégie |
| `tests/fixtures/registry_run16/` + `tests/test_registry_golden.py` | **nouveau** | bundle d'artefacts curé + test d'équivalence canonique |
| `tests/test_registry.py` / `test_merge_strategies.py` | **nouveaux tests** | `merge()` + conflits, vocabulaire de stratégie |

## 4. Le layer `MergeStrategy`

Nouveau module `wiki_creator/merge_strategies.py`. Compte tenu de la décision
hybride + la frontière « pas de refonte de stage (M2) », les stratégies sont des
**fabriques/normaliseurs de décision**, pas des détecteurs réimplémentés : elles
prennent le signal qu'un détecteur a déjà produit et le transforment en
`MergeDecision` normalisée. Elles possèdent aussi les deux stratégies de
*reconstruction* utilisées par `from_artifacts`.

```python
class MergeStrategy(Protocol):
    name: str
    def propose(self, survivor_id, absorbed, *, evidence, confidence,
                chapter_id=None) -> MergeDecision: ...
```

Vocabulaire — un mapping explicite unique (méthode enregistrée → nom de stratégie
spec), pour que `registry.json` parle une seule langue :

| Signal source | chaîne pas-1 (aujourd'hui) | stratégie pas-2 | fidélité évidence |
|---|---|---|---|
| Cluster Jaro-Winkler (`splits.json`) | `cluster_jw` | `cluster_jw` | reconstruite |
| `_detect_title_alias` | `title_alias` | **`title_apposition`** | réelle (+chapter_id) |
| `_detect_pure_title_in_context` | `pure_title` | `pure_title` | réelle (+chapter_id) |
| `_detect_role_symmetric_pairs` | `role_symmetric` | `role_symmetric` | réelle |
| Confirmation Ollama | `llm` | **`llm_confirm`** | réelle |
| `_detect_pattern_match` | `pattern` | `pattern` (conservé) | réelle |
| `_detect_reveal_signal` | `cooccurrence` | `cooccurrence` (conservé) | réelle |
| Variante de surface d'extraction | `extraction_grouping` | `extraction_grouping` (conservé) | reconstruite |
| Correction humaine (réservé) | — | `manual` | certain |

Seuls renommages : `title_alias→title_apposition` et `llm→llm_confirm` (aligne sur
l'enum nommé de l'issue) ; tout le reste est conservé. La cascade par alias de
`from_artifacts` (merged_from → stratégie de la méthode enregistrée ; cluster JW →
`cluster_jw` ; sinon → `extraction_grouping`) est inchangée en *logique* — elle
route juste à travers ces objets stratégie au lieu de construire les décisions
en ligne.

## 5. Sémantique de `merge()` + politique de conflit

```python
def merge(self, survivor: str, absorbed: str, decision: MergeDecision) -> str
```

`survivor` est un `entity_id` existant. `absorbed` est **soit** un autre
`entity_id` (replier tout le record — usage live/manuel futur) **soit** un slug
d'alias sans record (l'attacher comme alias — le cas reconstruction d'aujourd'hui).
Une seule primitive couvre les deux :

- **fold** : union des aliases + mentions + decisions d'`absorbed` dans
  `survivor`, on retire le record `absorbed` ;
- **attach** : on ajoute l'alias à `survivor` ;
- dans les deux cas : on enregistre `decision` et on ajoute son id à
  `survivor.decisions` ; on retourne `survivor`.

**Conflit** (tie-break déterministe) : si un alias ajouté est déjà possédé par une
tierce entité `c`, on résout *propriétaire canonique gagne → plus grand nombre de
mentions (`len(mentions)`) → ordre d'apparition*. Le perdant lâche l'alias et sa
décision devenue orpheline, et une ligne `warnings` est ajoutée. C'est exactement
la règle actuelle de `_resolve_alias_collisions`, remontée dans `merge()` pour
qu'il n'y ait qu'une implémentation.

**Réversibilité :** `decision.reversible` est porté et sérialisé mais **ne pilote
pas** la résolution de conflit en pas 2 (le tie-break déterministe gagne toujours).
L'override réversibilité/priorité-confiance est du ressort v4 — noté, pas construit.

**Conséquence :** `_merge_duplicate_canonicals` et `_resolve_alias_collisions`
cessent d'être des passes autonomes — leur comportement passe *dans* `merge()`,
appelé incrémentalement à mesure que les décisions sont appliquées. Mêmes sorties,
un seul chemin. Les 16 tests registry existants sont le premier filet prouvant que
ce refactor a préservé le comportement.

## 6. Test d'or + fixture

**Ce que « `entities_classified.json` identique » veut dire, précisément.** Le
registre modélise l'*identité* (quelles entités existent, leur nom canonique,
type, aliases, source_ids) — **pas** les labels de classification, qui
appartiennent à `entity_classification.py` et restent hors périmètre. Le test d'or
compare donc la **projection identité**, canoniquement :

```python
Registry.to_entities_classified() -> list[dict]
    # par entité : {canonical_name, type, aliases (triés), source_ids (triés)}
```

Le test construit le registre depuis le bundle Run 16, projette, et affirme
l'égalité contre un golden commité — les deux côtés normalisés (entités triées,
listes aliases/source triées) pour que l'ordre des dicts et le jitter de tie-break
ne causent pas de faux échecs (§4 ligne de risque). C'est le filet honnête et
non-circulaire : il prouve que le registre reproduit **exactement le regroupement
d'entités** du pipeline, la garantie dont pas 4 a besoin pour basculer la source.
Les labels de classification sont un axe séparé, délibérément non affirmé ici.

**Fixture `tests/fixtures/registry_run16/`** — un bundle curé (~6–8 entités),
assez petit pour être lu à l'œil, exerçant chaque stratégie + la régression clé :

| Cas d'entité | Exerce |
|---|---|
| Deux variantes de surface co-clusterisées | `cluster_jw` (reconstruite) |
| Fusion title-alias | `title_apposition` |
| Apposition `Brullo — the Master —` | `pure_title` (+ chapter_id) |
| Paire role-symmetric, confirmée LLM | `role_symmetric` / `llm_confirm` |
| **Crown Prince vs Perrington (doivent rester séparés)** | régression non-merge STU-430 |
| Personne multi-alias simple | `extraction_grouping` |
| Un PLACE ou ORG | pass-through non-PERSON |

Fichiers : `splits.json`, sortie alias-resolution (avec les blocs de provenance
`alias_resolution`), `persons_full.json` (+ un `places_full.json`), et
`entities_classified.golden.json` (la projection identité).

## 7. Portée des changements de stage (minimale)

Un vrai choix de footprint. L'évidence devrait être `snippet + chapter_id`
(§3.2). Les snippets alias enregistrés ne portent pas `chapter_id` aujourd'hui.

- **Recommandé — le récupérer dans le layer registre, zéro changement de stage.**
  `from_artifacts` charge déjà les `*_full.json` ; le layer stratégie matche le
  snippet enregistré contre `mentions_by_chapter` pour rattacher le chapitre.
  `alias_resolution.py` reste **totalement intact** — respectant pleinement la
  frontière M2 « pas de refonte de stage » — et tous les tests alias existants
  restent verts par construction. Si un snippet ne matche pas, `chapter_id`
  dégrade en `None` gracieusement.
- Repli (seulement si la fiabilité du match est mauvaise) : ajouter un champ
  additif `chapter_id` au dict d'évidence dans les deux détecteurs qui l'ont déjà
  (`pure_title`, `role_symmetric`). Petit et rétrocompatible, mais touche un
  fichier chaud très testé.

En prenant le chemin recommandé, **toute la modif pas-2 tient dans `registry.py`
+ le nouveau `merge_strategies.py` + fixtures/tests**. Les stratégies « émettent
toujours des `MergeDecision` à travers le registre » (via le layer stratégie +
`merge()`) ; on ne réécrit juste pas les internes des détecteurs.

## 8. Filet de tests (dans l'ordre)

1. Les 16 tests registry existants (comportement préservé à travers le refactor
   `merge()`).
2. Nouveaux tests unitaires `merge()` — fold, attach, et le tie-break de conflit.
3. Tests du vocabulaire de stratégie (mapping des noms + fidélité d'évidence).
4. Le test d'or d'équivalence canonique (projection identité vs golden Run 16).
5. `pytest -q` complet — baseline antérieure + nouveaux, zéro régression.
6. `mypy wiki_creator/` — `Success: no issues found`.

## 9. Hors périmètre (explicite)

- Faire remonter le score JW hors du clustering / instrumenter le hot path (M2).
- Enregistrement des rejets Ollama (décision 4).
- Consommation du registre par l'aval (pas 3 STU-435 / pas 4).
- L'invariant INV-WC dans `invariants.md` (STU-444, bloqué par ce ticket).
- Override réversibilité / priorité-confiance (v4).

## 10. Critères de succès

- `Registry.merge(a, b, decision)` existe, est la seule primitive de mutation, et
  `from_artifacts` l'utilise.
- Chaque décision porte stratégie (vocabulaire normalisé) + évidence + confiance ;
  l'évidence alias est réelle, `cluster_jw` reconstruite.
- Le test d'or passe : projection identité du registre ≡ regroupement Run 16.
- `pytest -q` vert (baseline + nouveaux), `mypy wiki_creator/` vert.
- Aucun script de production modifié.
