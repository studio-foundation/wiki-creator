"""`wiki preview` launcher (STU-646): serve a book's exported ``output/`` to the
M5.1 Fandom Preview app and open the browser.

The pure helpers (:func:`build_index`, :func:`load_templates`, :func:`read_page`)
are the source of truth for the ``/api`` shape the app fetches; the dev-time Vite
middleware (``preview/src/server/fixture-server.js``) mirrors them so the app is
identical in dev and here. The HTTP server also serves the built SPA
(``preview/dist``) so ``wiki preview`` is a single command.
"""
from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Export subdir -> entity type (mirrors base.yaml#entity_types.export.subdir and
# the JS SUBDIR_TYPE in preview/src/server/fixture-server.js).
_SUBDIR_TYPE = {
    "characters": "PERSON",
    "locations": "PLACE",
    "organizations": "ORG",
    "events": "EVENT",
    "factions": "FACTION",
}

_STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}


def build_index(output_dir: Path, book: str = "") -> dict:
    """The page index a book's ``output/`` exposes: Main_Page first, then a
    stable order by path. Excludes the ``templates/`` dir."""
    pages = []
    for wiki in sorted(output_dir.rglob("*.wiki")):
        rel = wiki.relative_to(output_dir).as_posix()
        if rel.startswith("templates/"):
            continue
        subdir = rel.rsplit("/", 1)[0] if "/" in rel else ""
        stem = wiki.stem
        pages.append(
            {
                "title": stem.replace("_", " "),
                "path": rel,
                "slug": rel[: -len(".wiki")],
                "entityType": _SUBDIR_TYPE.get(subdir),
                "subdir": subdir,
            }
        )
    pages.sort(key=lambda p: (p["path"] != "Main_Page.wiki", p["path"]))
    return {"book": book, "pages": pages}


def load_templates(output_dir: Path) -> dict:
    """``templates/*.wiki`` -> ``{"Infobox character": "<source>"}`` (filename ``_`` -> space)."""
    tdir = output_dir / "templates"
    if not tdir.is_dir():
        return {}
    return {
        f.stem.replace("_", " "): f.read_text(encoding="utf-8")
        for f in sorted(tdir.glob("*.wiki"))
    }


def read_page(output_dir: Path, rel_path: str) -> str:
    """Raw wikitext for one page path, refusing anything that escapes ``output_dir``."""
    target = (output_dir / rel_path).resolve()
    if not str(target).startswith(str(output_dir.resolve())):
        raise ValueError(f"path escapes output dir: {rel_path!r}")
    return target.read_text(encoding="utf-8")


def _make_handler(output_dir: Path, dist_dir: Path, book: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # quiet
            pass

        def _send(self, code, body: bytes, content_type: str):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, body, code=200):
            self._send(code, json.dumps(body).encode("utf-8"), "application/json")

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                if path == "/api/index.json":
                    return self._json(build_index(output_dir, book))
                if path == "/api/templates.json":
                    return self._json(load_templates(output_dir))
                if path == "/api/page":
                    rel = parse_qs(parsed.query).get("path", [""])[0]
                    return self._send(200, read_page(output_dir, rel).encode("utf-8"),
                                      "text/plain; charset=utf-8")
                return self._serve_static(path)
            except (FileNotFoundError, ValueError) as exc:
                return self._json({"error": str(exc)}, code=404)

        def _serve_static(self, path: str):
            rel = "index.html" if path in ("", "/") else path.lstrip("/")
            target = (dist_dir / rel).resolve()
            if not str(target).startswith(str(dist_dir.resolve())) or not target.is_file():
                return self._json({"error": f"not found: {path}"}, code=404)
            ctype = _STATIC_TYPES.get(target.suffix, "application/octet-stream")
            return self._send(200, target.read_bytes(), ctype)

    return Handler


def preview_app_built(dist_dir: Path) -> bool:
    return (dist_dir / "index.html").is_file()


def serve(
    output_dir: Path,
    dist_dir: Path,
    book: str = "",
    host: str = "127.0.0.1",
    port: int = 4173,
    open_browser: bool = True,
) -> ThreadingHTTPServer:
    """Start the preview server. Returns the (already-serving) server so a caller
    can shut it down; the CLI blocks on it via :func:`serve_forever`."""
    httpd = ThreadingHTTPServer((host, port), _make_handler(output_dir, dist_dir, book))
    url = f"http://{host}:{httpd.server_address[1]}/"
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    return httpd
