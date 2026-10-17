"""The web API around the planning engine, and (once built) the web app itself.

    uv run uvicorn freight.api.app:create_app --factory --reload

Every request is tied to a signed-in user, and every query is filtered by that
user's company, so one carrier can never see another's data. Requests that
change something must carry the header ``X-Requested-With: freight`` (a simple
defence against cross-site request forgery for a same-origin web app).
"""

import logging
from collections.abc import AsyncIterator
from concurrent.futures import Executor, ProcessPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from freight.api.db import Database
from freight.api.routes import auth, data, plans, steering
from freight.api.runner import Runner, fail_interrupted
from freight.settings import get_settings, key_override_warning

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
    ),
}


def create_app(database_url: str | None = None, executor: Executor | None = None) -> FastAPI:
    settings = get_settings()
    if warning := key_override_warning():
        logging.getLogger("freight").warning(warning)
    url = database_url or settings.database_url
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    database = Database(url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        fail_interrupted(database.session)
        pool = executor or ProcessPoolExecutor(max_workers=settings.plan_workers)
        app.state.runner = Runner(pool, database.session)
        yield
        pool.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="Madar freight planning", lifespan=lifespan)
    app.state.database = database

    @app.middleware("http")
    async def guard(request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.method not in ("GET", "HEAD", "OPTIONS") and (
            request.headers.get("x-requested-with") != "freight"
        ):
            return JSONResponse({"detail": "Missing X-Requested-With header"}, status_code=403)
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if settings.secure_cookies:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response

    @app.get("/api/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    for module in (auth, plans, steering, data):
        app.include_router(module.router)

    serve_web_app(app, settings.web_dist)
    return app


def serve_web_app(app: FastAPI, dist: Path) -> None:
    """Serve the built single-page app; every non-API path gets its index.html."""
    index = dist / "index.html"
    if not index.is_file():
        return  # development: Vite serves the app and proxies /api here
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def web_app(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(404, "Not found")
        file = (dist / path).resolve()
        if path and file.is_file() and file.is_relative_to(dist.resolve()):
            return FileResponse(file)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
