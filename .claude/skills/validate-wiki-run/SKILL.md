---
name: validate-wiki-run
description: Audit de run de génération Wiki Creator. Use this skill whenever the user uploads wiki_pages.json and/or batch_*.json files from the Wiki Creator pipeline, or says "valide la run", "audit de run", "qu'est-ce qui fonctionne", "nouvelles pages", or drops JSON files from the pipeline. Produces a structured delta table, per-issue validation, and new issues to create in Linear.
---

# validate-wiki-run

Skill d'audit qualité pour Wiki Creator. L'utilisatrice dépose des fichiers d'une run de génération et attend un bilan structuré avec delta vs run précédente, validation des critères qualité, et identification des nouveaux problèmes.

## Inputs attendus

- `wiki_pages.json` — output de génération (obligatoire)
- `batch_*.json` — batches d'entrée (optionnel mais recommandé, itérer sur tous)
- Tout autre batch ou fichier intermédiaire fourni

## Ground-Truth (Throne of Glass)

Quand le livre audité est dans la série Throne of Glass, des fichiers de vérité terrain sont disponibles sous :
```
library/sarah_j_maas/throne-of-glass/books/ground-truth/
```
Fichiers : `celeana.json`, `chaol.json`, `dorian.json`, `elena_and_gavin.json`, `king-of-adarlan.json`, `nehemia.json`, `perrington.json`

Chaque fichier contient :
- `canonical_aliases_book1` — noms valides pour ce livre
- `known_facts_book1` — faits vrais dans le livre 1
- `known_relations_book1` — relations réelles dans le livre 1
- `forbidden_book1` — éléments qui n'existent pas encore dans ce livre
- `hallucination_signals` — phrases/termes qui signalent une invention du LLM
- `identity_confusion_forbidden` — phrases explicites de confusion d'identité (champ optionnel, ex: "alias: Elena" dans l'infobox)

**Intégrer ces fichiers dans l'étape 1b ci-dessous lorsque disponibles.**

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

### Étape 1b — Validation ground-truth (Throne of Glass uniquement)

Si le livre audité est dans la série Throne of Glass, exécute ce bloc **avant** l'analyse des batches :

