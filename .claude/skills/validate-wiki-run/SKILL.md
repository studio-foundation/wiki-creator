---
name: validate-wiki-run
description: Audit de run de génération Wiki Creator. Use this skill whenever the user uploads wiki_pages.json and/or batch_*.json files from the Wiki Creator pipeline, or says "valide la run", "audit de run", "qu'est-ce qui fonctionne", "nouvelles pages", or drops JSON files from the pipeline. Produces a structured delta table, per-issue validation, and new issues to create in Linear.
---

# validate-wiki-run

Skill d'audit qualité pour Wiki Creator. L'utilisatrice dépose des fichiers d'une run de génération et attend un bilan structuré avec delta vs run précédente, validation des issues actives, et identification des nouveaux problèmes.

## Inputs attendus

- `wiki_pages.json` — output de génération (obligatoire)
- `batch_000.json` — premier batch d'entrée (optionnel mais recommandé)
- Tout autre batch ou fichier intermédiaire fourni

## Workflow

### Étape 1 — Analyse des fichiers

Exécute ce bloc d'analyse Python sur les fichiers fournis. Adapte les chemins selon ce qui est disponible dans `/mnt/user-data/uploads/`.

```python
import json

with open('/mnt/user-data/uploads/wiki_pages.json') as f:
    data = json.load(f)
pages = data.get('pages', data) if isinstance(data, dict) else data

titles = [p['title'] for p in pages]

# Métriques de base
for p in pages:
    ib = p.get('infobox_fields', {})
    content = p.get('content', '')
    issues = []
    if not ib: issues.append('infobox_vide')
    if any(k.startswith('- ') for k in ib): issues.append('clés_préfixées')
    if '.xhtml' in content: issues.append('IDs_EPUB')
    if '## Relations' in content or '**Relations**' in content: issues.append('✓Relations')
    if p.get('_failed'): issues.append('_failed')
    # Hallucinations cross-série connues
    for kw, label in [('Kiera Cass','halluc_KieraCass'),('Aelin Gallian','halluc_Aelin'),
                      ('Kingkiller','halluc_Kingkiller'),('Lysandra','halluc_Lysandra'),
                      ('La cour des lions','halluc_titre'),('Duchess of Danger','halluc_titre')]:
        if kw in content + str(ib): issues.append(label)
    en = any(w in content for w in ['is the','was a','known as','also known','she was','he is'])
    fr = any(w in content for w in ['est le','est un','était','dans le','il est','elle est'])
    lang = 'MIXTE' if en and fr else ('EN' if en else 'FR')
    print(f"{p['title'][:30]:<30} {p['importance']:<10} {p.get('entity_type','?'):<8} ib={len(ib)} {lang} | {', '.join(issues) if issues else 'OK'}")

# Sommaire
print(f"\nPages: {len(pages)}")
print(f"Infobox peuplées: {sum(1 for p in pages if p.get('infobox_fields'))}/{len(pages)}")
print(f"Clés préfixées: {sum(1 for p in pages if any(k.startswith('- ') for k in p.get('infobox_fields',{})))}")
print(f"## Relations: {sum(1 for p in pages if '## Relations' in p.get('content','') or '**Relations**' in p.get('content',''))}/{len(pages)}")
print(f"IDs EPUB: {sum(1 for p in pages if '.xhtml' in p.get('content',''))}")
print(f"Pages FR: {sum(1 for p in pages if not any(w in p.get('content','') for w in ['is the','was a','known as']))}/{len(pages)}")

# Doublons connus
for d in ['Captain Westfall','Crown Prince','Chaol Westfall']:
    print(f"Doublon {d}: {'PRÉSENT' if d in titles else 'absent'}")
```

Si `batch_000.json` est disponible, ajoute :

```python
with open('/mnt/user-data/uploads/batch_000.json') as f:
    batch = json.load(f)

for e in batch.get('entities', []):
    rels = e.get('relationships', [])
    typed = [r for r in rels if r.get('relationship_type')]
    null_evol = [r for r in rels if r.get('evolution') in (None, 'relation stable dans les extraits fournis', '')]
    empty_moments = [r for r in rels if not r.get('key_moments')]
    print(f"\n{e['canonical_name']}: {len(typed)}/{len(rels)} relations typées")
    print(f"  evolution générique/null: {len(null_evol)}/{len(rels)}")
    print(f"  key_moments vides: {len(empty_moments)}/{len(rels)}")
    print(f"  aliases: {e.get('aliases', [])}")
    if typed:
        from collections import Counter
        type_dist = Counter(r.get('relationship_type') for r in typed)
        print(f"  types: {dict(type_dist)}")
```

