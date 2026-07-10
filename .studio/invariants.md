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
`status` (limitation des contracts Studio actuels — required_fields only).
Le gate de `wiki_export.py` est le mécanisme bloquant.

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
- **Ordre du pipeline `wiki-resolution`** : `merge-entities` →
  `alias-resolution` → `entity-classification` (l'entrée de la génération est
  la sortie d'`entity-classification`, donc toujours post-alias-resolution).
- **Vérification mesurée** : métrique `alias_duplicates` suivie par run dans
  `library/**/audits/audit_log.json` (0 doublon runs 7→15).

Note : il n'existe pas de contract `entity-registry-resolved` ; la garantie
est structurelle (ordre des stages), pas contractuelle.
