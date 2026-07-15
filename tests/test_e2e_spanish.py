"""End-to-end proof that the Spanish lang pack (es.json) drives a real run (STU-452).

Gated on the es_core_news_sm spaCy model: skips cleanly when it is absent (a
fresh clone / CI without the model), runs a genuine extraction + clustering pass
on Spanish text when it is present. This is the "run on a Spanish VO tome" proof
the format-validation task asks for, scaled down to a hermetic fixture (no EPUB
lives in the repo).
"""
import spacy

from _markers import requires_es_sm
from scripts.entity_extraction import extract_entities, split_entities, _load_cue_words
from scripts.entity_clustering import build_clusters


_CHAPTERS = [
    {
        "id": "ch01",
        "title": "Capítulo 1",
        "content": (
            "Don Andrés Corelli caminaba por la calle Aribau, en Barcelona. "
            "El señor Corelli era un editor misterioso. "
            "Andrés Corelli se dirigió hacia la plaza del pueblo."
        ),
    },
    {
        "id": "ch02",
        "title": "Capítulo 2",
        "content": (
            "La señora Cristina Sagnier vivía en el mismo barrio. "
            "Cristina Sagnier conoció a Corelli en Barcelona."
        ),
    },
]


@requires_es_sm
def test_spanish_extraction_and_clustering_end_to_end():
    nlp = spacy.load("es_core_news_sm")
    result = extract_entities(_CHAPTERS, nlp, cue_words=_load_cue_words("es"))

    all_mentions = [m for e in result["entities"].values() for m in e["raw_mentions"]]
    # Spanish NER (PER/LOC) surfaces the characters and a place.
    assert any("Corelli" in m for m in all_mentions), all_mentions
    assert any("Barcelona" in m for m in all_mentions), all_mentions

    entities_for_resolution, _ = split_entities(result["entities"])
    clusters, unclustered = build_clusters(entities_for_resolution, language="es")

    # The "Don"/"señor" honorifics (from es.json) are stripped before comparison,
    # so the Corelli surface forms collapse into a single cluster instead of
    # fragmenting across the honorific-bearing and bare forms.
    corelli = [
        c for c in clusters
        if any("Corelli" in m for m in c["all_mentions"])
    ]
    assert len(corelli) == 1, [c["all_mentions"] for c in corelli]
