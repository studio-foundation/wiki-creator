"""STU-508: post-generation editorial-stance consolidation is advisory, single
pass, section-aware, and reports page/deviation/quote — never just a score."""

import pytest

from wiki_creator.consolidation import (
    build_report,
    format_summary,
    scan_page,
    scan_pages,
)
from wiki_creator.editorial_stance import EditorialStance
from wiki_creator.lang import LangPackError


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


def test_unknown_language_raises_loudly():
    # An unsupported language has no cue_words file → load_lang_config fails
    # loudly (STU-451) instead of silently scanning with English markers.
    stance = EditorialStance(mode="in_universe", hybrid_exceptions=frozenset())
    with pytest.raises(LangPackError):
        scan_pages([_page("le roman")], stance, "xx")


# --- STU-579: leaked pipeline metric (raw mention/cooccurrence count) ---


def _metric_findings(findings):
    return [f for f in findings if f.category == "pipeline_metric"]


def test_flags_raw_mentions_count_leaked_into_prose():
    stance = EditorialStance()  # hybrid — the axis is stance-independent
    findings = scan_page(
        _page("Proche de [[Chaol]] (503 mentions communes) tout au long du récit."),
        stance,
        "fr",
    )
    metric = _metric_findings(findings)
    assert metric, "a raw '503 mentions communes' must be flagged as a pipeline metric"
    assert "503" in metric[0].marker
    assert metric[0].quote  # page/deviation/quote, not just a score


def test_flags_cooccurrence_count_label_and_number():
    stance = EditorialStance()
    findings = scan_page(_page("Relation forte, cooccurrence count: 42."), stance, "fr")
    assert any("42" in f.marker for f in _metric_findings(findings))


def test_metric_leak_flagged_even_out_of_universe():
    # meta/reader/author can be legitimate out-of-universe, but a raw pipeline
    # metric never is — it must still be flagged.
    stance = EditorialStance(mode="out_of_universe")
    findings = scan_page(_page("Allié de [[Dorian]] — 175 cooccurrences."), stance, "fr")
    assert _metric_findings(findings)


def test_clean_number_near_no_metric_term_is_not_flagged():
    stance = EditorialStance(mode="out_of_universe")
    # A number that is not a leaked count (age) must not trip the detector.
    assert _metric_findings(scan_page(_page("Âgée de 42 ans, elle règne."), stance, "fr")) == []


def test_metric_leak_flagged_in_english_and_spanish():
    stance_en = EditorialStance(mode="out_of_universe")
    en = scan_page(_page("A close ally (503 common mentions).", entity_type="PERSON"), stance_en, "en")
    assert _metric_findings(en)
    stance_es = EditorialStance(mode="out_of_universe")
    es = scan_page(_page("Aliada cercana (503 menciones comunes).", entity_type="PERSON"), stance_es, "es")
    assert _metric_findings(es)


def test_metric_leak_surfaces_in_report_and_summary():
    stance = EditorialStance(mode="out_of_universe")
    pages = [_page("Proche de [[Chaol]] (503 mentions communes).", title="Celaena")]
    report = build_report(scan_pages(pages, stance, "fr"), stance, pages_scanned=1)
    assert report["drift_count"] >= 1
    assert any(f["category"] == "pipeline_metric" for f in report["findings"])
    assert "503" in format_summary(report)
