"""Tests for the `wiki preview` launcher (STU-646).

The pure index/template/read helpers are the /api contract the preview app
fetches (mirrored by preview/src/server/fixture-server.js). They are verified
against the STU-645 fixture; the server is smoke-tested end to end on an
ephemeral port. The full `wiki preview <real book>` run needs a pipeline output
(claude:local), but every piece here is web-verifiable against the fixture.
"""
import http.client
import json
from pathlib import Path

import pytest

from wiki_creator import cli, preview

FIXTURE = Path(__file__).parent / "fixtures" / "preview" / "output"


# --- pure helpers ----------------------------------------------------------

def test_build_index_matches_the_api_shape():
    index = preview.build_index(FIXTURE, "01-alice-in-wonderland")
    assert index["book"] == "01-alice-in-wonderland"
    assert index["pages"][0]["path"] == "Main_Page.wiki"  # Main_Page first
    by_path = {p["path"]: p for p in index["pages"]}
    assert by_path["characters/Alice.wiki"]["entityType"] == "PERSON"
    assert by_path["locations/Wonderland.wiki"]["entityType"] == "PLACE"
    assert by_path["organizations/Court_of_Hearts.wiki"]["entityType"] == "ORG"
    assert by_path["events/A_Mad_Tea-Party.wiki"]["entityType"] == "EVENT"
    assert by_path["Synopsis.wiki"]["entityType"] is None
    assert by_path["real-wiki/Alice.wiki"]["entityType"] == "ORIGINAL"
    assert by_path["characters/Alice.wiki"]["slug"] == "characters/Alice"
    assert by_path["characters/Alice.wiki"]["title"] == "Alice"
    assert "Characters" in by_path["characters/Alice.wiki"]["categories"]
    assert not any(p["path"].startswith("templates/") for p in index["pages"])


def test_load_templates_keys_by_name():
    templates = preview.load_templates(FIXTURE)
    assert "{{{nom}}}" in templates["Infobox character"]
    assert "Infobox location" in templates


def test_read_page_returns_wikitext():
    assert "{{Infobox character" in preview.read_page(FIXTURE, "characters/Alice.wiki")


@pytest.mark.parametrize("bad", ["../../../etc/passwd", "/etc/passwd"])
def test_read_page_rejects_traversal(bad):
    with pytest.raises(ValueError):
        preview.read_page(FIXTURE, bad)


# --- server ----------------------------------------------------------------

def _get(port, path):
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read().decode("utf-8")
    conn.close()
    return resp.status, body


def test_server_serves_api_and_static(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<title>Wiki Preview</title>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")

    httpd = preview.serve(FIXTURE, dist, book="alice", port=0, open_browser=False)
    port = httpd.server_address[1]
    try:
        import threading

        threading.Thread(target=httpd.serve_forever, daemon=True).start()

        status, body = _get(port, "/api/index.json")
        assert status == 200
        assert json.loads(body)["pages"][0]["path"] == "Main_Page.wiki"

        status, body = _get(port, "/api/page?path=characters/Alice.wiki")
        assert status == 200 and "{{Infobox character" in body

        status, body = _get(port, "/api/templates.json")
        assert "Infobox character" in json.loads(body)

        status, body = _get(port, "/")
        assert status == 200 and "Wiki Preview" in body

        status, body = _get(port, "/assets/app.js")
        assert status == 200 and "console.log" in body

        status, _ = _get(port, "/api/page?path=../../secret")
        assert status == 404
    finally:
        httpd.shutdown()


# --- CLI wiring ------------------------------------------------------------

def test_cli_preview_requires_a_book_or_output(capsys):
    assert cli.main(["preview"]) == 2
    assert "give a book" in capsys.readouterr().err


def test_cli_preview_errors_when_no_output_exists(tmp_path, capsys):
    assert cli.main(["preview", "--output", str(tmp_path / "nope")]) == 2
    assert "no exported wiki" in capsys.readouterr().err


def test_cli_preview_dry_run(capsys):
    rc = cli.main(["--dry-run", "preview", "--output", str(FIXTURE)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "serve" in out and str(FIXTURE) in out


# --- auto-build on first run (STU-673) -------------------------------------

class _FakeServer:
    server_address = ("127.0.0.1", 4173)

    def serve_forever(self):
        raise KeyboardInterrupt

    def shutdown(self):
        pass


def test_cli_preview_builds_when_dist_missing(monkeypatch, capsys):
    built = []
    monkeypatch.setattr(preview, "preview_app_built", lambda _dist: False)
    monkeypatch.setattr(preview, "build_preview_app", lambda d: built.append(d))
    monkeypatch.setattr(preview, "serve", lambda *a, **k: _FakeServer())
    rc = cli.main(["preview", "--output", str(FIXTURE), "--no-open"])
    assert rc == 0
    assert len(built) == 1  # dist missing -> build invoked
    assert "building preview app" in capsys.readouterr().err


def test_cli_preview_skips_build_when_dist_present(monkeypatch):
    built = []
    monkeypatch.setattr(preview, "preview_app_built", lambda _dist: True)
    monkeypatch.setattr(preview, "build_preview_app", lambda d: built.append(d))
    monkeypatch.setattr(preview, "serve", lambda *a, **k: _FakeServer())
    rc = cli.main(["preview", "--output", str(FIXTURE), "--no-open"])
    assert rc == 0
    assert built == []  # dist present -> build skipped


def test_cli_preview_errors_when_build_fails(monkeypatch, capsys):
    monkeypatch.setattr(preview, "preview_app_built", lambda _dist: False)

    def _boom(_dir):
        raise preview.PreviewBuildError("npm not found — install Node.js")

    monkeypatch.setattr(preview, "build_preview_app", _boom)
    rc = cli.main(["preview", "--output", str(FIXTURE), "--no-open"])
    assert rc == 2
    assert "npm not found" in capsys.readouterr().err


def test_build_preview_app_raises_when_npm_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(preview.shutil, "which", lambda _cmd: None)
    with pytest.raises(preview.PreviewBuildError, match="npm not found"):
        preview.build_preview_app(tmp_path)


def test_build_preview_app_runs_ci_then_build(monkeypatch, tmp_path):
    monkeypatch.setattr(preview.shutil, "which", lambda _cmd: "/usr/bin/npm")
    calls = []

    class _Ok:
        returncode = 0

    def _run(cmd, cwd):
        calls.append((cmd, cwd))
        return _Ok()

    monkeypatch.setattr(preview.subprocess, "run", _run)
    preview.build_preview_app(tmp_path)  # no node_modules -> ci then build
    assert [c[0] for c in calls] == [["npm", "ci"], ["npm", "run", "build"]]
    assert all(c[1] == tmp_path for c in calls)


def test_build_preview_app_skips_ci_when_node_modules_present(monkeypatch, tmp_path):
    (tmp_path / "node_modules").mkdir()
    monkeypatch.setattr(preview.shutil, "which", lambda _cmd: "/usr/bin/npm")
    calls = []

    class _Ok:
        returncode = 0

    monkeypatch.setattr(preview.subprocess, "run", lambda cmd, cwd: calls.append(cmd) or _Ok())
    preview.build_preview_app(tmp_path)
    assert calls == [["npm", "run", "build"]]  # node_modules present -> only build
