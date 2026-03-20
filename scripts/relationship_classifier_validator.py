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
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_VALID_TYPES = {
    "famille", "mentor/protégé", "amoureux", "antagoniste",
    "allié", "employeur/employé", "ami", "connaissance", "autre",
}

_GENERIC_EVOLUTIONS = {
    "relation stable dans les extraits fournis",
    "relation stable",
    "",
}


def parse_payload(payload: dict) -> tuple[dict, dict]:
    prev = payload.get("previous_outputs", {})
    clf = prev.get("relationship-classifier", {})
    inp = payload.get("input", {})
    return clf, inp


def check_relationship_type_valid(clf: dict) -> list[str]:
    rt = clf.get("relationship_type", "")
    if rt not in _VALID_TYPES:
        return [f"❌ relationship_type invalide ou hors taxonomie : '{rt}'"]
    return []


def check_evolution_not_generic(clf: dict) -> list[str]:
    evol = (clf.get("evolution") or "").strip().lower()
    if not evol or evol in _GENERIC_EVOLUTIONS:
        return ["❌ evolution générique ou nulle — décris comment la relation évolue concrètement"]
    return []


def validate_classification(clf: dict, meta: dict) -> dict:
    errors: list[str] = []
    errors += check_relationship_type_valid(clf)
    errors += check_evolution_not_generic(clf)
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "feedback": build_feedback(errors) if errors else "",
    }


def build_feedback(errors: list[str]) -> str:
    lines = "\n".join(f"- {e}" for e in errors)
    return (
        "La classification précédente contient les erreurs suivantes. Régénère-la :\n"
        f"{lines}\n\n"
        "Rappels : utilise uniquement les types autorisés "
        "(famille|mentor/protégé|amoureux|antagoniste|allié|employeur/employé|ami|connaissance|autre). "
        "evolution doit décrire une évolution observable dans les extraits, pas une phrase générique."
    )


if __name__ == "__main__":
    payload = json.load(sys.stdin)
    clf, inp = parse_payload(payload)
    result = validate_classification(clf, inp)
    print(json.dumps(result))
