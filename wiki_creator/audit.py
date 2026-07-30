"""Run-audit logic behind scripts/audit_run.py (validate-wiki-run skill).

Pure functions over run artifacts — no LLM, no network. Each check ports the
inline audit code the skill used to carry, with its accumulated fixes:
- STU-294: hallucination signals match on the full phrase, not the first token;
- STU-465: forbidden terms are suppressed when attributed to another entity;
- STU-314: identity-confusion phrases + infobox alias cross-entity check;
- STU-717: structured infobox relation slots checked with polarity keywords.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from wiki_creator.ground_truth import GtEntry, alias_lookup

# ---------------------------------------------------------------------------
# Page loading

def load_pages(wiki_pages_path: Path | str) -> list[dict]:
    data = json.loads(Path(wiki_pages_path).read_text())
    return data.get("pages", data) if isinstance(data, dict) else data


_INFOBOX_RE = re.compile(r"\{\{Infobox[^\n]*\n(.*?)\n\}\}", re.DOTALL)


def pages_from_wiki_dir(output_dir: Path | str) -> list[dict]:
    """Rebuild {title, content, infobox_fields} records from rendered .wiki
    files, so the ground-truth validation can run against a committed run
    (gate 1 of the corpus double-gate) with the exact same logic."""
    pages = []
    root = Path(output_dir)
    for wf in sorted(root.rglob("*.wiki")):
        # templates/ holds infobox sources; real-wiki/ is a scraped reference
        # copy — neither is generated output.
        rel = wf.relative_to(root).as_posix()
        if rel.startswith(("templates/", "real-wiki/")):
            continue
        text = wf.read_text()
        infobox: dict[str, str] = {}
        m = _INFOBOX_RE.search(text)
        content = text
        if m:
            for line in m.group(1).splitlines():
                line = line.strip()
                if line.startswith("|") and "=" in line:
                    k, _, v = line[1:].partition("=")
                    infobox[k.strip()] = v.strip()
            content = text[: m.start()] + text[m.end() :]
        pages.append(
            {
                "title": wf.stem.replace("_", " "),
                "content": content,
                "infobox_fields": infobox,
            }
        )
    return pages


# ---------------------------------------------------------------------------
# Step 1 — per-page metrics

def page_metrics(pages: list[dict], known_issues: dict | None = None) -> dict:
    """Per-page issue flags + summary. known_issues is the optional per-series
    audits/known_issues.json: {"hallucination_keywords": {kw: label},
    "duplicate_titles": [...]}."""
    ki = known_issues or {}
    halluc_kw: dict[str, str] = ki.get("hallucination_keywords", {})
    rows = []
    for p in pages:
        ib = p.get("infobox_fields", {})
        content = p.get("content", "")
        issues = []
        if not ib:
            issues.append("infobox_vide")
        if any(k.startswith("- ") for k in ib):
            issues.append("clés_préfixées")
        if ".xhtml" in content:
            issues.append("IDs_EPUB")
        if "## Relations" in content or "**Relations**" in content:
            issues.append("✓Relations")
        if p.get("_failed"):
            issues.append("_failed")
        for kw, label in halluc_kw.items():
            if kw in content + str(ib):
                issues.append(label)
        en = any(
            w in content
            for w in ["is the", "was a", "known as", "also known", "she was", "he is"]
        )
        fr = any(
            w in content
            for w in [" est ", " une ", " était", "dans le", " il est", " elle est"]
        )
        # Absence of the EN sample phrases is NOT French — expected language is
        # the book's own; the sniff only surfaces cross-language contamination.
        lang = "MIXTE" if en and fr else ("FR" if fr else "EN")
        rows.append(
            {
                "title": p.get("title", "?"),
                "importance": p.get("importance", "?"),
                "entity_type": p.get("entity_type", "?"),
                "infobox_len": len(ib),
                "lang": lang,
                "issues": issues,
            }
        )
    titles = [p.get("title") for p in pages]
    summary = {
        "pages": len(pages),
        "infobox_populated": sum(1 for p in pages if p.get("infobox_fields")),
        "prefixed_keys": sum(
            1
            for p in pages
            if any(k.startswith("- ") for k in p.get("infobox_fields", {}))
        ),
        "relations_heading": sum(
            1
            for p in pages
            if "## Relations" in p.get("content", "")
            or "**Relations**" in p.get("content", "")
        ),
        "epub_ids": sum(1 for p in pages if ".xhtml" in p.get("content", "")),
        "duplicates_present": [
            d for d in ki.get("duplicate_titles", []) if d in titles
        ],
    }
    return {"rows": rows, "summary": summary}


# ---------------------------------------------------------------------------
# Step 1b — ground-truth validation

REL_POLARITY = {
    # Polarity keywords per slot: a forbidden only contradicts a slot when it
    # carries the right TYPE of relation — plain name co-occurrence must not
    # fire on a real, legitimate relation (STU-717).
    "friends_allies": ("friend", "ally", "allies", "allié", "companion", "knows"),
    "enemies": ("enemy", "enemies", "ennemi", "adversar", "attack", "hostile", "rival", "foe"),
    "romance": ("married", "marries", "marry", "spouse", "lover", "romance",
                "betroth", "wife", "husband", "in love", "épous"),
    "family": ("mother", "father", "sister", "brother", "aunt", "uncle", "cousin",
               "relative", "daughter", "son ", "parent", "spouse", "married",
               "belonging to", "niece", "nephew", "grandmother", "grandfather"),
}

_SIGNAL_PREFIXES = (
    "Toute mention de ",
    "Toute scène ou dialogue de ",
    "Toute mention d'",
    "Any mention of ",
    "Any scene or dialogue of ",
)


def _extract_match_phrases(signal: str) -> list[str]:
    """Match phrases from a hallucination signal — the full phrase, never the
    first token (STU-294), and never cut on 'comme \\w' which reduced
    discriminating phrases to bare tokens (STU-465)."""
    phrase = signal
    for prefix in _SIGNAL_PREFIXES:
        if phrase.startswith(prefix):
            phrase = phrase[len(prefix):]
            break
    phrase = re.split(
        r"\s*[\(—]|\s+dans (?:le|la|une|l')\b|\s+en lien\b|\s+par nom\b|\s+scopée\b",
        phrase,
    )[0]
    phrase = phrase.strip(" '\"")
    parts = [part.strip(" '\"") for part in phrase.split(",")]
    return [part for part in parts if len(part) >= 5]


@dataclass
class PageResult:
    title: str
    entity: str | None
    violations: list[str] = field(default_factory=list)
    advisories: list[str] = field(default_factory=list)


def validate_ground_truth(
    pages: list[dict], entries: list[GtEntry], by_entity: dict[str, dict]
) -> list[PageResult]:
    lookup = alias_lookup(entries)
    results = []
    for p in pages:
        results.append(_validate_page(p, entries, by_entity, lookup))
    return results


def _find_page_entry(title: str, entries: list[GtEntry]) -> GtEntry | None:
    # Bidirectional: the page title can be a bare token ("Elena") while the GT
    # aliases are full names ("Elena Galathynius") — and the reverse (STU-465).
    for entry in entries:
        if any(
            a.lower() in title.lower()
            or (len(title) >= 4 and title.lower() in a.lower())
            for a in entry.canonical_aliases
        ):
            return entry
    return None


def _validate_page(
    p: dict,
    entries: list[GtEntry],
    by_entity: dict[str, dict],
    lookup: dict[str, str],
) -> PageResult:
    title = p.get("title", "?")
    content = p.get("content", "")
    ib = p.get("infobox_fields", {})
    full_text = content + " " + str(ib)
    tl = full_text.lower()

    entry = _find_page_entry(title, entries)
    res = PageResult(title=title, entity=entry.entity if entry else None)

    # 1. Hallucination signals — scoped to the owning entity's page.
    if entry:
        for sig in entry.hallucination_signals:
            phrases = _extract_match_phrases(sig)
            if any(ph.lower() in tl for ph in phrases):
                res.violations.append(f"HALLUC_SIGNAL [{entry.entity}]: {sig}")

        # 1b. Explicit identity confusions (STU-314).
        for phrase in entry.identity_confusion_forbidden:
            if phrase.lower() in tl:
                res.violations.append(
                    f"IDENTITY_CONFUSION [{entry.entity}]: '{phrase}'"
                )

        # 1c. Infobox alias naming another GT entity (STU-314).
        for ak in ["alias", "aliases", "pseudonyme", "pseudonymes",
                   "noms alternatifs", "other names"]:
            ib_val = ib.get(ak, "")
            if not ib_val:
                continue
            parts = (
                ib_val
                if isinstance(ib_val, list)
                else [v.strip() for v in str(ib_val).split(",")]
            )
            for part in parts:
                part = part.strip()
                matched = lookup.get(part.lower()) if part else None
                if matched and matched != entry.entity:
                    res.violations.append(
                        f"INFOBOX_ALIAS_CROSS [{entry.entity}→{matched}]: "
                        f"infobox '{ak}={part}' matches GT entity '{matched}'"
                    )

    # 2. Forbidden terms, with attribution suppression (STU-465): a term
    # forbidden for entity A may be a legitimate fact of entity B mentioned on
    # the page. Look at the closest GT entity named BEFORE the occurrence.
    def _attributed_entity(pos: int, window: int = 60) -> str | None:
        seg = tl[max(0, pos - window):pos]
        best_off, best_ent = -1, None
        for alias_lower, ent in lookup.items():
            off = seg.rfind(alias_lower)
            if off > best_off:
                best_off, best_ent = off, ent
        return best_ent

    page_entity = entry.entity if entry else None
    for e in entries:
        for term, cat in e.forbidden:
            # Word-boundary match, not bare substring: the old .find() forced
            # dropping every <=4-char term ('Bree' in 'breeze'), silencing
            # short proper nouns ('Elva', 'Aren') entirely.
            if len(term) <= 2:
                continue
            real_hit = False
            for m in re.finditer(
                r"(?<!\w)" + re.escape(term.lower()) + r"(?!\w)", tl
            ):
                attributed = _attributed_entity(m.start())
                if e.entity == page_entity:
                    # Page owned by the term's entity: flag, UNLESS explicitly
                    # attributed to ANOTHER GT entity.
                    if attributed is None or attributed == e.entity:
                        real_hit = True
                        break
                else:
                    # Foreign forbidden term: almost always a legitimate
                    # mention — flag only when the OWNER is named just before
                    # (true cross-page contamination).
                    if attributed == e.entity:
                        real_hit = True
                        break
            if real_hit:
                res.violations.append(f"FORBIDDEN [{e.entity}/{cat}]: '{term}'")

    # 3. Structured infobox relation slots vs the corpus (STU-717): a slot
    # violation ("enemies=[[Bill]]") never matches the corpus sentence in
    # substring — read the slots themselves.
    if entry:
        def _entity_aliases(ent: str) -> list[str]:
            obj = by_entity.get(ent, {})
            return obj.get("canonical_aliases_book1", []) or [ent]

        def _named_in(ent: str, phrase_lower: str) -> bool:
            return any(
                re.search(r"(?<!\w)" + re.escape(a.lower()) + r"(?!\w)", phrase_lower)
                for a in _entity_aliases(ent)
            )

        def _forbidden_phrases(ent: str) -> list[str]:
            out = []
            for items in by_entity.get(ent, {}).get("forbidden_book1", {}).values():
                if isinstance(items, list):
                    out.extend(items)
            return out

        def _resolve_target(name: str) -> str | None:
            n = name.strip().lower()
            hit = lookup.get(n)
            if hit:
                return hit
            n2 = re.sub(r"^the\s+", "", n)  # [[Mouse]] <-> GT "the Mouse"
            for alias_lower, ent in lookup.items():
                if n2 == re.sub(r"^the\s+", "", alias_lower):
                    return ent
            return None

        known_rels = by_entity.get(entry.entity, {}).get("known_relations_book1", {})
        for slot, keywords in REL_POLARITY.items():
            slot_val = ib.get(slot)
            if not slot_val:
                continue
            targets = re.findall(r"\[\[([^\]|]+)", str(slot_val))
            if not targets:
                targets = [t.strip() for t in str(slot_val).split(",") if t.strip()]
            for tgt in targets:
                tgt = tgt.strip()
                target_entity = _resolve_target(tgt)
                # HARD: a forbidden (page side OR target side) names BOTH ends
                # with the right polarity — the relation is explicitly banned.
                hit = None
                for src in [entry.entity] + ([target_entity] if target_entity else []):
                    for ph in _forbidden_phrases(src):
                        pl = ph.lower()
                        if (
                            target_entity
                            and _named_in(entry.entity, pl)
                            and _named_in(target_entity, pl)
                            and any(k in pl for k in keywords)
                        ):
                            hit = ph
                            break
                    if hit:
                        break
                if hit:
                    res.violations.append(
                        f"STRUCTURED_REL [{entry.entity}/{slot}]: [[{tgt}]] — "
                        f"forbidden by the corpus: '{hit}'"
                    )
                    continue
                # WEAK (never counted): slot naming a GT entity absent from
                # known_relations_book1 — that field is not exhaustive by
                # construction (STU-717).
                if target_entity and target_entity != entry.entity:
                    known = any(
                        _resolve_target(k) == target_entity for k in known_rels
                    )
                    if not known:
                        res.advisories.append(
                            f"REL_ABSENT [{entry.entity}/{slot}]: [[{tgt}]] "
                            f"absent from known_relations_book1 (weak signal)"
                        )
    return res


# ---------------------------------------------------------------------------
# Step 1c — upstream trace

def default_stage_files(processing: Path | str, wiki_inputs: Path | str) -> list[tuple[str, Path]]:
    """Pipeline chain, most-upstream first — the first file containing the term
    is the component that introduced it."""
    processing, wiki_inputs = Path(processing), Path(wiki_inputs)
    stages: list[tuple[str, Path]] = [
        ("entities_classified", processing / "entities_classified.json"),
        ("relationships_classified", processing / "relationships_classified.json"),
        ("relationships (raw)", processing / "relationships.json"),
        ("chapter_summaries", processing / "chapter_summaries.json"),
    ]
    for bf in sorted(wiki_inputs.glob("batch_*.json")):
        stages.append((f"batch {bf.name}", bf))
    stages.append(("wiki_pages", processing / "wiki_pages.json"))
    return stages


def trace_terms(
    terms: list[str], stages: list[tuple[str, Path]]
) -> dict[str, dict]:
    """For each term: presence per stage + the first stage that contains it
    (None everywhere = pure LLM hallucination at generation)."""
    out: dict[str, dict] = {}
    cache: dict[Path, str] = {}
    for term in terms:
        seen: list[tuple[str, bool | None]] = []
        first_seen = None
        for name, path in stages:
            if path not in cache:
                try:
                    cache[path] = path.read_text().lower()
                except (FileNotFoundError, OSError):
                    cache[path] = ""
            raw = cache[path]
            found = term.lower() in raw if raw else None
            if found and first_seen is None:
                first_seen = name
            seen.append((name, found))
        out[term] = {"stages": seen, "first_seen": first_seen}
    return out


# ---------------------------------------------------------------------------
# Step 1d — coverage

def coverage(processing: Path | str, wiki_inputs: Path | str) -> dict:
    processing, wiki_inputs = Path(processing), Path(wiki_inputs)
    batch_entities: set[str] = set()
    for bf in sorted(wiki_inputs.glob("batch_*.json")):
        batch = json.loads(bf.read_text())
        for e in batch.get("entities", []):
            batch_entities.add(e["canonical_name"])

    pages = load_pages(processing / "wiki_pages.json")
    page_titles = {p["title"] for p in pages}
    failed = {p["title"] for p in pages if p.get("_failed")}

    classified_names: set[str] = set()
    cf = processing / "entities_classified.json"
    if cf.exists():
        classified = json.loads(cf.read_text())
        ents = classified.get("entities", classified if isinstance(classified, list) else [])
        classified_names = {e["canonical_name"] for e in ents}

    return {
        "batch_entities": sorted(batch_entities),
        "pages": sorted(page_titles),
        "missing_from_pages": sorted(batch_entities - page_titles),
        "failed_pages": sorted(failed),
        "filtered_before_batch": sorted(classified_names - batch_entities),
    }


# ---------------------------------------------------------------------------
# Step 1e — batch stats / weak entities

_ANTAGONIST_KW = {"rival", "antagoniste", "ennemi", "empoisonne", "possédé",
                  "adversaire", "venin", "enemy", "villain"}
_POSITIVE_TYPES = {"amoureux", "allié", "ami", "protecteur", "mentor",
                   "confident", "partenaire", "amie", "ally", "friend",
                   "lover", "protector"}
_GENERIC_EVOLUTION = (None, "relation stable dans les extraits fournis", "")


def _rel_target(rel: dict, entity_name: str) -> str:
    a, b = rel.get("entity_a", ""), rel.get("entity_b", "")
    if a and b:
        return b if a == entity_name else a
    return (rel.get("target") or rel.get("character") or "").strip()


def batch_stats(
    wiki_inputs: Path | str, by_entity: dict[str, dict] | None = None
) -> dict:
    by_entity = by_entity or {}
    entity_rows = []
    all_rels: list[dict] = []
    for bf in sorted(Path(wiki_inputs).glob("batch_*.json")):
        batch = json.loads(bf.read_text())
        for e in batch.get("entities", []):
            name = e.get("canonical_name", "?")
            rels = e.get("relationships", [])
            all_rels.extend(rels)
            issues: list[str] = []
            mismatches: list[str] = []
            if not rels:
                entity_rows.append({"name": name, "rels": 0,
                                    "issues": ["0 relations"], "mismatches": []})
                continue
            total = len(rels)
            typed = sum(1 for r in rels if r.get("relationship_type"))
            no_evidence = sum(1 for r in rels if not r.get("evidence"))
            generic_evol = sum(1 for r in rels if r.get("evolution") in _GENERIC_EVOLUTION)
            empty_moments = sum(1 for r in rels if not r.get("key_moments"))
            if typed < total:
                issues.append(f"untyped: {total - typed}/{total}")
            if no_evidence > total * 0.5:
                issues.append(f"evidence absent: {no_evidence}/{total}")
            if generic_evol > total * 0.7:
                issues.append(f"generic evolution: {generic_evol}/{total}")
            if empty_moments > total * 0.3:
                issues.append(f"empty key_moments: {empty_moments}/{total}")

            # Relation-type sanity vs GT known_relations (STU-314): a target the
            # corpus describes as antagonist must not carry a positive type.
            gt_rels = by_entity.get(name, {}).get("known_relations_book1", {})
            for r in rels:
                target = _rel_target(r, name)
                rel_type = (r.get("relationship_type") or "").lower()
                if not target or not rel_type:
                    continue
                for gt_char, gt_desc in gt_rels.items():
                    if gt_char.lower() in target.lower() or target.lower() in gt_char.lower():
                        if any(kw in gt_desc.lower() for kw in _ANTAGONIST_KW) and any(
                            pos in rel_type for pos in _POSITIVE_TYPES
                        ):
                            mismatches.append(
                                f"{name}<->{target}: type='{rel_type}' but GT says antagonist"
                            )
            entity_rows.append({"name": name, "rels": total,
                                "issues": issues, "mismatches": mismatches})

    total = len(all_rels)
    return {
        "entities": entity_rows,
        "weak": [r for r in entity_rows if r["issues"] or r["mismatches"]],
        "global": {
            "relations": total,
            "typed": sum(1 for r in all_rels if r.get("relationship_type")),
            "generic_evolution": sum(1 for r in all_rels if r.get("evolution") in _GENERIC_EVOLUTION),
            "empty_key_moments": sum(1 for r in all_rels if not r.get("key_moments")),
            "evidence_absent": sum(1 for r in all_rels if not r.get("evidence")),
            "type_distribution": dict(Counter(
                r.get("relationship_type") for r in all_rels if r.get("relationship_type")
            )),
        },
    }


# ---------------------------------------------------------------------------
# Providers — which model produced each LLM stage

_ENV_RE = re.compile(r"\$\{(\w+)(?::-([^}]*))?\}")


def _interp_env(value: str, env: dict[str, str]) -> str:
    def repl(m: re.Match) -> str:
        return env.get(m.group(1)) or (m.group(2) or "")
    return _ENV_RE.sub(repl, value)


def provider_mix(repo_root: Path | str, env: dict[str, str] | None = None) -> dict:
    """provider/model per agent yaml + the config.yaml defaults, with
    ${VAR:-default} interpolation resolved against env (default os.environ).
    A content hallucination reads first against the generation model."""
    import os

    env = dict(os.environ) if env is None else env
    root = Path(repo_root)
    out: dict[str, dict[str, str]] = {}

    def _extract(text: str) -> dict[str, str]:
        found = {}
        for key in ("provider", "model"):
            m = re.search(rf"^\s*{key}:\s*(.+)$", text, re.MULTILINE)
            if m:
                raw = m.group(1).strip().strip("'\"")
                found[key] = _interp_env(raw, env)
        return found

    cfg = root / ".studio" / "config.yaml"
    if cfg.exists():
        m = re.search(r"^defaults:\n((?:[ \t]+.*\n?)*)", cfg.read_text(), re.MULTILINE)
        if m:
            out["defaults"] = _extract(m.group(1))
    for af in sorted((root / ".studio" / "agents").glob("*.agent.yaml")):
        found = _extract(af.read_text())
        if found:
            out[af.stem.replace(".agent", "")] = found
    return out
