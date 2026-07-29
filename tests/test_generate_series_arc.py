"""Tests for scripts/generate_series_arc.py — the STU-708 stage script."""
import json

import yaml

import scripts.generate_series_arc as gsa


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _series(tmp_path, *, with_registry=True, with_material=True):
    """A two-tome series on disk: book YAMLs, epub metadata, synopses, events,
    pages and a series registry."""
    series_dir = tmp_path / "library" / "sarah_j_maas" / "throne-of-glass"
    for index, (slug, title) in enumerate(
        [("01-heir", "Heir of Fire"), ("02-crown", "Queen of Shadows")], start=1
    ):
        book_yaml = series_dir / "books" / f"{slug}.yaml"
        book_yaml.parent.mkdir(parents=True, exist_ok=True)
        book_yaml.write_text(
            yaml.safe_dump({
                "file_path": f"{series_dir}/books/{slug}.epub",
                "language": "en",
                "generation": {"output_language": "fr"},
            }),
            encoding="utf-8",
        )
        processing = series_dir / "processing_output" / slug
        _write(processing / "epub_data.json", {"title": title})
        if not with_material:
            continue
        _write(processing / "book_synopsis.json",
               {"page": {"content": f"## Synopsis\n\n{title} runs its course."}})
        _write(processing / "events.json", {"events": [
            {"chapter": index, "description": f"the turning point of {title}", "salience": 0.9},
            {"chapter": index, "description": "a corridor scene", "salience": 0.1},
        ]})
        _write(processing / "wiki_pages.json", {"pages": [
            {"title": "Aelin Galathynius", "importance": "principal", "entity_type": "PERSON",
             "content": "## Biography\n\nQueen of Terrasen."},
        ]})

    if with_registry:
        _write(series_dir / "registry.json", {
            "version": 1,
            "entities": [{"entity_id": "aelin", "canonical_name": "Aelin Galathynius",
                          "entity_type": "PERSON", "aliases": ["Aelin Galathynius"],
                          "books": ["01-heir", "02-crown"]}],
            "decisions": [], "warnings": [],
        })
    return series_dir


# --- build_arc_inputs ---


def test_inputs_ground_on_every_tome_in_reading_order(tmp_path):
    inputs = gsa.build_arc_inputs(_series(tmp_path))

    assert inputs is not None
    prompt = inputs.prompt
    assert prompt.index("Heir of Fire") < prompt.index("Queen of Shadows")
    assert "Heir of Fire runs its course." in prompt
    assert "the turning point of Queen of Shadows" in prompt
    # Below the salience cut: never grounds the arc.
    assert "a corridor scene" not in prompt
    assert "Aelin Galathynius" in prompt
    assert "Throne Of Glass" in prompt
    assert inputs.lang == "fr"
    assert inputs.cache_path == tmp_path / "library/sarah_j_maas/throne-of-glass/series_arc.json"


def test_a_missing_registry_costs_the_characters_not_the_arc(tmp_path):
    inputs = gsa.build_arc_inputs(_series(tmp_path, with_registry=False))

    assert inputs is not None
    assert "Aelin Galathynius" not in inputs.prompt
    assert "Heir of Fire runs its course." in inputs.prompt


def test_no_material_at_all_yields_no_inputs(tmp_path):
    assert gsa.build_arc_inputs(_series(tmp_path, with_material=False)) is None


def test_a_failed_synopsis_stub_never_grounds_the_arc(tmp_path):
    series_dir = _series(tmp_path)
    _write(
        series_dir / "processing_output" / "01-heir" / "book_synopsis.json",
        {"page": {"content": "## Synopsis\n\n*Échec technique.*", "_failed": True}},
    )

    prompt = gsa.build_arc_inputs(series_dir).prompt

    assert "Échec technique" not in prompt
    assert "Synopsis: (none available)" in prompt


# --- run_for_series ---


def test_run_generates_then_replays_from_cache(tmp_path, monkeypatch):
    series_dir = _series(tmp_path)
    calls = []

    def _fake(prompt, *, lang, timeout=120):
        calls.append(prompt)
        return "Une saga de feu et de verre."

    monkeypatch.setattr(gsa, "generate_arc", _fake)

    assert gsa.run_for_series(series_dir) == "Une saga de feu et de verre."
    assert gsa.run_for_series(series_dir) == "Une saga de feu et de verre."
    assert len(calls) == 1


def test_a_regenerated_synopsis_busts_the_cache(tmp_path, monkeypatch):
    series_dir = _series(tmp_path)
    monkeypatch.setattr(gsa, "generate_arc", lambda prompt, **kw: "arc " + str(len(prompt)))
    first = gsa.run_for_series(series_dir)

    _write(series_dir / "processing_output" / "02-crown" / "book_synopsis.json",
           {"page": {"content": "## Synopsis\n\nA different account entirely."}})

    assert gsa.run_for_series(series_dir) != first


