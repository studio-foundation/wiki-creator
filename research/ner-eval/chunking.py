"""Sentence-boundary chunking. Pure, stdlib-only.

Mirrors the chunking the training set was built with (scripts/ner_dataset_generation.py)
so chunk size is not a free variable between the trained model and this eval.
"""
import re

MIN_CHUNK_CHARS = 200
TARGET_CHUNK_CHARS = 1600  # ~400 tokens


def chunk_text(text: str, target: int = TARGET_CHUNK_CHARS) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks: list[str] = []
    current = ""
    for sent in sentences:
        if len(current) + len(sent) > target and len(current) >= MIN_CHUNK_CHARS:
            chunks.append(current.strip())
            current = sent
        else:
            current = (current + " " + sent).strip() if current else sent
    if current.strip():
        chunks.append(current.strip())
    return chunks
