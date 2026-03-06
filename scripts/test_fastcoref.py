#!/usr/bin/env python3
"""
STU-237 — Test fastcoref + LingMessCoref on French literary text.

Usage:
    python scripts/test_fastcoref.py
    python scripts/test_fastcoref.py --chapter x106.xhtml  # default
    python scripts/test_fastcoref.py --chapter x106.xhtml x107.xhtml x108.xhtml
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

CHAPTERS_PATH = Path(__file__).parent.parent / "chapters.json"
# chapters.json is gitignored — look in the main worktree if not present locally
if not CHAPTERS_PATH.exists():
    CHAPTERS_PATH = Path(__file__).resolve().parents[3] / "chapters.json"
CORELLI_ALIASES = {"corelli", "le patron", "andreas corelli", "m. corelli"}


def load_chapters() -> dict[str, str]:
    with open(CHAPTERS_PATH) as f:
        data = json.load(f)
    return data["chapters"]


def get_candidate_chapters(chapters: dict[str, str], n: int = 3) -> list[str]:
    """Return chapters that mention Corelli, longest first."""
    candidates = [
        (k, v) for k, v in chapters.items()
        if any(alias in v.lower() for alias in CORELLI_ALIASES) and len(v) > 1000
    ]
    candidates.sort(key=lambda x: -len(x[1]))
    return [k for k, _ in candidates[:n]]


def _patch_transformers_eager() -> None:
    """
    Force attn_implementation='eager' for all AutoModel.from_config calls.

    LingMessCoref uses LongformerModel which doesn't support SDPA yet
    (transformers >= ~4.45). This monkey-patch avoids a ValueError on load.
    See: https://github.com/huggingface/transformers/issues/28005
    """
    import transformers

    _orig = transformers.AutoModel.from_config.__func__

    @classmethod  # type: ignore[misc]
    def _patched(cls, config, **kwargs):  # type: ignore[misc]
        kwargs.setdefault("attn_implementation", "eager")
        return _orig(cls, config, **kwargs)

    transformers.AutoModel.from_config = _patched


def run_fastcoref_on_text(text: str, chapter_id: str) -> dict:
    """Run fastcoref LingMessCoref on text and return analysis."""
    import spacy
    from fastcoref import spacy_component  # noqa: F401 — registers the pipe

    _patch_transformers_eager()

    print(f"\n[{chapter_id}] Chargement du modèle spaCy + fastcoref...", file=sys.stderr)
    t0 = time.time()

    nlp = spacy.load(
        "fr_core_news_lg",
        exclude=["parser", "lemmatizer", "ner", "textcat"],
    )
    nlp.add_pipe(
        "fastcoref",
        config={
            "model_architecture": "LingMessCoref",
            "model_path": "biu-nlp/lingmess-coref",
            "device": "cpu",
        },
    )

    # Truncate to first 8000 chars to avoid OOM on CPU
    chunk = text[:8000]
    print(f"[{chapter_id}] Texte: {len(chunk)} chars — inference...", file=sys.stderr)

    doc = nlp(chunk, component_cfg={"fastcoref": {"resolve_text": True}})
    elapsed = time.time() - t0
    print(f"[{chapter_id}] Done in {elapsed:.1f}s", file=sys.stderr)

    resolved = doc._.resolved_text or ""

    # Extract clusters — fastcoref returns (start_char, end_char) tuples
    raw_clusters = doc._.coref_clusters or []
    cluster_summary = []
    corelli_resolved = False

    for cluster in raw_clusters:
        # Each mention is either a Span or a (start, end) char-offset tuple
        mentions_text = []
        for mention in cluster:
            if hasattr(mention, "text"):
                text_span = mention.text
            elif isinstance(mention, (tuple, list)) and len(mention) == 2:
                start, end = int(mention[0]), int(mention[1])
                text_span = chunk[start:end]
            else:
                # str repr like "(110, 112)" — parse it
                try:
                    coords = str(mention).strip("()").split(",")
                    start, end = int(coords[0].strip()), int(coords[1].strip())
                    text_span = chunk[start:end]
                except Exception:
                    text_span = str(mention)
            mentions_text.append(text_span)

        cluster_summary.append(mentions_text)
        lowered_all = " ".join(m.lower() for m in mentions_text)
        if any(alias in lowered_all for alias in CORELLI_ALIASES):
            corelli_resolved = True

    # Count pronoun resolution (before vs after)
    fr_pronouns = {"il", "elle", "ils", "elles", "lui", "leur"}
    pronoun_count_before = sum(
        1 for token in doc if token.text.lower() in fr_pronouns
    )
    pronoun_count_after = sum(
        1 for w in resolved.split() if w.lower() in fr_pronouns
    )

    return {
        "chapter_id": chapter_id,
        "text_length": len(chunk),
        "elapsed_s": round(elapsed, 1),
        "num_clusters": len(raw_clusters),
        "cluster_sample": cluster_summary[:10],  # first 10 clusters
        "corelli_resolved": corelli_resolved,
        "pronouns_before": pronoun_count_before,
        "pronouns_after": pronoun_count_after,
        "resolved_preview": resolved[:600],
    }


def print_result(result: dict) -> None:
    print(f"\n{'='*60}")
    print(f"Chapitre : {result['chapter_id']}")
    print(f"Texte    : {result['text_length']} chars | Temps: {result['elapsed_s']}s")
    print(f"Clusters : {result['num_clusters']}")
    print(f"Pronoms avant/après résolution : {result['pronouns_before']} / {result['pronouns_after']}")
    print(f"Corelli résolu vers entité nommée : {'✓ OUI' if result['corelli_resolved'] else '✗ NON'}")
    print("\nClusters (10 premiers) :")
    for i, cluster in enumerate(result["cluster_sample"], 1):
        print(f"  [{i}] {cluster}")
    print("\nTexte résolu (extrait) :")
    print(result["resolved_preview"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Test fastcoref + LingMessCoref sur Le Jeu de l'Ange")
    parser.add_argument("--chapter", nargs="+", help="IDs de chapitres à tester (ex: x106.xhtml)")
    args = parser.parse_args()

    chapters = load_chapters()

    if args.chapter:
        chapter_ids = args.chapter
    else:
        chapter_ids = get_candidate_chapters(chapters, n=3)
        print(f"Chapitres sélectionnés automatiquement : {chapter_ids}", file=sys.stderr)

    results = []
    for cid in chapter_ids:
        if cid not in chapters:
            print(f"[WARN] Chapitre introuvable : {cid}", file=sys.stderr)
            continue
        try:
            result = run_fastcoref_on_text(chapters[cid], cid)
            results.append(result)
            print_result(result)
        except Exception as e:
            print(f"[ERROR] {cid}: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()

    # Summary
    print(f"\n{'='*60}")
    print("RÉSUMÉ")
    print(f"Chapitres testés : {len(results)}")
    corelli_ok = sum(1 for r in results if r["corelli_resolved"])
    print(f"Corelli résolu   : {corelli_ok}/{len(results)}")
    avg_clusters = sum(r["num_clusters"] for r in results) / max(len(results), 1)
    print(f"Clusters moy.    : {avg_clusters:.1f}")
    avg_time = sum(r["elapsed_s"] for r in results) / max(len(results), 1)
    print(f"Temps moy.       : {avg_time:.1f}s")


if __name__ == "__main__":
    main()
