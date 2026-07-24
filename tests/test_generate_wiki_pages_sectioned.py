import scripts.generate_wiki_pages as gwp
from wiki_creator.editorial_stance import GROUNDING_BLOCK, EditorialStance


def test_assemble_joins_nonempty_blocks_with_blank_line():
    blocks = ["## Biographie\n\nTexte.", "  ", "", "## Anecdotes\n\nFait."]
    out = gwp._assemble_section_blocks(blocks)
    assert out == "## Biographie\n\nTexte.\n\n## Anecdotes\n\nFait."


def test_assemble_empty_is_empty_string():
    assert gwp._assemble_section_blocks([]) == ""
    assert gwp._assemble_section_blocks(["", "   "]) == ""


def test_references_block_lists_only_book_title():
    assert gwp._references_block("Throne of Glass") == "## Références\n\n- Throne of Glass"


def _fake_item(content):
    return {"title": "X", "importance": "principal", "entity_type": "PERSON",
            "infobox_fields": {}, "content": content}


def test_generate_one_section_returns_content(monkeypatch):
    monkeypatch.setattr(gwp, "_run_wiki_page_item",
                        lambda **kw: _fake_item("## Biographie\n\nTexte."))
    out, _ = gwp._generate_one_section(entity={"canonical_name": "A"}, section="biography",
                                    book_title="B", model="m", timeout=10, max_tokens=500)
    assert out == "## Biographie\n\nTexte."


def test_generate_one_section_none_on_error(monkeypatch):
    monkeypatch.setattr(gwp, "_run_wiki_page_item", lambda **kw: {"error": "studio_run_failed"})
    out, _ = gwp._generate_one_section(entity={"canonical_name": "A"}, section="powers",
                                    book_title="B", model="m", timeout=10, max_tokens=500)
    assert out is None


def test_generate_one_section_scopes_to_single_section(monkeypatch):
    seen = {}
    def fake(**kw):
        seen["sections"] = kw["sections"]
        return _fake_item("## Anecdotes\n\nFait.")
    monkeypatch.setattr(gwp, "_run_wiki_page_item", fake)
    gwp._generate_one_section(entity={"canonical_name": "A"}, section="trivia",
                              book_title="B", model="m", timeout=10, max_tokens=500)
    assert seen["sections"] == ["trivia"]


def test_generate_one_section_omits_on_persistent_forbidden(monkeypatch):
    monkeypatch.setattr(gwp, "_run_wiki_page_item",
                        lambda **kw: _fake_item("## Biographie\n\nNehemia dies."))
    out, _ = gwp._generate_one_section(entity={"canonical_name": "A"}, section="biography",
                                    book_title="B", model="m", timeout=10, max_tokens=500,
                                    forbidden_names=["Nehemia"])
    assert out is None   # one retry attempted, still hit → omit


def _entity(rels=None):
    return {"canonical_name": "Chaol", "type": "PERSON", "importance": "principal",
            "aliases": ["Captain Westfall"], "titles": ["Captain"],
            "context_by_chapter": {"C01": ["ctx"]}, "context_chapters": [1], "relationships": rels or []}


def _sectioned(monkeypatch, produced):
    # produced: dict section -> content string, or None to simulate failure
    calls = []
    def fake(**kw):
        sec = kw["sections"][0]
        calls.append(sec)
        val = produced.get(sec, f"## {sec}\n\ntext")
        return {"error": "x"} if val is None else _fake_item(val)
    monkeypatch.setattr(gwp, "_run_wiki_page_item", fake)
    return calls


def test_sectioned_calls_once_per_content_section_and_assembles(monkeypatch):
    calls = _sectioned(monkeypatch, {"biography": "## Biographie\n\nBio."})
    from pathlib import Path
    page = gwp._run_generation_sectioned(
        entity=_entity(), book_title="ToG", model="m", timeout=10,
        sections=["infobox", "biography", "references"], max_tokens=500,
        dry_run=False, debug_dir=Path("/tmp"), book_config={})
    assert calls == ["biography"]                       # infobox + references not LLM'd
    assert "## Biographie" in page["content"]
    assert "## Références\n\n- ToG" in page["content"]   # deterministic refs
    assert page["infobox_fields"]["nom"] == "Chaol"     # slice-B binding still applied
    assert page["infobox_fields"]["titles"] == "Captain"


