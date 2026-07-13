from pathlib import Path
from wiki_creator.paths import book_paths_from_epub, book_paths_from_yaml

def test_book_paths_from_epub():
    paths = book_paths_from_epub("library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.epub")
    assert paths.epub == Path("library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.epub")
    assert paths.processing == Path("library/sarah_j_maas/throne-of-glass/processing_output/01-throne-of-glass")
    assert paths.wiki_inputs == Path("library/sarah_j_maas/throne-of-glass/wiki_inputs/01-throne-of-glass")
    assert paths.output == Path("library/sarah_j_maas/throne-of-glass/output/01-throne-of-glass")

def test_book_paths_from_yaml():
    paths = book_paths_from_yaml("library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml")
    assert paths.epub == Path("library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.epub")
    assert paths.processing == Path("library/sarah_j_maas/throne-of-glass/processing_output/01-throne-of-glass")
    assert paths.wiki_inputs == Path("library/sarah_j_maas/throne-of-glass/wiki_inputs/01-throne-of-glass")
    assert paths.output == Path("library/sarah_j_maas/throne-of-glass/output/01-throne-of-glass")

def test_paths_accept_path_object():
    p = Path("library/carlos-ruiz-zafon/el-cementerio/books/02-le-jeu.epub")
    paths = book_paths_from_epub(p)
    assert paths.processing == Path("library/carlos-ruiz-zafon/el-cementerio/processing_output/02-le-jeu")

def test_series_registry_path():
    """STU-485: series identity registry lives next to the series graph."""
    paths = book_paths_from_yaml("library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml")
    assert paths.series_registry == Path("library/sarah_j_maas/throne-of-glass/registry.json")
    assert paths.series_registry.parent == paths.series_character_graph.parent

def test_book_registry_delta_path():
    paths = book_paths_from_yaml("library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml")
    assert paths.book_registry_delta == Path(
        "library/sarah_j_maas/throne-of-glass/processing_output/01-throne-of-glass/registry_delta.json"
    )
