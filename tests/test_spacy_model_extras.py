"""Declared spaCy models must be installable from the project's extras (STU-522).

spaCy models are not PyPI dependencies, so nothing pulls them transitively: a
declared model that no extra provides degrades to a smaller sibling at load
time (wiki_creator/nlp/loader.py), and the config that runs is not the config
the book declares.
"""
import tomllib
from pathlib import Path

import yaml

from wiki_creator.lang import infer_language

ROOT = Path(__file__).resolve().parents[1]


def _extras() -> dict[str, list[str]]:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]["optional-dependencies"]


def _requirement_names(extra: list[str]) -> set[str]:
    return {requirement.split("@", 1)[0].strip() for requirement in extra}


def _declared_models() -> set[str]:
    models = set()
    for book in (ROOT / "library").rglob("books/*.yaml"):
        config = yaml.safe_load(book.read_text(encoding="utf-8")) or {}
        model = (config.get("spacy_model") or "").strip()
        if model:
            models.add(model)
    return models


def test_the_library_declares_spacy_models():
    assert _declared_models(), "no book declares a spacy_model — the guard below is vacuous"


def test_every_declared_stock_model_is_installed_by_an_extra():
    extras = _extras()
    installed = _requirement_names(extras["models"]) | _requirement_names(extras["dev"])
    # A name carrying a language signal is a stock model; a local path or a
    # community model returns None and is the user's to install (STU-453).
    declared = {model for model in _declared_models() if infer_language(model)}
    missing = declared - installed
    assert not missing, f"declared by a book but installed by no extra: {sorted(missing)}"
