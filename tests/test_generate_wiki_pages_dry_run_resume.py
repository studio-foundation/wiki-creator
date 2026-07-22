"""STU-618: a --dry-run must not poison resume.

A dry run is a preview, not a result: its stub pages are left unstamped so the
next real run regenerates every entity instead of skipping it as already done.
"""

import scripts.generate_wiki_pages as gwp
from scripts.generate_wiki_pages import CollectingRunner


PLACE = {
    "canonical_name": "Cair Paravel",
    "type": "PLACE",
    "importance": "figurant",
    "context_by_chapter": {"1": ["The castle by the sea."]},
}


def _config(tmp_path, dry_run):
    return gwp.GenerationConfig(
        book_title="Narnia",
        generation_cfg={},
        output_file=str(tmp_path / "wiki_pages.json"),
        debug_dir=tmp_path / "debug",
        language="en",
        dry_run=dry_run,
    )


def test_dry_run_then_real_run_regenerates_every_page(tmp_path):
    batches = [("b1.json", {"batch_id": "b1", "entities": [dict(PLACE)]})]

    dry_pages = gwp.generate_pages(batches, _config(tmp_path, dry_run=True))
    assert dry_pages and dry_pages[0].get("_prompt") is None

    real_pages = gwp.generate_pages(
        batches, _config(tmp_path, dry_run=False), runner=CollectingRunner()
    )
    assert len(real_pages) == 1
    page = real_pages[0]
    assert page["content"] == "planned"  # regenerated, not the dry-run stub
    assert page.get("_prompt") is not None
