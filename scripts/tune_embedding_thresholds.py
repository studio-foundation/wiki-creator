"""Dev-only: sweep propose/veto thresholds over the golden pairs (STU-468).

Not part of any pipeline stage. Requires the `embeddings` extra
(`pip install -e '.[embeddings]'`). Reads the self-contained fixture
`tests/fixtures/embedding_golden_pairs.json` (contexts are baked in — the
run's processing_output/ is gitignored), embeds each entity's contexts with
the real e5-small model, and prints per-pair cosine plus a precision/recall
grid so the winning defaults can be baked into the module constants.

Usage: python scripts/tune_embedding_thresholds.py
"""
import json
from pathlib import Path

from wiki_creator.embedding_disambiguation import EmbeddingBackend, cosine, entity_centroid

FIXTURE = Path("tests/fixtures/embedding_golden_pairs.json")


def main():
    spec = json.loads(FIXTURE.read_text(encoding="utf-8"))
    entities = spec["entities"]
    backend = EmbeddingBackend(device="cpu")

    centroids = {name: entity_centroid(ctxs, backend) for name, ctxs in entities.items()}

    scored = []
    for pair in spec["pairs"]:
        ca, cb = centroids.get(pair["a"]), centroids.get(pair["b"])
        if ca is None or cb is None:
            print(f"SKIP (no context): {pair['a']} / {pair['b']}")
            continue
        scored.append((cosine(ca, cb), pair["label"], pair["a"], pair["b"]))

    print("\ncosine  label      pair")
    for score, label, a, b in sorted(scored, reverse=True):
        print(f"{score:.3f}  {label:9s}  {a} / {b}")

    print("\nthreshold  precision(same)  recall(same)  false-merges")
    for thr in [round(0.70 + 0.02 * i, 2) for i in range(16)]:
        tp = sum(1 for s, l, *_ in scored if s >= thr and l == "same")
        fp = sum(1 for s, l, *_ in scored if s >= thr and l == "different")
        fn = sum(1 for s, l, *_ in scored if s < thr and l == "same")
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        print(f"{thr:.2f}       {prec:.2f}             {rec:.2f}          {fp}")


if __name__ == "__main__":
    main()
