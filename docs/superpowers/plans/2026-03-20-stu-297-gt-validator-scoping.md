# STU-297 GT Validator Scoping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scope `hallucination_signals` checks to the relevant entity's page only, and fix GT loading to handle both flat and nested JSON formats.

**Architecture:** Single file edit in `.claude/skills/validate-wiki-run/SKILL.md`. The Python block in Étape 1b is replaced in two parts: (1) the loading block is replaced with a normalizer that handles flat and nested GT files, (2) the signal matching loop is scoped per entity. No pipeline code is touched.

**Tech Stack:** Python (embedded in Markdown), existing GT JSON files under `library/sarah_j_maas/throne-of-glass/books/ground-truth/`.

---

### Task 1: Update GT file list in SKILL.md prose

**Files:**
- Modify: `.claude/skills/validate-wiki-run/SKILL.md` (prose section above Étape 1b)

The current prose lists 6 files and omits `elena_and_gavin.json`. Find this line:

```
Fichiers : `celeana.json`, `chaol.json`, `dorian.json`, `king-of-adarlan.json`, `nehemia.json`, `perrington.json`
```

- [ ] **Step 1: Add `elena_and_gavin.json` to the file list**

Replace with:

```
Fichiers : `celeana.json`, `chaol.json`, `dorian.json`, `elena_and_gavin.json`, `king-of-adarlan.json`, `nehemia.json`, `perrington.json`
```

- [ ] **Step 2: Verify the edit**

Read the prose block of Étape 1b in SKILL.md. Confirm `elena_and_gavin.json` appears in the list.

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/validate-wiki-run/SKILL.md
git commit -m "docs(skill): add elena_and_gavin.json to GT file list in validate-wiki-run"
```

---

### Task 2: Replace the GT loading block (normalisation)

**Files:**
- Modify: `.claude/skills/validate-wiki-run/SKILL.md` (Python block, Étape 1b, lines ~88–107)

The current loading block does `name = gt['entity']` which crashes on `elena_and_gavin.json`. Replace the entire loading block (from `GT_DIR = ...` through `all_forbidden.append(...)`) with the normalizer below.

The new block produces:
- `gt_entries` — list of normalized dicts (one per entity), used for scoped signal matching
- `gt_by_entity` — dict (entity name → raw sub-object), kept for the relation check in section 3 (unchanged)

- [ ] **Step 1: Replace the loading block**

> ⚠️ Steps 1–2 show an intermediate version and its correction. **Use the final code from Step 3 directly** — skip Step 1's version if reading linearly.

Find and replace this block in the SKILL.md Python code:

```python
GT_DIR = 'library/sarah_j_maas/throne-of-glass/books/ground-truth'
gt_files = glob.glob(f'{GT_DIR}/*.json')

# Charge toutes les ground-truths
gt_by_entity = {}
all_signals = []   # (signal_text, entity_name)
all_forbidden = [] # (term, entity_name)

for gf in gt_files:
    with open(gf) as f:
        gt = json.load(f)
    name = gt['entity']
    gt_by_entity[name] = gt
    for sig in gt.get('hallucination_signals', []):
        all_signals.append((sig, name))
    forbidden = gt.get('forbidden_book1', {})
    for cat, items in forbidden.items():
        if isinstance(items, list):
            for item in items:
                all_forbidden.append((item, name, cat))
```

Replace with:

```python
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
            # Format imbriqué : clés dont la valeur est un dict (exclut 'entities', 'note', etc.)
            sub_objects = [(k, v) for k, v in gt.items() if isinstance(v, dict)]
        for name, obj in sub_objects:
            aliases = [name] + obj.get('canonical_aliases_book1', [])
            forbidden = []
            for cat, items in obj.get('forbidden_book1', {}).items():
                if isinstance(items, list):
                    for item in items:
                        forbidden.append((item, cat))
            entries.append({
                'entity': name,
                'canonical_aliases': aliases,
                'hallucination_signals': obj.get('hallucination_signals', []),
                'forbidden': forbidden,
            })
            by_entity[name] = obj
    return entries, by_entity

gt_entries, gt_by_entity = _load_gt_entries(gt_files)

# all_forbidden reste global (termes interdits s'appliquent à toutes les pages)
all_forbidden = []  # (term, entity_name, category)
for entry in gt_entries:
    for term, cat in entry['forbidden']:
        all_forbidden.append((term, entry['entity'], cat))
