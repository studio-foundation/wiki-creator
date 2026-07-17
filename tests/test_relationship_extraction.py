"""Tests for scripts/relationship_extraction.py — spaCy-only pronoun heuristic."""
import json
import subprocess
import sys
import os
from unittest.mock import patch, MagicMock

from scripts.relationship_extraction import enrich_mentions_with_coref


from _markers import requires_fastcoref, requires_fr_lg


@requires_fastcoref
@requires_fr_lg
def test_enrich_mentions_adds_pronoun_sentence():
    """Pronoun sentence after a named entity must be added to its mentions."""
    chapters = {
        "ch01": (
            "David Martín était un écrivain qui vivait à Barcelone. "
            "Il travaillait chaque nuit dans son atelier. "
            "Il écrivait des romans sombres et poétiques."
        ),
    }
    entities = [
        {"canonical_name": "David Martín", "type": "PERSON", "aliases": ["Martín", "David"], "relevant": True},
    ]
    mentions_by_entity = {
        "David Martín": {"ch01": ["David Martín était un écrivain qui vivait à Barcelone."]}
    }

    enriched = enrich_mentions_with_coref(chapters, entities, mentions_by_entity)

    ch01_sentences = enriched.get("David Martín", {}).get("ch01", [])
    pronoun_sentences = [s for s in ch01_sentences if "Il" in s or "il" in s]
    assert len(pronoun_sentences) >= 1, (
        f"Expected at least one pronoun sentence added, got: {ch01_sentences}"
    )


def test_enrich_mentions_no_crash_on_empty_chapters():
    """If chapters dict is empty, function returns mentions_by_entity unchanged."""
    entities = [
        {"canonical_name": "David Martín", "type": "PERSON", "aliases": [], "relevant": True},
    ]
    mentions_by_entity = {"David Martín": {"ch01": ["David Martín entra."]}}
    result = enrich_mentions_with_coref({}, entities, mentions_by_entity)
    assert result == mentions_by_entity


def test_enrich_mentions_no_duplicate_sentences():
    """Already-present sentences must not be added again."""
    # This sentence has no pronouns, so it won't be re-added via coref logic.
    # We just verify existing sentences are not duplicated.
    sentence = "David Martín était un écrivain qui vivait à Barcelone."
    chapters = {"ch01": sentence}
    entities = [
        {"canonical_name": "David Martín", "type": "PERSON", "aliases": ["Martín"], "relevant": True},
    ]
    mentions_by_entity = {"David Martín": {"ch01": [sentence]}}

    enriched = enrich_mentions_with_coref(chapters, entities, mentions_by_entity)
    assert enriched["David Martín"]["ch01"].count(sentence) == 1


def test_enrich_mentions_resets_after_silence():
    """Active entity resets after silence_window sentences with no PERSON."""
    # After 6 sentences with no entity, the active entity resets
    # and pronouns in a later sentence should NOT be attributed
    silence_sentences = " ".join([f"La pluie tombait sur la ville." for _ in range(6)])
    chapters = {
        "ch01": (
            "David Martín entra dans la pièce. "  # sets active_entity = David Martín
            + silence_sentences +                   # 6 sentences, resets after 5
            " Il pleuvait encore."                  # pronoun but active_entity is None
        ),
    }
    entities = [
        {"canonical_name": "David Martín", "type": "PERSON", "aliases": ["Martín"], "relevant": True},
    ]
    mentions_by_entity: dict = {}

    enriched = enrich_mentions_with_coref(chapters, entities, mentions_by_entity, silence_window=5)

    # "Il pleuvait encore." should NOT be in David Martín's mentions
    dm_mentions = enriched.get("David Martín", {}).get("ch01", [])
    assert "Il pleuvait encore." not in dm_mentions


