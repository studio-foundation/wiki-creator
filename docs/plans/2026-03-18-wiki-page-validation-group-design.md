# Design — Wiki Page Validation Group (STU-291)

## Contexte

La Run 7 révèle des hallucinations persistantes dans les pages générées : mauvaise série (Kingkiller Chronicle pour Celaena), langue EN (Elena), alias inventés (Elena = Philippa), faits non ancrés. Le mécanisme Ralph existant retente aveuglément — il ne sait pas ce qui a cloché.

## Objectif

Ajouter un stage `wiki-page-validator` dans `wiki-page-item.pipeline.yaml`, wrappé dans un `group` Studio avec `max_iterations: 3`. Quand la validation échoue, le `group_feedback` (erreurs précises + instructions correctives) est injecté dans le contexte de `wiki-page-item` au tour suivant.

## Architecture

### Pipeline modifié

```yaml
# .studio/pipelines/wiki-page-item.pipeline.yaml
name: wiki-page-item
version: 2

stages:
  - group: generation-validation
    max_iterations: 3
    stages:
      - name: wiki-page-item
        kind: analysis
        agent: wiki-page-item
        contract: wiki-page-item
        ralph:
          max_attempts: 3
        context:
          include:
            - input
            - group_feedback   # erreurs du validator au tour précédent

      - name: wiki-page-validator
        kind: validation
        executor: script
        runtime: python
        script: scripts/wiki_page_validator.py
        contract: wiki-page-validator
        context:
          include:
            - input
            - previous_stage_output
```

### Logique du validator (`scripts/wiki_page_validator.py`)

Deux passes :

**Passe 1 — Checks structurels (toutes importances)**

| Check | Source de configuration | Message d'erreur |
|---|---|---|
| Langue FR | détection lexicale (`is the`, `was a`, `known as`…) | `❌ Contenu en anglais détecté` |
| Zéro ID EPUB | `.xhtml` dans `content` | `❌ ID EPUB dans le contenu` |
| Clés infobox sans `- ` | préfixe sur les clés de `infobox_fields` | `❌ Clé infobox préfixée` |
| Infobox non vide | `infobox_fields` non vide pour PERSON/PLACE | `⚠️ Infobox vide` |
| Zéro hallucination cross-série | `book.yaml > validation.forbidden_series` | `❌ Hallucination cross-série : <keyword>` |
| Série ancrée au premier paragraphe | titre depuis `book.yaml > series` | `❌ Titre de série absent du premier paragraphe` |

Les mots interdits viennent du YAML du livre — jamais hardcodés dans le script.

**Passe 2 — Grounding LLM (PERSON `principal` et `secondary` seulement)**

Agent `wiki-page-validator` : compare les extraits source (input prompt) avec la page générée, flag les affirmations non ancrées.

**Format de sortie :**

```json
{
  "valid": false,
  "errors": [
    "❌ Langue anglaise détectée",
    "❌ Hallucination cross-série : Kingkiller Chronicle"
  ],
  "feedback": "Régénère la page en respectant ces contraintes : ..."
}
```

### Agent de grounding (`.studio/agents/wiki-page-validator.agent.yaml`)

```yaml
name: wiki-page-validator
provider: ollama
model: mistral
system_prompt: |
  Tu es un validateur de pages wiki pour un roman fantasy.
  Tu reçois les extraits source (input["prompt"]) et la page générée (input["page"]).
  Pour chaque affirmation dans la page, vérifie qu'elle est directement ancrée dans les extraits.
  Retourne UNIQUEMENT :
  {
    "grounded": true | false,
    "ungrounded_claims": ["claim non supportée", ...]
  }
  Ne t'appuie sur aucune connaissance externe.
```

## Fichiers à créer/modifier

| Fichier | Action |
|---|---|
| `.studio/pipelines/wiki-page-item.pipeline.yaml` | Modifier — wrap dans un `group generation-validation` |
| `.studio/agents/wiki-page-validator.agent.yaml` | Créer |
| `.studio/contracts/wiki-page-validator.contract.yaml` | Créer |
| `scripts/wiki_page_validator.py` | Créer |
| `library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml` | Modifier — ajouter `validation.forbidden_series` |

## Configuration book YAML

```yaml
validation:
  forbidden_series:
    - Kingkiller Chronicle
    - A Court of Thorns and Roses
    - An Ember in the Ashes
    - The Selection
  series: Throne of Glass
```

## Critères de validation

- Run 8 : Celaena mentionne "Throne of Glass" au premier paragraphe
- Run 8 : Elena page en FR, sans alias Philippa
- Run 8 : Zéro hallucination cross-série dans toutes les pages
- `wiki_page_validator.py` couvert par tests unitaires (checks structurels)
