import json

import pytest

from wiki_creator.lang import (
    OPTIONAL_KEYS,
    REQUIRED_KEYS,
    LangPackError,
    book_language,
    infer_language,
    load_lang_config,
)


def test_infer_language_fr():
    assert infer_language("fr_core_news_lg") == "fr"
    assert infer_language("fr_core_news_sm") == "fr"


def test_infer_language_en():
    assert infer_language("en_core_web_lg") == "en"


def test_infer_language_es():
    assert infer_language("es_core_news_lg") == "es"
    assert infer_language("es_core_news_sm") == "es"


def test_infer_language_non_standard_returns_none():
    # Local paths and community models carry no language signal (STU-453).
    assert infer_language("") is None
    assert infer_language("models/wiki-ner-fr/model-best") is None
    assert infer_language("fr_solipcysme_lg") is None


def test_load_lang_config_en_has_existing_keys():
    cfg = load_lang_config("en")
    # These keys already exist in cue_words/en.json
    assert "place_cue_words" in cfg


def test_load_lang_config_unknown_raises():
    with pytest.raises(LangPackError) as exc:
        load_lang_config("xx")
    msg = str(exc.value)
    assert "xx" in msg
    assert "docs/lang-packs.md" in msg  # actionable pointer


def test_load_lang_config_unknown_opt_in_fallback():
    cfg = load_lang_config("xx", allow_en_fallback=True)
    assert "place_cue_words" in cfg  # explicit opt-in falls back to en.json


def test_shipped_packs_satisfy_required_keys():
    for code in ("en", "fr", "es"):
        cfg = load_lang_config(code)
        assert REQUIRED_KEYS <= cfg.keys()


def test_es_pack_repatriated_spanish_snippets():
    """STU-452: the Spanish snippets formerly hardcoded in scripts now live in es.json."""
    cfg = load_lang_config("es")
    # entity_clustering TITLE_PREFIXES honorifics
    for w in ("don", "doña", "señor", "señora", "señorita"):
        assert w in cfg["person_cue_words"], f"missing honorific: {w}"
    # entity_clustering gendered title sets
    assert "don" in cfg["masculine_titles"] and "señor" in cfg["masculine_titles"]
    assert "doña" in cfg["feminine_titles"] and "señora" in cfg["feminine_titles"]
    # verify_entity_types GEOGRAPHIC_KEYWORDS
    for w in ("calle", "plaza", "barrio"):
        assert w in cfg["place_cue_words"], f"missing place noun: {w}"


def test_es_pack_only_declares_known_keys():
    cfg = load_lang_config("es")
    assert set(cfg.keys()) <= (REQUIRED_KEYS | OPTIONAL_KEYS)


def test_packs_only_declare_known_keys():
    for code in ("en", "fr", "es"):
        cfg = load_lang_config(code)
        unknown = set(cfg.keys()) - (REQUIRED_KEYS | OPTIONAL_KEYS)
        assert not unknown, f"{code}.json declares unknown key(s): {unknown}"


def test_detection_vocabulary_is_in_the_packs_not_python():
    """STU-518: title/gender/geographic vocab lives in the packs, per language."""
    fr = load_lang_config("fr")
    en = load_lang_config("en")
    # French honorifics + translated-works Spanish ones.
    assert {"monsieur", "inspecteur", "don"} <= set(fr["title_prefixes"])
    assert "monsieur" in fr["masculine_titles"] and "madame" in fr["feminine_titles"]
    assert {"rue", "église"} <= set(fr["geographic_keywords"])
    # English pack carries its own (no French leaking in).
    assert "mr." in en["title_prefixes"]
    assert {"church", "street"} <= set(en["geographic_keywords"])
    assert "monsieur" not in set(en["title_prefixes"])


def test_required_and_optional_keys_are_disjoint():
    assert REQUIRED_KEYS.isdisjoint(OPTIONAL_KEYS)