def test_narrator_passthrough_in_output():
    """narrator from entity-resolution is passed through to output unchanged."""
    import json
    import subprocess
    import sys
    import os

    narrator = {
        "entity": "David Martín",
        "pov": "first_person",
        "reliability": "unreliable",
        "evidence": ["ch20: hallucinations"],
    }
    resolution_output = {
        "entities": [
            {"canonical_name": "David Martín", "type": "PERSON", "aliases": [], "source_ids": [], "relevant": True}
        ],
        "narrator": narrator,
    }
    payload = {
        "previous_outputs": {
            "entity-resolution": resolution_output,
            "epub-parse": {"title": "Test", "author": None, "chapters": [], "pov_detection": {"pov": "first_person", "first_person_count": 100, "total_tokens": 500, "confidence": "high"}},
        },
        "additional_context": "",
    }
    result = subprocess.run(
        [sys.executable, "scripts/relationship_extraction.py"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    )
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    output = json.loads(result.stdout)
    assert "narrator" in output, "narrator key missing from output"
    assert output["narrator"] == narrator


def test_narrator_passthrough_null_when_absent():
    """If entity-resolution has no narrator, output narrator is None."""
    import json
    import subprocess
    import sys
    import os

    resolution_output = {
        "entities": [
            {"canonical_name": "David Martín", "type": "PERSON", "aliases": [], "source_ids": [], "relevant": True}
        ],
        # no narrator key
    }
    payload = {
        "previous_outputs": {
            "entity-resolution": resolution_output,
            "epub-parse": {"title": "Test", "author": None, "chapters": [], "pov_detection": {"pov": "omniscient", "first_person_count": 0, "total_tokens": 500, "confidence": "high"}},
        },
        "additional_context": "",
    }
    result = subprocess.run(
        [sys.executable, "scripts/relationship_extraction.py"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    )
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    output = json.loads(result.stdout)
    assert output.get("narrator") is None


def test_coref_worker_returns_list():
    """_coref_worker returns a list (empty when fastcoref not available)."""
    from scripts.relationship_extraction import _coref_worker
    result = _coref_worker(("ch01", "Il travaillait.", {"david martín": "David Martín"}, "fr_core_news_lg", 8000, frozenset({"il"})))
    assert isinstance(result, list)
    for item in result:
        assert len(item) == 3
        assert isinstance(item[0], str)
        assert isinstance(item[1], str)
        assert isinstance(item[2], str)


def test_enrich_fastcoref_accepts_workers_param():
    """enrich_mentions_with_fastcoref accepts workers param without crashing."""
    import inspect
    from scripts.relationship_extraction import enrich_mentions_with_fastcoref
    sig = inspect.signature(enrich_mentions_with_fastcoref)
    assert "workers" in sig.parameters
    assert sig.parameters["workers"].default == 1


def test_enrich_fastcoref_accepts_max_chars_param():
    """enrich_mentions_with_fastcoref accepts max_chars with default 8000."""
    import inspect
    from scripts.relationship_extraction import enrich_mentions_with_fastcoref
    sig = inspect.signature(enrich_mentions_with_fastcoref)
    assert "max_chars" in sig.parameters
    assert sig.parameters["max_chars"].default == 8000


def test_enrich_fastcoref_accepts_device_param():
    """enrich_mentions_with_fastcoref accepts device, default None (auto-detect)."""
    import inspect
    from scripts.relationship_extraction import enrich_mentions_with_fastcoref
    sig = inspect.signature(enrich_mentions_with_fastcoref)
    assert "device" in sig.parameters
    assert sig.parameters["device"].default is None


def test_resolve_coref_device_respects_explicit():
    """An explicit device is returned verbatim, never overridden by auto-detect."""
    from scripts.relationship_extraction import _resolve_coref_device
    assert _resolve_coref_device("cpu") == "cpu"
    assert _resolve_coref_device("cuda") == "cuda"


def test_resolve_coref_device_falls_back_to_cpu_without_cuda(monkeypatch):
    """With no CUDA available, auto-detect returns 'cpu'."""
    import sys
    import types
    from scripts.relationship_extraction import _resolve_coref_device
    fake_torch = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: False))
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    assert _resolve_coref_device() == "cpu"
    assert _resolve_coref_device(None) == "cpu"


def test_resolve_coref_device_picks_cuda_when_available(monkeypatch):
    """With CUDA available, auto-detect returns 'cuda'."""
    import sys
    import types
    from scripts.relationship_extraction import _resolve_coref_device
    fake_torch = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: True))
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    assert _resolve_coref_device() == "cuda"


def test_coref_forces_single_worker_on_gpu(monkeypatch, capsys):
    """On GPU, workers>1 is forced to 1 (a single card can't hold N×590M in VRAM)."""
    import sys
    import scripts.relationship_extraction as rel
    monkeypatch.setattr(rel, "_resolve_coref_device", lambda explicit=None: "cuda")
    # Sequential path loads fastcoref for real wherever it is installed; hide it
    # so the forced-to-1 run falls back to the stubbed heuristic instead of the
    # 590M model on a GPU (STU-530).
    monkeypatch.setitem(sys.modules, "fastcoref", None)
    monkeypatch.setattr(rel, "enrich_mentions_with_coref", lambda chapters, entities, m: m)
    entities = [{"canonical_name": "Alice", "type": "PERSON", "aliases": [], "relevant": True}]
    chapters = {"ch01": "Alice walked. She smiled."}
    mentions = {"Alice": {"ch01": ["Alice walked."]}}
    rel.enrich_mentions_with_fastcoref(chapters, entities, mentions, workers=8, device="cuda")
    err = capsys.readouterr().err
    assert "forcing workers=1" in err


def test_main_parses_workers_flag(monkeypatch):
    """--workers N is parsed and passed through to run_live_mode."""
    import sys
    import scripts.relationship_extraction as rel

    captured = {}

    def fake_run_live(window_size, threshold, coref=False, workers=1, min_cooccurrence=None, min_chapters_together=2, coref_max_chars=8000, coref_device=None):
        captured["workers"] = workers

    monkeypatch.setattr(rel, "run_live_mode", fake_run_live)
    monkeypatch.setattr(sys, "argv", ["rel.py", "--live", "--coref", "--workers", "4"])
    rel.main()

    assert captured["workers"] == 4


def test_main_parses_coref_max_chars_flag(monkeypatch):
    """--coref-max-chars N is parsed and passed through to run_live_mode."""
    import sys
    import scripts.relationship_extraction as rel

    captured = {}

    def fake_run_live(window_size, threshold, coref=False, workers=1, min_cooccurrence=None, min_chapters_together=2, coref_max_chars=8000, coref_device=None):
        captured["coref_max_chars"] = coref_max_chars

    monkeypatch.setattr(rel, "run_live_mode", fake_run_live)
    monkeypatch.setattr(sys, "argv", ["rel.py", "--live", "--coref", "--coref-max-chars", "0"])
    rel.main()

    assert captured["coref_max_chars"] == 0


