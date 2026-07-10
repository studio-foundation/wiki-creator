from wiki_creator.lang import book_language, infer_language, load_lang_config


def test_infer_language_fr():
    assert infer_language("fr_core_news_lg") == "fr"
    assert infer_language("fr_core_news_sm") == "fr"


def test_infer_language_en():
    assert infer_language("en_core_web_lg") == "en"
    assert infer_language("") == "en"


def test_load_lang_config_en_has_existing_keys():
    cfg = load_lang_config("en")
    # These keys already exist in cue_words/en.json
    assert "place_cue_words" in cfg


def test_load_lang_config_unknown_falls_back_to_en():
    cfg = load_lang_config("xx")
    assert "place_cue_words" in cfg  # falls back to en.json


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
    for key in ("alias_pattern_templates", "action_cues", "geo_suffixes", "role_words", "role_patterns"):
        assert key in cfg, f"missing key: {key}"
        assert len(cfg[key]) > 0, f"key is empty: {key}"


def test_load_lang_config_fr_has_all_new_keys():
    cfg = load_lang_config("fr")
    for key in ("alias_pattern_templates", "action_cues", "geo_suffixes", "role_words", "role_patterns"):
        assert key in cfg, f"missing key: {key}"
        assert len(cfg[key]) > 0, f"key is empty: {key}"


def test_en_alias_pattern_templates_contain_placeholder():
    cfg = load_lang_config("en")
    assert any("{b}" in t for t in cfg["alias_pattern_templates"])


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
    assert book_language({"spacy_model": "models/wiki-ner-en/model-best"}) == "en"


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