```

- [ ] **Step 2: Verify by mental trace**

Trace mentally (or exécute en console Python) avec `elena_and_gavin.json` :
- `'entity' in gt` → False (le fichier a `"entities"`, pas `"entity"`)
- `sub_objects` → `[('elena', {...}), ('gavin', {...})]`
- Pour `elena` : `aliases = ['elena'] + [...]` → à corriger : `name` est la clé string `'elena'`, pas le nom canonique

**Attention** : dans le format imbriqué, `name` est la clé du dict (`'elena'`, `'gavin'`), pas le nom canonique. Les `canonical_aliases_book1` de l'objet `gavin` sont `["Gavin Havilliard", "le premier roi d'Adarlan"]`. Donc `aliases[0]` = `'gavin'` (la clé), puis les aliases canoniques.

Pour que le scoping fonctionne, `canonical_aliases` doit contenir le nom canonique. Modifier la ligne :

```python
aliases = [name] + obj.get('canonical_aliases_book1', [])
```

en :

```python
canonical = obj.get('canonical_aliases_book1', [])
aliases = (canonical if canonical else [name]) + (canonical if canonical else [])
# Simplifié :
aliases = canonical if canonical else [name]
```

Soit plus lisiblement :

```python
aliases = obj.get('canonical_aliases_book1', []) or [name]
```

Cette version utilise les aliases canoniques en priorité (ex: `["Gavin Havilliard", "le premier roi d'Adarlan"]`). Si la liste est vide, repli sur la clé string.

Mettre à jour la ligne dans le code de l'étape précédente.

- [ ] **Step 3: Vérifier le résultat final du bloc de chargement**

Le bloc de chargement complet (après correction de l'étape 2) doit être :

```python
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
            })
            by_entity[entity_name] = obj
    return entries, by_entity

gt_entries, gt_by_entity = _load_gt_entries(gt_files)

# all_forbidden reste global (termes interdits s'appliquent à toutes les pages)
all_forbidden = []  # (term, entity_name, category)
for entry in gt_entries:
    for term, cat in entry['forbidden']:
        all_forbidden.append((term, entry['entity'], cat))
```

Note : `entity_name = canonical[0] if canonical else name` — utilise le premier alias canonique comme nom d'entité (ex: `"Gavin Havilliard"` plutôt que `"gavin"`). Cela assure que les messages de violation affichent un nom lisible.

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/validate-wiki-run/SKILL.md
git commit -m "fix(skill): normalize GT loading to handle flat and nested formats (STU-297)"
```

---

### Task 3: Remplacer le check de signaux (scoping)

**Files:**
- Modify: `.claude/skills/validate-wiki-run/SKILL.md` (Python block, Étape 1b, section "1. Cherche les signaux d'hallucination")

Le code actuel itère `all_signals` globalement. Remplacer par une boucle scopée sur `gt_entries`.

- [ ] **Step 1: Remplacer la section "1. Cherche les signaux d'hallucination"**

Trouver et remplacer :

```python
    for sig, entity in all_signals:
        phrases = _extract_match_phrases(sig)
        if any(ph.lower() in full_text.lower() for ph in phrases):
            page_violations.append(f"HALLUC_SIGNAL [{entity}]: {sig}")
```

Remplacer par :

```python
    # 1. Cherche les signaux d'hallucination — scopés à la page de l'entité concernée
    for entry in gt_entries:
        is_entity_page = any(a.lower() in title.lower() for a in entry['canonical_aliases'])
        if not is_entity_page:
            continue
        for sig in entry['hallucination_signals']:
            phrases = _extract_match_phrases(sig)
            if any(ph.lower() in full_text.lower() for ph in phrases):
                page_violations.append(f"HALLUC_SIGNAL [{entry['entity']}]: {sig}")
```

- [ ] **Step 2: Vérifier que `all_signals` n'est plus référencé**

Chercher dans le bloc Python de l'étape 1b toute occurrence de `all_signals`. Il ne doit plus en rester (la variable n'existe plus).

- [ ] **Step 3: Vérifier que la section 3 (relations) est intacte**

La section 3 utilise `gt_by_entity` (non modifié). Lire les lignes correspondantes et confirmer qu'elles sont inchangées :

```python
    # 3. Vérifie les relations contre known_relations_book1
    for gt_name, gt in gt_by_entity.items():
        if gt_name.lower() in title.lower() or any(a.lower() in title.lower() for a in gt.get('canonical_aliases_book1', [])):
```

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/validate-wiki-run/SKILL.md
git commit -m "fix(skill): scope hallucination_signals to entity page only (STU-297)"
```

---

### Task 4: Validation manuelle finale

- [ ] **Step 1: Lire le bloc Python complet de l'étape 1b**

Lire `.claude/skills/validate-wiki-run/SKILL.md` lignes 81–175 et tracer mentalement pour une page fictive "Gavin Havilliard" :

- Le signal `"Toute mention de son rôle dans la guerre contre Erawan"` (entité `Gavin Havilliard`) → `is_entity_page` = True seulement si `"Gavin Havilliard"` ou `"le premier roi d'Adarlan"` est dans le titre de la page
- Sur la page `"Celaena Sardothien"` → `is_entity_page` = False → signal ignoré ✓
- Sur la page `"Gavin Havilliard"` → `is_entity_page` = True → signal vérifié ✓

- [ ] **Step 2: Tracer pour `all_forbidden` (global)**

Confirmer que les termes de `forbidden_book1` sont toujours vérifiés sur toutes les pages via `all_forbidden` (inchangé).

- [ ] **Step 3: Commit final si des ajustements ont été faits**

```bash
git add .claude/skills/validate-wiki-run/SKILL.md
git commit -m "fix(skill): STU-297 GT validator scoping — final cleanup"
```
