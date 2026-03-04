# Invariants — Wiki Creator

## INV-WC-01 — Pas de reproduction verbatim
L'output ne reproduit jamais plus de 2-3 phrases consécutives du texte source.
Enforced par : contract `entity-registry` (champ `excerpt_max_sentences`)

## INV-WC-02 — Progression narrative chronologique
Les révélations dans une page wiki apparaissent dans l'ordre où elles surviennent dans le livre.
Une révélation du chapitre 15 n'apparaît pas avant sa position narrative.
Enforced par : contract `wiki-page` (champ `revelations` trié par `chapter`)

## INV-WC-03 — Entités résolues avant génération
Aucune page wiki n'est générée tant que le registre d'entités n'est pas résolu.
Les aliases non fusionnés produisent des pages dupliquées — validation fail.
Enforced par : contract `entity-registry-resolved`
