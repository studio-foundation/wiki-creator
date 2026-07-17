# Wiki Creator
# Pipeline: EPUB parsing → entity extraction → LLM entity resolution → wiki generation

import os
from pathlib import Path


def _assert_imported_from_cwd() -> None:
    """Fail loudly when a worktree imports another checkout's wiki_creator (STU-569).

    ``pip install -e .`` pins ONE absolute checkout on ``sys.path`` for the whole
    interpreter. A git worktree runs its own ``scripts/`` but ``import wiki_creator``
    silently resolves to the INSTALLED tree — so a subprocess (``studio run``,
    ``python scripts/x.py``) exercises code the branch never wrote. The Makefile and
    conftest prepend the right tree; this catches the paths that bypass both, turning
    a silent behavior drift (same signature, changed body) into a crash.

    Trip only on the exact mismatch: the cwd holds a wiki_creator package that is not
    the one imported. A cwd without one (installed elsewhere, run from a subdir) is
    left alone. ``WIKI_CREATOR_ALLOW_FOREIGN_CHECKOUT`` opts out.
    """
    if os.environ.get("WIKI_CREATOR_ALLOW_FOREIGN_CHECKOUT"):
        return
    imported = Path(__file__).resolve().parent
    local = Path.cwd() / "wiki_creator"
    if local.is_dir() and local.resolve() != imported:
        raise ImportError(
            f"wiki_creator imported from {imported} but the current directory holds a "
            f"different checkout at {local.resolve()} (STU-569). `pip install -e .` pins "
            f"one checkout; a worktree needs its own tree on sys.path. Run via `make`, or "
            f"prefix with PYTHONPATH={Path.cwd()}, or set "
            f"WIKI_CREATOR_ALLOW_FOREIGN_CHECKOUT=1 to silence."
        )


_assert_imported_from_cwd()