def test_executor_parses_coref_max_chars(monkeypatch, tmp_path, capsys):
    """coref_max_chars in additional_context reaches enrich_mentions_with_fastcoref."""
    import io
    import json
    import sys
    from types import SimpleNamespace
    import scripts.relationship_extraction as rel

    (tmp_path / "chapters.json").write_text(json.dumps({"chapters": {"ch01": "Celaena walked. She smiled."}}), encoding="utf-8")

    captured = {}

    def fake_enrich(chapters, entities, mentions_by_entity, workers=1, spacy_model="fr_core_news_lg", max_chars=8000, device=None):
        captured["max_chars"] = max_chars
        return mentions_by_entity

    monkeypatch.setattr(rel, "enrich_mentions_with_fastcoref", fake_enrich)
    monkeypatch.setattr(rel.studio_io, "paths_from_payload", lambda payload, strict=False: SimpleNamespace(processing=tmp_path))

    payload = {
        "previous_outputs": {
            "entity-resolution": {
                "entities": [{"canonical_name": "Celaena", "type": "PERSON", "aliases": [], "source_ids": [], "relevant": True}],
            },
        },
        "additional_context": "coref: true\ncoref_max_chars: 4321\n",
    }
    monkeypatch.setattr(sys, "argv", ["rel.py"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    rel.main()

    assert captured["max_chars"] == 4321
    out = capsys.readouterr().out
    assert json.loads(out)  # executor still emits valid JSON


def test_parallel_merge_matches_direct_process_chapters():
    """Parallel path merge produces same sentences as _process_chapter_clusters directly.

    We mock ProcessPoolExecutor.map to return pre-computed results from
    _process_chapter_clusters, then verify enrich_mentions_with_fastcoref
    (workers=2) merges them into mentions_by_entity identically.
    """
    from unittest.mock import patch, MagicMock
    import scripts.relationship_extraction as rel

    chapters = {
        "ch01": "David Martín entra dans la pièce. Il ferma la porte derrière lui.",
        "ch02": "Pedro Vidal écrivit toute la nuit. Il signa le contrat au matin.",
    }
    entities = [
        {"canonical_name": "David Martín", "type": "PERSON", "aliases": ["Martín", "David"], "relevant": True},
        {"canonical_name": "Pedro Vidal", "type": "PERSON", "aliases": ["Vidal"], "relevant": True},
    ]

    # Build the name_to_canonical map the same way the function does
    name_to_canonical: dict[str, str] = {}
    for entity in entities:
        if entity.get("type") == "PERSON" and entity.get("relevant", True):
            canonical = entity["canonical_name"]
            name_to_canonical[canonical.lower()] = canonical
            for alias in entity.get("aliases", []):
                if len(alias) >= 3:
                    name_to_canonical[alias.lower()] = canonical

    # What _process_chapter_clusters would return for each chapter
    # (We compute it directly here so the test doesn't depend on fastcoref)
    # Since fastcoref isn't available in CI, raw_clusters will be empty → []
    # We simulate non-empty results manually.
    # Simulate a worker returning the same sentence twice (e.g., from overlapping clusters)
    # The merge should deduplicate — only one copy should end up in mentions_by_entity
    simulated_worker_results = {
        "ch01": [
            ("David Martín", "ch01", "Il ferma la porte derrière lui."),
            ("David Martín", "ch01", "Il ferma la porte derrière lui."),  # duplicate
        ],
        "ch02": [("Pedro Vidal", "ch02", "Il signa le contrat au matin.")],
    }

    # Fake executor that returns pre-computed results without loading the model
    class FakeExecutor:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def map(self, fn, items):
            return [simulated_worker_results.get(item[0], []) for item in items]

    mentions = {"David Martín": {}, "Pedro Vidal": {}}
    # device="cpu" is load-bearing: auto-detect picks CUDA on a GPU host, which
    # forces workers=1 (STU-466) and takes the sequential path — FakeExecutor is
    # never constructed and the real model runs instead (STU-530).
    with patch("concurrent.futures.ProcessPoolExecutor", return_value=FakeExecutor()):
        result = rel.enrich_mentions_with_fastcoref(chapters, entities, mentions, workers=2, device="cpu")

    # Verify the expected sentences are present (from simulated worker results)
    dm_sentences = result.get("David Martín", {}).get("ch01", [])
    pv_sentences = result.get("Pedro Vidal", {}).get("ch02", [])

    assert "Il ferma la porte derrière lui." in dm_sentences, (
        f"Expected David Martín ch01 sentence, got: {dm_sentences}"
    )
    assert "Il signa le contrat au matin." in pv_sentences, (
        f"Expected Pedro Vidal ch02 sentence, got: {pv_sentences}"
    )

    # Verify deduplication: same sentence returned twice by worker → only once in result
    assert dm_sentences.count("Il ferma la porte derrière lui.") == 1, (
        f"Expected exactly 1 copy after dedup, got: {dm_sentences}"
    )
    assert pv_sentences.count("Il signa le contrat au matin.") == 1, (
        f"Expected exactly 1 copy after dedup, got: {pv_sentences}"
    )


# ---------------------------------------------------------------------------
# STU-248: min_cooccurrence and min_chapters_together filters
# ---------------------------------------------------------------------------

def _stu248_entities():
    return [
        {"canonical_name": "David Martín", "type": "PERSON", "aliases": ["Martín"], "relevant": True},
        {"canonical_name": "Pedro Vidal",  "type": "PERSON", "aliases": ["Vidal"],  "relevant": True},
        {"canonical_name": "Regarde",      "type": "PERSON", "aliases": [],          "relevant": True},
    ]


def _stu248_chapters():
    return {
        "ch01": "Vidal tendit le manuscrit à Martín. Martín retrouva Vidal. — Regarde, il est là.",
        "ch02": "Martín reçut une lettre. Vidal encouragea Martín.",
    }


def test_false_entity_filtered_by_min_chapters():
    """'Regarde' only appears in 1 chapter — must be filtered with min_chapters_together=2."""
    from scripts.relationship_extraction import build_cooccurrence_graph
    rels, stats = build_cooccurrence_graph(
        _stu248_entities(),
        _stu248_chapters(),
        window_size=5,
        min_cooccurrence=2,
        min_chapters_together=2,
    )
    entity_names = {r["entity_a"] for r in rels} | {r["entity_b"] for r in rels}
    assert "Regarde" not in entity_names


def test_true_relation_survives_filter():
    """Martín ↔ Vidal appears in 2 chapters — must survive the filter."""
    from scripts.relationship_extraction import build_cooccurrence_graph
    rels, stats = build_cooccurrence_graph(
        _stu248_entities(),
        _stu248_chapters(),
        window_size=5,
        min_cooccurrence=2,
        min_chapters_together=2,
    )
    pairs = {(r["entity_a"], r["entity_b"]) for r in rels}
    assert ("David Martín", "Pedro Vidal") in pairs or ("Pedro Vidal", "David Martín") in pairs


def test_coref_worker_accepts_6_tuple():
    """_coref_worker must unpack (chapter_id, text, name_to_canonical, spacy_model, max_chars, pronouns)."""
    from scripts.relationship_extraction import _coref_worker
    result = _coref_worker(("ch01", "", {}, "en_core_web_sm", 8000, frozenset({"she"})))
    assert result == []


def test_enrich_heuristic_accepts_pronouns_param():
    """enrich_mentions_with_heuristic should accept custom pronouns without error."""
    from scripts.relationship_extraction import enrich_mentions_with_heuristic
    chapters = {"ch01": "Alice walked in. She smiled."}
    entities = [{"canonical_name": "Alice", "type": "PERSON", "relevant": True, "aliases": []}]
    mentions = {"Alice": {"ch01": ["Alice walked in."]}}
    # spaCy blank model (no NER, no senter) — use a real EN model if available
    import spacy
    nlp = spacy.blank("en")
    nlp.add_pipe("sentencizer")
    result = enrich_mentions_with_heuristic(
        chapters, entities, mentions, nlp=nlp, pronouns=frozenset({"she"})
    )
    assert isinstance(result, dict)


def test_stats_include_new_fields():
    """Stats dict must expose min_cooccurrence and min_chapters_together."""
    from scripts.relationship_extraction import build_cooccurrence_graph
    _, stats = build_cooccurrence_graph(
        _stu248_entities(),
        _stu248_chapters(),
        window_size=5,
        min_cooccurrence=3,
        min_chapters_together=2,
    )
    assert stats["min_cooccurrence"] == 3
    assert stats["min_chapters_together"] == 2


# ---------------------------------------------------------------------------
# STU-283: _tightest_span returns minimal span containing both names
# ---------------------------------------------------------------------------

def test_tightest_span_returns_sentence_with_both_names():
    """When both names are in the same sentence, return just that sentence."""
    from scripts.relationship_extraction import _tightest_span
    window = [
        "The snow fell hard.",
        "Dorian and Hollin argued bitterly.",
        "The king watched from afar.",
    ]
    result = _tightest_span(window, "dorian", "hollin")
    assert "Dorian" in result
    assert "Hollin" in result
    assert "snow" not in result


def test_tightest_span_spans_two_sentences_when_names_separated():
    """Names in adjacent sentences (gap=1) must be returned as a 2-sentence span, excluding non-adjacent name occurrences."""
    from scripts.relationship_extraction import _tightest_span
    window = [
        "Dorian entered the hall.",    # Dorian @ 0
        "Hollin ran toward him.",      # Hollin @ 1 — gap=1, best pair
        "Dorian watched from afar.",   # Dorian @ 2 — farther, should NOT expand span
    ]
    result = _tightest_span(window, "dorian", "hollin")
    assert result is not None
    assert "Dorian" in result
    assert "Hollin" in result
    assert "watched from afar" not in result   # sent 2 not part of closest pair span


def test_tightest_span_excludes_sentences_with_neither_name():
    """Names more than 1 sentence apart must return None — no direct interaction evidence."""
    from scripts.relationship_extraction import _tightest_span
    window = [
        "Dorian entered the hall.",
        "The fireplace crackled.",
        "The prince watched from afar.",
        "Hollin ran toward him.",          # gap=3 from Dorian
    ]
    result = _tightest_span(window, "dorian", "hollin")
    assert result is None


def test_tightest_span_returns_closest_pair_span():
    """When names appear multiple times, return the span around the closest pair."""
    from scripts.relationship_extraction import _tightest_span
    window = [
        "Dorian entered the hall.",        # Dorian @ 0
        "Dorian looked at Hollin.",        # both @ 1 — gap=0, best pair
        "Hollin did not answer.",          # Hollin @ 2
    ]
    result = _tightest_span(window, "dorian", "hollin")
    assert result is not None
    # Best pair is sentence 1 (gap=0), so only that sentence is returned
    assert "Dorian" in result
    assert "Hollin" in result
    assert "did not answer" not in result   # sent 2 not included (best gap is 0, not 1)


def test_tightest_span_returns_none_when_name_not_found():
    """If either name is absent from the window, return None — no evidence possible."""
    from scripts.relationship_extraction import _tightest_span
    window = ["Some unrelated sentence.", "Another sentence."]
    result = _tightest_span(window, "dorian", "hollin")
    assert result is None


def test_tightest_span_name_matching_is_case_insensitive():
    """Name lookup must be case-insensitive (matching the detection regex)."""
    from scripts.relationship_extraction import _tightest_span
    window = ["DORIAN met hollin at the gate."]
    result = _tightest_span(window, "dorian", "hollin")
    assert "DORIAN" in result
    assert "hollin" in result


def test_build_cooccurrence_graph_sample_contexts_contain_both_names():
    """sample_contexts must contain both entity names (STU-283)."""
    from scripts.relationship_extraction import build_cooccurrence_graph

    entities = [
        {"canonical_name": "Dorian", "type": "PERSON", "aliases": [], "relevant": True},
        {"canonical_name": "Hollin", "type": "PERSON", "aliases": [], "relevant": True},
    ]
    chapters = {
        "ch01": (
            "The snow fell hard. "
            "Dorian entered the hall. "
            "Hollin ran toward him. "
            "They spoke quietly. "
            "The king watched."
        )
    }
    rels, _ = build_cooccurrence_graph(entities, chapters, window_size=5, min_cooccurrence=1, min_chapters_together=1)
    assert rels, "Expected at least one relationship"
    for rel in rels:
        for ctx in rel["sample_contexts"]:
            assert "Dorian" in ctx or "dorian" in ctx.lower(), f"Missing Dorian in: {ctx}"
            assert "Hollin" in ctx or "hollin" in ctx.lower(), f"Missing Hollin in: {ctx}"


def test_build_cooccurrence_graph_sample_contexts_prefer_same_sentence():
    """gap=0 contexts (both names same sentence) must appear before gap=1 (adjacent sentences)."""
    from scripts.relationship_extraction import build_cooccurrence_graph

    entities = [
        {"canonical_name": "Alice", "type": "PERSON", "aliases": [], "relevant": True},
        {"canonical_name": "Bob", "type": "PERSON", "aliases": [], "relevant": True},
    ]
    # ch01..ch10: gap=1 (Alice in sentence 1, Bob in sentence 2 — no same-sentence occurrence)
    # ch11..ch20: gap=0 (Alice and Bob in the same sentence)
    chapters = {f"ch{i:02d}": "Alice entered the room. Bob followed behind." for i in range(1, 11)}
    chapters |= {f"ch{i:02d}": "Alice and Bob spoke quietly together." for i in range(11, 21)}

    rels, _ = build_cooccurrence_graph(
        entities, chapters, window_size=3, min_cooccurrence=1, min_chapters_together=1
    )
    assert rels, "Expected at least one relationship"
    contexts = rels[0]["sample_contexts"]
    # All gap=0 contexts should appear before any gap=1
    gap0_texts = {c for c in contexts if "Alice and Bob" in c}
    gap1_texts = {c for c in contexts if "Alice and Bob" not in c}
    assert gap0_texts, "Expected at least one same-sentence (gap=0) context in results"
    if gap1_texts:
        # gap=0 entries must fill the front of the list before gap=1 entries
        first_gap1_idx = next(i for i, c in enumerate(contexts) if c in gap1_texts)
        last_gap0_idx = max(i for i, c in enumerate(contexts) if c in gap0_texts)
        assert last_gap0_idx < first_gap1_idx or len(gap0_texts) == 12, (
            "gap=0 contexts must be exhausted before gap=1 contexts are included"
        )


def test_build_cooccurrence_graph_sample_contexts_distributed_across_chapters():
    """sample_contexts must draw from early and late chapters, not just the first 3."""
    from scripts.relationship_extraction import build_cooccurrence_graph

    entities = [
        {"canonical_name": "Alice", "type": "PERSON", "aliases": [], "relevant": True},
        {"canonical_name": "Bob", "type": "PERSON", "aliases": [], "relevant": True},
    ]
    # 20 chapters, each with one co-occurrence sentence
    chapters = {f"ch{i:02d}": f"Alice met Bob in chapter {i}." for i in range(1, 21)}

    rels, _ = build_cooccurrence_graph(
        entities, chapters, window_size=3, min_cooccurrence=1, min_chapters_together=1
    )
    assert rels, "Expected at least one relationship"
    contexts = rels[0]["sample_contexts"]
    assert len(contexts) <= 12, f"Expected at most 12 contexts, got {len(contexts)}"
    # Must include contexts from late chapters (chapter 15+)
    late_contexts = [c for c in contexts if any(f"chapter {i}" in c for i in range(15, 21))]
    assert late_contexts, "sample_contexts must include contexts from late chapters"


def test_tightest_span_returns_none_when_names_too_far_apart():
    """Names separated by more than 1 sentence (gap=2) must return None."""
    from scripts.relationship_extraction import _tightest_span
    window = [
        "Nehemia entered the hall.",
        "The crowd murmured.",          # neither name
        "Cain flexed his arms.",        # gap=2 from Nehemia
    ]
    result = _tightest_span(window, "cain", "nehemia")
    assert result is None


def test_tightest_span_uses_closest_pair_when_multiple_occurrences():
    """When a name appears multiple times, use the pair with minimum gap."""
    from scripts.relationship_extraction import _tightest_span
    window = [
        "Cain entered first.",          # Cain @ 0 — gap=3 from Nehemia @ 3
        "The hall was silent.",
        "Cain looked up.",              # Cain @ 2 — gap=1 from Nehemia @ 3
        "Nehemia stepped forward.",     # Nehemia @ 3
    ]
    result = _tightest_span(window, "cain", "nehemia")
    assert result is not None
    # Should use the closest pair: Cain@2 + Nehemia@3 (gap=1)
    assert "Cain looked up" in result
    assert "Nehemia stepped forward" in result
    assert "Cain entered first" not in result   # farther pair not included


def test_tightest_span_returns_none_when_name_appears_only_in_artifact_genitive():
    """'Eye of Elena' — 'Elena' after 'of' is an artifact reference, not the character. Must return None."""
    from scripts.relationship_extraction import _tightest_span
    window = ["Celaena grabbed the Eye of Elena from the altar."]
    result = _tightest_span(window, "Celaena", "Elena")
    assert result is None, f"Expected None when Elena only appears as artifact genitive, got: {result!r}"


def test_tightest_span_uses_standalone_name_even_when_artifact_also_present():
    """If 'Elena' appears both in 'Eye of Elena' and standalone, the standalone counts."""
    from scripts.relationship_extraction import _tightest_span
    window = [
        "Celaena entered the chamber.",      # Celaena @ 0
        "Elena spoke to her from the mist.", # Elena @ 1 — standalone, gap=1
        "The Eye of Elena glowed.",          # Elena @ 2 — artifact only, should not count
    ]
    result = _tightest_span(window, "Celaena", "Elena")
    assert result is not None
    assert "Celaena" in result
    assert "Elena spoke" in result


def test_build_cooccurrence_graph_excludes_pairs_without_proximity_context():
    """Pairs whose names never appear within 1 sentence of each other must be excluded."""
    from scripts.relationship_extraction import build_cooccurrence_graph

    entities = [
        {"canonical_name": "Cain", "type": "PERSON", "aliases": [], "relevant": True},
        {"canonical_name": "Nehemia", "type": "PERSON", "aliases": [], "relevant": True},
    ]
    # Names appear in same window but always gap>=2 apart
    chapters = {"ch01": (
        "Nehemia watched the competition. "   # Nehemia @ 0
        "The crowd cheered loudly. "          # gap filler @ 1
        "Cain flexed his arms."               # Cain @ 2 — gap=2 from Nehemia
    )}
    rels, _ = build_cooccurrence_graph(
        entities, chapters, window_size=5, min_cooccurrence=1, min_chapters_together=1
    )
    names_in_output = {(r["entity_a"], r["entity_b"]) for r in rels}
    assert ("Cain", "Nehemia") not in names_in_output
    assert ("Nehemia", "Cain") not in names_in_output


# --- Studio classifier item tests ---

from scripts.relationship_extraction import _run_studio_classifier_item


def test_run_studio_classifier_item_returns_classification_on_success():
    fake_output = json.dumps({
        "stages": [
            {
                "stage_name": "relationship-classifier",
                "status": "success",
                "output": {
                    "relationship_type": "ami",
                    "direction": "symétrique",
                    "evolution": "Leur complicité grandit.",
                    "key_moments": ["ch03: entraînement commun"],
                },
            }
        ]
    })
    mock_result = MagicMock(returncode=0, stdout=fake_output, stderr="")
    with patch("subprocess.run", return_value=mock_result):
        rel = {"entity_a": "Celaena", "entity_b": "Chaol", "sample_contexts": ["ctx1"], "cooccurrence_count": 5}
        result = _run_studio_classifier_item(rel, novel_summary="", additional_context="")
    assert result["relationship_type"] == "ami"


def test_run_studio_classifier_item_degrades_on_studio_missing():
    with patch("subprocess.run", side_effect=FileNotFoundError):
        rel = {"entity_a": "A", "entity_b": "B", "sample_contexts": [], "cooccurrence_count": 1}
        result = _run_studio_classifier_item(rel, novel_summary="", additional_context="")
    assert result.get("error") == "studio_cli_missing"


# ---------------------------------------------------------------------------
# STU-286: filter PLACE/OTHER entities before classification
# ---------------------------------------------------------------------------

from scripts.relationship_extraction import _should_classify_pair


def test_should_classify_pair_allows_person_person():
    rel = {"entity_a": "Celaena", "entity_b": "Chaol"}
    entity_types = {"Celaena": "PERSON", "Chaol": "PERSON"}
    assert _should_classify_pair(rel, entity_types) is True


def test_should_classify_pair_skips_when_entity_b_is_place():
    rel = {"entity_a": "Chaol Westfall", "entity_b": "White Fang Mountains"}
    entity_types = {"Chaol Westfall": "PERSON", "White Fang Mountains": "PLACE"}
    assert _should_classify_pair(rel, entity_types) is False


def test_should_classify_pair_skips_when_entity_b_is_other():
    rel = {"entity_a": "King of Adarlan", "entity_b": "Nothung"}
    entity_types = {"King of Adarlan": "PERSON", "Nothung": "OTHER"}
    assert _should_classify_pair(rel, entity_types) is False


def test_should_classify_pair_skips_when_entity_a_is_place():
    rel = {"entity_a": "White Fang Mountains", "entity_b": "Celaena"}
    entity_types = {"White Fang Mountains": "PLACE", "Celaena": "PERSON"}
    assert _should_classify_pair(rel, entity_types) is False


def test_should_classify_pair_allows_unknown_type_entity():
    """If an entity is not in entity_types, default to allowing classification."""
    rel = {"entity_a": "Celaena", "entity_b": "Chaol"}
    assert _should_classify_pair(rel, {}) is True


def test_build_cooccurrence_graph_stores_at_most_one_context_per_chapter():
    """When the same pair co-appears multiple times in the same chapter, only one context is stored."""
    from scripts.relationship_extraction import build_cooccurrence_graph

    entities = [
        {"canonical_name": "Cain", "type": "PERSON", "aliases": [], "relevant": True},
        {"canonical_name": "Chaol", "type": "PERSON", "aliases": [], "relevant": True},
    ]
    # 5 sentences in same chapter, all with tight proximity (gap=0 or gap=1)
    # This would normally produce 3 contexts without per-chapter cap
    chapters = {"ch01": (
        "Cain faced Chaol. "
        "The hall was silent. "
        "Cain and Chaol exchanged glares. "
        "Someone else spoke. "
        "Cain watched Chaol leave."
    )}
    rels, _ = build_cooccurrence_graph(
        entities, chapters, window_size=3, min_cooccurrence=1, min_chapters_together=1
    )
    assert len(rels) == 1
    assert len(rels[0]["sample_contexts"]) == 1  # only 1 context from ch01


def test_is_negating_relationship_detects_it_wasnt_with():
    """'it wasn't with [name]' must be identified as a negation-of-relationship context."""
    from scripts.relationship_extraction import _is_negating_relationship
    assert _is_negating_relationship("Whatever Nehemia's involvement was, it wasn't with Cain.") is True


def test_is_negating_relationship_detects_nothing_to_do_with():
    from scripts.relationship_extraction import _is_negating_relationship
    assert _is_negating_relationship("Chaol had nothing to do with Dorian's scheme.") is True


def test_is_negating_relationship_does_not_filter_genuine_antagonism():
    """'Cain wasn't amused by Celaena' is an interaction — must NOT be filtered."""
    from scripts.relationship_extraction import _is_negating_relationship
    assert _is_negating_relationship("Cain wasn't amused by Celaena's performance.") is False


def test_build_cooccurrence_graph_excludes_negation_of_relationship_contexts():
    """Contexts explicitly negating a direct connection must be excluded from sample_contexts."""
    from scripts.relationship_extraction import build_cooccurrence_graph

    entities = [
        {"canonical_name": "Nehemia", "type": "PERSON", "aliases": [], "relevant": True},
        {"canonical_name": "Cain", "type": "PERSON", "aliases": [], "relevant": True},
    ]
    # Only evidence is a sentence that explicitly negates their relationship
    chapters = {"ch01": "Whatever Nehemia's involvement was, it wasn't with Cain."}
    rels, _ = build_cooccurrence_graph(
        entities, chapters, window_size=3, min_cooccurrence=1, min_chapters_together=1
    )
    # The pair may still co-occur, but must have 0 valid contexts
    for r in rels:
        if {r["entity_a"], r["entity_b"]} == {"Nehemia", "Cain"}:
            assert r["sample_contexts"] == [], (
                f"Negation context must be excluded, got: {r['sample_contexts']}"
            )


def test_run_studio_classifier_item_degrades_on_timeout():
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["studio"], timeout=30)):
        rel = {"entity_a": "A", "entity_b": "B", "sample_contexts": [], "cooccurrence_count": 1}
        result = _run_studio_classifier_item(rel, novel_summary="", additional_context="")
    assert result.get("error") == "studio_run_timeout"