```python
import json, glob, os

GT_DIR = 'library/sarah_j_maas/throne-of-glass/books/ground-truth'
gt_files = glob.glob(f'{GT_DIR}/*.json')

def _load_gt_entries(gt_files):
    """Normalise les fichiers GT en une liste d'entrées uniformes.
    Gère deux formats :
    - Flat  : { "entity": "...", "canonical_aliases_book1": [...], ... }
    - Imbriqué : { "entities": [...], "elena": {...}, "gavin": {...}, ... }
    """
    entries = []
    by_entity = {}  # entity_name -> raw sub-object, pour le check de relations (section 3)
    for gf in gt_files:
        with open(gf) as f:
            gt = json.load(f)
        if 'entity' in gt:
            # Format flat
            sub_objects = [(gt['entity'], gt)]
        else:
            # Format imbriqué : clés dont la valeur est un dict
            sub_objects = [(k, v) for k, v in gt.items() if isinstance(v, dict)]
        for name, obj in sub_objects:
            canonical = obj.get('canonical_aliases_book1', [])
            aliases = canonical if canonical else [name]
            forbidden = []
            for cat, items in obj.get('forbidden_book1', {}).items():
                if isinstance(items, list):
                    for item in items:
                        forbidden.append((item, cat))
            entity_name = canonical[0] if canonical else name
            entries.append({
                'entity': entity_name,
                'canonical_aliases': aliases,
                'hallucination_signals': obj.get('hallucination_signals', []),
                'forbidden': forbidden,
                'identity_confusion_forbidden': obj.get('identity_confusion_forbidden', []),
                'known_relations': obj.get('known_relations_book1', {}),
            })
            by_entity[entity_name] = obj
    return entries, by_entity

gt_entries, gt_by_entity = _load_gt_entries(gt_files)

# all_forbidden reste global (termes interdits s'appliquent à toutes les pages)
all_forbidden = []  # (term, entity_name, category)
for entry in gt_entries:
    for term, cat in entry['forbidden']:
        all_forbidden.append((term, entry['entity'], cat))

# Charge les pages générées
with open('/mnt/user-data/uploads/wiki_pages.json') as f:
    data = json.load(f)
pages = data.get('pages', data) if isinstance(data, dict) else data

print("=== VALIDATION GROUND-TRUTH ===\n")
violations_found = 0

for p in pages:
    title = p['title']
    content = p.get('content', '')
    ib_str = str(p.get('infobox_fields', {}))
    full_text = content + ' ' + ib_str
    page_violations = []

    import re as _re
    def _extract_match_phrases(signal):
        """Extrait des phrases de correspondance depuis un signal d'hallucination.
        Utilise la phrase complète plutôt que le premier token pour éviter les faux positifs
        sur des mots génériques comme 'livres', 'pouvoirs', 'possession'. (STU-294)
        """
        phrase = signal
        for prefix in ["Toute mention de ", "Toute scène ou dialogue de ", "Toute mention d'"]:
            if phrase.startswith(prefix):
                phrase = phrase[len(prefix):]
                break
        # Supprime le contexte trailing : parenthèses, tirets cadratins, clauses "dans le livre N"...
        phrase = _re.split(r"\s*[\(—]|\s+dans (?:le|la|une|l')\b|\s+en lien\b|\s+comme \w|\s+par nom\b|\s+scopée\b", phrase)[0]
        phrase = phrase.strip(" '\"")
        # Gère les listes séparées par des virgules (ex: "Lysandra, Aedion, Manon, Elide")
        parts = [part.strip(" '\"") for part in phrase.split(",")]
        return [part for part in parts if len(part) >= 5]

    # Reverse-lookup : alias_lower -> entity_name (pour check cross-entité)
    all_canonical_lookup = {}
    for entry in gt_entries:
        for alias in entry['canonical_aliases']:
            all_canonical_lookup[alias.lower()] = entry['entity']

    # Entité GT correspondant à cette page (si applicable)
    page_entity = None
    page_entry = None
    for entry in gt_entries:
        if any(a.lower() in title.lower() for a in entry['canonical_aliases']):
            page_entity = entry['entity']
            page_entry = entry
            break

    # 1. Cherche les signaux d'hallucination — scopés à la page de l'entité concernée
    if page_entry:
        for sig in page_entry['hallucination_signals']:
            phrases = _extract_match_phrases(sig)
            if any(ph.lower() in full_text.lower() for ph in phrases):
                page_violations.append(f"HALLUC_SIGNAL [{page_entity}]: {sig}")

    # 1b. Confusions d'identité explicites (STU-314) — scopées à la page de l'entité
    if page_entry:
        for phrase in page_entry['identity_confusion_forbidden']:
            if phrase.lower() in full_text.lower():
                page_violations.append(f"IDENTITY_CONFUSION [{page_entity}]: '{phrase}'")

    # 1c. Alias infobox cross-entité (STU-314) — infobox alias ne doit pas nommer une autre entité GT
    if page_entity:
        ib = p.get('infobox_fields', {})
        for ak in ['alias', 'aliases', 'pseudonyme', 'pseudonymes', 'noms alternatifs', 'other names']:
            ib_val = ib.get(ak, '')
            if not ib_val:
                continue
            parts = ib_val if isinstance(ib_val, list) else [v.strip() for v in str(ib_val).split(',')]
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                matched = all_canonical_lookup.get(part.lower())
                if matched and matched != page_entity:
                    page_violations.append(f"INFOBOX_ALIAS_CROSS [{page_entity}→{matched}]: infobox '{ak}={part}' correspond à l'entité GT '{matched}'")

    # 2. Cherche les termes interdits
    for term, entity, cat in all_forbidden:
        if len(term) > 4 and term.lower() in full_text.lower():
            page_violations.append(f"FORBIDDEN [{entity}/{cat}]: '{term}'")

    # 3. Vérifie les relations contre known_relations_book1
    # Cherche des noms de personnages liés à cet entity qui ne devraient pas apparaître
    for gt_name, gt in gt_by_entity.items():
        if gt_name.lower() in title.lower() or any(a.lower() in title.lower() for a in gt.get('canonical_aliases_book1', [])):
            # C'est la page de cette entité — vérifie les relations déclarées
            known_rels = set(gt.get('known_relations_book1', {}).keys())
            forbidden_rels = gt.get('forbidden_book1', {}).get('relationships', [])
            for fr in forbidden_rels:
                rel_name = fr.split("(")[0].strip()
                if rel_name and rel_name.lower() in full_text.lower():
                    page_violations.append(f"FORBIDDEN_REL [{gt_name}]: '{rel_name}' — {fr}")

    if page_violations:
        violations_found += len(page_violations)
        print(f"❌ {title}")
        for v in page_violations:
            print(f"   {v}")
    else:
        print(f"✅ {title}")

print(f"\nTotal violations ground-truth: {violations_found}")
print(f"Pages propres: {sum(1 for p in pages if True)}/{len(pages)}")
```

