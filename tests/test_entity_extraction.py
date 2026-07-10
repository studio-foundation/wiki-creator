"""Tests for scripts/entity_extraction.py — spaCy NER stage."""
import pytest
import spacy
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.entity_extraction import (
    extract_entities, extract_context, split_entities, split_by_type,
    KEPT_LABELS, _is_valid_mention, FRONTMATTER_ID_PATTERNS, _truncate_mention,
    _get_min_mentions_absolute, filter_entities_by_min_mentions,
    _retag_entity_type_from_context, _infer_cue_words_language,
    _resolve_cue_words_language, _load_cue_words,
    _spacy_model_candidates, _load_spacy_model_with_fallback,
    _is_frontmatter_chapter, _ensure_sentencizer,
)


from _markers import requires_en_sm, requires_fr_lg


@pytest.fixture(scope="module")
def nlp():
    """Small English model for fast tests."""
    from _markers import spacy_model_available
    if not spacy_model_available("en_core_web_sm"):
        pytest.skip("requires spaCy model en_core_web_sm")
    return spacy.load("en_core_web_sm")


def test_extracts_person_entity(nlp):
    """A clearly named person should appear in the registry."""
    chapters = [
        {"id": "ch01", "title": "Chapter 1", "content": "Harry Potter lived at number four, Privet Drive. He was a wizard."}
    ]
    result = extract_entities(chapters, nlp)
    all_mentions = [
        m
        for entry in result["entities"].values()
        for m in entry["raw_mentions"]
    ]
    assert any("Harry" in m or "Potter" in m for m in all_mentions), (
        f"Expected a Harry/Potter mention, got: {all_mentions}"
    )


def test_filters_irrelevant_types(nlp):
    """DATE and CARDINAL entities should be excluded."""
    chapters = [
        {"id": "ch01", "title": "Chapter 1", "content": "It was January 1st, 2024. There were 42 chairs."}
    ]
    result = extract_entities(chapters, nlp)
    assert result["entities"] == {}, (
        f"Expected empty registry, got: {result['entities']}"
    )


def test_accumulates_cross_chapter(nlp):
    """Same surface form in two chapters → one registry entry with both chapters."""
    chapters = [
        {"id": "ch01", "title": "Chapter 1", "content": "Alice walked into the room and greeted everyone."},
        {"id": "ch02", "title": "Chapter 2", "content": "Alice sat down quietly by the window."},
    ]
    result = extract_entities(chapters, nlp)
    alice_entries = [
        entry for entry in result["entities"].values()
        if any("alice" in m.lower() for m in entry["raw_mentions"])
    ]
    assert len(alice_entries) == 1, f"Expected 1 Alice entry, got {len(alice_entries)}"
    entry = alice_entries[0]
    assert "ch01" in entry["mentions_by_chapter"], "ch01 should be in mentions_by_chapter"
    assert "ch02" in entry["mentions_by_chapter"], "ch02 should be in mentions_by_chapter"


def test_context_does_not_exceed_3_sentences(nlp):
    """Context extracted around an entity should be at most ~3 sentences."""
    content = (
        "The wind blew hard across the moor. "
        "Alice entered the grand hall and looked around. "
        "She noticed the paintings on the wall. "
        "The flames in the fireplace danced wildly. "
        "Nobody spoke a single word."
    )
    chapters = [{"id": "ch01", "title": "Chapter 1", "content": content}]
    result = extract_entities(chapters, nlp)
    for entry in result["entities"].values():
        for contexts in entry["mentions_by_chapter"].values():
            for ctx in contexts:
                approx_sentences = ctx.count(". ") + ctx.count("! ") + ctx.count("? ") + 1
                assert approx_sentences <= 4, (
                    f"Context has too many sentences ({approx_sentences}): {ctx!r}"
                )


