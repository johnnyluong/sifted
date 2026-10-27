from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from sift.runtime import ROOT

DIST = ROOT / "web" / "dist"
BUILD = "bun install --cwd web && bun run --cwd web build"

IMMUTABLE = "public, max-age=31536000, immutable"  # Vite puts a content hash in every name under assets/
REVALIDATE = "no-cache"

NOT_BUILT = """<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sift: web UI not built</title>
<body style="font: 15px/1.55 system-ui, sans-serif; max-width: 34rem; margin: 14vh auto; padding: 0 16px">
<h1 style="font-size: 20px">The web UI isn't built yet</h1>
<p>Sift is running, but <code>web/dist</code> is missing. Build it, then reload this page:</p>
<pre style="padding: 12px; background: #f1f2f4; border-radius: 8px">bun install --cwd web
bun run --cwd web build</pre>
<p>The API is up meanwhile: <a href="/api/docs">/api/docs</a>.</p>
</body></html>
"""


def mount(app: FastAPI, dist: Path) -> None:
    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def spa(path: str) -> Response:
        return respond(dist, path)


def respond(dist: Path, path: str) -> Response:
    if path == "api" or path.startswith("api/"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    index = dist / "index.html"
    if not index.is_file():
        return HTMLResponse(NOT_BUILT, status_code=503)
    root = dist.resolve()
    file = (dist / path).resolve()
    if path and file.is_file() and file.is_relative_to(root):
        cache = IMMUTABLE if file.is_relative_to(root / "assets") else REVALIDATE
        return FileResponse(file, headers={"Cache-Control": cache})
    if path == "assets" or path.startswith("assets/"):
        return Response(status_code=404)
    return FileResponse(index, headers={"Cache-Control": REVALIDATE})
