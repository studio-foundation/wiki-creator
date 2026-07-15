#!/usr/bin/env python3
"""
Generate 8 gold training examples for LoRA fine-tuning in Alpaca JSONL format.

Uses build_prompt() from generate_wiki_pages.py to produce real instructions,
then pairs them with hand-crafted high-quality French wiki page outputs.

Usage:
    cd <worktree-root>
    python scripts/generate_gold_examples.py
"""

import glob
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAIN_REPO = PROJECT_ROOT.parents[1]  # the main repo root (batch files live there)

from scripts.generate_wiki_pages import (
    _DEFAULT_SECTIONS_BY_IMPORTANCE,
    build_prompt,
)
from wiki_creator.page_templates import slot_label

BOOK_TITLE = "Throne of Glass"

# Batch files may live in the main repo if the worktree wiki_inputs is empty
BATCH_DIR_CANDIDATES = [
    PROJECT_ROOT / "library/sarah_j_maas/throne-of-glass/wiki_inputs/01-throne-of-glass",
    MAIN_REPO / "library/sarah_j_maas/throne-of-glass/wiki_inputs/01-throne-of-glass",
]

ENTITY_NAMES = [
    "Chaol",
    "Nehemia",
    "Nox Owen",
    "Hollin",
    "Wyrdmarks",
    "Cain",
    "Elena",
    "Dorian Havilliard",
]

# ── Gold outputs ──────────────────────────────────────────────────────────────

