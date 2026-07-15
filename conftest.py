"""Make subprocess-spawned scripts import the checkout under test.

``pip install -e .`` pins ONE absolute path on ``sys.path`` for the whole interpreter —
whichever checkout was installed. In a git worktree that path is the *other* tree, so a
test spawning ``python scripts/x.py`` silently exercised the installed checkout instead
of the branch under test, and reported green for code it never ran.

In-process imports are already correct (pytest prepends the rootdir); only subprocesses
need this, and they pick it up by inheriting the environment.
"""

import os
from pathlib import Path

ROOT = Path(__file__).parent


def pytest_configure(config):
    existing = os.environ.get("PYTHONPATH", "")
    entries = [str(ROOT)] + [p for p in existing.split(os.pathsep) if p]
    os.environ["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(entries))