def test_narrative_role_prompt_carries_salience_tiers_and_rule():
    """STU-503: the arc block tags each event with its salience tier and the rule
    tells the writer to spend prose proportionally."""
    entity = _entity()
    entity["entity_events"] = [
        {"chapter": 1, "description": "voyage Endovier vers Rifthold",
         "participants": ["Chaol"], "salience": 0.2},
        {"chapter": 12, "description": "duel final", "participants": ["Chaol"],
         "salience": 0.85},
    ]
    p = gwp.build_prompt(entity, "ToG", sections=["narrative_role"])
    assert "importance: low" in p      # low-salience travel beat
    assert "importance: high" in p      # climax
    assert "proportion" in p.lower()


def test_sectioned_page_carries_content_units(monkeypatch):
    """STU-491: page output tags each emitted section with its reveal chapter."""
    entity = _entity(rels=[{"chapters": [3, 2]}])
    entity["entity_events"] = [{"chapter": 4}]
    _sectioned(monkeypatch, {})
    from pathlib import Path
    page = gwp._run_generation_sectioned(
        entity=entity, book_title="ToG", model="m", timeout=10,
        sections=["infobox", "biography", "relationships", "narrative_role", "references"],
        max_tokens=500, dry_run=False, debug_dir=Path("/tmp"), book_config={})
    units = {u["section"]: u["revealed_at_chapter"] for u in page["content_units"]}
    assert units == {"biography": 1, "relationships": 2, "narrative_role": 4}
    assert "infobox" not in units and "references" not in units


def test_build_prompt_covered_prose_injects_anti_repeat_block_and_rule():
    """STU-643: passing prior section prose adds a read-only ALREADY WRITTEN block
    plus an explicit do-not-repeat rule; empty covered_prose leaves it out."""
    entity = _entity()
    p_with = gwp.build_prompt(entity, "ToG", sections=["trivia"],
                              covered_prose="## Biographie\n\nThe gardeners painted the roses red.")
    assert "ALREADY WRITTEN" in p_with
    assert "gardeners painted the roses red" in p_with
    assert "do not re-tell" in p_with.lower() or "do not re-narrate" in p_with.lower()
    p_without = gwp.build_prompt(entity, "ToG", sections=["trivia"])
    assert "ALREADY WRITTEN" not in p_without


def test_build_prompt_personality_overrides_omit_if_covered():
    """STU-653: personality gets a distillation rule that scopes the omit to a
    genuine absence of traits, and its covered_rule drops the omit-if-covered
    escape (kept for the other portrait sections)."""
    entity = _entity()
    p = gwp.build_prompt(entity, "ToG", sections=["personality"],
                         covered_prose="## Biographie\n\nAlice curiously followed the rabbit.")
    assert "Omit this section ONLY when the excerpts ground no character traits" in p
    assert "distil the disposition" in p
    assert "keep this section brief or omit it rather than repeating" not in p
    # a non-personality portrait section keeps the omit escape
    p_trivia = gwp.build_prompt(entity, "ToG", sections=["trivia"],
                                covered_prose="## Biographie\n\nAlice followed the rabbit.")
    assert "keep this section brief or omit it rather than repeating" in p_trivia


def test_build_prompt_biography_defers_to_sibling_sections():
    """STU-643: when narrative_role/personality also exist on the page, biography
    is told to stay factual and not absorb the arc or trait analysis. With no
    siblings (figurant), it gets no such constraint."""
    entity = _entity()
    p = gwp.build_prompt(entity, "ToG", sections=["biography"],
                         page_sections=["biography", "narrative_role", "personality", "trivia"])
    assert "own a scope" in p
    assert "beat by beat" in p          # defers the arc to narrative_role
    assert "do NOT analyse" in p        # defers traits to personality
    p_solo = gwp.build_prompt(entity, "ToG", sections=["biography"],
                              page_sections=["biography"])
    assert "own a scope" not in p_solo  # figurant biography stays self-contained