GOLD_OUTPUTS = {
    "Chaol": {
        "title": "Chaol",
        "importance": "principal",
        "entity_type": "PERSON",
        "infobox_fields": {
            "nom": "Chaol Westfall",
            "alias": "Captain Westfall",
            "rôle": "Capitaine de la Garde Royale",
            "affiliation": "Couronne d'Adarlan",
            "statut": "Actif",
        },
        "content": (
            "## Infobox\n\n"
            "- Nom: Chaol Westfall\n"
            "- Alias: Captain Westfall\n"
            "- Rôle: Capitaine de la Garde Royale\n"
            "- Affiliation: Couronne d'Adarlan\n"
            "- Statut: Actif\n\n"
            "## Biographie\n\n"
            "Chaol Westfall est le capitaine de la Garde Royale du château de verre d'Adarlan. "
            "Chargé par le prince héritier Dorian Havilliard d'escorter l'assassin Celaena Sardothien "
            "depuis les mines de sel d'Endovier, il supervise son entraînement en vue du tournoi "
            "du Champion du Roi. Malgré ses réticences initiales à l'égard d'une criminelle condamnée, "
            "il développe progressivement un respect mutuel avec Celaena au fil de leurs séances "
            "d'entraînement quotidiennes.\n\n"
            "En tant que capitaine, Chaol est responsable de la sécurité du château et répond directement "
            "au prince Dorian. Sa position l'oblige à naviguer entre sa loyauté envers la couronne et "
            "les doutes croissants que lui inspire la compétition elle-même, notamment lorsque des "
            "concurrents commencent à mourir dans des circonstances suspectes. Il mène discrètement "
            "sa propre enquête sur ces décès tout en poursuivant sa mission officielle.\n\n"
            "## Personnalité\n\n"
            "Chaol se distingue par un sens aigu du devoir et une loyauté sans faille envers la couronne. "
            "Rigide dans l'application des règles, il se montre néanmoins capable de nuance lorsque "
            "les circonstances l'exigent. Son attitude envers Celaena évolue d'une méfiance professionnelle "
            "à une préoccupation sincère, bien qu'il s'efforce de maintenir une distance appropriée. "
            "Il exprime rarement ses émotions ouvertement, préférant agir plutôt que discourir.\n\n"
            "## Description physique\n\n"
            "Chaol possède des yeux brun doré et un visage aux traits marqués. De constitution athlétique, "
            "il porte l'uniforme de la Garde Royale avec une rigueur qui reflète son tempérament. "
            "Son apparence est celle d'un soldat aguerri, sans ostentation.\n\n"
            "## Relations\n\n"
            "**[[Celaena Sardothien]]** — allié / protecteur (mentions communes fréquentes). "
            "D'abord chargé de la surveiller, Chaol développe un respect grandissant pour les "
            "compétences et la détermination de Celaena. Leur relation évolue d'une méfiance "
            "réciproque vers une confiance prudente.\n\n"
            "**[[Dorian Havilliard]]** — ami proche / supérieur hiérarchique (mentions communes fréquentes). "
            "Ami d'enfance du prince, Chaol le sert avec une loyauté qui dépasse le cadre professionnel. "
            "Il est l'un des rares à oser contredire Dorian lorsqu'il estime que ses décisions sont imprudentes.\n\n"
            "## Anecdotes\n\n"
            "- Chaol accompagne régulièrement Celaena lors de ses promenades dans les jardins du château, "
            "officiellement pour la surveiller, mais ces sorties deviennent un rituel tacite entre eux.\n"
            "- Il est l'un des rares membres de la cour à s'entraîner quotidiennement à l'épée, "
            "maintenant une discipline martiale que la plupart des courtisans ont abandonnée.\n\n"
            "## Références\n\n"
            "- Throne of Glass"
        ),
    },
    "Nehemia": {
        "title": "Nehemia",
        "importance": "secondary",
        "entity_type": "PERSON",
        "infobox_fields": {
            "nom": "Nehemia",
            "rôle": "Princesse d'Eyllwe",
            "affiliation": "Royaume d'Eyllwe",
            "statut": "Actif",
        },
        "content": (
            "## Infobox\n\n"
            "- Nom: Nehemia\n"
            "- Rôle: Princesse d'Eyllwe\n"
            "- Affiliation: Royaume d'Eyllwe\n"
            "- Statut: Actif\n\n"
            "## Biographie\n\n"
            "Nehemia est la princesse héritière du royaume d'Eyllwe, envoyée à la cour d'Adarlan en qualité "
            "d'ambassadrice. Surnommée la « Lumière d'Eyllwe » par son peuple, elle représente les intérêts "
            "de sa nation conquise auprès du roi d'Adarlan. Malgré sa position diplomatique délicate, elle "
            "n'hésite pas à défendre ouvertement la cause de son peuple opprimé. Elle se lie d'amitié avec "
            "Celaena Sardothien, avec qui elle partage une intelligence vive et un refus de se soumettre.\n\n"
            "Nehemia possède une connaissance approfondie des Wyrdmarks, d'anciens symboles magiques qu'elle "
            "étudie et utilise. Sa maîtrise de ces signes la distingue de la plupart des habitants du château "
            "et la place au centre des mystères surnaturels qui s'y déroulent.\n\n"
            "## Relations\n\n"
            "**[[Celaena Sardothien]]** — alliée / confidente (mentions communes fréquentes). "
            "Nehemia et Celaena développent une amitié profonde fondée sur le respect mutuel "
            "et une combativité partagée face à l'injustice.\n\n"
            "## Références\n\n"
            "- Throne of Glass"
        ),
    },
    "Nox Owen": {
        "title": "Nox Owen",
        "importance": "figurant",
        "entity_type": "PERSON",
        "infobox_fields": {
            "nom": "Nox Owen",
            "rôle": "Voleur",
            "affiliation": "Perranth",
        },
        "content": (
            "## Infobox\n\n"
            "- Nom: Nox Owen\n"
            "- Rôle: Voleur\n"
            "- Affiliation: Perranth\n\n"
            "## Biographie\n\n"
            "Nox Owen est un jeune voleur originaire de Perranth, sélectionné comme concurrent dans le "
            "tournoi du Champion du Roi. Parmi les compétiteurs, il est l'un des rares à se montrer "
            "amical envers Celaena Sardothien, avec qui il développe une camaraderie discrète. Lors "
            "de l'épreuve d'escalade, Celaena intervient pour lui sauver la vie, un geste qui scelle "
            "leur alliance informelle au sein de la compétition."
        ),
    },
    "Hollin": {
        "title": "Hollin",
        "importance": "figurant",
        "entity_type": "PERSON",
        "infobox_fields": {
            "nom": "Hollin",
            "rôle": "Prince d'Adarlan",
            "affiliation": "Famille royale d'Adarlan",
        },
        "content": (
            "## Infobox\n\n"
            "- Nom: Hollin\n"
            "- Rôle: Prince d'Adarlan\n"
            "- Affiliation: Famille royale d'Adarlan\n\n"
            "## Biographie\n\n"
            "Hollin est le frère cadet du prince Dorian Havilliard, actuellement pensionnaire dans une "
            "école éloignée du château de verre. Bien qu'absent du récit principal, sa réputation le "
            "précède : décrit comme gâté et désagréable, il est réputé tenir davantage de son père "
            "que de son frère aîné, tant sur le plan physique que comportemental."
        ),
    },
    "Wyrdmarks": {
        "title": "Wyrdmarks",
        "importance": "principal",
        "entity_type": "OTHER",
        "infobox_fields": {},
        "content": (
            "## Infobox\n\n"
            "(Aucun champ applicable)\n\n"
            "## Biographie\n\n"
            "Les Wyrdmarks sont d'anciens symboles magiques dont l'origine remonte à une époque antérieure "
            "à la fondation des royaumes actuels. Ces marques constituent un système d'écriture arcane "
            "capable de canaliser des forces surnaturelles. Bien que la magie ait été interdite à Adarlan, "
            "les Wyrdmarks persistent sous forme de vestiges gravés dans la pierre et de savoirs transmis "
            "en secret.\n\n"
            "Dans le château de verre, des Wyrdmarks sont découverts dans les jardins et les passages "
            "souterrains. Leur présence est liée aux phénomènes surnaturels qui frappent la forteresse, "
            "notamment les apparitions spectrales et les morts inexpliquées parmi les concurrents du "
            "tournoi du Champion du Roi. Ces symboles semblent servir de conduits entre le monde physique "
            "et des forces anciennes.\n\n"
            "## Personnalité\n\n"
            "Sans objet — les Wyrdmarks sont des symboles, non une entité consciente.\n\n"
            "## Description physique\n\n"
            "Les Wyrdmarks se présentent sous la forme de symboles géométriques et curvilignes, souvent "
            "gravés dans la pierre ou tracés à même le sol. Leur apparence varie selon leur fonction : "
            "certains forment des cercles concentriques, d'autres des lignes angulaires entrecroisées. "
            "Lorsqu'ils sont activés, ils émettent une lueur caractéristique.\n\n"
            "## Pouvoirs et compétences\n\n"
            "Les Wyrdmarks possèdent des propriétés variées selon leur configuration. Parmi les usages "
            "attestés dans les extraits : la guérison de blessures, la protection contre des forces "
            "surnaturelles, et l'invocation ou le contrôle d'entités d'un autre plan. La princesse "
            "Nehemia d'Eyllwe est l'une des rares personnes à maîtriser leur utilisation, ayant hérité "
            "ce savoir de la tradition de son peuple.\n\n"
            "Les Wyrdmarks sont également associés aux Wyrdgates, des portails entre les mondes dont "
            "l'ouverture requiert une connaissance précise des symboles. L'utilisation incorrecte de ces "
            "marques peut avoir des conséquences catastrophiques, ce qui explique le secret entourant "
            "leur pratique.\n\n"
            "## Relations\n\n"
            "**[[Nehemia]]** — utilisatrice (mentions communes fréquentes). Nehemia possède une "
            "connaissance héritée des Wyrdmarks et les utilise à plusieurs reprises dans le récit.\n\n"
            "**[[Elena]]** — connexion historique. L'ancienne reine d'Adarlan est associée aux "
            "Wyrdmarks à travers l'histoire ancienne du royaume.\n\n"
            "## Anecdotes\n\n"
            "- Les Wyrdmarks trouvés dans les jardins du château sont initialement pris pour de simples "
            "décorations anciennes avant que leur nature magique ne soit révélée.\n"
            "- Celaena découvre un lien entre les Wyrdmarks et les meurtres des concurrents, ce qui "
            "l'amène à approfondir ses recherches sur ces symboles.\n\n"
            "## Références\n\n"
            "- Throne of Glass"
        ),
    },
    "Cain": {
        "title": "Cain",
        "importance": "secondary",
        "entity_type": "PERSON",
        "infobox_fields": {
            "nom": "Cain",
            "rôle": "Soldat, ancien membre de l'armée du roi",
            "affiliation": "Duc Perrington",
        },
        "content": (
            "## Infobox\n\n"
            "- Nom: Cain\n"
            "- Rôle: Soldat, ancien membre de l'armée du roi\n"
            "- Affiliation: Duc Perrington\n\n"
            "## Biographie\n\n"
            "Cain est un ancien soldat parrainé par le duc Perrington comme candidat au tournoi "
            "du Champion du Roi. D'une stature imposante et d'un tempérament intimidant, il s'impose "
            "rapidement comme le principal rival de Celaena Sardothien dans la compétition. Sa force "
            "physique semble croître de manière anormale au fil du tournoi, un phénomène lié à des "
            "forces surnaturelles auxquelles il est connecté par l'intermédiaire de son patron.\n\n"
            "Au-delà de ses capacités martiales, Cain est impliqué dans les aspects les plus sombres "
            "des événements du château. Sa connexion avec des forces occultes, facilitée par le duc "
            "Perrington, en fait non seulement un adversaire physique redoutable mais aussi une menace "
            "d'ordre surnaturel pour les autres concurrents.\n\n"
            "## Relations\n\n"
            "**[[Celaena Sardothien]]** — rival / antagoniste (mentions communes fréquentes). "
            "Cain représente le principal obstacle de Celaena dans le tournoi, tant sur le plan "
            "physique que surnaturel.\n\n"
            "**[[Duc Perrington]]** — patron (mentions communes). Le duc parraine Cain et semble "
            "impliqué dans l'augmentation surnaturelle de ses capacités.\n\n"
            "## Références\n\n"
            "- Throne of Glass"
        ),
    },
    "Elena": {
        "title": "Elena",
        "importance": "figurant",
        "entity_type": "PERSON",
        "infobox_fields": {
            "nom": "Elena",
            "rôle": "Première reine d'Adarlan",
            "affiliation": "Maison royale d'Adarlan, Terrasen",
        },
        "content": (
            "## Infobox\n\n"
            "- Nom: Elena\n"
            "- Rôle: Première reine d'Adarlan\n"
            "- Affiliation: Maison royale d'Adarlan, Terrasen\n\n"
            "## Biographie\n\n"
            "Elena est la première reine d'Adarlan, épouse du roi Gavin et fille de Brannon, "
            "fondateur de Terrasen. Figure historique du royaume, elle apparaît sous forme spectrale "
            "à Celaena Sardothien pour la mettre en garde contre une force maléfique tapie dans "
            "le château de verre. Ses interventions surnaturelles orientent Celaena vers la "
            "découverte des menaces occultes qui pèsent sur la compétition et le royaume."
        ),
    },
    "Dorian Havilliard": {
        "title": "Dorian Havilliard",
        "importance": "principal",
        "entity_type": "PERSON",
        "infobox_fields": {
            "nom": "Dorian Havilliard",
            "rôle": "Prince héritier d'Adarlan",
            "affiliation": "Couronne d'Adarlan",
            "statut": "Actif",
        },
        "content": (
            "## Infobox\n\n"
            "- Nom: Dorian Havilliard\n"
            "- Rôle: Prince héritier d'Adarlan\n"
            "- Affiliation: Couronne d'Adarlan\n"
            "- Statut: Actif\n\n"
            "## Biographie\n\n"
            "Dorian Havilliard est le prince héritier du royaume d'Adarlan, fils aîné du roi. "
            "C'est lui qui choisit Celaena Sardothien comme sa candidate au tournoi du Champion "
            "du Roi, la faisant extraire des mines de sel d'Endovier où elle purgeait sa peine. "
            "Cette décision, motivée autant par la curiosité que par le calcul politique, le place "
            "en opposition implicite avec son père et les autres membres de la cour.\n\n"
            "Dorian passe une grande partie de son temps dans la bibliothèque du château, où il "
            "nourrit une passion pour la lecture qui le distingue des autres membres de la famille "
            "royale. Sa relation avec son père est tendue : le roi méprise ce qu'il perçoit comme "
            "de la faiblesse chez son héritier, tandis que Dorian rejette la brutalité qui caractérise "
            "le règne paternel.\n\n"
            "## Personnalité\n\n"
            "Dorian se distingue par un charme naturel et un esprit vif qui dissimulent une profondeur "
            "inattendue. Lecteur avide et observateur attentif, il préfère la diplomatie à la force. "
            "Sa gentillesse, souvent perçue comme de la naïveté par les courtisans, masque une "
            "détermination tranquille à tracer son propre chemin. Il est capable d'autodérision et "
            "fait preuve d'un humour léger qui allège les situations tendues.\n\n"
            "Son rapport au pouvoir est ambivalent : conscient des responsabilités qui l'attendent, "
            "il refuse d'adopter les méthodes de son père et cherche une voie différente, sans "
            "toujours savoir laquelle.\n\n"
            "## Description physique\n\n"
            "Dorian possède des yeux bleu saphir, des cheveux noirs et des traits qui lui confèrent "
            "un charme classique. Son apparence soignée reflète son statut princier, mais il porte "
            "ses vêtements avec une décontraction qui le distingue de la rigidité formelle de la cour.\n\n"
            "## Relations\n\n"
            "**[[Celaena Sardothien]]** — intérêt romantique / allié (mentions communes très fréquentes). "
            "Dorian est attiré par l'intelligence et l'indépendance de Celaena. Leur relation oscille "
            "entre flirt, complicité intellectuelle et tension liée à leurs positions respectives.\n\n"
            "**[[Chaol Westfall]]** — ami proche (mentions communes très fréquentes). Ami d'enfance "
            "de Chaol, Dorian entretient avec lui une relation de confiance qui transcende la hiérarchie. "
            "Chaol est l'un des rares à lui parler sans déférence.\n\n"
            "**[[Roi d'Adarlan]]** — père / antagoniste (mentions communes). La relation entre Dorian "
            "et son père est marquée par le mépris du roi pour les inclinations intellectuelles de son "
            "fils et le refus de Dorian d'embrasser la cruauté paternelle.\n\n"
            "## Anecdotes\n\n"
            "- Dorian est un lecteur passionné qui fréquente la bibliothèque du château plus que "
            "tout autre membre de la famille royale.\n"
            "- Il offre des livres à Celaena, un geste qui devient un langage partagé entre eux.\n"
            "- Son chien de chasse l'accompagne fréquemment, ajoutant une touche informelle à son "
            "image princière.\n\n"
            "## Références\n\n"
            "- Throne of Glass"
        ),
    },
}


