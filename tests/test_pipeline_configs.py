"""Sanity checks for Studio pipeline YAML files."""

import re
from pathlib import Path

import yaml


PIPELINES_DIR = Path(__file__).resolve().parents[1] / ".studio" / "pipelines"
CONTRACTS_DIR = Path(__file__).resolve().parents[1] / ".studio" / "contracts"
AGENTS_DIR = Path(__file__).resolve().parents[1] / ".studio" / "agents"
BASE_YAML = Path(__file__).resolve().parents[1] / "wiki_creator" / "templates" / "base.yaml"


def _load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_script_stages_use_script_paths_only() -> None:
    """`script` must be a file path, not a command with inline flags."""
    for pipeline_path in PIPELINES_DIR.glob("*.pipeline.yaml"):
        doc = _load_yaml(pipeline_path)
        all_stages = _iter_stages(doc.get("stages", []))
        for stage in all_stages:
            if stage.get("executor") != "script":
                continue
            script = stage.get("script", "")
            assert script.endswith(".py"), (
                f"{pipeline_path.name}:{stage.get('name')} script must end with .py, got {script!r}"
            )
            assert " " not in script.strip(), (
                f"{pipeline_path.name}:{stage.get('name')} script must be path only, got {script!r}"
            )


def test_chapter_summary_item_contract_exists_with_required_fields() -> None:
    contract_path = CONTRACTS_DIR / "chapter-summary-item.contract.yaml"
    assert contract_path.exists(), "chapter-summary-item contract is missing"

    doc = _load_yaml(contract_path)
    required_fields = doc.get("schema", {}).get("required_fields", [])
    assert required_fields == ["chapter_id", "chapter_title", "summary_bullets"]


def test_chapter_summary_item_pipeline_uses_ralph_and_contract() -> None:
    pipeline_path = PIPELINES_DIR / "chapter-summary-item.pipeline.yaml"
    agent_path = AGENTS_DIR / "chapter-summary.agent.yaml"

    assert pipeline_path.exists(), "chapter-summary-item pipeline is missing"
    assert agent_path.exists(), "chapter-summary agent is missing"

    doc = _load_yaml(pipeline_path)
    llm_stage = next(
        stage for stage in _iter_stages(doc.get("stages", []))
        if stage.get("contract") == "chapter-summary-item"
    )
    assert llm_stage.get("agent") == "chapter-summary"
    assert isinstance(llm_stage.get("ralph"), dict), "chapter-summary-item stage must configure ralph"


def test_wiki_page_item_contract_exists_with_required_fields() -> None:
    contract_path = CONTRACTS_DIR / "wiki-page-item.contract.yaml"
    assert contract_path.exists(), "wiki-page-item contract is missing"

    doc = _load_yaml(contract_path)
    required_fields = doc.get("schema", {}).get("required_fields", [])
    assert required_fields == ["title", "importance", "entity_type", "infobox_fields", "content"]


def _iter_stages(stages: list) -> list:
    """Flatten top-level and group-nested stages into a single iterable."""
    result = []
    for stage in stages:
        if "group" in stage:
            result.extend(stage.get("stages", []))
        else:
            result.append(stage)
    return result


def test_wiki_page_item_pipeline_uses_ralph_and_contract() -> None:
    pipeline_path = PIPELINES_DIR / "wiki-page-item.pipeline.yaml"
    agent_path = AGENTS_DIR / "wiki-page-item.agent.yaml"

    assert pipeline_path.exists(), "wiki-page-item pipeline is missing"
    assert agent_path.exists(), "wiki-page-item agent is missing"

    doc = _load_yaml(pipeline_path)
    all_stages = _iter_stages(doc.get("stages", []))
    llm_stage = next(
        stage for stage in all_stages
        if stage.get("contract") == "wiki-page-item"
    )
    assert llm_stage.get("agent") == "wiki-page-item"
    assert isinstance(llm_stage.get("ralph"), dict), "wiki-page-item stage must configure ralph"


def test_wiki_resolution_pipeline_alias_resolution_runs_after_merge_and_relationship() -> None:
    pipeline_path = PIPELINES_DIR / "wiki-resolution.pipeline.yaml"
    doc = _load_yaml(pipeline_path)
    stage_names = [stage.get("name") for stage in doc.get("stages", [])]

    assert "alias-resolution" in stage_names
    assert stage_names.index("resolve-clusters") < stage_names.index("relationship-extraction")
    assert stage_names.index("relationship-extraction") < stage_names.index("alias-resolution")
    assert stage_names.index("alias-resolution") < stage_names.index("entity-classification")

    alias_stage = next(
        stage for stage in doc.get("stages", [])
        if stage.get("name") == "alias-resolution"
    )
    assert alias_stage.get("script") == "scripts/alias_resolution.py"


