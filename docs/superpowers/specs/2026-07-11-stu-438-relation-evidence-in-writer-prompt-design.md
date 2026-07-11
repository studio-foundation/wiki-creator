# STU-438 — Consommer key_moments / evidence / sample_contexts dans le prompt du writer

Date : 2026-07-11
Issue : [STU-438](https://linear.app/studioag/issue/STU-438/consommer-key-moments-evidence-sample-contexts-dans-le-prompt-du)

## Problème

`classify_relationships` produit par paire `key_moments` (liste de chaînes
`"chXX: description"`) et `evidence` (phrase verbatim ou `null`) ;
`relationship_extraction` produit `sample_contexts` (extraits bruts). Ces champs
traversent toute la chaîne jusqu'aux `batch_*.json` via `filter_relationships`,
mais `build_prompt` (`scripts/generate_wiki_pages.py`) ne lit que
`relationship_type`, `direction`, `evolution`, `cooccurrence_count`. La section
« Relations » est donc générée sans preuve textuelle — le LLM paraphrase des
types abstraits.

## Décisions de design (validées)

1. **Budget d'enrichissement par importance de l'entité de la page** :
   `principal → 5`, `secondary → 3`, `figurant → 0`. La liste des relations est
   déjà triée par `cooccurrence_count` décroissant et cappée à 10 ; seules les
   `N` premières reçoivent l'enrichissement, les autres gardent le format nu
   actuel.
2. **Contenu de l'enrichissement par relation** :
   - `evidence: "<verbatim>"` quand non nul / non vide ;
   - jusqu'à 2 `key_moments`, en filtrant la sentinelle
     `"no specific moment identifiable in provided excerpts"` ;
   - `context: "<sample_contexts[0]>"` tronqué à 200 caractères, **uniquement en
     fallback quand `evidence` est absent** (évite la redondance : `evidence`
     est déjà tirée de `sample_contexts`).
3. **Nouvelle règle d'écriture**, émise seulement si au moins une relation a été
   enrichie : ancrer chaque entrée `## Relations` sur les `evidence` /
   `key_moments` fournis (citer ou paraphraser fidèlement), interdiction
   d'inventer des moments non listés.
4. **Robustesse** : tous les accès via `.get(...)` avec défauts. Les batches
   antérieurs à la classification (ou `relationship_type: null`) produisent des
   lignes nues — comportement actuel inchangé. Une relation non typée peut
   quand même recevoir le fallback `context` (elle n'a jamais d'`evidence`).

## Hors scope

- Comptage de ces champs dans `_entity_context_char_count` (batching) —
  inchangé.
- STU-428 (marqueurs de confiance) — `evidence` en est la matière première mais
  les marqueurs sont une issue distincte.

## Tests (TDD, `tests/test_generate_wiki_pages.py`)

- evidence + key_moments présents pour les relations top-N d'une entité
  principale ;
- sentinelle key_moment filtrée ;
- `context` présent seulement quand `evidence` absent, tronqué à 200 chars ;
- figurant : aucun enrichissement ; secondary : cap à 3 ;
- règle d'ancrage présente ssi enrichissement effectif ;
- champs absents → prompt identique au comportement actuel (garde-fou de
  régression).
