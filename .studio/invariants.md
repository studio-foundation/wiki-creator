# Invariants — Wiki Creator

> Chaque invariant référence le mécanisme **réel** qui l'enforce dans le code.
> Un invariant sans mécanisme bloquant est explicitement marqué NON ENFORCED —
> ne jamais documenter un enforcement fictif.

## INV-WC-01 — Pas de reproduction verbatim
L'output ne reproduit jamais 15 mots consécutifs ou plus du texte source
(seuil plus strict que « 2-3 phrases »).

Enforced par :
- **Détection** : `scripts/copyright_check.py` — index n-grams (15 mots) du
  source EPUB, masquage des citations courtes (≤5 mots), fusion des runs.
  Stage `copyright-check` des pipelines `pages-export` et `wiki-generation`.
- **Blocage** : `scripts/wiki_export.py::_copyright_gate` — si
  `copyright-check.status == "fail"`, le stage `wiki-export` échoue
  (`exit 1`) et aucun fichier wikitext n'est écrit.

Note : le contract `copyright-check` ne valide que la présence du champ
`status` — le gate de `wiki_export.py` est le mécanisme bloquant. Ce n'est pas
une limitation des contracts Studio : `validators:` permettrait de porter le
gate dans le contract (cf. INV-WC-05).

## INV-WC-02 — Progression narrative chronologique — ⚠️ NON ENFORCED
Les révélations dans une page wiki devraient apparaître dans l'ordre où elles
surviennent dans le livre.

État réel : **aucun mécanisme ne l'enforce.** Le schéma de page généré
(`title`, `importance`, `entity_type`, `infobox_fields`, `content`) ne porte
pas de champ `revelations` ; le contract `wiki-page` ne le valide pas.
L'ordre chronologique est seulement encouragé par le prompt de génération.
Backlog : introduire un champ structuré `revelations[{chapter, text}]` dans
le schéma de page + check de tri dans `wiki_page_validator.py`.

## INV-WC-03 — Entités résolues avant génération
Aucune page wiki n'est générée tant que le registre d'entités n'est pas
résolu ; les aliases non fusionnés produiraient des pages dupliquées.

Enforced par :
- **Ordre du pipeline `wiki-resolution`** : `resolve-clusters` →
  `alias-resolution` → `entity-classification` (l'entrée de la génération est
  la sortie d'`entity-classification`, donc toujours post-alias-resolution).
- **Vérification mesurée** : métrique `alias_duplicates` suivie par run dans
  `library/**/audits/audit_log.json` (0 doublon runs 7→15).

Note : il n'existe pas de contract `entity-registry-resolved` ; la garantie
est structurelle (ordre des stages), pas contractuelle.

## INV-WC-04 — Tout fix d'identité passe par le registre
Toute fusion, séparation ou correction d'identité d'entité (alias,
`canonical_name`) passe par `wiki_creator/registry.py`, tracée par une
`MergeDecision`. Aucun script ne modifie directement les alias ou le
`canonical_name` d'une entité hors du registre.

Enforced par :
- **Blocage (chemin registre)** : `Registry.validate()` — invariant 2 lève
  `ValueError` si un alias ≠ `canonical_name` n'est justifié par aucune
  `MergeDecision` attachée à l'entité. Une fusion introduite sans décision
  tracée fait échouer la validation.
- **Traçabilité** : chaque fusion construite dans
  `Registry.from_artifacts` / `_merge_duplicate_canonicals` émet une
  `MergeDecision` (`decision_id` dérivé du contenu, `strategy`, `evidence`,
  `confidence`, `reversible`) exposée via `Registry.audit_log()`.

⚠️ NON ENFORCED (clause « aucun script ne modifie directement ») : aucun
garde-fou n'empêche un script d'écrire `canonical_name`/`aliases` en dur dans
un JSON en contournant le registre. La clause tient par convention +
injection de ce fichier dans le system prompt de chaque agent Studio ;
`validate()` ne la détecte que si le registre est effectivement l'auteur des
sorties.

## INV-WC-05 — Le vocabulaire de types de page est déclaré dans `base.yaml`
`wiki_creator/templates/base.yaml#entity_types` est la seule autorité sur les
types de page. Aucun autre fichier ne redéclare l'énumération : un enum
restatté dérive en silence, et celui du contract `wiki-page` l'avait déjà fait
(il annonçait `PERSON | PLACE | ORG` longtemps après la sortie d'`EVENT`).

Enforced par :
- **Blocage** : validateur externe `entity-type-declared` du contract
  `wiki-page` (`scripts/validate_entity_type_declared.py`). Il lit `base.yaml`
  à l'exécution et reçoit la sortie réelle du stage sur stdin ; un type absent
  fait échouer le stage `wiki-generation` de `pages-export`, donc le run —
  aucun wikitext n'est écrit. Vérifié sur ToG 01 : retirer `EVENT` de
  `base.yaml` fait échouer le run sur les 20 pages d'événements.
- **Blocage (corollaire)** : validateur externe `unique-page-title`
  (`scripts/validate_unique_page_title.py`) — deux pages rendant le même
  `page_filename` font échouer le run. Les sous-dossiers par type séparent les
  fichiers, mais l'espace de noms des titres wiki est plat.
- Logique pure : `wiki_creator/page_validators.py`.

⚠️ Portée : l'invariant couvre les types *sortis en pages*, au stage
`wiki-page`. `wiki_creator/types.py::ENTITY_TYPE` reste un `Literal` figé,
parallèle à `base.yaml`, et 4 autres tables Python (`entity_extraction.py`,
`export_helpers.py`, `wiki_export.py`, `md2wiki.py`) portent encore leur propre
vocabulaire — leur convergence est STU-505. `OTHER` et `SYNOPSIS` sont déclarés
dans `base.yaml` sans template (zéro slot) : c'est leur état réel, pas un
template à écrire.

Note : les contracts Studio ne sont pas limités à `required_fields` — le noyau
expose `validators:` (commande shell, sortie réelle du stage sur stdin,
`{valid, errors}` sur stdout, exécutée dans la boucle RALPH). C'est le
mécanisme utilisé ici, et il est réutilisable par tout autre contract.