def test_sectioned_feeds_prior_prose_to_portrait_sections_only(monkeypatch):
    """STU-643: personality/trivia (portrait sections) receive the prose written by
    earlier sections; biography (a contributor) receives none, and the pool grows."""
    seen: dict[str, str] = {}
    def fake(**kw):
        sec = kw["sections"][0]
        seen[sec] = kw.get("covered_prose", "")
        return _fake_item(f"## {sec}\n\n{sec} body.")
    monkeypatch.setattr(gwp, "_run_wiki_page_item", fake)
    from pathlib import Path
    gwp._run_generation_sectioned(
        entity=_entity(), book_title="ToG", model="m", timeout=10,
        sections=["infobox", "biography", "personality", "trivia", "references"],
        max_tokens=500, dry_run=False, debug_dir=Path("/tmp"), book_config={})
    assert seen["biography"] == ""                          # first / non-consumer
    assert "biography body." in seen["personality"]         # consumes biography
    assert "biography body." in seen["trivia"]              # pool grows...
    assert "personality body." in seen["trivia"]            # ...to include personality


def test_item_key_ignores_covered_prose_block():
    """STU-653: the ALREADY WRITTEN anti-repeat block (STU-643) must not enter the
    item identity — the plan walk stubs the prior prose ("planned") and the replay
    walk carries the real biography, so a covered-prose-sensitive key drops the
    section's fan-out result on replay. Two personality items differing ONLY in
    covered_prose must hash identically; a real content difference still differs."""
    entity = _entity()
    a = {"title": "Chaol", "prompt": gwp.build_prompt(
        entity, "ToG", sections=["personality"], covered_prose="## Bio\n\nStub planned.")}
    b = {"title": "Chaol", "prompt": gwp.build_prompt(
        entity, "ToG", sections=["personality"],
        covered_prose="## Bio\n\nA long, real biography of many sentences and events.")}
    assert gwp._item_key(a) == gwp._item_key(b)
    # a genuinely different item (no covered block at all) still hashes apart only
    # by its real content, not by the stripped block
    c = {"title": "Chaol", "prompt": gwp.build_prompt(entity, "ToG", sections=["trivia"])}
    assert gwp._item_key(c) != gwp._item_key(a)


def test_sectioned_biography_failure_returns_stub(monkeypatch):
    _sectioned(monkeypatch, {"biography": None})
    from pathlib import Path
    page = gwp._run_generation_sectioned(
        entity=_entity(), book_title="ToG", model="m", timeout=10,
        sections=["infobox", "biography", "references"], max_tokens=500,
        dry_run=False, debug_dir=Path("/tmp"), book_config={})
    assert page.get("_failed") is True


def test_sectioned_omits_failed_optional_section(monkeypatch):
    _sectioned(monkeypatch, {"biography": "## Biographie\n\nBio.", "powers": None})
    from pathlib import Path
    page = gwp._run_generation_sectioned(
        entity=_entity(), book_title="ToG", model="m", timeout=10,
        sections=["infobox", "biography", "powers", "references"], max_tokens=500,
        dry_run=False, debug_dir=Path("/tmp"), book_config={})
    assert page.get("_failed") is not True
    assert "## Biographie" in page["content"]
    assert "powers" not in page["content"]              # failed OPT section omitted


def test_narrative_role_prompt_forbids_periphrasis():
    """STU-500: the arc writer must name entities, never substitute a vague
    periphrasis for a character that has its own page."""
    entity = _entity()
    entity["entity_events"] = [
        {"chapter": 3, "description": "rencontre",
         "participants": ["Chaol", "Celaena Sardothien"], "salience": 0.8},
    ]
    p = gwp.build_prompt(entity, "ToG", sections=["narrative_role"])
    assert "periphrasis" in p.lower()
    assert "the protagonist" in p


