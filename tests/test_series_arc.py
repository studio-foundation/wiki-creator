"""Tests for the series arc projection (STU-708) — pure logic, LLM-free."""
from wiki_creator.series_arc import (
    CACHE_VERSION,
    DEFAULT_MIN_SALIENCE,
    TomeGrounding,
    arc_cache_key,
    build_arc_prompt,
    clean_arc,
    grounding_block,
    load_cached_arc,
    save_arc_cache,
    select_tome_events,
)


def _event(chapter, description, salience, **extra):
    return {"chapter": chapter, "description": description, "salience": salience, **extra}


# --- select_tome_events ---


def test_selects_the_strongest_events_above_the_salience_cut():
    events = [
        _event(1, "a low beat", 0.2),
        _event(2, "a duel", 0.9),
        _event(3, "a coronation", 0.7),
    ]

    selected = select_tome_events(events, max_events=5)

    assert [e["description"] for e in selected] == ["a duel", "a coronation"]
    assert all(e["salience"] >= DEFAULT_MIN_SALIENCE for e in selected)


def test_capped_selection_keeps_the_most_salient_but_reads_chronologically():
    events = [
        _event(9, "the last stand", 0.7),
        _event(2, "the escape", 0.95),
        _event(5, "the betrayal", 0.8),
    ]

    selected = select_tome_events(events, max_events=2)

    assert [e["description"] for e in selected] == ["the escape", "the betrayal"]


# --- grounding_block ---


def test_grounding_lists_every_tome_even_without_material():
    block = grounding_block([
        TomeGrounding("1", "Heir of Fire", synopsis="## Synopsis\n\nShe trains.",
                      events=[_event(4, "she reaches Wendlyn", 0.9)]),
        TomeGrounding("2", "Queen of Shadows"),
    ])

    assert "## Book 1 — Heir of Fire" in block
    assert "She trains." in block
    assert "[Chapter 4] she reaches Wendlyn" in block
    # A tome the pipeline produced nothing for must not be silently skipped — the
    # writer would bridge a gap it cannot see.
    assert "## Book 2 — Queen of Shadows" in block
    assert "(none available)" in block


# --- build_arc_prompt ---


def _prompt(**kwargs):
    kwargs.setdefault("lang", "fr")
    tomes = [
        TomeGrounding("1", "Heir of Fire", synopsis="She trains in Wendlyn.",
                      events=[_event(4, "she reaches Wendlyn", 0.9)]),
        TomeGrounding("2", "Queen of Shadows", synopsis="She takes back Rifthold."),
    ]
    return build_arc_prompt(tomes, ["Aelin Galathynius", "Gavriel"], "Throne Of Glass", **kwargs)


def test_prompt_grounds_on_synopses_characters_and_events():
    prompt = _prompt()

    assert "Throne Of Glass" in prompt
    assert "Aelin Galathynius, Gavriel" in prompt
    assert "She takes back Rifthold." in prompt
    assert "[Chapter 4] she reaches Wendlyn" in prompt
    assert "ONLY authoritative source of truth" in prompt


def test_prompt_follows_the_output_language_and_register():
    assert "encyclopedic French" in _prompt(lang="fr")
    english = _prompt(lang="en", register="Wry and playful.")
    assert "encyclopedic English" in english
    assert "Wry and playful." in english


def test_prompt_asks_for_bare_prose_across_the_tomes():
    prompt = _prompt()

    assert "no headings" in prompt
    assert "1 to 3 paragraphs" in prompt
    assert "Prefer what carries across tomes" in prompt


# --- clean_arc ---


def test_clean_arc_drops_a_heading_and_renders_wikitext():
    arc = clean_arc("## Arc\n\nUne saga **haletante** portée par Aelin.")

    assert arc == "Une saga '''haletante''' portée par Aelin."


# --- cache ---


def test_cache_roundtrips_and_misses_on_changed_inputs(tmp_path):
    path = tmp_path / "series_arc.json"
    key = arc_cache_key("prompt A", "fingerprint-1")
    save_arc_cache(path, key, "Une saga.")

    assert load_cached_arc(path, key) == "Une saga."
    # A tome added, a synopsis regenerated: the prompt changes, the arc re-runs.
    assert load_cached_arc(path, arc_cache_key("prompt B", "fingerprint-1")) is None
    # The agent prompt was edited (STU-560).
    assert load_cached_arc(path, arc_cache_key("prompt A", "fingerprint-2")) is None


def test_cache_misses_on_an_older_schema(tmp_path):
    path = tmp_path / "series_arc.json"
    key = arc_cache_key("prompt A", "fingerprint-1")
    save_arc_cache(path, key, "Une saga.")
    path.write_text(
        path.read_text(encoding="utf-8").replace(f'"version": {CACHE_VERSION}', '"version": 0'),
        encoding="utf-8",
    )

    assert load_cached_arc(path, key) is None


def test_absent_cache_is_a_miss(tmp_path):
    assert load_cached_arc(tmp_path / "nothing.json", "k") is None
