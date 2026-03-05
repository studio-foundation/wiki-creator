# Design — STU-227 : Nettoyage phase 2

Date: 2026-03-04
Linear: STU-227

## Problème

Trois catégories d'artefacts passent encore après le nettoyage de STU-219 :

1. `\xa0` (espace insécable) dans les tokens spaCy — produit des mentions dupliquées (`M.\xa0Martín` ≠ `M. Martín`)
2. Espaces parasites dans les mots — `P edro` au lieu de `Pedro`, artefact de lettres capitulaires HTML
3. Mentions trop longues — spaCy étend l'entité au-delà du nom propre (`"Sempere junior acquiesça"`)

## Fichiers concernés

- `scripts/parse_epub.py` — fixes 1 et 2 (nettoyage texte)
- `scripts/entity_extraction.py` — fix 3 (post-traitement des spans spaCy)

---

## Fix 1 : Normalisation `\xa0` (`parse_epub.py`)

Dans `clean_chapter_text`, après `html.unescape()`, ajouter :

```python
text = text.replace('\xa0', ' ')
```

`html.unescape()` convertit `&nbsp;` HTML en `\xa0` Python. Le replace vient donc **après** unescape. Pas d'effet de bord.

## Fix 2 : Espaces dans les mots — lettres capitulaires (`parse_epub.py`)

Source : `<span class="lettrine">P</span>edro` → BeautifulSoup produit `P edro`.

Post-traitement dans `clean_chapter_text`, après l'unescape et le replace `\xa0` :

```python
# Coller une lettre majuscule isolée au mot suivant (artefact lettrine HTML)
text = re.sub(r'\b([A-ZÀÂÇÉÈÊËÎÏÔÙÛÜ])\s+(?=[a-záàâçéèêëîïôùûü])', r'\1', text)
```

Transforme `P edro` → `Pedro`, `L orca` → `Lorca`. Ne touche pas `M. Pedro` (suivi d'un point) ni les majuscules en fin de phrase.

## Fix 3 : Truncation des mentions trop longues (`entity_extraction.py`)

Approche choisie : tronquer au dernier token qui ressemble à un nom propre (commence par une majuscule ou a le POS tag `PROPN`).

Nouvelle fonction `_truncate_mention(span)` :

```python
def _truncate_mention(span) -> str:
    """Truncate span to its last proper-noun-like token."""
    tokens = list(span)
    last_proper = len(tokens)
    for i in range(len(tokens) - 1, -1, -1):
        if tokens[i].is_title or tokens[i].pos_ == "PROPN":
            last_proper = i + 1
            break
    return span.doc[span.start : span.start + last_proper].text
```

Appelé dans `extract_entities` pour obtenir le texte de mention avant de construire la clé :

```python
mention_text = _truncate_mention(ent)
key = mention_text.lower().strip()
```

Résultat attendu :
- `"Sempere junior acquiesça"` → `"Sempere junior"` (si `junior` est considéré title/propn)
- `"Barcelone de ténèbres"` → `"Barcelone"`
- `"Victor Grandes me sourit"` → `"Victor Grandes"`

---

## Critères d'acceptation

- [ ] `\xa0` normalisé — plus de `M.\xa0Martín` dans l'output
- [ ] `P edro` → `Pedro` — espaces parasites dans les mots corrigées
- [ ] `"Sempere junior acquiesça"` → `"Sempere junior"` — bouts de phrase éliminés
- [ ] `"Barcelone de ténèbres"` → `"Barcelone"` — idem pour les PLACE
- [ ] `make test` passe et le top-20 des clusters est propre