def test_sectioned_narrative_role_wikilinks_first_mention(monkeypatch):
    """STU-500: the first bare mention of a sibling entity in the arc section is
    wikilinked deterministically, even when the LLM emits a plain name."""
    entity = _entity()
    entity["entity_events"] = [{"chapter": 3, "participants": ["Chaol"]}]
    _sectioned(monkeypatch, {
        "biography": "## Biographie\n\nBio.",
        "narrative_role": "## Rôle dans le récit\n\nChaol forme Celaena Sardothien.",
    })
    from pathlib import Path
    page = gwp._run_generation_sectioned(
        entity=entity, book_title="ToG", model="m", timeout=10,
        sections=["biography", "narrative_role"], max_tokens=500,
        dry_run=False, debug_dir=Path("/tmp"), book_config={},
        sibling_canonicals={"Celaena Sardothien"})
    assert "[[Celaena Sardothien]]" in page["content"]
    # Only the arc section is linkified — the subject's own name is not self-linked.
    assert "[[Chaol]]" not in page["content"]


def test_isolate_section_drops_leaked_infobox(monkeypatch):
    leaked = "## Infobox\n\n- Nom: X\n\n## Biographie\n\nBio réelle."
    monkeypatch.setattr(gwp, "_run_wiki_page_item", lambda **kw: _fake_item(leaked))
    out, _ = gwp._generate_one_section(entity={"canonical_name": "A"}, section="biography",
                                    book_title="B", model="m", timeout=10, max_tokens=500)
    assert out == "## Biographie\n\nBio réelle."
    assert "Infobox" not in out


def test_isolate_section_wraps_bare_body(monkeypatch):
    monkeypatch.setattr(gwp, "_run_wiki_page_item", lambda **kw: _fake_item("Juste le corps."))
    out, _ = gwp._generate_one_section(entity={"canonical_name": "A"}, section="biography",
                                    book_title="B", model="m", timeout=10, max_tokens=500)
    assert out == "## Biographie\n\nJuste le corps."


def test_isolate_section_forces_canonical_title_on_mismatched_heading(monkeypatch):
    # The model wrote `## Biographie` for a `physical` section (few-shot drift);
    # the single-bloc fallback must relabel it to the requested title, not keep
    # the model's heading (which would duplicate Biographie and drop Apparence).
    mismatched = "## Biographie\n\nDescription physique réelle."
    monkeypatch.setattr(gwp, "_run_wiki_page_item", lambda **kw: _fake_item(mismatched))
    out, _ = gwp._generate_one_section(entity={"canonical_name": "A"}, section="physical",
                                    book_title="B", model="m", timeout=10, max_tokens=500)
    assert out == f"## {gwp.slot_label('physical', 'fr')}\n\nDescription physique réelle."
    assert "Biographie" not in out


def test_isolate_section_none_when_only_infobox(monkeypatch):
    monkeypatch.setattr(gwp, "_run_wiki_page_item", lambda **kw: _fake_item("## Infobox\n\n- Nom: X"))
    out, _ = gwp._generate_one_section(entity={"canonical_name": "A"}, section="biography",
                                    book_title="B", model="m", timeout=10, max_tokens=500)
    assert out is None


def test_sectioned_page_carries_relationship_index(monkeypatch):
    from pathlib import Path
    monkeypatch.setattr(gwp, "_generate_one_section", lambda **kw: ("## Biographie\n\nBio.", None))
    entity = {
        "canonical_name": "Celaena", "type": "PERSON", "importance": "principal",
        "aliases": [], "context_by_chapter": {"C01.xhtml": ["ctx"]}, "context_chapters": [1],
        "relationships": [
            {"entity_a": "Celaena", "entity_b": "Chaol",
             "relationship_type": "amoureux", "chapters": [1, 55]},
        ],
    }
    page = gwp._run_generation_sectioned(
        entity=entity, book_title="ToG", model="m", timeout=10,
        sections=["biography", "relationships"], max_tokens=500,
        dry_run=False, debug_dir=Path("/tmp"), book_config={})
    assert page["relationship_index"] == ["* [[Chaol]] — Amoureux (ch.1→ch.55)"]