def test_alias_resolution_contract_exists_with_required_fields() -> None:
    contract_path = CONTRACTS_DIR / "alias-resolution.contract.yaml"
    assert contract_path.exists(), "alias-resolution contract is missing"

    doc = _load_yaml(contract_path)
    required_fields = doc.get("schema", {}).get("required_fields", [])
    assert required_fields == ["entities", "narrator"]


def _entity_type_vocab() -> tuple[set[str], set[str]]:
    """(every declared type, the NER/resolution subset) from base.yaml.

    The NER subset is the types with `ner_labels` — PERSON/PLACE/ORG/EVENT/
    FACTION — i.e. the live vocabulary a restated `entity_type` enum would list.
    """
    types = _load_yaml(BASE_YAML)["entity_types"]
    all_types = set(types)
    ner_types = {name for name, cfg in types.items() if cfg.get("ner_labels")}
    return all_types, ner_types


def _comment_blocks(text: str) -> list[str]:
    """Contiguous runs of full-line YAML comments, each joined by spaces.

    A non-comment line breaks a block, so an enumeration can't bridge across
    code; joining consecutive comment lines lets a multi-line enum be seen whole.
    """
    blocks: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            current.append(stripped.lstrip("#").strip())
        elif current:
            blocks.append(" ".join(current))
            current = []
    if current:
        blocks.append(" ".join(current))
    return blocks


def _enum_restatements(text: str, all_types: set[str], ner_types: set[str]) -> list[str]:
    """Comment runs that restate the whole NER vocabulary as an enum.

    A run is a maximal sequence of type tokens joined *only* by enum separators
    (`| , /` + whitespace); prose words between two types break it. A run trips
    only when it covers every NER type — an outdated quote (missing a
    later-added type) never does, a fresh exhaustive restatement does.
    """
    token = "|".join(sorted(all_types, key=len, reverse=True))
    run_re = re.compile(rf"\b(?:{token})(?:[\s,|/]+(?:{token}))*\b")
    type_re = re.compile(rf"\b(?:{token})\b")
    offenders = []
    for block in _comment_blocks(text):
        for match in run_re.finditer(block):
            if ner_types <= set(type_re.findall(match.group())):
                offenders.append(match.group())
    return offenders


def test_no_contract_comment_restates_entity_type_enum() -> None:
    """STU-596: a contract comment must not restate the full entity-type enum.

    Copying the vocabulary into a comment is how `entity_type` drifted three
    times (wiki-page, entity-classification, resolve-clusters): the enum ships in
    base.yaml#entity_types and is read at runtime, so a restatement rots the
    moment a type is added (FACTION, STU-505). This guards against a fourth. The
    surviving cautionary quotes cite an *incomplete* enum, which by construction
    can never equal the complete current vocabulary.
    """
    all_types, ner_types = _entity_type_vocab()
    offenders = []
    for contract_path in sorted(CONTRACTS_DIR.glob("*.contract.yaml")):
        text = contract_path.read_text(encoding="utf-8")
        for run in _enum_restatements(text, all_types, ner_types):
            offenders.append(f"{contract_path.name}: {run!r}")
    assert not offenders, (
        "Contract comment restates the full entity-type enum — read it from "
        "base.yaml#entity_types at runtime instead of copying it:\n"
        + "\n".join(offenders)
    )


def test_enum_restatement_detector_calibration() -> None:
    """The detector fires on an exhaustive restatement, not a 1-2 type mention."""
    all_types, ner_types = _entity_type_vocab()

    def restates(comment: str) -> bool:
        return bool(_enum_restatements(comment, all_types, ner_types))

    # A fresh full restatement (the bug) — any separator variant trips.
    assert restates("# entity_type: PERSON | PLACE | ORG | EVENT | FACTION | OTHER")
    assert restates("# type is one of PERSON, PLACE, ORG, EVENT, FACTION, OTHER")
    assert restates("# PERSON/PLACE/ORG/EVENT/FACTION")
    # The historical cautionary quotes (incomplete enums) must NOT trip.
    assert not restates("# the enum that stood here read PERSON|PLACE|ORG|EVENT|OTHER long after FACTION shipped")
    assert not restates("# stood here claimed PERSON|PLACE|ORG long after EVENT shipped")
    # A passing mention of one or two types is fine.
    assert not restates("# narrator metadata from entity-resolution-PERSON, or null")
    assert not restates("# adjudicated PERSON and PLACE entries")


