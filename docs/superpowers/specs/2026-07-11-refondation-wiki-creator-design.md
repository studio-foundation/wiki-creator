# Re-fondation Wiki Creator — Design du programme et de la Fondation Identité

> Validé le 2026-07-11. Base : audit complet 5 axes (architecture, flux de données,
> archéologie git, couches de compensation, tests & intégration Studio) mené le même jour
> sur main @ 252b449, complété après les merges #53–#61 (main @ cd21e86).

## 1. Contexte et décision

### Le déclencheur

Constat vécu : « je patche et je patche » — l'impression qu'un problème de fondation
se cache sous l'accumulation de correctifs. Question posée : faut-il repartir de zéro
(comme Studio v1–v6 NextJS → v7 Node/packages), ou faire évoluer l'existant ?

### Verdict de l'audit

**Pas un rewrite : une re-fondation ciblée.** 4 axes sur 5 concluent « fondation saine
ou incomplète » ; un seul axe conclut « fondation manquante » — et c'est toujours le même
concept : **l'identité d'entité (« qui est qui »)**.

| Axe | Verdict | Preuve la plus forte |
|---|---|---|
| Architecture | Incomplète, pas fausse | Le cœur de chaque étape est déjà une fonction pure typée (`resolve_aliases`, `extract_entities`, `build_entity_bundle`) ; mais 92 % du code vit dans `scripts/`, boilerplate Studio copié 12–15×, 4 normalisations de noms, 28 `sys.path.insert` |
| Flux de données | Sous-outillé, pas faux | Le bus disque est une bonne fondation (restart par stage) ; mais `types.py` est un schéma mort (0 import) et l'info riche est jetée au dernier maillon |
| Git (test empirique) | Dette localisée qui dérive | « Pure-title merge » fixé en mars (STU-275) et re-fixé en juillet (#49, puis #57) ; ~15 couches défensives sur le chemin de génération ; ratio fix/feat doublé (0,34 → 0,64) ; 16 runs de validation en boucle |
| Compensations NLP | 2 couches précises | (1) typage NER fiction — remplaçable, le modèle maison `wiki-ner-en` existe (f=0.98) ; (2) coref absente, émulée partout par string-matching |
| Tests & Studio | Tests sains / Studio contourné | Studio n'apporte de valeur qu'aux 3 pipelines `*-item` ; `run_wiki.py` est un second orchestrateur ; re-shell `studio run` + scraping de logs (~200 lignes de glue) |

Chaîne causale du « je patche et je patche » :

```
coref absente → identité émulée par string-matching → fusions d'alias fragiles
  → identity confusion dans les pages → grounding/forbidden/force-correct empilés
    → ~15 couches défensives → 16 runs d'audit → patches → re-audit
```

### Décision

- **Approche B — re-fondation en place, par strates (strangler)**, dans ce repo,
  avec le harnais de régression (735+ tests, runs ground-truth, `make smoke`)
  vivant en permanence.
- **Objectif produit : open source** — outil personnel d'abord, publié pour les
  communautés fandom ensuite.
- **Studio au cœur, mais bien** : Wiki Creator devient la vitrine de référence de
  Studio ; chaque contournement actuel devient soit une intégration propre, soit une
  feature à ajouter à Studio (workflow « Powered by Studio » habituel).

### Ce qu'on garde (explicitement)

- Le bus disque + restart par stage (fondation d'idempotence qui marche)
- Les fonctions pures + la suite de tests
- Le reshape page-templates (slices A–E, livrées) — même direction que la cible
- Le NER fiction maison `wiki-ner-en` (reconnecté par STU-439)

## 2. Le programme : 5 milestones

Structure reflétée dans Linear (projet Wiki Creator) le 2026-07-11. v1, v2, v1.5
marqués livrés le même jour.

| Milestone | Contenu | Critère de sortie |
|---|---|---|
| **M1 — Fondation Identité (EntityRegistry)** | Source de vérité unique « qui est qui » ; string-matching → stratégies ; décisions de fusion tracées. Issues : STU-435 (+ STU-427, STU-439 déjà Done) | Plus aucun fix identité ne touche >1 module ; safety nets STU-318/319 silencieux sur les runs |
| **M2 — Package & Schémas** | `studio_io`, client LLM partagé, `types.py` branché sur la sérialisation, packaging installable, scission du main() de generate_wiki_pages | `pip install -e .` suffit ; un drift de schéma casse bruyamment |
| **M3 — Lang & NLP première classe** | Lang-packs documentés, échec bruyant si absent, modèles spaCy non standard supportés. Issue : STU-437 (solipCysme, recherche) | Un contributeur ajoute une langue sans lire le code |
| **M4 — Intégration Studio native** | Fan-out par item, contracts schéma (STU-432), propagation d'artefacts, mort de run_wiki.py — features remontées côté Studio | Plus de re-shell + scraping ; pipelines top-level sur les vrais mécanismes Studio |
| **M5 — Open Source Release** | Docs, licence, CI publique, hygiène (secrets `.studio/config.yaml`, `library/` sous copyright hors publication) | Un inconnu clone → EPUB traité en <30 min |

L'ordre est M1 → M5. v3 (enrichissements narratifs) et v4 (modèle communautaire)
suivent, débloqués respectivement par M1 et M5.

## 3. Design M1 — `EntityRegistry`

### 3.1 Principe

Un module pur `wiki_creator/registry.py` (même pattern éprouvé que
`page_templates.py`). Règle unique : **plus personne ne fusionne deux noms sans passer
par `registry.merge(a, b, decision)`.** Les mécanismes existants — clustering
Jaro-Winkler, apposition, title-alias, role-symmetric, confirmation Ollama, coref —
deviennent des **stratégies** qui *proposent* des `MergeDecision` au registre.

### 3.2 Modèle de données

```python
@dataclass
class Mention:
    surface: str          # forme exacte dans le texte
    chapter_id: str
    start: int            # offsets caractères dans le chapitre nettoyé
    end: int
    source: str           # "ner" | "coref" | "pattern"
    raw_label: str        # label émis par le modèle (PER, PERSON, PLACE, …)

@dataclass
class MergeDecision:
    decision_id: str
    strategy: str         # "cluster_jw" | "title_apposition" | "pure_title"
                          # | "role_symmetric" | "llm_confirm" | "coref" | "manual"
    inputs: tuple[str, str]   # les deux entity_id fusionnés
    evidence: str         # snippet textuel + chapter_id
    confidence: str       # "high" | "medium" | "low" | "certain" (manual)
    reversible: bool      # une décision manuelle peut invalider une décision auto

@dataclass
class EntityRecord:
    entity_id: str        # stable, slug dérivé de la première forme canonique
    canonical_name: str
    entity_type: str      # PERSON | PLACE | ORG | EVENT | OTHER
    aliases: list[str]    # chaque alias arrivé par une MergeDecision identifiable
    mentions: list[Mention]
    decisions: list[str]  # decision_ids qui ont construit ce record
```

Invariants (vérifiés à chaque sérialisation) :
1. Un alias appartient à exactement une entité.
2. Chaque alias (≠ canonical_name) est justifié par au moins une `MergeDecision`.
3. `canonical_name ∈ aliases`.
4. Les `entity_id` sont stables entre deux runs sur le même texte (déterminisme).

### 3.3 L'artefact : `registry.json`

Le registre se sérialise en `processing_output/<slug>/registry.json` et devient
l'artefact identité que tout l'aval consulte. Cohérent avec le bus disque existant.

Trois bénéfices en cascade :
1. **Débogage** : « pourquoi Crown Prince est chez Perrington ? » → la stratégie,
   l'évidence et la confiance sont dans le fichier.
2. **Multi-tomes (STU-233)** : le registre du tome 1 devient l'entrée du tome 2
   (`Registry.load(prior)`), l'accumulation est native.
3. **Corrections communautaires (v4)** : une correction humaine =
   `MergeDecision(strategy="manual", confidence="certain")` — directement exploitable
   comme signal d'entraînement LoRA.

### 3.4 API (esquisse)

```python
class Registry:
    @classmethod
    def from_artifacts(cls, splits, alias_output) -> "Registry": ...   # pas 1
    @classmethod
    def load(cls, path) -> "Registry": ...
    def save(self, path) -> None: ...                # vérifie les invariants
    def merge(self, a: str, b: str, decision: MergeDecision) -> str: ...
    def lookup(self, surface: str) -> EntityRecord | None: ...
    def alias_table(self) -> dict[str, str]: ...     # surface → entity_id (STU-435)
    def audit_log(self) -> list[MergeDecision]: ...
```

### 3.5 Migration strangler en 4 pas

| Pas | Contenu | Filet de sécurité |
|---|---|---|
| 1 — Registre en lecture | Construit depuis les artefacts existants (splits + alias-resolution), sérialisé, invariants actifs. Aucun changement de comportement. | Pure addition |
| 2 — Les stratégies écrivent à travers lui | clustering/alias deviennent des `MergeStrategy` émettant des `MergeDecision`. | **Test d'or** : registre reconstruit sur les fixtures Run 16 ⇒ `entities_classified.json` identique |
| 3 — STU-435 | Repli du graphe de relations via `alias_table()` avant classification ; une classification par paire canonique. | Métriques de relations du run de validation |
| 4 — L'aval consulte le registre | Préparation + binding génération lisent le registre ; les safety nets STU-318/319 deviennent des assertions télémétriques, retirés quand ils ne se déclenchent plus. | Runs de validation successifs |

### 3.6 Hors périmètre M1

- Coref pronominale obligatoire (reste une stratégie optionnelle ; le harnais
  d'évaluation STU-427/#60 permet de la juger sur pièces).
- Refonte des stages eux-mêmes (M2).
- Changement de format des autres artefacts.

### 3.7 Tests

- La suite existante reste verte à chaque pas.
- Test d'or de non-régression (pas 2) sur les fixtures Run 16.
- Tests unitaires du registre : invariants, déterminisme des `entity_id`,
  round-trip sérialisation, `merge` avec conflits (alias déjà pris).
- Le smoke test (`make smoke`) couvre la novella fixture de bout en bout.

## 4. Risques

| Risque | Mitigation |
|---|---|
| Le test d'or du pas 2 est trop strict (ordre de dicts, tie-breaks) | Comparaison canonique (tri, normalisation) plutôt que diff brut |
| Tentation de re-patcher l'ancien chemin pendant la migration | Tout nouveau fix identité doit passer par le registre — règle affichée dans invariants.md |
| `registry.json` devient un 2e schéma mort comme types.py | Le registre est *consommé* dès le pas 3 (STU-435) — il a un client réel immédiatement |
| Périmètre M1 qui gonfle (coref, refonte stages) | Hors périmètre explicite (§3.6) |

## 5. Critères de succès du programme

- M1 : plus aucun fix identité ne touche plus d'un module ; safety nets silencieux.
- M2 : zéro duplication de boilerplate ; schémas appliqués aux frontières d'I/O.
- M3 : une langue s'ajoute par lang-pack documenté, échec bruyant sinon.
- M4 : plus de contournement de Studio ; les manques sont des features Studio livrées.
- M5 : un inconnu traite un EPUB en <30 min après clone.
