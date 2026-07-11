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
