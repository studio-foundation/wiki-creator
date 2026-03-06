# Design — STU-117 : Export wiki complet (wikitext, infobox, catégories, Main_Page)

**Date :** 2026-03-05
**Ticket :** [STU-117](https://linear.app/studioag/issue/STU-117)
**Dépend de :** STU-231 (done)

---

## Problème

Le stage `wiki-generation` produit du Markdown. Fandom utilise MediaWiki markup (wikitext). STU-117 ajoute un stage d'export qui :

1. Convertit le Markdown en wikitext
2. Génère les templates d'infobox réutilisables
3. Génère les catégories hiérarchiques
4. Génère une Main_Page de navigation
5. Écrit un dossier `output/wiki/` prêt à importer dans Fandom

---

## Architecture

### Approche choisie : stage `wiki-export` + module `md2wiki`

- Un seul stage script executor (`wiki-export`) après `wiki-generation`
- La logique de conversion dans `wiki_creator/md2wiki.py` (testable indépendamment)
- `scripts/wiki_export.py` orchestre la génération des fichiers

---

## Modifications de wiki-generation (STU-231 output)

Le writer agent modifie son output par page pour séparer l'infobox du body :

```json
{
  "title": "David Martín",
  "importance": "principal",
  "entity_type": "PERSON",
  "infobox_fields": {
    "name": "David Martín",
    "aliases": "Raspoutine (par Isabella)",
    "status": "Vivant",
    "occupation": "Écrivain",
    "first_seen": "Chapitre 1"
  },
  "content": "## Biographie\n...\n## Personnalité\n..."
}
```

- `infobox_fields` : dict key-value pour le template Fandom
- `content` : body markdown **sans** l'infobox (le LLM ne la duplique pas)
- `entity_type` : `"PERSON"` | `"PLACE"` | `"ORG"`

Le contrat `wiki-generation.contract.yaml` ajoute `entity_type` et `infobox_fields` comme champs requis.

---

## Module `wiki_creator/md2wiki.py`

Conversion déterministe markdown → wikitext.

### Conversions

| Markdown | Wikitext |
|---|---|
| `## Heading` | `== Heading ==` |
| `### Sub` | `=== Sub ===` |
| `#### Sub2` | `==== Sub2 ====` |
| `**gras**` | `'''gras'''` |
| `*italique*` | `''italique''` |
| `[[Nom]]` | `[[Nom]]` ✓ passthrough |
| `[[Category:X]]` | `[[Category:X]]` ✓ passthrough |
| `> ⚠️ Spoilers...` | supprimé (inline warning géré par catégories) |

### API publique

```python
def convert(markdown: str) -> str:
    """Converts markdown body text to wikitext. Cross-refs and categories passthrough."""

def make_infobox_call(entity_type: str, fields: dict[str, str]) -> str:
    """
    Returns the wikitext template call for the given entity type.
    Example: '{{Infobox character\\n|name=David Martín\\n|status=Vivant\\n}}'
    entity_type: 'PERSON' | 'PLACE' | 'ORG'
    """
```

---

## Stage `wiki-export`

### Pipeline YAML

```yaml
- name: wiki-export
  kind: extraction
  executor: script
  runtime: python
  script: scripts/wiki_export.py
  context:
    include:
      - input
      - epub-parse
      - entity-classification
      - previous_stage_output   # wiki-generation
```

### Ce que fait `wiki_export.py`

1. Parse le contexte Studio (`additional_context` YAML + `previous_outputs`)
2. Pour chaque page dans `wiki-generation.pages` :
   - Appelle `md2wiki.make_infobox_call(entity_type, infobox_fields)`
   - Appelle `md2wiki.convert(content)` pour le body
   - Ajoute les `[[Category:X]]` selon type + importance
   - Écrit le fichier `.wiki` dans le bon sous-dossier
3. Génère les templates d'infobox statiques (`templates/`)
4. Génère `categories.wiki` (hiérarchie de catégories)
5. Génère `Main_Page.wiki`
6. Retourne un JSON avec les stats (`files_written`, `pages_count`, etc.)

---

## Structure de sortie

```
output/wiki/
├── Main_Page.wiki                    # Page d'accueil avec navigation
├── templates/
│   ├── Infobox_character.wiki        # Template MediaWiki réutilisable
│   ├── Infobox_location.wiki
│   └── Infobox_organization.wiki
├── characters/
│   ├── David_Martín.wiki
│   └── ...
├── locations/
│   └── ...
├── organizations/
│   └── ...
└── categories.wiki                   # Définitions des catégories parentes
```

### Nommage de fichiers

`canonical_name` → remplacer espaces par `_`, conserver accents.

---

## Templates d'infobox (MediaWiki)

Fichiers statiques générés une fois par type. Exemple `Infobox_character.wiki` :

```mediawiki
<includeonly>
{| class="infobox"
|-
! colspan="2" | {{{name}}}
|-
| '''Aussi connu comme''' || {{{aliases|}}}
|-
| '''Statut''' || {{{status|}}}
|-
| '''Occupation''' || {{{occupation|}}}
|-
| '''Résidence''' || {{{residence|}}}
|-
| '''Affiliation''' || {{{affiliation|}}}
|-
| '''Première apparition''' || {{{first_seen|}}}
|}
</includeonly>
```

Usage dans une page :
```
{{Infobox character
|name=David Martín
|aliases=Raspoutine (par Isabella)
|status=Vivant
|occupation=Écrivain
}}
```

---

## Catégories hiérarchiques

### Hiérarchie (langue configurable)

```
Contenu
├── Personnages
│   ├── Personnages principaux
│   └── Personnages secondaires
├── Lieux
└── Organisations
```

### Catégories ajoutées à chaque page

- PERSON, importance=principal → `[[Category:Personnages]]` + `[[Category:Personnages principaux]]`
- PERSON, importance=secondary → `[[Category:Personnages]]` + `[[Category:Personnages secondaires]]`
- PERSON, importance=figurant → `[[Category:Personnages]]`
- PLACE → `[[Category:Lieux]]`
- ORG → `[[Category:Organisations]]`

### Config langue dans `book.input.yaml`

```yaml
export:
  wiki_dir: output/wiki
  categories:
    language: fr   # ou 'en'
    labels:
      persons: Personnages
      principal: Personnages principaux
      secondary: Personnages secondaires
      locations: Lieux
      organizations: Organisations
```

---

## Main_Page.wiki

Contenu généré à partir des données pipeline :

- Titre du livre + auteur (depuis `epub-parse`)
- Top 5-8 personnages principaux (depuis `entity-classification`, triés par mentions)
- Top 5 lieux importants
- Navigation par catégorie
- Statistiques (N pages wiki, N personnages, N lieux, N organisations)

---

## Critères d'acceptation

- [ ] `wiki_creator/md2wiki.py` implémenté avec tests unitaires
- [ ] `writer.agent.yaml` modifié pour sortir `infobox_fields` + `entity_type` + body sans infobox
- [ ] `wiki-generation.contract.yaml` mis à jour
- [ ] `scripts/wiki_export.py` implémenté comme stage executor
- [ ] `wiki-pipeline.pipeline.yaml` inclut le stage `wiki-export`
- [ ] Templates d'infobox générés pour PERSON, PLACE, ORG
- [ ] Catégories hiérarchiques configurables en YAML (langue)
- [ ] Chaque page `.wiki` inclut les `[[Category:X]]` appropriées
- [ ] `categories.wiki` généré avec la hiérarchie parente
- [ ] `Main_Page.wiki` générée avec navigation et stats
- [ ] Noms de fichiers : espaces → underscores
- [ ] Cross-refs `[[Nom]]` passthrough (déjà générés par le writer)
- [ ] Testé sur *Le Jeu de l'Ange* : dossier `output/wiki/` copiable dans Fandom
