from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from sift import runtime
from sift.runtime import Runtime
from sift.web import api, openapi, spa

SAFE_FETCH_SITES = frozenset({"same-origin", "none"})


def write_allowed(sec_fetch_site: str | None, origin: str | None, host: str) -> bool:
    if sec_fetch_site is not None:
        return sec_fetch_site in SAFE_FETCH_SITES
    return origin is None or urlsplit(origin).netloc == host


def create_app(rt: Runtime, *, run_background: bool = True, dist: Path = spa.DIST) -> FastAPI:

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if run_background:
            async with runtime.lifespan(rt):
                yield
        else:
            yield

    app = FastAPI(title=openapi.TITLE, lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")

    @app.middleware("http")
    async def same_site_writes(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if request.method not in ("GET", "HEAD", "OPTIONS") and not write_allowed(
            request.headers.get("sec-fetch-site"), request.headers.get("origin"), request.url.netloc
        ):
            return JSONResponse({"detail": "Cross-site request refused"}, status_code=403)
        return await call_next(request)

    app.state.rt = rt

    @app.get("/health", response_class=PlainTextResponse, include_in_schema=False)
    def health() -> str:
        return "ok"

    app.include_router(api.router)
    spa.mount(app, dist)
    return app
