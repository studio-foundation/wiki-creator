"""A script spawned as a subprocess must import the checkout under test.

Pins the conftest's PYTHONPATH wiring. Delete it and this fails in any git worktree —
which is exactly the failure mode it exists to catch, because without it the suite
reports green for code from a different checkout entirely.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_subprocess_imports_wiki_creator_from_this_checkout():
    result = subprocess.run(
        [sys.executable, "-c", "import wiki_creator; print(wiki_creator.__file__)"],
        cwd=ROOT / "scripts",  # a script's own dir wins over cwd on sys.path
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()) == ROOT / "wiki_creator" / "__init__.py"
