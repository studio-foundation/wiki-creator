#!/usr/bin/env python3
"""Stage: relationship-classifier-validator (script executor)

Valide la classification d'une relation générée par relationship-classifier.

Input (Studio stdin):
  previous_outputs["relationship-classifier"]: classification générée
  input: données originales de la paire (entity_a, entity_b, sample_contexts)

Output (stdout):
  { "valid": bool, "errors": [...], "feedback": str }
"""
import json
import sys

from wiki_creator.page_templates import confidence_tokens, relationship_tokens

_GENERIC_EVOLUTIONS = {
    "relation stable dans les extraits fournis",
    "relation stable",
}

# Role-asymmetric authority relations (STU-495): in single-POV / group scenes the
# evidence is group-directed and often names only one party, so a single literal name
# in evidence is sufficient for these types.
_ROLE_ASYMMETRIC_TYPES = {"mentor", "employment"}

# Structural relationships (STU-496): pairs that never share a dyadic scene (rival
# Champions, institutional employer, mediated narrator-attributed killer). The
# classifier flags them with evidence_kind == "structural"; their evidence is a
# role/institution/causation line that may name only one party, like the asymmetric case.
_STRUCTURAL_EVIDENCE_KIND = "structural"


def parse_payload(payload: dict) -> tuple[dict, dict]:
    prev = payload.get("previous_outputs", {})
    clf = prev.get("relationship-classifier", {})
    inp = payload.get("input", {})
    return clf, inp


def allowed_types(meta: dict | None) -> list[str]:
    """Le vocabulaire réellement montré au modèle (STU-472).

    Il voyage dans le payload, donc les types propres au livre en font partie ;
    les valider contre `relationship_tokens()` rejetterait un type que le livre
    déclare et que le prompt vient d'envoyer. Payload sans vocabulaire (artefact
    pré-STU-472, appel hors pipeline) → l'enum générique.
    """
    declared = [
        str(d.get("name")).strip()
        for d in (meta or {}).get("relationship_types") or []
        if isinstance(d, dict) and str(d.get("name") or "").strip()
    ]
    return declared or relationship_tokens()


def check_relationship_type_valid(clf: dict, meta: dict | None = None) -> list[str]:
    rt = clf.get("relationship_type")
    if rt is None:
        return []  # null = co-occurrence sans interaction directe attestée, réponse valide
    if rt not in allowed_types(meta):
        return [f"❌ relationship_type invalide ou hors taxonomie : '{rt}'"]
    return []


def check_evidence_contains_both_names(clf: dict, meta: dict) -> list[str]:
    """Vérifie que le champ evidence mentionne les deux entités de la paire.

    Skippé si relationship_type est null (pas d'interaction directe).
    """
    rt = clf.get("relationship_type")
    if rt is None:
        return []  # null type → pas d'evidence requise

    evidence = clf.get("evidence") or ""
    evidence_lower = evidence.lower()

    entity_a = meta.get("entity_a", "")
    entity_b = meta.get("entity_b", "")

    if not evidence_lower:
        if not entity_a or not entity_b:
            return []  # pas d'info sur les entités, impossible de vérifier
        return [
            f"❌ evidence absent — fournis un extrait verbatim montrant l'interaction directe entre "
            f"'{entity_a}' et '{entity_b}'"
        ]

    present = [n for n in (entity_a, entity_b) if n and n.lower() in evidence_lower]
    missing = [n for n in (entity_a, entity_b) if n and n.lower() not in evidence_lower]

    is_structural = clf.get("evidence_kind") == _STRUCTURAL_EVIDENCE_KIND
    if is_structural or rt in _ROLE_ASYMMETRIC_TYPES:
        if not present and (entity_a or entity_b):
            reason = (
                "atteste le rôle/l'institution/la causation structurelle"
                if is_structural
                else "atteste la relation d'autorité (souvent une action dirigée vers un groupe)"
            )
            return [
                f"❌ evidence ne mentionne ni '{entity_a}' ni '{entity_b}' — "
                f"fournis l'extrait verbatim qui {reason}"
            ]
        return []

    if missing:
        return [
            f"❌ evidence ne mentionne pas : {', '.join(missing)} — "
            f"l'extrait doit montrer une interaction directe entre '{entity_a}' et '{entity_b}'"
        ]
    return []


def check_evolution_not_generic(clf: dict) -> list[str]:
    if clf.get("relationship_type") is None:
        return []  # null type → evolution non requise
    evol = clf.get("evolution")
    if evol is None:
        return []  # null explicite = valide (aucune évolution observable dans les extraits)
    if not evol.strip():
        return ["❌ evolution générique ou nulle — décris comment la relation évolue concrètement"]
    if evol.strip().lower() in _GENERIC_EVOLUTIONS:
        return ["❌ evolution générique ou nulle — décris comment la relation évolue concrètement"]
    return []


def check_confidence_graded(clf: dict) -> list[str]:
    """STU-476 : une relation typée porte un grade de confiance déclaré, une relation null aucun."""
    conf = clf.get("confidence")
    tokens = confidence_tokens()
    if clf.get("relationship_type") is None:
        if conf is None:
            return []
        return [f"❌ confidence doit être null quand relationship_type est null (reçu : '{conf}')"]
    if conf is None:
        return [
            "❌ confidence absent — grade la force de l'evidence citée : "
            f"{'|'.join(tokens)}"
        ]
    if conf not in tokens:
        return [f"❌ confidence hors vocabulaire : '{conf}' — attendu {'|'.join(tokens)}"]
    return []


def validate_classification(clf: dict, meta: dict) -> dict:
    errors: list[str] = []
    errors += check_relationship_type_valid(clf, meta)
    errors += check_evolution_not_generic(clf)
    errors += check_evidence_contains_both_names(clf, meta)
    errors += check_confidence_graded(clf)
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "feedback": build_feedback(errors, meta) if errors else "",
    }


def build_feedback(errors: list[str], meta: dict | None = None) -> str:
    lines = "\n".join(f"- {e}" for e in errors)
    return (
        "La classification précédente contient les erreurs suivantes. Régénère-la :\n"
        f"{lines}\n\n"
        "Rappels : utilise uniquement les types autorisés "
        f"({'|'.join(allowed_types(meta))}). "
        "evolution doit décrire une évolution observable dans les extraits, pas une phrase générique. "
        "evidence doit être un extrait verbatim de sample_contexts montrant les deux personnages "
        "en interaction directe — ce champ est obligatoire quand relationship_type n'est pas null. "
        f"confidence ({'|'.join(confidence_tokens())}) grade la force de cet extrait, pas ta "
        "certitude : un sourire cité verbatim reste un sourire."
    )


if __name__ == "__main__":
    payload = json.load(sys.stdin)
    clf, inp = parse_payload(payload)
    result = validate_classification(clf, inp)
    print(json.dumps(result))
