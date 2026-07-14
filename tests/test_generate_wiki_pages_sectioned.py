import scripts.generate_wiki_pages as gwp


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
    out = gwp._generate_one_section(entity={"canonical_name": "A"}, section="biography",
                                    book_title="B", model="m", timeout=10, max_tokens=500)
    assert out == "## Biographie\n\nTexte."


def test_generate_one_section_none_on_error(monkeypatch):
    monkeypatch.setattr(gwp, "_run_wiki_page_item", lambda **kw: {"error": "studio_run_failed"})
    out = gwp._generate_one_section(entity={"canonical_name": "A"}, section="powers",
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
    out = gwp._generate_one_section(entity={"canonical_name": "A"}, section="biography",
                                    book_title="B", model="m", timeout=10, max_tokens=500,
                                    forbidden_names=["Nehemia"])
    assert out is None   # one retry attempted, still hit → omit


def _entity(rels=None):
    return {"canonical_name": "Chaol", "type": "PERSON", "importance": "principal",
            "aliases": ["Captain Westfall"], "titles": ["Captain"],
            "context_by_chapter": {"C01": ["ctx"]}, "relationships": rels or []}


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


def test_sectioned_page_carries_content_units(monkeypatch):
    """STU-491: page output tags each emitted section with its reveal chapter."""
    entity = _entity(rels=[{"chapters": ["ch03", "ch02"]}])
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


def test_isolate_section_drops_leaked_infobox(monkeypatch):
    leaked = "## Infobox\n\n- Nom: X\n\n## Biographie\n\nBio réelle."
    monkeypatch.setattr(gwp, "_run_wiki_page_item", lambda **kw: _fake_item(leaked))
    out = gwp._generate_one_section(entity={"canonical_name": "A"}, section="biography",
                                    book_title="B", model="m", timeout=10, max_tokens=500)
    assert out == "## Biographie\n\nBio réelle."
    assert "Infobox" not in out


def test_isolate_section_wraps_bare_body(monkeypatch):
    monkeypatch.setattr(gwp, "_run_wiki_page_item", lambda **kw: _fake_item("Juste le corps."))
    out = gwp._generate_one_section(entity={"canonical_name": "A"}, section="biography",
                                    book_title="B", model="m", timeout=10, max_tokens=500)
    assert out == "## Biographie\n\nJuste le corps."


def test_isolate_section_none_when_only_infobox(monkeypatch):
    monkeypatch.setattr(gwp, "_run_wiki_page_item", lambda **kw: _fake_item("## Infobox\n\n- Nom: X"))
    out = gwp._generate_one_section(entity={"canonical_name": "A"}, section="biography",
                                    book_title="B", model="m", timeout=10, max_tokens=500)
    assert out is None


def test_sectioned_page_carries_relationship_index(monkeypatch):
    from pathlib import Path
    monkeypatch.setattr(gwp, "_generate_one_section", lambda **kw: "## Biographie\n\nBio.")
    entity = {
        "canonical_name": "Celaena", "type": "PERSON", "importance": "principal",
        "aliases": [], "context_by_chapter": {"C01.xhtml": ["ctx"]},
        "relationships": [
            {"entity_a": "Celaena", "entity_b": "Chaol",
             "relationship_type": "amoureux", "chapters": ["C01.xhtml", "C55.xhtml"]},
        ],
    }
    page = gwp._run_generation_sectioned(
        entity=entity, book_title="ToG", model="m", timeout=10,
        sections=["biography", "relationships"], max_tokens=500,
        dry_run=False, debug_dir=Path("/tmp"), book_config={})
    assert page["relationship_index"] == ["* [[Chaol]] — amoureux (ch.1→ch.55)"]


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
                   "chapters": ["ch55"]},
                  {"entity_a": "Cain", "entity_b": "Chaol", "relationship_type": "antagoniste",
                   "chapters": ["ch07"]},
                  {"entity_a": "Chaol", "entity_b": "Nox", "relationship_type": None,
                   "chapters": ["ch02"]}]}
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
         "chapters": ["ch55"]},
        {"entity_a": "Cain", "entity_b": "Chaol", "relationship_type": "antagoniste",
         "chapters": ["ch07"]}])
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
                            "relationship_type": "amoureux", "chapters": ["ch55"]}])
    _sectioned(monkeypatch, {"relationships": "## Relations\n\nProse unique."})
    from pathlib import Path
    page = gwp._run_generation_sectioned(
        entity=entity, book_title="ToG", model="m", timeout=10,
        sections=["infobox", "biography", "relationships", "references"],
        max_tokens=500, dry_run=False, debug_dir=Path("/tmp"), book_config={})
    assert "Prose unique." in page["content"]
    assert "relation_units" not in page
    assert page["relationship_index"]  # STU-492 index still built