def find_batch_dir() -> Path:
    for d in BATCH_DIR_CANDIDATES:
        if list(d.glob("batch_*.json")):
            return d
    raise FileNotFoundError("No batch files found in any candidate directory")


def load_entity(batch_dir: Path, name: str) -> dict:
    for batch_file in sorted(batch_dir.glob("batch_*.json")):
        data = json.loads(batch_file.read_text())
        for entity in data.get("entities", []):
            if entity.get("canonical_name") == name:
                return entity
    raise ValueError(f"Entity '{name}' not found in batch files")


def get_sections(entity: dict) -> list[str]:
    importance = entity["importance"]
    section_keys = _DEFAULT_SECTIONS_BY_IMPORTANCE.get(importance, ["infobox", "biography"])
    return [slot_label(k, "fr") for k in section_keys]


def validate_example(example: dict, idx: int) -> list[str]:
    errors = []
    output = json.loads(example["output"])
    if not output.get("title"):
        errors.append(f"Example {idx}: empty title")
    if not output.get("content"):
        errors.append(f"Example {idx}: empty content")
    if output.get("entity_type") not in ("PERSON", "PLACE", "ORG", "EVENT", "OTHER"):
        errors.append(f"Example {idx}: invalid entity_type '{output.get('entity_type')}'")
    if output.get("importance") not in ("principal", "secondary", "figurant"):
        errors.append(f"Example {idx}: invalid importance '{output.get('importance')}'")
    if output.get("importance") != "figurant" and "## " not in output.get("content", ""):
        errors.append(f"Example {idx}: non-figurant missing ## headers")
    return errors