def test_no_raw_chapter_content_in_registry(nlp):
    """No registry value should equal the full chapter content."""
    content = (
        "Sherlock Holmes walked down Baker Street in the fog. "
        "He turned his collar up against the chill. "
        "Watson followed close behind."
    )
    chapters = [{"id": "ch01", "title": "Chapter 1", "content": content}]
    result = extract_entities(chapters, nlp)
    for entry in result["entities"].values():
        for contexts in entry["mentions_by_chapter"].values():
            for ctx in contexts:
                assert ctx != content, (
                    f"Context must not be the full chapter text. Got: {ctx!r}"
                )


def test_frontmatter_detection_matches_author_or_ack_titles():
    assert _is_frontmatter_chapter({"id": "author.xhtml", "title": "Author"}) is True
    assert _is_frontmatter_chapter({"id": "misc.xhtml", "title": "Acknowledgements"}) is True
    assert _is_frontmatter_chapter({"id": "c01.xhtml", "title": "Chapter 1"}) is False


@pytest.mark.parametrize(
    "chapter",
    [
        {"id": "sinopsis.xhtml", "title": "sinopsis.xhtml"},
        {"id": "info.xhtml", "title": "info.xhtml"},
        {"id": "dedicatoria.xhtml", "title": "dedicatoria.xhtml"},
        {"id": "autor.xhtml", "title": "Author"},
    ],
)
def test_frontmatter_detection_matches_localized_metadata_chapters(chapter):
    assert _is_frontmatter_chapter(chapter) is True


def test_entity_ids_are_sequential(nlp):
    """Entity IDs should be entity_001, entity_002, etc."""
    chapters = [
        {
            "id": "ch01",
            "title": "Chapter 1",
            "content": "Elizabeth Bennet met Mr. Darcy at the ball in London.",
        }
    ]
    result = extract_entities(chapters, nlp)
    ids = sorted(result["entities"].keys())
    for i, entity_id in enumerate(ids, start=1):
        assert entity_id == f"entity_{i:03d}", f"Expected entity_{i:03d}, got {entity_id}"


def test_first_seen_is_correct(nlp):
    """first_seen should be the chapter ID where the entity first appears."""
    chapters = [
        {"id": "ch01", "title": "Chapter 1", "content": "Sherlock Holmes visited London on a grey morning."},
        {"id": "ch02", "title": "Chapter 2", "content": "Sherlock Holmes walked through London again the next day."},
    ]
    result = extract_entities(chapters, nlp)
    london_entries = [
        entry for entry in result["entities"].values()
        if any("london" in m.lower() for m in entry["raw_mentions"])
    ]
    assert len(london_entries) >= 1, "London should be recognized as a GPE entity"
    assert london_entries[0]["first_seen"] == "ch01"


def test_entity_type_is_included(nlp):
    """Each entity entry should have a type field."""
    chapters = [
        {"id": "ch01", "title": "Chapter 1", "content": "Alice walked into London."}
    ]
    result = extract_entities(chapters, nlp)
    for entry in result["entities"].values():
        assert "type" in entry, f"Missing 'type' field in entry: {entry}"
        assert entry["type"] in {"PERSON", "PLACE", "ORG", "EVENT", "OTHER"}


def test_retags_place_from_context():
    entity = {
        "type": "PERSON",
        "raw_mentions": ["Endovier"],
        "mentions_by_chapter": {
            "ch01": [
                "Celaena was imprisoned in Endovier for one year.",
                "Endovier was a brutal labor camp in Adarlan.",
            ]
        },
    }
    assert _retag_entity_type_from_context(entity) == "PLACE"


def test_retags_event_from_context():
    entity = {
        "type": "PERSON",
        "raw_mentions": ["Yulemas"],
        "mentions_by_chapter": {
            "ch01": [
                "The court announced the Yulemas ball at dusk.",
                "She woke on Yulemas morning to church bells.",
            ]
        },
    }
    assert _retag_entity_type_from_context(entity) == "EVENT"


