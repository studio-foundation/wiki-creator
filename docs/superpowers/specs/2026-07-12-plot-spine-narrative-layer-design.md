# Plot Spine — Couche narrative pour Wiki Creator

**Date :** 2026-07-12
**Statut :** Design approuvé, à décomposer en issues (STU-478 + SP1–SP4)
**Issue parente :** STU-478

## Problème

Les pages générées sont **exactes mais incomplètes**. Comparé à la ground-truth livre 1 (`known_facts_book1`), la page Celaena capte le **décor** (corridors, escaliers, barre de traction) mais rate l'**intrigue** : le tournoi du Champion du Roi, sa libération par Dorian, la victoire sur Cain, l'empoisonnement de Kaltain, son couronnement — aucun n'apparaît.

**Cause racine :** la génération remonte le *fréquent* (mentions nombreuses de lieux/scènes) au détriment du *rare-mais-crucial* (« couronnée Champion » = 1 occurrence, climax). La lentille de fréquence ≠ importance narrative. Le résultat est une **fiche d'entité**, pas un **wiki d'histoire**.

Découverte de l'audit (run 18, 2026-07-12) : le matériau narratif **existe déjà** dans le pipeline mais n'est ni structuré ni assemblé.
- `chapter_summaries.json` : 55 résumés de chapitre avec `summary_bullets` (beats datés, grounded — STU-464).
- `relationships_classified.json` : `key_moments` par paire, datés par chapitre.
- Mais `chapter_summary_context` dans les bundles est **vide pour 11 entités sur 29**, dont Celaena (la protagoniste) — le générateur ne reçoit souvent pas les résumés.

## Objectifs

1. Doter le wiki d'une couverture d'**intrigue** fidèle et spoiler-safe, sur quatre surfaces : arc par personnage, synopsis du livre, pages d'événements, lieux à rôle narratif.
2. Ne pas dupliquer la logique de plot : une seule source structurée, plusieurs vues.
3. Réutiliser l'existant (résumés, key_moments, grounding STU-464, registre d'entités) — pas de nouvelle extraction LLM lourde.
4. Rester borné au livre courant (spoiler-free, invariant INV-WC-02).

Non-objectif : multi-livres/accumulation (STU-233), raisonnement multi-hop complet (STU-469) — cette couche les *alimente* mais ne les traite pas ici.

## Architecture

Une **couche d'événements structurée** construite en amont, et **quatre projections** rendues en prose LLM ancrée.

```
chapter_summaries.summary_bullets ─┐
relationships.key_moments ─────────┴──▶ [Event Layer]  (structuration déterministe)
                                          → events.json
                                                   │
        ┌──────────────┬──────────────────────────┼───────────────┬──────────────┐
        ▼              ▼                           ▼               ▼
  A. Arc perso    D. Lieu narratif           C. Page événement   B. Synopsis livre
  (par participant) (par lieu)                (un event déplié)   (tous events, ordonnés)
        └───────────── writer LLM ancré + validation grounding (pattern STU-464) ────────┘
```

### Composant central : Event Layer

Nouveau stage déterministe (zéro nouvelle extraction LLM), placé **après** `chapter-summary` et `relationship-classification`, **avant** `wiki-preparation` (qui construit les bundles).

**Entrées :** `chapter_summaries.json`, `relationships_classified.json`, le registre d'entités (`registry.json` / `alias_table`).

**Traitement :**
1. Collecter les beats : chaque `summary_bullet` (par chapitre) et chaque `key_moment` (par paire, par chapitre) est un beat candidat.
2. Résoudre les entités nommées dans le beat vers leurs **entités canoniques** via le registre (réutilise `alias_table`, cf. STU-435). Les noms de lieux → entités PLACE.
3. Agréger les beats d'un même chapitre décrivant le même événement (dédup par recouvrement participants + proximité textuelle).
4. Renseigner `outcome` quand un verbe de résolution / `action_cue` est présent (couronna, vainquit, tua…).
5. Scorer `salience` : combinaison de (a) présence d'`action_cues`, (b) position dans le livre (climax = derniers chapitres), (c) importance des participants. Sert au tri et au seuil des pages d'événements.
6. Conserver `source_bullets` pour la traçabilité/grounding.

