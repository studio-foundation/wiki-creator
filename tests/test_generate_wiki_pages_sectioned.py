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