def test_span_contains_both_returns_false_when_name_absent():
    """_span_contains_both must return False if either name is absent from span."""
    from scripts.relationship_extraction import _span_contains_both
    assert _span_contains_both("Chaol stood. Crown Prince entered.", "Chaol", "Crown Prince") is True
    assert _span_contains_both("Chaol stood. Crown Prince entered.", "Chaol", "Philippa") is False
    assert _span_contains_both("Chaol stood. Crown Prince entered.", "Elena", "Crown Prince") is False


def test_patch_datasets_pickler_py314_makes_signature_compatible():
    """On py3.14 with datasets < 4.4, the patch must make Pickler._batch_setitems
    accept the stdlib's (items, obj) call; it must no-op cleanly otherwise."""
    import inspect
    import sys as _sys

    import pytest as _pytest

    from scripts.relationship_extraction import _patch_datasets_pickler_py314

    _patch_datasets_pickler_py314()  # must never raise

    if _sys.version_info < (3, 14):
        return
    ds_dill = _pytest.importorskip("datasets.utils._dill")
    params = inspect.signature(ds_dill.Pickler._batch_setitems).parameters
    accepts_obj = len(params) > 2 or any(
        p.kind is inspect.Parameter.VAR_POSITIONAL for p in params.values()
    )
    assert accepts_obj, "Pickler._batch_setitems still incompatible with py3.14 pickle"


