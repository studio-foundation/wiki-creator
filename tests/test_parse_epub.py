"""Tests for scripts/parse_epub.py."""
import json
import subprocess
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_parse_epub_missing_file_path():
    """Missing file_path → error JSON + exit 1."""
    result = subprocess.run(
        [sys.executable, "scripts/parse_epub.py"],
        input=json.dumps({}),
        capture_output=True,
        text=True,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    )
    output = json.loads(result.stdout)
    assert "error" in output
    assert result.returncode == 1


def test_parse_epub_module_imports():
    """parse_epub module can be imported and parse_epub function exists."""
    from scripts.parse_epub import parse_epub
    assert callable(parse_epub)