**Pour chaque violation trouvée, dans l'Étape 4 (Nouveaux problèmes) :**
- Préciser le terme/signal exact trouvé dans la page
- Identifier la cause probable : contamination cross-série (LLM entraîné sur tous les tomes), extrapolation biographique (LLM complète ce qu'il "sait"), ou confusion d'alias
- Préciser quel composant pipeline a laissé passer (génération, prompt système, contexte batch)

Si des fichiers `batch_*.json` sont disponibles, itère sur tous :

```python
import glob, json
from collections import Counter

# Charge GT pour la validation des types de relation (STU-314)
import glob as _glob
_gt_files = _glob.glob('library/sarah_j_maas/throne-of-glass/books/ground-truth/*.json')
_gt_by_entity = {}
_ANTAGONIST_KW = {'rival', 'antagoniste', 'ennemi', 'empoisonne', 'possédé', 'adversaire', 'venin'}
_POSITIVE_TYPES = {'amoureux', 'allié', 'ami', 'protecteur', 'mentor', 'confident', 'partenaire', 'amie'}
for _gf in _gt_files:
    with open(_gf) as _f:
        _gt = json.load(_f)
    if 'entity' in _gt:
        _subs = [(_gt['entity'], _gt)]
    else:
        _subs = [(k, v) for k, v in _gt.items() if isinstance(v, dict)]
    for _name, _obj in _subs:
        _canonical = _obj.get('canonical_aliases_book1', [])
        _entity_name = _canonical[0] if _canonical else _name
        _gt_by_entity[_entity_name] = _obj

batch_files = sorted(glob.glob('/mnt/user-data/uploads/batch_*.json'))
all_rels = []
for bf in batch_files:
    with open(bf) as f:
        batch = json.load(f)
    entities = batch.get('entities', [])
    print(f"\n=== {bf.split('/')[-1]} — {len(entities)} entités ===")
    for e in entities:
        rels = e.get('relationships', [])
        typed = [r for r in rels if r.get('relationship_type')]
        null_evol = [r for r in rels if r.get('evolution') in (None, 'relation stable dans les extraits fournis', '')]
        empty_moments = [r for r in rels if not r.get('key_moments')]
        no_evidence = [r for r in rels if not r.get('evidence')]
        tc = e.get('chapter_summary_context', [])
        tc_values = [s.get('temporal_context', '?') for s in tc] if isinstance(tc, list) else []
        print(f"\n{e['canonical_name']}: {len(typed)}/{len(rels)} relations typées")
        print(f"  evolution générique/null: {len(null_evol)}/{len(rels)}")
        print(f"  key_moments vides: {len(empty_moments)}/{len(rels)}")
        print(f"  evidence absent: {len(no_evidence)}/{len(rels)}")
        print(f"  aliases: {e.get('aliases', [])}")
        if typed:
            type_dist = Counter(r.get('relationship_type') for r in typed)
            print(f"  types: {dict(type_dist)}")
        if tc_values:
            tc_dist = Counter(tc_values)
            print(f"  temporal_context chapitres: {dict(tc_dist)}")
        # Validation types de relation contre GT known_relations_book1 (STU-314)
        entity_name = e.get('canonical_name', '')
        gt_obj = _gt_by_entity.get(entity_name, {})
        known_rels_gt = gt_obj.get('known_relations_book1', {})
        for r in rels:
            target = (r.get('target') or r.get('character') or '').strip()
            rel_type = (r.get('relationship_type') or '').lower()
            if not target or not rel_type:
                continue
            for gt_char, gt_desc in known_rels_gt.items():
                if gt_char.lower() in target.lower() or target.lower() in gt_char.lower():
                    is_antagonist = any(kw in gt_desc.lower() for kw in _ANTAGONIST_KW)
                    if is_antagonist and any(pos in rel_type for pos in _POSITIVE_TYPES):
                        print(f"  ⚠️ REL_TYPE_GT_MISMATCH: {entity_name}↔{target}: type='{rel_type}' mais GT décrit comme antagoniste/rival")
        all_rels.extend(rels)

# Sommaire global
print(f"\n=== GLOBAL ===")
total = len(all_rels)
print(f"Relations totales: {total}")
print(f"Typées: {sum(1 for r in all_rels if r.get('relationship_type'))}/{total}")
print(f"evolution générique: {sum(1 for r in all_rels if r.get('evolution') in (None,'relation stable dans les extraits fournis',''))}/{total}")
print(f"key_moments vides: {sum(1 for r in all_rels if not r.get('key_moments'))}/{total}")
print(f"evidence absent: {sum(1 for r in all_rels if not r.get('evidence'))}/{total}")
all_types = Counter(r.get('relationship_type') for r in all_rels if r.get('relationship_type'))
print(f"Distribution types: {dict(all_types)}")
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
| Zéro violation ground-truth (termes interdits, relations futures, signaux) | GT | ✅/⚠️/❌ | pages + terme exact |

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
| Violations ground-truth | - | - | - | - | - | - | ? | ? |
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

### Étape 6 — Sauvegarde de l'audit

Après avoir produit le verdict, sauvegarder les résultats dans le log d'audit du livre.

**Chemin pour Throne of Glass :**
```
library/sarah_j_maas/throne-of-glass/audits/audit_log.json
```

Le fichier est un tableau JSON. S'il n'existe pas, le créer avec `[]`. Sinon, charger le contenu existant et **ajouter** une nouvelle entrée à la fin — ne jamais écraser les entrées précédentes.

Structure d'une entrée :
```json
{
  "run": <numéro déduit du tableau cross-runs>,
  "date": "<date du jour YYYY-MM-DD>",
  "pages_generated": <N>,
  "infobox_pct": <0-100>,
  "lang_fr_pct": <0-100>,
  "alias_duplicates": <N>,
  "hallucinations": <N>,
  "gt_violations": [
    {"page": "<titre>", "signal": "<terme exact>", "cause": "<contamination_cross_serie|extrapolation|confusion_alias>"}
  ],
  "regression": {
    "prefixed_keys": "✅|⚠️|❌",
    "epub_ids": "✅|⚠️|❌",
    "entity_type_null": "✅|⚠️|❌",
    "alias_duplicates": "✅|⚠️|❌",
    "cross_serie": "✅|⚠️|❌",
    "evolution_quality": "✅|⚠️|❌",
    "temporal_context": "✅|⚠️|❌",
    "ground_truth": "✅|⚠️|❌"
  },
  "verdict": "<phrase de verdict concise>",
  "new_issues": ["<STU-XXX: description>"]
}
```

Utilise l'outil `Read` pour charger le fichier existant (s'il existe), ajoute l'entrée, puis `Write` pour sauvegarder le fichier complet.

## Format de sortie

Produis les étapes 2-5 dans cet ordre, sans reformuler les données brutes. Pas de prose introductive — aller direct au tableau de validation.

Si des nouvelles issues Linear sont justifiées, les créer via l'outil Linear après le verdict.

## Historique des issues connues

Issues Done (ne pas re-créer) : STU-260, STU-261, STU-262, STU-263, STU-264, STU-265, STU-266, STU-267, STU-268, STU-269, STU-270, STU-271, STU-272, STU-273, STU-274, STU-275, STU-276, STU-277, STU-278, STU-279, STU-280, STU-281, STU-282, STU-283, STU-284, STU-285, STU-286, STU-287, STU-288, STU-289, STU-290, STU-294, STU-314

Issues Backlog actives : aucune issue qualité ouverte au 2026-03-25.

Avant de créer une nouvelle issue, vérifier qu'elle ne doublon pas une issue existante via `Linear:list_issues` sur le projet Wiki Creator.