def test_pronouns_for_model_derives_language():
    """Pronoun set for coref must follow the book's language, not default to fr."""
    from scripts.relationship_extraction import _pronouns_for_model

    en = _pronouns_for_model("models/wiki-ner-en/model-best")
    assert "she" in en and "he" in en
    fr = _pronouns_for_model("fr_core_news_lg")
    assert "elle" in fr and "il" in fr


def test_process_chapter_clusters_english_pronouns():
    """An English pronoun in a cluster with a known entity is attributed to it."""
    from scripts.relationship_extraction import _process_chapter_clusters

    chunk = "Celaena walked into the hall. She smiled at Dorian."
    clusters = [[(0, 7), (30, 33)]]  # "Celaena", "She"
    out = _process_chapter_clusters(
        clusters, chunk, "ch01", {"celaena": "Celaena"}, frozenset({"she", "he"})
    )
    assert ("Celaena", "ch01", "She smiled at Dorian.") in out


# ---------------------------------------------------------------------------
# STU-536: the window slides over the chapter, in the chapter's order
# ---------------------------------------------------------------------------

def _stu536_chapter(pair_distance_sentences: int) -> str:
    """One chapter naming Alice, then Bob `pair_distance_sentences` sentences later."""
    filler = " ".join("The rain kept falling on the city." for _ in range(pair_distance_sentences - 1))
    return f"Alice crossed the courtyard. {filler} Bob locked the gate."