# STU-733: the two regressions the audit found, pinned by shape rather than by a
# blanket non-ASCII gate (agent prompts legitimately carry `—`, `→`, `Ebrithil`).
# A prompt that names an output language contradicts the language directive
# `generate_wiki_pages.build_prompt` already emits from `output_language`; a
# validator prompt written in French checks a Spanish book's groundedness in French.
_LANGUAGE_DIRECTIVE_RE = re.compile(r"\b(?:in|en)\s+(?:French|français|francais)\b", re.I)

# Function words no non-French agent prompt would contain, as whole words.
_FRENCH_MARKERS = (
    "vérifie", "retourne", "reçois", "règles", "aucune", "tu es", "n'utilise",
    "extraits", "affirmation", "chaque", "les deux", "générée",
)


def _agent_prompts() -> list[tuple[str, str]]:
    prompts = []
    for agent_path in sorted(AGENTS_DIR.glob("*.agent.yaml")):
        doc = _load_yaml(agent_path)
        prompt = doc.get("system_prompt") or ""
        assert prompt, f"{agent_path.name} declares no system_prompt"
        prompts.append((agent_path.name, prompt))
    return prompts


def test_no_agent_prompt_hardcodes_an_output_language() -> None:
    """The write-in-<language> directive comes from `output_language`, not a prompt.

    `wiki-page-item` used to order French unconditionally ("Always write content
    in French, even if the source excerpts are in English"), so every non-French
    book generated against a contradiction — and the system prompt is the
    stronger channel.
    """
    offenders = [
        f"{name}: {match.group(0)!r}"
        for name, prompt in _agent_prompts()
        for match in [_LANGUAGE_DIRECTIVE_RE.search(prompt)]
        if match
    ]
    assert not offenders, (
        "Agent prompt names a hardcoded output language — the prompt builder "
        "emits it from output_language(book_config):\n" + "\n".join(offenders)
    )


def test_agent_prompts_are_written_in_english() -> None:
    """Prompt scaffolding stays English whatever the book's output language.

    The three validators emit structured JSON verdicts, not reader text, so a
    French prompt gave a Spanish book a French groundedness check (STU-733).
    """
    offenders = [
        f"{name}: {marker!r}"
        for name, prompt in _agent_prompts()
        for marker in _FRENCH_MARKERS
        if re.search(rf"(?<!\w){re.escape(marker)}(?!\w)", prompt, re.I)
    ]
    assert not offenders, (
        "Agent prompt is written in French — scaffolding is English "
        "unconditionally (scripts/CLAUDE.md):\n" + "\n".join(offenders)
    )


def test_no_agent_prompt_hardcodes_a_non_english_section_heading() -> None:
    """Section headings reach the writer through `slot_label`, in the output language.

    `wiki-page-item` hardcoded `## Relations`, so an English page got the French
    heading and `_isolate_section` — matching on `slot_label(section, lang)` —
    found no `Relationships` block to extract (STU-733). Only headings whose
    non-English label differs from the English one are evidence of hardcoding;
    the rest (`Type`, `Infobox`) are the same word in both.
    """
    labels = (_load_yaml(BASE_YAML).get("labels") or {}).values()
    translated = {
        heading
        for entry in labels
        if isinstance(entry, dict)
        for lang, heading in entry.items()
        if lang != "en" and heading != entry.get("en")
    }
    offenders = [
        f"{name}: '## {heading}'"
        for name, prompt in _agent_prompts()
        for heading in sorted(translated)
        if f"## {heading}" in prompt
    ]
    assert not offenders, (
        "Agent prompt hardcodes a non-English section heading — input['prompt'] "
        "carries it from slot_label:\n" + "\n".join(offenders)
    )


def test_french_prompt_detectors_catch_the_pre_stu733_prompts() -> None:
    """The three gates above fire on what `.studio/agents/` actually held."""
    assert _LANGUAGE_DIRECTIVE_RE.search(
        "Always write content in French, even if the source excerpts are in English."
    )
    assert _LANGUAGE_DIRECTIVE_RE.search("Rédige la page en français.")
    assert not _LANGUAGE_DIRECTIVE_RE.search("Write in the output language input[\"prompt\"] names.")

    def is_french(text: str) -> bool:
        return any(
            re.search(rf"(?<!\w){re.escape(marker)}(?!\w)", text, re.I)
            for marker in _FRENCH_MARKERS
        )

    assert is_french("Tu es un validateur de pages wiki pour un roman fantasy.")
    assert is_french("Pour chaque bullet, vérifie qu'il est ancré dans le texte.")
    assert not is_french("You validate wiki pages for a fantasy novel.")
