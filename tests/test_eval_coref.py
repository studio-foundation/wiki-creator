"""Unit tests for the coref evaluation harness (STU-427). Pure functions only."""
import scripts.eval_coref as ec

BASELINE_MENTIONS = {
    "Celaena": {"ch01": ["Celaena walked."], "ch02": ["Celaena fought."]},
    "Dorian": {"ch01": ["Dorian watched."]},
}
VARIANT_MENTIONS = {
    "Celaena": {"ch01": ["Celaena walked.", "She smiled."], "ch02": ["Celaena fought."]},
    "Dorian": {"ch01": ["Dorian watched.", "He laughed.", "He left."]},
    "Chaol": {"ch03": ["He trained."]},
}


def test_count_sentences():
    assert ec.count_sentences(BASELINE_MENTIONS) == 3
    assert ec.count_sentences(VARIANT_MENTIONS) == 7


def test_compute_mention_deltas():
    deltas = ec.compute_mention_deltas(BASELINE_MENTIONS, VARIANT_MENTIONS)
    assert deltas["total_added"] == 4
    assert deltas["per_entity"][0] == ("Dorian", 2)  # sorted desc by added
    assert ("Chaol", 1) in deltas["per_entity"]


def test_relationship_key_is_order_insensitive():
    a = {"entity_a": "Celaena", "entity_b": "Dorian"}
    b = {"entity_a": "Dorian", "entity_b": "Celaena"}
    assert ec.relationship_key(a) == ec.relationship_key(b)


def test_compute_relationship_deltas():
    base = [
        {"entity_a": "Celaena", "entity_b": "Dorian", "cooccurrence_count": 5},
        {"entity_a": "Celaena", "entity_b": "Nehemia", "cooccurrence_count": 3},
    ]
    var = [
        {"entity_a": "Dorian", "entity_b": "Celaena", "cooccurrence_count": 9},
        {"entity_a": "Celaena", "entity_b": "Chaol", "cooccurrence_count": 4},
    ]
    d = ec.compute_relationship_deltas(base, var)
    assert [ec.relationship_key(r) for r in d["added"]] == [("Celaena", "Chaol")]
    assert [ec.relationship_key(r) for r in d["removed"]] == [("Celaena", "Nehemia")]
    assert d["reweighted"] == [{"pair": ("Celaena", "Dorian"), "before": 5, "after": 9}]


def test_new_sentences_only_additions():
    added = ec.new_sentences(BASELINE_MENTIONS, VARIANT_MENTIONS)
    sentences = {a["sentence"] for a in added}
    assert sentences == {"She smiled.", "He laughed.", "He left.", "He trained."}
    for a in added:
        assert set(a) == {"entity", "chapter_id", "sentence"}


def test_sample_new_sentences_seeded_and_capped():
    s1 = ec.sample_new_sentences(BASELINE_MENTIONS, VARIANT_MENTIONS, n=2, seed=42)
    s2 = ec.sample_new_sentences(BASELINE_MENTIONS, VARIANT_MENTIONS, n=2, seed=42)
    assert s1 == s2
    assert len(s1) == 2
    everything = ec.sample_new_sentences(BASELINE_MENTIONS, VARIANT_MENTIONS, n=99, seed=1)
    assert len(everything) == 4


def test_extract_context_windows_around_sentence():
    text = "A" * 300 + " He laughed. " + "B" * 300
    ctx = ec.extract_context(text, "He laughed.", radius=50)
    assert "He laughed." in ctx
    assert len(ctx) <= 50 * 2 + len("He laughed.") + 2  # ellipsis margin


def test_extract_context_falls_back_when_absent():
    assert ec.extract_context("some chapter", "Missing sentence.") == "Missing sentence."


def test_parse_time_v():
    stderr = (
        "\tCommand being timed: \"python x\"\n"
        "\tMaximum resident set size (kbytes): 3145728\n"
        "\tExit status: 0\n"
    )
    assert ec.parse_time_v(stderr) == {"peak_rss_kb": 3145728}
    assert ec.parse_time_v("no match") == {"peak_rss_kb": None}


def test_render_report_contains_tables():
    results = {
        "coref-8k": {
            "wall_seconds": 62.1,
            "peak_rss_kb": 3145728,
            "pronoun_sentences_added": 4,
            "mention_deltas": {"total_added": 4, "per_entity": [("Dorian", 2), ("Celaena", 1), ("Chaol", 1)]},
            "relationship_deltas": {"added": [{"entity_a": "Celaena", "entity_b": "Chaol", "cooccurrence_count": 4}], "removed": [], "reweighted": []},
        },
    }
    report = ec.render_report("01-throne-of-glass", results)
    assert "coref-8k" in report
    assert "Dorian" in report
    assert "3.0 GB" in report


def test_render_sample_has_checkbox_column():
    samples = {"coref-8k": [{"entity": "Dorian", "chapter_id": "ch01", "sentence": "He laughed."}]}
    chapters = {"ch01": "Dorian watched. He laughed. He left."}
    md = ec.render_sample(samples, chapters)
    assert "He laughed." in md
    assert "✓/✗" in md
    assert "Dorian" in md


def test_variant_output_dir_layout(tmp_path):
    d = ec.variant_dir(tmp_path, "coref-8k")
    assert d == tmp_path / "coref_eval" / "coref-8k"


def test_build_child_command_uses_time_v(monkeypatch):
    monkeypatch.setattr(ec.shutil, "which", lambda name: "/usr/bin/time" if name == "time" else None)
    cmd = ec.build_child_command("coref-8k", "book.yaml", workers=4)
    assert cmd[:2] == ["/usr/bin/time", "-v"]
    assert "--variant-run" in cmd and "coref-8k" in cmd
    assert cmd[cmd.index("--workers") + 1] == "4"


def test_build_child_command_without_gnu_time(monkeypatch):
    monkeypatch.setattr(ec.shutil, "which", lambda name: None)
    cmd = ec.build_child_command("baseline", "book.yaml", workers=1)
    assert cmd[0].endswith("python") or "python" in cmd[0]
    assert "/usr/bin/time" not in cmd