def _stu536_entities():
    return [
        {"canonical_name": "Alice", "type": "PERSON", "aliases": [], "relevant": True},
        {"canonical_name": "Bob", "type": "PERSON", "aliases": [], "relevant": True},
        {"canonical_name": "Cora", "type": "PERSON", "aliases": [], "relevant": True},
    ]


def test_graph_does_not_depend_on_entity_order():
    """The roster is a dict; its order carries no information about the book."""
    from scripts.relationship_extraction import build_cooccurrence_graph

    chapters = {
        "ch01": "Alice greeted Bob. Cora watched them from the stairs. Bob said nothing.",
        "ch02": "Cora found Alice alone. Alice asked about Bob. Bob never came.",
    }
    entities = _stu536_entities()

    def graph(roster):
        rels, _ = build_cooccurrence_graph(
            roster, chapters, window_size=5, min_cooccurrence=1, min_chapters_together=1
        )
        return [(r["entity_a"], r["entity_b"], r["cooccurrence_count"], r["sample_contexts"]) for r in rels]

    baseline = graph(entities)
    assert len(baseline) == 3, f"Expected the three pairs, got {baseline}"
    for permutation in ([2, 0, 1], [1, 2, 0], [2, 1, 0]):
        assert graph([entities[i] for i in permutation]) == baseline


