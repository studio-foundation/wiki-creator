from wiki_creator.lang import infer_language, load_lang_config


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