def test_load_lang_config_missing_required_key_raises(tmp_path, monkeypatch):
    import wiki_creator.lang as lang

    pack = {k: [] for k in REQUIRED_KEYS if k != "pronouns"}
    (tmp_path / "zz.json").write_text(json.dumps(pack), encoding="utf-8")
    monkeypatch.setattr(lang, "_CUE_WORDS_DIR", tmp_path)
    with pytest.raises(LangPackError) as exc:
        load_lang_config("zz")
    assert "pronouns" in str(exc.value)


def test_load_lang_config_malformed_json_raises(tmp_path, monkeypatch):
    import wiki_creator.lang as lang

    (tmp_path / "zz.json").write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(lang, "_CUE_WORDS_DIR", tmp_path)
    with pytest.raises(LangPackError):
        load_lang_config("zz")


def test_load_lang_config_en_has_new_keys():
    cfg = load_lang_config("en")
    for key in ("pronouns", "noise_words", "reveal_words", "geo_keywords",
                "event_keywords", "coordination_connectors",
                "first_person_artifact_tails", "false_positive_words"):
        assert key in cfg, f"missing key: {key}"


def test_load_lang_config_fr_has_new_keys():
    cfg = load_lang_config("fr")
    for key in ("pronouns", "noise_words", "reveal_words", "geo_keywords",
                "event_keywords", "coordination_connectors",
                "false_positive_words"):
        assert key in cfg, f"missing key: {key}"


def test_load_lang_config_fr_pronouns_contains_elle():
    cfg = load_lang_config("fr")
    assert "elle" in cfg["pronouns"]


def test_load_lang_config_en_reveal_words_contains_alias():
    cfg = load_lang_config("en")
    assert "alias" in cfg["reveal_words"]


def test_load_lang_config_en_has_all_new_keys():
    cfg = load_lang_config("en")
    for key in ("action_cues", "geo_suffixes", "role_words", "role_patterns"):
        assert key in cfg, f"missing key: {key}"
        assert len(cfg[key]) > 0, f"key is empty: {key}"


def test_load_lang_config_fr_has_all_new_keys():
    cfg = load_lang_config("fr")
    for key in ("action_cues", "geo_suffixes", "role_words", "role_patterns"):
        assert key in cfg, f"missing key: {key}"
        assert len(cfg[key]) > 0, f"key is empty: {key}"



def test_en_action_cues_contains_found():
    cfg = load_lang_config("en")
    assert "found" in cfg["action_cues"]


def test_en_geo_suffixes_contains_mountains():
    cfg = load_lang_config("en")
    assert "mountains" in cfg["geo_suffixes"]


def test_en_role_words_contains_captain():
    cfg = load_lang_config("en")
    assert "captain" in cfg["role_words"]


def test_book_language_explicit_key_wins():
    assert book_language({"language": "EN", "spacy_model": "fr_core_news_lg"}) == "en"


def test_book_language_infers_from_spacy_model():
    assert book_language({"spacy_model": "fr_core_news_lg"}) == "fr"
    assert book_language({"spacy_model": "en_core_web_sm"}) == "en"


def test_book_language_non_inferable_model_requires_explicit_language():
    # A local-path model with no explicit language fails loudly (STU-453).
    with pytest.raises(ValueError, match="Cannot infer language"):
        book_language({"spacy_model": "models/wiki-ner-en/model-best"})
    # ...unless language is declared.
    assert book_language({"spacy_model": "models/wiki-ner-en/model-best", "language": "en"}) == "en"


def test_book_language_defaults_to_fr():
    assert book_language({}) == "fr"
    assert book_language({"language": "", "spacy_model": ""}) == "fr"


def test_load_lang_config_pov_keys_present():
    for code in ("fr", "en"):
        cfg = load_lang_config(code)
        assert isinstance(cfg.get("first_person_pronouns"), list)
        assert isinstance(cfg.get("third_person_thought_markers"), list)
    assert "je" in load_lang_config("fr")["first_person_pronouns"]
    assert "i" in load_lang_config("en")["first_person_pronouns"]


def test_load_lang_config_en_language_id_markers():
    markers = load_lang_config("en").get("language_id_markers", [])
    assert "is the" in markers