def test_build_relation_prompt_grounds_and_requires_french():
    entity = {"canonical_name": "Chaol", "type": "PERSON"}
    rel = {"entity_a": "Chaol", "entity_b": "Celaena", "relationship_type": "amoureux",
           "evolution": "Evolves from antagonism to trust.",
           "key_moments": ["ch10: sparring"], "evidence": "He watched her fight."}
    p = gwp.build_relation_prompt(entity, "Celaena", rel, "ToG", forbidden_names=["Nehemia"])
    assert "Celaena" in p
    assert "amoureux" in p
    assert "Evolves from antagonism to trust." in p          # grounding present
    assert "français" in p.lower() or "french" in p.lower()  # FR instruction
    assert "### [[Celaena]]" in p                             # heading format specified
    assert "Nehemia" in p                                     # forbidden name surfaced


def test_prompt_override_used_when_set():
    item = gwp._wiki_page_item_input(entity={"canonical_name": "A"}, book_title="B",
                                     sections=["relationships"], max_tokens=500,
                                     prompt_override="CUSTOM PROMPT")
    assert item["prompt"] == "CUSTOM PROMPT"


def test_generate_one_relation_returns_prose(monkeypatch):
    monkeypatch.setattr(gwp, "_run_wiki_page_item",
                        lambda **kw: _fake_item("### [[Celaena]]\n\nLeur méfiance mue en respect."))
    out = gwp._generate_one_relation(
        entity={"canonical_name": "Chaol", "type": "PERSON"}, other="Celaena",
        rel={"entity_a": "Chaol", "entity_b": "Celaena", "relationship_type": "amoureux"},
        book_title="ToG", model="m", timeout=10, max_tokens=500)
    assert out == "### [[Celaena]]\n\nLeur méfiance mue en respect."


def test_generate_one_relation_omits_on_persistent_forbidden(monkeypatch):
    monkeypatch.setattr(gwp, "_run_wiki_page_item",
                        lambda **kw: _fake_item("### [[Celaena]]\n\nNehemia meurt."))
    out = gwp._generate_one_relation(
        entity={"canonical_name": "Chaol", "type": "PERSON"}, other="Celaena",
        rel={"entity_a": "Chaol", "entity_b": "Celaena", "relationship_type": "amoureux"},
        book_title="ToG", model="m", timeout=10, max_tokens=500, forbidden_names=["Nehemia"])
    assert out is None


def test_generate_relationships_subsections_concatenates(monkeypatch):
    entity = {"canonical_name": "Chaol", "type": "PERSON", "aliases": [],
              "relationships": [
                  {"entity_a": "Chaol", "entity_b": "Celaena", "relationship_type": "amoureux",
                   "chapters": [55]},
                  {"entity_a": "Cain", "entity_b": "Chaol", "relationship_type": "antagoniste",
                   "chapters": [7]},
                  {"entity_a": "Chaol", "entity_b": "Nox", "relationship_type": None,
                   "chapters": [2]}]}
    monkeypatch.setattr(gwp, "_generate_one_relation",
                        lambda **kw: f"### [[{kw['other']}]]\n\nprose {kw['other']}")
    out = gwp._generate_relationships_subsections(
        entity=entity, book_title="ToG", model="m", timeout=10, max_tokens=500)
    assert out.startswith("## Relations")
    assert "### [[Celaena]]" in out and "### [[Cain]]" in out
    assert "Nox" not in out  # untyped relation skipped


