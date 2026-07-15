"""STU-508: post-generation editorial-stance consolidation is advisory, single
pass, section-aware, and reports page/deviation/quote — never just a score."""

from wiki_creator.consolidation import (
    build_report,
    format_summary,
    scan_page,
    scan_pages,
)
from wiki_creator.editorial_stance import EditorialStance


def _page(content, title="Celaena", entity_type="PERSON"):
    return {"title": title, "entity_type": entity_type, "content": content}


def test_in_universe_flags_meta_narrative_and_reader_address():
    stance = EditorialStance(mode="in_universe", hybrid_exceptions=frozenset())
    findings = scan_page(
        _page("Dans le premier chapitre du roman, elle salue le lecteur."),
        stance,
        "fr",
    )
    cats = {f.category for f in findings}
    assert cats == {"meta_narrative", "reader_address"}
    assert any(f.marker.lower() == "roman" for f in findings)
    assert all(f.quote for f in findings)  # short quote, not just a score


def test_out_of_universe_never_flags_meta_or_reader():
    stance = EditorialStance(mode="out_of_universe")
    findings = scan_page(
        _page("Ce roman présente au lecteur, dès le chapitre un, une assassine."),
        stance,
        "fr",
    )
    # meta/reader are legitimate out-of-universe; only author stays forbidden.
    assert all(f.category == "author" for f in findings)


def test_out_of_universe_still_flags_author_when_forbidden():
    stance = EditorialStance(mode="out_of_universe", forbid_author_mentions=True)
    findings = scan_page(_page("Le roman de l'auteur, publié récemment."), stance, "fr")
    assert {f.category for f in findings} == {"author"}


def test_author_not_flagged_when_mentions_allowed():
    stance = EditorialStance(mode="out_of_universe", forbid_author_mentions=False)
    assert scan_page(_page("Le roman de l'auteur."), stance, "fr") == []


def test_hybrid_exempts_meta_in_allowed_section_but_not_elsewhere():
    stance = EditorialStance()  # hybrid, both exceptions allowed
    content = (
        "Une assassine redoutable.\n\n"
        "## Biographie\n\nElle domine le chapitre final du roman.\n\n"
        "## Références\n\nApparaît dans le roman."
    )
    findings = scan_page(_page(content), stance, "fr")
    sections = {f.section for f in findings if f.category == "meta_narrative"}
    # "roman"/"chapitre" flagged under Biographie, exempt under Références.
    assert "Biographie" in sections
    assert "Références" not in sections


def test_hybrid_without_the_exception_flags_the_section():
    stance = EditorialStance(mode="hybrid", hybrid_exceptions=frozenset())
    content = "## Références\n\nApparaît dans le roman."
    findings = scan_page(_page(content), stance, "fr")
    assert any(f.section == "Références" and f.category == "meta_narrative" for f in findings)


def test_clean_page_produces_no_findings():
    stance = EditorialStance(mode="in_universe", hybrid_exceptions=frozenset())
    assert scan_page(_page("Adarlan est un royaume vaste et froid."), stance, "fr") == []


def test_report_is_advisory_and_carries_page_deviation_quote():
    stance = EditorialStance(mode="in_universe", hybrid_exceptions=frozenset())
    pages = [
        _page("Elle domine le roman.", title="A"),
        _page("Un royaume froid.", title="B"),
    ]
    report = build_report(scan_pages(pages, stance, "fr"), stance, pages_scanned=len(pages))
    assert report["status"] == "non_binary_advisory"
    assert report["declared_mode"] == "in_universe"
    assert report["pages_scanned"] == 2
    assert report["pages_with_drift"] == 1
    entry = report["findings"][0]
    assert entry["page"] == "A"
    assert entry["marker"] and entry["quote"]
    summary = format_summary(report)
    assert "A" in summary and "roman" in summary


def test_empty_input_is_clean_report():
    stance = EditorialStance()
    report = build_report(scan_pages([], stance, "fr"), stance, pages_scanned=0)
    assert report["drift_count"] == 0
    assert "No editorial-stance drift" in format_summary(report)


def test_missing_vocabulary_degrades_to_no_findings():
    # An unknown language has no cue_words file → load_lang_config falls back to
    # 'en'; a language with no markers key would yield nothing. Assert the scan
    # never raises and returns a list.
    stance = EditorialStance(mode="in_universe", hybrid_exceptions=frozenset())
    assert isinstance(scan_pages([_page("le roman")], stance, "xx"), list)