@pytest.mark.parametrize(
    ("name", "source_type", "contexts"),
    [
        (
            "Dorian",
            "ORG",
            ["Prince Dorian said nothing and looked away."],
        ),
        (
            "Nehemia",
            "ORG",
            ["Princess Nehemia asked Celaena to train with her."],
        ),
        (
            "Cain",
            "ORG",
            ["Cain said he would win the duel."],
        ),
        (
            "Kaltain",
            "PLACE",
            ["Lady Kaltain smiled and walked toward the prince."],
        ),
    ],
)
def test_retags_org_or_place_to_person_from_context(name, source_type, contexts):
    entity = {
        "type": source_type,
        "raw_mentions": [name],
        "mentions_by_chapter": {"ch01": contexts},
    }
    assert _retag_entity_type_from_context(entity) == "PERSON"


def test_infer_cue_words_language_from_spacy_model():
    assert _infer_cue_words_language("fr_core_news_lg") == "fr"
    assert _infer_cue_words_language("fr_core_news_sm") == "fr"
    assert _infer_cue_words_language("en_core_web_sm") == "en"


def test_resolve_cue_words_language_auto():
    assert _resolve_cue_words_language("fr_core_news_lg", "auto") == "fr"
    assert _resolve_cue_words_language("en_core_web_sm", None) == "en"


def test_load_cue_words_all_merges_languages():
    cues = _load_cue_words("all")
    assert "in" in cues["place_prepositions"]      # EN
    assert "dans" in cues["place_prepositions"]    # FR


# --- split_entities tests ---

def test_split_entities_for_resolution_has_no_mentions_by_chapter(nlp):
    """entities_for_resolution must not include mentions_by_chapter."""
    chapters = [
        {"id": "ch01", "title": "Chapter 1", "content": "Alice walked into London."}
    ]
    result = extract_entities(chapters, nlp)
    entities_for_resolution, _ = split_entities(result["entities"])
    for entry in entities_for_resolution.values():
        assert "mentions_by_chapter" not in entry, (
            f"entities_for_resolution must not contain mentions_by_chapter: {entry}"
        )


def test_split_entities_full_has_mentions_by_chapter(nlp):
    """entities_full must include mentions_by_chapter."""
    chapters = [
        {"id": "ch01", "title": "Chapter 1", "content": "Alice walked into London."}
    ]
    result = extract_entities(chapters, nlp)
    _, entities_full = split_entities(result["entities"])
    for entry in entities_full.values():
        assert "mentions_by_chapter" in entry, (
            f"entities_full must contain mentions_by_chapter: {entry}"
        )


def test_split_entities_same_keys(nlp):
    """Both split outputs must have the same entity IDs."""
    chapters = [
        {"id": "ch01", "title": "Chapter 1", "content": "Sherlock Holmes visited Watson in London."}
    ]
    result = extract_entities(chapters, nlp)
    entities_for_resolution, entities_full = split_entities(result["entities"])
    assert set(entities_for_resolution.keys()) == set(entities_full.keys())


def test_split_entities_for_resolution_has_core_fields(nlp):
    """entities_for_resolution entries must have type, raw_mentions, and first_seen."""
    chapters = [
        {"id": "ch01", "title": "Chapter 1", "content": "Elizabeth Bennet met Mr. Darcy in London."}
    ]
    result = extract_entities(chapters, nlp)
    entities_for_resolution, _ = split_entities(result["entities"])
    for entity_id, entry in entities_for_resolution.items():
        assert "type" in entry, f"[{entity_id}] missing 'type'"
        assert "raw_mentions" in entry, f"[{entity_id}] missing 'raw_mentions'"
        assert "first_seen" in entry, f"[{entity_id}] missing 'first_seen'"


# --- --test mode integration test ---

