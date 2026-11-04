"""نقطه ورود برنامه FastAPI."""
from __future__ import annotations

import base64
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import get_settings
from .database import Base, SessionLocal, engine
from .errors import register_error_handlers
from .logging_conf import setup_logging
from .routers import analytics, assets, core, data, prices, reports, transactions
from .services.seed import is_seeded, seed_defaults

STATIC_DIR = Path(__file__).parent / "static"
log = logging.getLogger("capitalpilot")


def init_db() -> None:
    Base.metadata.create_all(engine)
    s = get_settings()
    if s.seed_on_startup:
        with SessionLocal() as db:
            if not is_seeded(db):
                seed_defaults(db)
                log.info("Initial data seeded")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    init_db()
    log.info("CapitalPilot %s started", __version__)
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="CapitalPilot API", version=__version__, lifespan=lifespan,
        description="سیستم هوشمند مدیریت سرمایه‌گذاری شخصی — کنترل سرمایه، تصمیم هوشمندانه. "
                    "این API هیچ سفارش خرید یا فروشی ارسال نمی‌کند.",
        docs_url="/api/docs" if s.docs_enabled else None, redoc_url="/api/redoc" if s.docs_enabled else None,
        openapi_url="/api/openapi.json" if s.docs_enabled else None,
    )
    register_error_handlers(app)

    if s.basic_auth_user and s.basic_auth_password:
        @app.middleware("http")
        async def basic_auth(request: Request, call_next):
            header = request.headers.get("authorization", "")
            ok = False
            if header.lower().startswith("basic "):
                try:
                    user, _, pwd = base64.b64decode(header[6:]).decode().partition(":")
                    ok = secrets.compare_digest(user, s.basic_auth_user) and secrets.compare_digest(pwd, s.basic_auth_password)
                except Exception:
                    ok = False
            if not ok:
                return Response("Unauthorized", status_code=401, headers={"WWW-Authenticate": 'Basic realm="CapitalPilot"'})
            return await call_next(request)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        if request.url.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    for r in (core, assets, transactions, prices, analytics, reports, data):
        app.include_router(r.router)

    @app.get("/api/health", tags=["core"])
    def health():
        return {"status": "ok", "version": __version__}

    @app.get("/api/{path:path}", include_in_schema=False)
    def api_404(path: str):
        return JSONResponse(status_code=404, content={"error": {"code": "not_found", "message": "مسیر API یافت نشد.", "details": None}})

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