def test_sectioned_per_relation_prose_when_enabled(monkeypatch):
    entity = _entity(rels=[
        {"entity_a": "Chaol", "entity_b": "Celaena", "relationship_type": "amoureux",
         "chapters": [55]},
        {"entity_a": "Cain", "entity_b": "Chaol", "relationship_type": "antagoniste",
         "chapters": [7]}])
    def fake(**kw):
        sec = kw["sections"][0]
        if sec == "relationships" and kw.get("prompt_override"):
            other = "Celaena" if "Celaena" in kw["prompt_override"] else "Cain"
            return _fake_item(f"### [[{other}]]\n\nprose {other}")
        return _fake_item(f"## {sec}\n\ntext")
    monkeypatch.setattr(gwp, "_run_wiki_page_item", fake)
    from pathlib import Path
    cfg = {"generation": {"relations": {"per_relation_prose": True}}}
    page = gwp._run_generation_sectioned(
        entity=entity, book_title="ToG", model="m", timeout=10,
        sections=["infobox", "biography", "relationships", "references"],
        max_tokens=500, dry_run=False, debug_dir=Path("/tmp"), book_config=cfg)
    assert "## Relations\n\n### [[Celaena]]" in page["content"]
    assert "### [[Cain]]" in page["content"]
    assert page["relation_units"] == [
        {"name": "Celaena", "revealed_at_chapter": 55},
        {"name": "Cain", "revealed_at_chapter": 7}]
    # relationships excluded from content_units; index dropped
    assert all(u["section"] != "relationships" for u in page["content_units"])
    assert page["relationship_index"] == []


def test_sectioned_per_relation_off_keeps_single_block(monkeypatch):
    entity = _entity(rels=[{"entity_a": "Chaol", "entity_b": "Celaena",
                            "relationship_type": "amoureux", "chapters": [55]}])
    _sectioned(monkeypatch, {"relationships": "## Relations\n\nProse unique."})
    from pathlib import Path
    page = gwp._run_generation_sectioned(
        entity=entity, book_title="ToG", model="m", timeout=10,
        sections=["infobox", "biography", "relationships", "references"],
        max_tokens=500, dry_run=False, debug_dir=Path("/tmp"), book_config={})
    assert "Prose unique." in page["content"]
    assert "relation_units" not in page
    assert page["relationship_index"]  # STU-492 index still built


def test_build_prompt_separates_grounding_from_stance():
    """STU-507: the two blocks are independent — switching posture must not be
    able to weaken 'invent nothing'."""
    entity = _entity()
    in_universe = gwp.build_prompt(
        entity, "Throne of Glass", sections=["infobox", "biography"],
        stance=EditorialStance(mode="in_universe"),
    )
    out_of_universe = gwp.build_prompt(
        entity, "Throne of Glass", sections=["infobox", "biography"],
        stance=EditorialStance(mode="out_of_universe"),
    )
    for prompt in (in_universe, out_of_universe):
        assert GROUNDING_BLOCK in prompt
    assert "EDITORIAL STANCE — in-universe" in in_universe
    assert "EDITORIAL STANCE — out-of-universe" in out_of_universe


def test_build_prompt_omits_references_rule_when_section_is_not_generated():
    entity = _entity()
    with_refs = gwp.build_prompt(entity, "Throne of Glass", sections=["infobox", "references"])
    without = gwp.build_prompt(entity, "Throne of Glass", sections=["infobox", "biography"])
    assert "## Références section must list ONLY" in with_refs
    assert "Références" not in without


def test_biography_failure_records_the_evidence(monkeypatch, tmp_path):
    """STU-533: `biography_failed` was a bare literal — no raw_response, no
    run_metadata — so the 14 pages that took this path carried zero signal."""
    from pathlib import Path
    import json as _json

    failure = {"error": "studio_run_output_missing", "raw_response": "truncated stdout",
               "run_metadata": {"run_id": "d9f310e4"}}
    monkeypatch.setattr(gwp, "_run_wiki_page_item", lambda **kw: failure)
    entity = {"canonical_name": "Lucy", "type": "PERSON", "importance": "principal",
              "context_by_chapter": {"C01": ["ctx"]}, "context_chapters": [1], "relationships": []}

    page = gwp._run_generation_sectioned(
        entity=entity, book_title="Narnia", model="m", timeout=10,
        sections=["biography"], max_tokens=500,
        dry_run=False, debug_dir=Path(tmp_path), book_config={})

    assert page["_failed"]
    artifact = _json.loads((tmp_path / "Lucy.json").read_text(encoding="utf-8"))
    assert artifact["error"] == "studio_run_output_missing"
    assert artifact["raw_response"] == "truncated stdout"
    assert artifact["run_metadata"] == {"run_id": "d9f310e4"}