@requires_en_sm
def test_test_mode_exits_successfully():
    """python scripts/entity_extraction.py --test should exit 0 and print a summary."""
    import subprocess
    result = subprocess.run(
        [sys.executable, "scripts/entity_extraction.py", "--test"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"--test mode failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    assert "Total entities extracted:" in result.stdout, (
        f"Expected entity count in output. Got:\n{result.stdout}"
    )
    assert "Sample (first 3 entities" in result.stdout, (
        f"Expected entity sample in output. Got:\n{result.stdout}"
    )

# --- _is_valid_mention filter tests ---


def test_is_valid_mention_rejects_too_short():
    assert _is_valid_mention("E") is False
    assert _is_valid_mention("Me") is False
    assert _is_valid_mention("II") is False
    assert _is_valid_mention("Ah") is False
    assert _is_valid_mention("Or") is False


def test_is_valid_mention_rejects_lowercase_start():
    assert _is_valid_mention("objectai") is False
    assert _is_valid_mention("plaidais-je") is False


def test_is_valid_mention_rejects_non_alpha_start():
    """Dash-prefixed dialog fragments like '— Liberté' must be rejected."""
    assert _is_valid_mention("— Liberté") is False
    assert _is_valid_mention("  ") is False


def test_is_valid_mention_accepts_valid_names():
    assert _is_valid_mention("David Martín") is True
    assert _is_valid_mention("Barcelone") is True
    assert _is_valid_mention("Sainte-Croix") is True
    assert _is_valid_mention("Balthazar") is True
    assert _is_valid_mention("Don Basilio") is True


# --- Frontmatter chapter skip tests ---


def test_frontmatter_patterns_exist():
    """The module must export a frozenset of lowercase frontmatter patterns."""
    assert isinstance(FRONTMATTER_ID_PATTERNS, (set, frozenset))
    assert "titlepage" in FRONTMATTER_ID_PATTERNS


def test_skips_titlepage_chapter(nlp):
    """Entities from a Titlepage.xhtml chapter must not appear in the registry."""
    chapters = [
        {"id": "Titlepage.xhtml", "title": "Title Page",
         "content": "Harry Potter is a renowned wizard from England."},
        {"id": "ch01", "title": "Chapter 1",
         "content": "Harry Potter walked through London on a cold morning."},
    ]
    result = extract_entities(chapters, nlp)
    for entry in result["entities"].values():
        assert "Titlepage.xhtml" not in entry["mentions_by_chapter"], (
            f"Frontmatter chapter leaked into registry: {entry}"
        )


def test_skips_cover_chapter(nlp):
    """Chapter IDs that include 'cover' are also frontmatter."""
    chapters = [
        {"id": "cover.xhtml", "title": "Cover",
         "content": "Alice Liddell discovered a magical land called Wonderland."},
    ]
    result = extract_entities(chapters, nlp)
    assert result["entities"] == {}, (
        f"Cover chapter should produce no entities, got: {result['entities']}"
    )


def test_non_frontmatter_chapter_not_skipped(nlp):
    """Normal chapter IDs must still be processed."""
    chapters = [
        {"id": "chapter01.xhtml", "title": "Chapter 1",
         "content": "Alice walked into London and met Harry Potter."},
    ]
    result = extract_entities(chapters, nlp)
    assert result["entities"] != {}, "Normal chapter should not be skipped"


# --- split_by_type tests ---

def test_split_by_type_separates_by_type(nlp):
    """split_by_type must return separate dicts for PERSON, PLACE, ORG, EVENT."""
    chapters = [
        {"id": "ch01", "title": "Chapter 1", "content": "Alice walked into London and met the Royal Society."}
    ]
    result = extract_entities(chapters, nlp)
    _, entities_full = split_entities(result["entities"])
    by_type = split_by_type(entities_full)

    assert "PERSON" in by_type
    assert "PLACE" in by_type
    assert "ORG" in by_type
    assert "EVENT" in by_type


def test_split_by_type_entities_are_in_correct_bucket(nlp):
    """Every entity in a bucket must have the matching type."""
    chapters = [
        {"id": "ch01", "title": "Chapter 1", "content": "Alice walked into London and met the Royal Society."}
    ]
    result = extract_entities(chapters, nlp)
    _, entities_full = split_entities(result["entities"])
    by_type = split_by_type(entities_full)

    for type_key in ("PERSON", "PLACE", "ORG", "EVENT"):
        for entity_id, entity in by_type[type_key].items():
            assert entity["type"] == type_key, (
                f"[{entity_id}] is in bucket {type_key!r} but has type={entity['type']!r}"
            )


def test_split_by_type_covers_all_entities(nlp):
    """All entities from entities_full must appear in exactly one bucket (no drops, no duplicates)."""
    chapters = [
        {"id": "ch01", "title": "Chapter 1", "content": "Alice walked into London and met the Royal Society."}
    ]
    result = extract_entities(chapters, nlp)
    _, entities_full = split_entities(result["entities"])
    by_type = split_by_type(entities_full)

    all_bucket_ids: set[str] = set()
    total_count = 0
    for bucket in by_type.values():
        all_bucket_ids |= set(bucket.keys())
        total_count += len(bucket)

    known_types = {e["type"] for e in entities_full.values()} & {"PERSON", "PLACE", "ORG", "EVENT"}
    expected_ids = {
        eid for eid, e in entities_full.items() if e["type"] in known_types
    }
    assert all_bucket_ids == expected_ids, f"Bucket IDs don't match expected: {all_bucket_ids ^ expected_ids}"
    assert total_count == len(expected_ids), (
        f"Duplicate entities across buckets: total_count={total_count} but expected {len(expected_ids)} unique entities"
    )


def test_split_by_type_entities_retain_mentions_by_chapter(nlp):
    """Entities in each bucket must still have mentions_by_chapter."""
    chapters = [
        {"id": "ch01", "title": "Chapter 1", "content": "Alice walked into London."}
    ]
    result = extract_entities(chapters, nlp)
    _, entities_full = split_entities(result["entities"])
    by_type = split_by_type(entities_full)

    assert any(len(b) > 0 for b in by_type.values()), (
        "Expected at least one entity to be classified into a bucket"
    )
    for bucket in by_type.values():
        for entity_id, entity in bucket.items():
            assert "mentions_by_chapter" in entity, (
                f"[{entity_id}] missing mentions_by_chapter in split_by_type output"
            )


# --- FALSE_POSITIVE_WORDS / stoplist tests ---


def test_false_positive_words_is_frozenset():
    """FALSE_POSITIVE_WORDS doit être un frozenset exportable."""
    from scripts.entity_extraction import FALSE_POSITIVE_WORDS  # fails until Task 2 is implemented
    assert isinstance(FALSE_POSITIVE_WORDS, frozenset)
    assert len(FALSE_POSITIVE_WORDS) > 0


def test_is_valid_mention_rejects_stoplist_words():
    """Les mots de la stoplist, seuls, doivent être rejetés."""
    from scripts.entity_extraction import FALSE_POSITIVE_WORDS  # noqa: F401 — ensures symbol exists
    assert _is_valid_mention("Cher") is False
    assert _is_valid_mention("Chère") is False
    assert _is_valid_mention("Monsieur") is False
    assert _is_valid_mention("Madame") is False
    assert _is_valid_mention("Bonjour") is False
    assert _is_valid_mention("Merci") is False
    assert _is_valid_mention("Adieu") is False


def test_is_valid_mention_allows_multiword_with_stoplist_root():
    """Les entités multi-mots contenant un mot de la stoplist doivent passer."""
    from scripts.entity_extraction import FALSE_POSITIVE_WORDS  # noqa: F401 — ensures symbol exists
    assert _is_valid_mention("Le Cher") is True
    assert _is_valid_mention("Monsieur Lefebvre") is True
    assert _is_valid_mention("Département du Cher") is True


def test_is_valid_mention_case_insensitive_check():
    """Le check stoplist doit être insensible à la casse."""
    from scripts.entity_extraction import FALSE_POSITIVE_WORDS  # noqa: F401 — ensures symbol exists
    assert _is_valid_mention("CHER") is False
    assert _is_valid_mention("bonjour") is False


def test_is_valid_mention_rejects_collapsed_first_person_artifacts():
    assert _is_valid_mention("Isuppose") is False
    assert _is_valid_mention("Iknew") is False
    assert _is_valid_mention("Iwin") is False
    assert _is_valid_mention("Isee") is False
    assert _is_valid_mention("Iwould") is False
    assert _is_valid_mention("Ilike") is False


def test_is_valid_mention_rejects_coordinated_duo_mentions():
    assert _is_valid_mention("Celaena and Chaol") is False
    assert _is_valid_mention("Celaena et Chaol") is False


# --- _truncate_mention tests ---


def test_truncate_mention_drops_trailing_lowercase_tokens(nlp):
    """Trailing lowercase tokens are dropped."""
    doc = nlp("She visited New York city streets yesterday.")
    start = next(i for i, t in enumerate(doc) if t.text == "New")
    # Find "city" as the last token to include (non-proper)
    york_idx = next(i for i, t in enumerate(doc) if t.text == "York")
    city_idx = york_idx + 1  # "city"
    span = doc[start:city_idx + 1]  # "New York city"
    result = _truncate_mention(span)
    assert "city" not in result, f"Expected 'city' to be dropped, got {result!r}"
    assert "New" in result, f"Expected 'New' to be in result, got {result!r}"


def test_truncate_mention_keeps_multiword_proper_noun(nlp):
    """Un nom propre multi-mots sans queue est retourné intact."""
    doc = nlp("I met Victor Hugo yesterday.")
    start = next(i for i, t in enumerate(doc) if t.text == "Victor")
    end = next(i for i, t in enumerate(doc) if t.text == "Hugo") + 1
    span = doc[start:end]
    result = _truncate_mention(span)
    assert result == "Victor Hugo", f"Expected 'Victor Hugo', got {result!r}"


def test_truncate_mention_single_token(nlp):
    """Un span d'un seul token propre est retourné tel quel."""
    doc = nlp("Alice smiled.")
    span = doc[0:1]  # "Alice"
    result = _truncate_mention(span)
    assert result == "Alice", f"Expected 'Alice', got {result!r}"


def test_truncate_mention_all_lowercase_returns_full(nlp):
    """Si aucun token n'est title/PROPN, retourner le span complet (cas dégénéré)."""
    doc = nlp("the quick brown fox.")
    span = doc[0:4]
    result = _truncate_mention(span)
    # Pas de token propre → retourne tout (comportement de fallback)
    assert result == span.text


def test_save_chapters_json_writes_chapter_texts(tmp_path):
    """save_chapters_json must write chapter id → content mapping."""
    import json
    from scripts.entity_extraction import save_chapters_json

    chapters = [
        {"id": "ch01", "title": "Ch 1", "content": "Hello world."},
        {"id": "ch02", "title": "Ch 2", "content": "Goodbye world."},
    ]
    out = tmp_path / "chapters.json"
    save_chapters_json(chapters, path=str(out))

    data = json.loads(out.read_text())
    assert data == {"chapters": {"ch01": "Hello world.", "ch02": "Goodbye world."}}


@requires_fr_lg
def test_pos_filter_rejects_verb_at_sentence_start():
    """Capitalized French verb at dialogue start must not appear as entity."""
    nlp = spacy.load("fr_core_news_lg")
    chapters = [
        {
            "id": "ch01",
            "content": (
                "Pedro Vidal tendit le manuscrit à Martín. "
                "— Regarde, il est là. "
                "— Avez-vous lu ce chapitre ? "
                "— Sériez-vous d'accord ?"
            ),
        }
    ]
    result = extract_entities(chapters, nlp)
    raw_mentions = [
        m
        for e in result["entities"].values()
        for m in e["raw_mentions"]
    ]
    assert "Regarde" not in raw_mentions
    assert "Avez" not in raw_mentions
    assert "Sériez" not in raw_mentions
    # True entities must survive
    assert any("Vidal" in m or "Martín" in m for m in raw_mentions)


@requires_en_sm
def test_main_exits_on_empty_entities():
    """main() must exit 1 with error JSON when no entities are extracted."""
    import subprocess
    import json as _json
    env = os.environ.copy()
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    env["PYTHONPATH"] = (
        f"{repo_root}:{env['PYTHONPATH']}" if env.get("PYTHONPATH") else repo_root
    )

    # Chapters whose content produces zero named entities (no PERSON/PLACE/ORG)
    payload = _json.dumps({
        "additional_context": "spacy_model: en_core_web_sm",
        "previous_outputs": {
            "epub-parse": {
                "title": "Test",
                "author": None,
                "chapters": [
                    {"id": "ch01", "title": "Ch1", "content": "It was 42 degrees. The year was 1900."},
                ],
            }
        },
    })
    result = subprocess.run(
        [sys.executable, "scripts/entity_extraction.py"],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert result.returncode == 1, f"Expected exit 1, got {result.returncode}. stdout={result.stdout}"
    output = _json.loads(result.stdout)
    assert "error" in output, f"Expected error field in output: {output}"
    assert "no entities" in output["error"].lower(), f"Unexpected error message: {output['error']}"


def test_get_min_mentions_absolute_defaults_to_3():
    assert _get_min_mentions_absolute({}) == 3


def test_get_min_mentions_absolute_accepts_valid_int():
    assert _get_min_mentions_absolute({"min_mentions_absolute": 1}) == 1
    assert _get_min_mentions_absolute({"min_mentions_absolute": 3}) == 3
    assert _get_min_mentions_absolute({"min_mentions_absolute": 10}) == 10


def test_get_min_mentions_absolute_invalid_falls_back_and_warns(capsys):
    assert _get_min_mentions_absolute({"min_mentions_absolute": "abc"}) == 3
    captured = capsys.readouterr()
    assert "invalid min_mentions_absolute" in captured.err

    assert _get_min_mentions_absolute({"min_mentions_absolute": -1}) == 3
    captured = capsys.readouterr()
    assert "invalid min_mentions_absolute" in captured.err

    assert _get_min_mentions_absolute({"min_mentions_absolute": True}) == 3
    captured = capsys.readouterr()
    assert "invalid min_mentions_absolute" in captured.err


def test_filter_entities_by_min_mentions_excludes_below_threshold():
    entities_full = {
        "entity_001": {"type": "PERSON", "mention_count": 1, "mentions_by_chapter": {"ch01": ["m1"]}},
        "entity_002": {"type": "PERSON", "mention_count": 3, "mentions_by_chapter": {"ch01": ["m1", "m2", "m3"]}},
        "entity_003": {"type": "PLACE", "mention_count": 5, "mentions_by_chapter": {"ch01": ["m1", "m2", "m3"]}},
    }
    filtered = filter_entities_by_min_mentions(entities_full, min_mentions_absolute=3)
    assert set(filtered.keys()) == {"entity_002", "entity_003"}


def test_spacy_model_candidates_for_english_adds_sm_fallback():
    assert _spacy_model_candidates("en_core_web_lg") == ["en_core_web_lg", "en_core_web_sm"]


def test_load_spacy_model_with_fallback_uses_second_candidate():
    calls = []

    def fake_load(model_name):
        calls.append(model_name)
        if model_name == "en_core_web_lg":
            raise OSError("missing model")
        if model_name == "en_core_web_sm":
            return {"model": model_name}
        raise OSError("unexpected model")

    nlp, loaded = _load_spacy_model_with_fallback(fake_load, "en_core_web_lg")
    assert loaded == "en_core_web_sm"
    assert nlp == {"model": "en_core_web_sm"}
    assert calls == ["en_core_web_lg", "en_core_web_sm"]


def test_ensure_sentencizer_adds_sentencizer_when_missing():
    """A model with no sentence segmenter should get a sentencizer added."""
    nlp = spacy.blank("en")
    assert "sentencizer" not in nlp.pipe_names
    assert "parser" not in nlp.pipe_names
    _ensure_sentencizer(nlp)
    assert "sentencizer" in nlp.pipe_names


@requires_en_sm
def test_ensure_sentencizer_skips_when_parser_present():
    """A model with a parser already sets sentence boundaries — don't add sentencizer."""
    nlp = spacy.load("en_core_web_sm")
    assert "parser" in nlp.pipe_names
    _ensure_sentencizer(nlp)
    assert "sentencizer" not in nlp.pipe_names


def test_ensure_sentencizer_allows_doc_sents(nlp):
    """After _ensure_sentencizer, doc.sents must not raise E030."""
    nlp_blank = spacy.blank("en")
    _ensure_sentencizer(nlp_blank)
    doc = nlp_blank("Bilbo walked. Frodo ran.")
    sents = list(doc.sents)  # must not raise
    assert len(sents) >= 1


@requires_en_sm
def test_main_writes_only_entities_meeting_min_mentions_threshold(tmp_path):
    """main() should exclude low-mention entities from persons_full.json."""
    import json as _json
    import subprocess
    env = os.environ.copy()
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    env["PYTHONPATH"] = (
        f"{repo_root}:{env['PYTHONPATH']}" if env.get("PYTHONPATH") else repo_root
    )

    book_yaml = tmp_path / "library" / "author" / "series" / "books" / "book.yaml"
    book_yaml.parent.mkdir(parents=True, exist_ok=True)
    book_yaml.write_text("description: test", encoding="utf-8")

    payload = _json.dumps({
        "additional_context": (
            f"file_path: {book_yaml}\n"
            "spacy_model: en_core_web_sm\n"
            "min_mentions_absolute: 3\n"
        ),
        "previous_outputs": {
            "epub-parse": {
                "title": "Test",
                "author": None,
                "chapters": [
                    {
                        "id": "ch01",
                        "title": "Ch1",
                        "content": "Alice met Bob. Alice smiled. Alice waved.",
                    },
                ],
            }
        },
    })

    result = subprocess.run(
        [sys.executable, "scripts/entity_extraction.py"],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert result.returncode == 0, f"Expected exit 0, got {result.returncode}. stderr={result.stderr}"

    processing = book_yaml.parent.parent / "processing_output" / "book"
    persons_data = _json.loads((processing / "persons_full.json").read_text(encoding="utf-8"))
    all_mentions = [
        mention
        for entity in persons_data["persons_full"].values()
        for mention in entity.get("raw_mentions", [])
    ]
    assert any("Alice" in mention for mention in all_mentions), f"Expected Alice in {all_mentions}"
    assert all("Bob" not in mention for mention in all_mentions), f"Bob should be filtered out: {all_mentions}"


# --- Word-boundary cue matching in _retag_entity_type_from_context ---
# Substring matching used to retag every protagonist of place-heavy prose
# ('sea' hit 'seawall', 'port' hit 'Port Saffron', 'miss' hit 'mission').


def test_retag_place_cue_requires_whole_word():
    """'seawall'/'important' must not fire the 'sea'/'port' place cues."""
    entity = {
        "type": "PERSON",
        "raw_mentions": ["Elias Thorn"],
        "mentions_by_chapter": {
            "ch01": [
                "Elias Thorn walked along the seawall at dusk.",
                "Elias Thorn made an important decision that night.",
            ]
        },
    }
    assert _retag_entity_type_from_context(entity) == "PERSON"


def test_retag_place_cue_standalone_word_still_fires():
    entity = {
        "type": "PERSON",
        "raw_mentions": ["Endovier"],
        "mentions_by_chapter": {
            "ch01": [
                "The sea surrounded Endovier on three sides.",
                "Endovier was a camp carved into the mountains.",
            ]
        },
    }
    assert _retag_entity_type_from_context(entity) == "PLACE"


def test_retag_person_cue_requires_whole_word():
    """'mission' must not fire the 'miss' person cue on an ORG."""
    entity = {
        "type": "ORG",
        "raw_mentions": ["Salt Guild"],
        "mentions_by_chapter": {
            "ch01": ["The Salt Guild gave them a mission along the coast."]
        },
    }
    assert _retag_entity_type_from_context(entity) == "ORG"


def test_retag_mention_match_requires_whole_word():
    """Mention 'Vale' must not match inside 'valeur'-like words."""
    entity = {
        "type": "PERSON",
        "raw_mentions": ["Vale"],
        "mentions_by_chapter": {
            # 'vale' appears only inside 'valentine'; the standalone city
            # cue in the same sentence must therefore not score.
            "ch01": ["The valentine card mentioned a city far away."]
        },
    }
    assert _retag_entity_type_from_context(entity) == "PERSON"