def main():
    batch_dir = find_batch_dir()
    print(f"Using batch dir: {batch_dir}")

    output_dir = PROJECT_ROOT / "processing_output/lora/throneofglass"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "gold_examples.jsonl"

    examples = []
    all_errors = []

    for i, name in enumerate(ENTITY_NAMES):
        entity = load_entity(batch_dir, name)
        importance = entity["importance"]
        section_keys = _DEFAULT_SECTIONS_BY_IMPORTANCE.get(importance, ["infobox", "biography"])

        instruction = build_prompt(entity, BOOK_TITLE, section_keys)
        gold = GOLD_OUTPUTS[name]
        output_json = json.dumps(gold, ensure_ascii=False)

        example = {
            "instruction": instruction,
            "input": "",
            "output": output_json,
        }
        examples.append(example)

        errors = validate_example(example, i + 1)
        all_errors.extend(errors)
        status = "PASS" if not errors else f"FAIL ({'; '.join(errors)})"
        print(f"  [{i+1}/8] {name} ({entity['type']}, {importance}) — {status}")

    with open(output_path, "w", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    print(f"\nWrote {len(examples)} examples to {output_path}")

    if all_errors:
        print(f"\nValidation errors ({len(all_errors)}):")
        for e in all_errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("All 8 examples passed validation.")

    # Summary stats
    print("\nSummary:")
    for ex in examples:
        out = json.loads(ex["output"])
        content_len = len(out["content"])
        has_headers = "## " in out["content"]
        print(f"  {out['title']:25s} | {out['entity_type']:6s} | {out['importance']:10s} | {content_len:5d} chars | headers: {has_headers}")


if __name__ == "__main__":
    main()