### Étape 2 — Validation des critères qualité

Produis un tableau de régression sur les critères clés. Tous les bugs listés ci-dessous ont été corrigés — signaler toute régression.

| Critère | Réf. | Statut | Détail |
|---|---|---|---|
| Zéro clé infobox préfixée `- ` | STU-263 | ✅/❌ | |
| Zéro ID EPUB dans content | STU-265 | ✅/❌ | pages concernées |
| entity_type non-null sur toutes les entités | STU-266 | ✅/❌ | |
| Doublons alias absents (Captain Westfall, Crown Prince…) | STU-261/275 | ✅/❌ | |
| Brullo / Master alias correctement fusionnés | STU-276 | ✅/❌ | |
| Zéro cross-série, 100% FR, relations orientées | STU-278 | ✅/⚠️/❌ | sous-critères |
| evolution non-générique, key_moments ≥50%, types diversifiés | STU-279 | ✅/⚠️/❌ | stats batch |
| temporal_context présent/flashback propagé dans chapter-summary | STU-271 | ✅/❌ | |
| Zéro hallucination cross-série connue | STU-278 | ✅/❌ | |

Utilise ✅ (ok), ⚠️ (partiel — préciser), ❌ (régression présente), ➕ (nouveau problème).

### Étape 3 — Tableau de bord cross-runs

Maintiens ce tableau en l'alimentant avec les nouvelles métriques. Remplace les `?` par les valeurs observées :

| Métrique | Run 1 | Run 2 | Run 3 | Run 4 | Run 5 | Run 6 | Run 7 | Run N |
|---|---|---|---|---|---|---|---|---|
| Pages générées | 20 | 20 | 20 | 14 | 14 | 11 | ? | ? |
| Infobox peuplées | 0% | 75% | 75% | 85% | 79% | 82% | ? | ? |
| Clés `- ` préfixées | 20 | 12 | 12 | 0 | 0 | 0 | ? | ? |
| ## Relations | 0 | 0 | 0 | 1 | 0 | 3 | ? | ? |
| IDs EPUB | 0 | 0 | 3 | 3 | 1 | 0 | ? | ? |
| Langue FR | 0% | ~50% | ~60% | 85% | 85% | 73% | ? | ? |
| Doublons alias | 5 | 5 | 5 | 3 | 3 | 2 | ? | ? |
| Hallucinations | 2 | 0 | 3 | 2 | 2 | 2 | ? | ? |
| Relations typées (batch) | 0% | 0% | 100% | 100% | 100% | 100% | ? | ? |
| key_moments peuplés | - | - | - | - | 14% | 14% | ? | ? |
| evolution non-générique | - | - | - | - | 0% | 0% | ? | ? |
| temporal_context propagé | - | - | - | - | - | - | ? | ? |

### Étape 4 — Nouveaux problèmes

Identifie tout problème absent des runs précédentes. Pour chaque nouveau problème :
- Une ligne de description concise
- La page ou entité concernée
- Le composant du pipeline responsable (agent, script, upstream)
- Si ça mérite une issue Linear : oui/non + pourquoi

### Étape 5 — Verdict et prochaine action

En 3-4 phrases : état du pipeline, ce qui est validé, ce qui bloque encore, **une seule** action prioritaire pour la prochaine run.

## Format de sortie

Produis les étapes 2-5 dans cet ordre, sans reformuler les données brutes. Pas de prose introductive — aller direct au tableau de validation.

Si des nouvelles issues Linear sont justifiées, les créer via l'outil Linear après le verdict.

## Historique des issues connues

Issues Done (ne pas re-créer) : STU-260, STU-261, STU-262, STU-263, STU-264, STU-265, STU-266, STU-267, STU-268, STU-269, STU-270, STU-271, STU-272, STU-273, STU-274, STU-275, STU-276, STU-277, STU-278, STU-279

Issues Backlog actives : aucune issue qualité ouverte au 2026-03-17. Les prochaines issues seront identifiées à partir de la Run 7.

Avant de créer une nouvelle issue, vérifier qu'elle ne doublon pas une issue existante via `Linear:list_issues` sur le projet Wiki Creator.