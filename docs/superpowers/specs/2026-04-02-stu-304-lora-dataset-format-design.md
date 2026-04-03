o# STU-304 + STU-305 — LoRA Dataset : Format JSONL et exemples gold pour wiki-page-item

## Objectif

Définir le format canonique des exemples d'entraînement LoRA pour fine-tuner l'agent `wiki-page-item`, produire un script d'export qui transforme les données existantes (fandom scrape + pipeline outputs) en dataset JSONL prêt pour Unsloth/HuggingFace PEFT, et générer ~20 exemples gold directement en conversation avec Claude.

## Format JSONL (Alpaca template)

Chaque ligne du fichier JSONL contient une paire instruction/output :

```json
{
  "instruction": "<prompt complet identique à build_prompt()>",
  "input": "",
  "output": "{\"title\": \"...\", \"importance\": \"...\", \"entity_type\": \"...\", \"infobox_fields\": {...}, \"content\": \"...\"}"
}
```

### Champs obligatoires dans `output`

| Champ | Type | Contraintes |
|-------|------|-------------|
| `title` | string | Non vide |
| `importance` | string | `principal` \| `secondary` \| `figurant` |
| `entity_type` | string | `PERSON` \| `PLACE` \| `ORG` \| `OTHER` |
| `infobox_fields` | dict | Peut être `{}` pour figurants |
| `content` | string | Markdown non vide, `##` headers (sauf figurants) |

### Compatibilité

- Template : **Alpaca** (`instruction` / `input` / `output`)
- Compatible : Unsloth, HuggingFace PEFT, Axolotl
- Le champ `input` reste vide — tout le contexte est dans `instruction`

## Sources de données

### 1. Fandom scrape (source principale)

- Fichier : `processing_output/fandom/throneofglass/lora_dataset_fandom.jsonl`
- Volume : 227 pages (185 PERSON, 42 PLACE)
- Langue du contenu : anglais (conservé tel quel — le prompt force la sortie en français)
- Format d'entrée : `{source, wiki_slug, page_title, entity_type, infobox_fields, content, content_lang, scraped_at}`

### 2. Pipeline outputs (source complémentaire)

- Fichier : `processing_output/<slug>/wiki_pages.json`
- Volume : ~30 pages par livre
- Les pages avec `_failed: true` sont exclues
- L'instruction est reconstruite via `build_prompt()` à partir des batch files correspondants

### 3. Exemples gold (STU-305)

- ~20 exemples générés en conversation avec Claude, basés sur les entités des batch files
- Couvrent la matrice complète : PERSON principal, PERSON secondaire, PERSON figurant, PLACE principal, PLACE figurant, ORG, OTHER
- Sauvegardés dans `processing_output/lora/throneofglass/gold_examples.jsonl`
- Servent de référence qualité pour le training set et de validation du format avant l'export complet
- Pas de script API — les exemples sont produits interactivement et validés par l'utilisatrice

## Split train/eval

| Split | Critère | Source |
|-------|---------|--------|
| **eval** | Entités `principal` du fandom (matchées contre les batch files, ou par heuristique de longueur) | ~20-30 pages |
| **train** | Tout le reste (fandom secondaires/figurants + pipeline validés + gold examples) | ~200+ pages |

Justification : les personnages principaux sont ceux où la qualité compte le plus ; on veut mesurer la performance du modèle sur eux, pas les mémoriser.

## Script d'export : `scripts/export_lora_dataset.py`

### Interface CLI

```bash
python scripts/export_lora_dataset.py \
  --fandom-jsonl processing_output/fandom/throneofglass/lora_dataset_fandom.jsonl \
  --book library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml \
  --output-dir processing_output/lora/throneofglass/
```

### Sorties

- `train.jsonl` — exemples d'entraînement
- `eval.jsonl` — exemples d'évaluation
- `export_report.json` — stats (nb exemples par source, par type, pages rejetées avec raison)

### Pipeline de nettoyage fandom

Le contenu fandom brut (wikitext) est converti en Markdown propre :

1. **Strip metadata** : `[[Category:...]]`, `<gallery>...</gallery>`, `{{templates}}`, `<references/>`
2. **Convertir syntaxe wiki → Markdown** : `[[Link|Text]]` → `Text`, `[[Link]]` → `Link`, `'''bold'''` → `**bold**`, `''italic''` → `*italic*`
3. **Supprimer sections vides** : header sans contenu avant le header suivant
4. **Normaliser infobox fields** : mapping configurable EN→FR (ex: `name` → `nom`, `allegiance` → `affiliation`, `status` → `statut`)
5. **Rejeter pages** : contenu < 50 caractères après nettoyage

### Reconstruction de l'instruction (fandom)

Pour les pages fandom, le prompt est synthétisé à partir des métadonnées disponibles :
- `page_title` → `canonical_name`
- `entity_type` → `type`
- `infobox_fields` → extraction d'aliases si disponibles
- Importance : d'abord match par `canonical_name` contre les entités du batch file (si `--book` fourni) pour récupérer l'importance connue. Sinon, heuristique par longueur de contenu : > 2000 chars → `principal`, > 500 → `secondary`, sinon `figurant`
- Pas de `context_by_chapter` ni `relationships` — ces blocs sont laissés vides dans le prompt synthétisé

### Reconstruction de l'instruction (pipeline)

Pour les pages pipeline, le prompt est reconstruit via `build_prompt()` en chargeant l'entité depuis le batch file correspondant (match par `title`).

## Validation par ligne

Chaque ligne JSONL est validée avant écriture :

- `output` est du JSON parseable
- `title` et `content` non vides
- `entity_type` ∈ `{PERSON, PLACE, ORG, OTHER}`
- `importance` ∈ `{principal, secondary, figurant}`
- `content` contient au moins un `##` header (sauf figurants)

Les lignes invalides sont rejetées et loguées dans `export_report.json`.

## Cas limites

| Cas | Traitement |
|-----|------------|
| **Figurant** | `infobox_fields` peut être `{}`, `content` = 1 paragraphe sans headers |
| **PERSON = animal** (ex: Abraxos) | On garde `PERSON` — le type couvre les personnages au sens large |
| **Pages fandom multi-livres** | Contenu complet conservé — le prompt spécifie le livre, le modèle apprend à filtrer |
| **Sections vides fandom** (`### ''Queen of Shadows''` sans contenu) | Supprimées au nettoyage |
| **Pages avec `_failed` ou `_spoiler_rejected`** | Exclues du dataset |

## Structure de fichiers

```
processing_output/lora/throneofglass/
├── train.jsonl
├── eval.jsonl
└── export_report.json
```
