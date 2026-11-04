"""نقطه ورود برنامه FastAPI."""
from __future__ import annotations

import base64
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import get_settings
from .database import Base, SessionLocal, engine
from .errors import register_error_handlers
from .migrations import run_migrations
from .logging_conf import setup_logging
from .routers import analytics, assets, catalog, core, data, iranmarket, market, portfolios, prices, reports, search, transactions
from .services.fsperm import harden_runtime_paths
from .services.seed import is_seeded, seed_defaults

STATIC_DIR = Path(__file__).parent / "static"


class RevalidatingStaticFiles(StaticFiles):
    """فایل‌های برنامه همیشه revalidate می‌شوند (ETag)، تا پس از به‌روزرسانی نسخهٔ قدیمی نمایش داده نشود."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code in (200, 304):
            if path.startswith("vendor/"):
                response.headers["Cache-Control"] = "public, max-age=604800"
            else:
                response.headers["Cache-Control"] = "no-cache"
        return response
log = logging.getLogger("capitalpilot")


def production_warnings(s) -> list[str]:
    """نکات امنیتی که در محیط production باید رعایت شوند (فقط هشدار؛ برنامه را متوقف نمی‌کند)."""
    if not s.is_production:
        return []
    out = []
    if not (s.basic_auth_user and s.basic_auth_password):
        out.append("BASIC_AUTH_USER/BASIC_AUTH_PASSWORD تنظیم نشده است؛ مطمئن شوید دسترسی با Nginx (Basic Auth/VPN) محدود شده است.")
    if s.docs_enabled:
        out.append("DOCS_ENABLED=true است؛ Swagger (/api/docs) در production را خاموش یا محدود کنید.")
    if not s.allowed_hosts:
        out.append("ALLOWED_HOSTS خالی است؛ برای جلوگیری از Host header attack دامنهٔ خود را تنظیم کنید.")
    return out


def init_db() -> None:
    info = run_migrations(engine)
    if info["applied"] and not info["fresh"]:
        log.info("Database migrated: %s", info)
    s = get_settings()
    if s.seed_on_startup:
        with SessionLocal() as db:
            if not is_seeded(db):
                seed_defaults(db)
                log.info("Initial data seeded")
    harden_runtime_paths(s)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    init_db()
    log.info("CapitalPilot %s started (env=%s)", __version__, get_settings().app_env)
    for w in production_warnings(get_settings()):
        log.warning("هشدار امنیتی: %s", w)
    scheduler = None
    if get_settings().scheduler_enabled:
        from .services.marketdata.scheduler import get_scheduler
        scheduler = get_scheduler()
        scheduler.start()
    yield
    if scheduler is not None:
        scheduler.stop()


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

    if s.allowed_host_list:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=s.allowed_host_list)
    if s.cors_origin_list:
        app.add_middleware(CORSMiddleware, allow_origins=s.cors_origin_list, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                           allow_headers=["Content-Type", "Authorization"], allow_credentials=False, max_age=600)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        if s.is_production and request.url.scheme == "https":
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        if request.url.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    for r in (core, catalog, assets, portfolios, transactions, prices, market, iranmarket, search, analytics, reports, data):
        app.include_router(r.router)

    @app.get("/api/health", tags=["core"])
    def health():
        return {"status": "ok", "version": __version__}

    @app.get("/api/{path:path}", include_in_schema=False)
    def api_404(path: str):
        return JSONResponse(status_code=404, content={"error": {"code": "not_found", "message": "مسیر API یافت نشد.", "details": None}})

    app.mount("/static", RevalidatingStaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