**Sortie :** `events.json`
```json
{
  "event_id": "e_ch12_final_duel",
  "chapter": 12,
  "description": "Celaena affronte Cain lors de l'épreuve finale du tournoi",
  "participants": ["Celaena Sardothien", "Cain"],
  "places": ["Rifthold"],
  "outcome": "Celaena gagne malgré l'empoisonnement au bloodbane",
  "salience": 0.9,
  "source_bullets": ["C12: ..."]
}
```

**Corrige au passage :** le câblage `chapter_summary_context` vide — la couche garantit que chaque entité (dont les principales) reçoit ses événements dans le bundle.

### Projections (vues sur l'Event Layer)

Chaque projection = un filtre/tri sur `events.json` → un writer LLM ancré (réutilise le pattern `wiki-page-item` + validation grounding STU-464, spoiler-safe hérité des résumés).

- **A. Arc perso** — events où l'entité est participante, triés par chapitre → section « Rôle dans le récit » en prose sur la page PERSON.
- **B. Synopsis du livre** — tous les events, ordonnés par chapitre (ou par acte) → nouvelle page de synopsis.
- **C. Pages d'événements** — un event de salience ≥ seuil → nouvelle page : prose + infobox `{participants, lieu, chapitre, issue}`.
- **D. Lieu narratif** — events dont l'entité PLACE est dans `places` → section « Événements » sur la page PLACE (corrige Rifthold creux).

## Décomposition en sous-projets

SP0 est le socle ; SP1–SP4 sont indépendantes et parallélisables une fois SP0 livré.

| SP | Issue | Sujet | Dépend | Effort |
|---|---|---|---|---|
| SP0 | STU-478 (rescopé) | Event Layer + fix câblage `chapter_summary_context` | — | L |
| SP1 | *(nouvelle)* | Arc perso (« Rôle dans le récit ») | SP0 | M |
| SP2 | *(nouvelle)* | Lieu narratif (« Événements » sur PLACE) | SP0 | S |
| SP3 | *(nouvelle)* | Pages d'événements (nouveau type) | SP0 | M |
| SP4 | *(nouvelle)* | Synopsis du livre (nouvelle page) | SP0 | M |

**Ordre de livraison :** SP0 → SP1 (besoin d'origine) → SP2 (cheap, corrige Rifthold) → SP3/SP4.

## Tests

- **SP0** : sur TOG livre 1, `events.json` doit contenir les beats-clés de `known_facts_book1` (tournoi, duel Cain, couronnement) avec participants résolus canoniques ; chaque entité principale a ≥ N events ; aucun event ne référence une entité hors-registre.
- **SP1** : la section « Rôle dans le récit » de Celaena mentionne tournoi, victoire sur Cain, couronnement (validés contre GT `known_facts_book1`) ; zéro terme `forbidden_book1` (spoiler).
- **SP2** : la page Rifthold liste des événements réels (le tournoi s'y tient), pas seulement des corridors.
- **Grounding** : chaque affirmation de prose trace à un `source_bullet` (réutilise la validation STU-464).

## Décisions actées (brainstorm 2026-07-12)

- **Surfaces :** les quatre (arc, synopsis, events, lieux).
- **Extraction :** structurer l'existant (résumés + key_moments), pas de nouvelle passe LLM.
- **Rendu :** prose LLM ancrée pour toutes les surfaces narratives.
- **Scope :** feature complète planifiée, décomposée en SP0–SP4 (une issue chacune).

## Dépendances / liens

- Prérequis **déjà faits** : STU-433 (résumés pondérés par importance), STU-464 (grounding des résumés), STU-465 (pages PLACE ne plantent plus).
- Converge avec STU-469 (l'Event Layer alimente la détection de communautés / GraphRAG).
- Le label `EVENT` du NER maison (sous-exploité) pourra enrichir SP0 plus tard, mais n'est pas requis (on part des résumés).