def test_names_pages_apart_are_not_a_direct_interaction():
    """Adjacent in the window must mean adjacent in the chapter (STU-536)."""
    from scripts.relationship_extraction import build_cooccurrence_graph

    entities = _stu536_entities()[:2]
    far = {f"ch{i:02d}": _stu536_chapter(40) for i in range(1, 4)}
    rels, _ = build_cooccurrence_graph(
        entities, far, window_size=5, min_cooccurrence=1, min_chapters_together=1
    )
    assert rels == []

    near = {f"ch{i:02d}": _stu536_chapter(1) for i in range(1, 4)}
    rels, _ = build_cooccurrence_graph(
        entities, near, window_size=5, min_cooccurrence=1, min_chapters_together=1
    )
    assert [(r["entity_a"], r["entity_b"]) for r in rels] == [("Alice", "Bob")]


def test_coref_sentence_counts_the_entity_as_present():
    """A pronoun sentence coref attributed to an entity is co-presence, not a context."""
    from scripts.relationship_extraction import build_cooccurrence_graph

    entities = _stu536_entities()[:2]
    chapters = {f"ch{i:02d}": "Alice crossed the courtyard. She waved at Bob." for i in range(1, 4)}
    attributed = {"Alice": {f"ch{i:02d}": ["She waved at Bob."] for i in range(1, 4)}}

    rels, _ = build_cooccurrence_graph(
        entities, chapters, window_size=1, min_cooccurrence=1, min_chapters_together=1,
        mentions_by_entity=attributed,
    )
    assert [(r["entity_a"], r["entity_b"], r["cooccurrence_count"]) for r in rels] == []

    rels, _ = build_cooccurrence_graph(
        entities, chapters, window_size=2, min_cooccurrence=1, min_chapters_together=1,
        mentions_by_entity=attributed,
    )
    assert [(r["entity_a"], r["entity_b"]) for r in rels] == [("Alice", "Bob")]