def _never_called(*args, **kwargs):
    raise AssertionError("the LLM must not be called")


def test_dry_run_prints_the_prompt_and_calls_nothing(tmp_path, monkeypatch, capsys):
    series_dir = _series(tmp_path)
    monkeypatch.setattr(gsa, "generate_arc", _never_called)

    assert gsa.run_for_series(series_dir, dry_run=True) is None
    assert "ONLY authoritative source of truth" in capsys.readouterr().out
    assert not (series_dir / "series_arc.json").exists()


def test_a_failed_generation_caches_nothing(tmp_path, monkeypatch):
    series_dir = _series(tmp_path)
    monkeypatch.setattr(gsa, "generate_arc", lambda *a, **kw: None)

    assert gsa.run_for_series(series_dir) is None
    assert not (series_dir / "series_arc.json").exists()


def test_generate_arc_returns_none_on_a_generation_error(monkeypatch):
    monkeypatch.setattr(gsa, "_execute_wiki_page_item",
                        lambda item, entity, timeout: {"error": "studio_run_timeout"})

    assert gsa.generate_arc("prompt", lang="fr") is None


def test_generate_arc_cleans_the_page_content(monkeypatch):
    monkeypatch.setattr(
        gsa, "_execute_wiki_page_item",
        lambda item, entity, timeout: {"content": "## Arc\n\nUne saga *âpre*."},
    )

    assert gsa.generate_arc("prompt", lang="fr") == "Une saga ''âpre''."


# --- the native call split (STU-720) ---


def _payload(series_dir, verdict=None):
    """A wiki-series stage payload: the input is any tome's yaml (the series comes
    from its path), plus the `series-arc-verdict` call's map output."""
    payload = {"additional_context": f"file_path: {series_dir}/books/01-heir.epub"}
    if verdict is not None:
        payload["all_stage_outputs"] = {gsa.VERDICT_STAGE: verdict}
    return payload


def _map_output(page):
    return {"results": [{"index": 0, "status": "success", "run_id": "r1", "output": page}]}


_ARC_PAGE = {
    "title": "Arc", "importance": "principal", "entity_type": "SYNOPSIS",
    "infobox_fields": {}, "content": "## Arc\n\nUne saga *âpre*.",
}


def test_pre_emits_one_map_item_carrying_the_rendered_prompt(tmp_path):
    out = gsa.run_pre(_payload(_series(tmp_path)))

    assert out["needs_verdict"] is True
    assert out["prompt_fingerprint"]
    (item,) = out["items"]
    assert item["entity_type"] == "SYNOPSIS"
    assert item["language"] == "fr"
    assert "Heir of Fire" in item["prompt"] and "Queen of Shadows" in item["prompt"]


def test_pre_skips_the_call_when_no_tome_carries_material(tmp_path):
    out = gsa.run_pre(_payload(_series(tmp_path, with_material=False)))

    assert out == {"items": [], "prompt_fingerprint": "", "needs_verdict": False}


def test_pre_skips_the_call_on_a_cache_hit_and_post_replays_it(tmp_path):
    series_dir = _series(tmp_path)
    assert gsa.arc_from_payload(_payload(series_dir, _map_output(_ARC_PAGE))) == "Une saga ''âpre''."

    assert gsa.run_pre(_payload(series_dir))["needs_verdict"] is False
    # No verdict in the payload: the cache is the only source left.
    assert gsa.arc_from_payload(_payload(series_dir)) == "Une saga ''âpre''."


def test_post_caches_the_arc_from_the_map_output(tmp_path):
    series_dir = _series(tmp_path)

    arc = gsa.arc_from_payload(_payload(series_dir, _map_output(_ARC_PAGE)))

    assert arc == "Une saga ''âpre''."
    cached = json.loads((series_dir / "series_arc.json").read_text(encoding="utf-8"))
    assert cached["arc"] == arc


def test_post_never_calls_a_subprocess(tmp_path, monkeypatch):
    """STU-720: inside wiki-series the LLM call is the native `series-arc-verdict`
    stage. A nested `studio run` from inside the stage is what produced no arc."""
    monkeypatch.setattr(gsa, "_execute_wiki_page_item", _never_called)

    assert gsa.arc_from_payload(_payload(_series(tmp_path), _map_output(_ARC_PAGE)))


def test_post_returns_none_and_caches_nothing_when_the_call_failed(tmp_path):
    series_dir = _series(tmp_path)
    failed = {"results": [{"index": 0, "status": "failed", "error": "boom"}]}

    assert gsa.arc_from_payload(_payload(series_dir, failed)) is None
    assert not (series_dir / "series_arc.json").exists()
