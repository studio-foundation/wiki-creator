import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from build_corpus import build, narrative_chapters  # noqa: E402


def chapters():
    return [
        {"id": "id_4", "title": "Copyright", "content": "x" * 2000},
        {"id": "id_7", "title": "Prologue", "content": "Sentence one. " * 400},
        {"id": "spam", "title": "spam", "content": "y" * 100},
        {"id": "id_8", "title": "Discovery", "content": "Sentence two. " * 400},
        {"id": "id_68", "title": "Glossary", "content": "z" * 2000},
    ]


def test_id_range_cuts_front_and_back_matter():
    kept = narrative_chapters(chapters(), "id_7", "id_8", min_chars=1000)
    assert [c["id"] for c in kept] == ["id_7", "id_8"]


def test_min_chars_cuts_interleaved_filler():
    kept = narrative_chapters(chapters(), "id_7", "id_8", min_chars=1000)
    assert "spam" not in [c["id"] for c in kept]


def test_unknown_chapter_id_exits():
    with pytest.raises(SystemExit):
        narrative_chapters(chapters(), "id_999", "id_8", min_chars=1000)


def test_inverted_range_exits():
    with pytest.raises(SystemExit):
        narrative_chapters(chapters(), "id_8", "id_7", min_chars=1000)


def test_same_seed_gives_same_corpus():
    kept = narrative_chapters(chapters(), "id_7", "id_8", min_chars=1000)
    assert build(kept, 5, seed=42) == build(kept, 5, seed=42)


def test_different_seed_gives_different_corpus():
    kept = narrative_chapters(chapters(), "id_7", "id_8", min_chars=1000)
    assert build(kept, 5, seed=42) != build(kept, 5, seed=7)


def test_asking_for_more_chunks_than_exist_returns_the_whole_pool():
    kept = narrative_chapters(chapters(), "id_7", "id_8", min_chars=1000)
    everything = build(kept, 10_000, seed=42)
    assert build(kept, len(everything), seed=1) == everything


def test_chunk_ids_are_unique_and_carry_provenance():
    kept = narrative_chapters(chapters(), "id_7", "id_8", min_chars=1000)
    corpus = build(kept, 10, seed=42)
    assert len({r["id"] for r in corpus}) == len(corpus)
    assert all(r["id"].startswith(r["chapter_id"] + ":") for r in corpus)
