import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from .config import settings
from .database import SessionLocal
from .dbcheck import assert_database_current
from .routers import auth, students, exams, allotments, results, admin, campus, documents, catalogue, reports, docproc, seating, notifications, communications, data_management, analytics, integration, vsb, vsb_alloc, portal, operations, public_live, live_admin
from . import doc_models  # register document-processing tables on SQLAlchemy metadata
from .security import get_secret_key, verify_password, LEGACY_DEFAULT_PASSWORD

VERSION = "0.9.0"
_DOC_PATHS = ("/docs", "/redoc", "/openapi.json")
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; object-src 'none'; base-uri 'self'; form-action 'self'; "
       "frame-ancestors 'none'")


def _check_production_config() -> None:
    """Refuse unsafe configuration instead of silently running with it."""
    if "*" in settings.cors_origin_list:
        raise RuntimeError("CORS_ORIGINS must list explicit origins, not '*'")
    if settings.environment == "production":
        bad = [o for o in settings.cors_origin_list if not o.startswith("https://")]
        if bad:
            raise RuntimeError(f"CORS_ORIGINS must use https:// in production (found {bad[0]})")
        if not settings.public_base_url.startswith("https://"):
            raise RuntimeError("PUBLIC_BASE_URL must be https:// in production (reset links are built from it)")


def _refuse_legacy_default_password() -> None:
    """A database upgraded from 0.1.0 may still contain admin / ChangeMe123!. Never run with it."""
    from sqlalchemy import select
    from . import models
    db = SessionLocal()
    try:
        for u in db.scalars(select(models.User).where(models.User.active == True)).all():  # noqa: E712
            if verify_password(LEGACY_DEFAULT_PASSWORD, u.password_hash):
                raise RuntimeError(
                    f"Account '{u.username}' still uses the well-known starter password. "
                    f"Change it first:  python -m app.cli reset-password {u.username}")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_secret_key()              # refuses to start with a missing/weak key
    _check_production_config()
    from . import notifications as _nt, scheduler as _sched
    _nt.check_timezone()          # APP_TIMEZONE must be a real IANA zone
    assert_database_current()     # refuses to start on an un-migrated database
    _refuse_legacy_default_password()
    if settings.seed_demo:
        if settings.environment == "production":
            raise RuntimeError("SEED_DEMO must not be enabled when ENVIRONMENT=production")
        from .seed import seed_demo
        db = SessionLocal()
        try:
            seed_demo(db)
        finally:
            db.close()
    try:
        from .vsb_live import render as _render
        _render.purge_obsolete_cache()    # page images cached by an older release are never served again
    except Exception:  # noqa: BLE001 - cache housekeeping must never block start-up
        pass
    _sched.start()                # reminders, scheduled announcements, e-mail queue (SCHEDULER_ENABLED=false to disable)
    try:
        yield
    finally:
        _sched.stop()


def create_app() -> FastAPI:
    docs = settings.enable_docs
    app = FastAPI(title="Exam Monitor Ultimate API", version=VERSION, lifespan=lifespan,
                  description="Independent student-convenience project. Use synthetic data until the "
                              "institution authorizes real data. Phase 2: examination management (subjects, "
                              "terms, eligibility, scheduling), rule-based seat allocation with preview/approval, "
                              "manual correction with history, and seating/allocation reports with CSV/XLSX/PDF export.",
                  docs_url="/docs" if docs else None, redoc_url="/redoc" if docs else None,
                  openapi_url="/openapi.json" if docs else None)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=False,
                       allow_methods=["GET", "POST", "PATCH", "DELETE"],
                       allow_headers=["Authorization", "Content-Type"], max_age=600)

    @app.middleware("http")
    async def same_origin_for_writes(request: Request, call_next):
        """CSRF defence in depth. The API authenticates with a bearer header (no ambient cookie), so a
        cross-site page cannot ride a session; additionally refuse state-changing requests whose Origin
        is neither this host nor an allowed origin."""
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            origin = request.headers.get("origin")
            if origin and origin != "null":
                from urllib.parse import urlparse
                host_ok = urlparse(origin).netloc == request.headers.get("host", "")
                if not host_ok and origin not in settings.cors_origin_list:
                    return JSONResponse({"detail": "Cross-site request refused"}, status_code=403)
            elif origin == "null":
                return JSONResponse({"detail": "Cross-site request refused"}, status_code=403)
        return await call_next(request)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        h = response.headers
        h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        h.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "no-referrer")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if request.url.path.startswith("/api/"):
            h.setdefault("Cache-Control", "no-store")
        if not request.url.path.startswith(_DOC_PATHS):  # Swagger UI needs inline scripts/CDN
            h.setdefault("Content-Security-Policy", CSP)
        if settings.environment == "production":
            h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    @app.get("/api/health", tags=["Health"])
    def health():
        return {"status": "ok", "service": "exam-monitor-api", "version": VERSION}

    @app.get("/api/ready", tags=["Health"])
    def readiness():
        from sqlalchemy import text
        from fastapi import HTTPException
        try:
            with SessionLocal() as db:
                db.execute(text("SELECT 1"))
            return {"status": "ready", "database": "reachable"}
        except Exception:
            raise HTTPException(status_code=503, detail="Database is not ready")

    @app.get("/api/config", tags=["Health"])
    def public_config():
        return {"college_name": settings.college_name, "product_name": "Exam Monitor Ultimate",
                "show_names": settings.public_show_names}

    for r in (auth.router, students.router, exams.router, allotments.router, results.router, admin.router, campus.router, documents.router,
              catalogue.router, reports.router, docproc.router, seating.router, notifications.router, communications.router, data_management.router, analytics.router, integration.router, vsb.router, vsb_alloc.router, portal.router, operations.router, public_live.router, live_admin.router):
        app.include_router(r)

    # Public student portal: /portal redirects to /portal/ so StaticFiles serves portal/index.html
    @app.get("/portal", tags=["Portal"], include_in_schema=False)
    def portal_redirect():
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/portal/", status_code=302)

    app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
    @app.exception_handler(SQLAlchemyError)
    async def _database_unavailable(request, exc):          # noqa: ANN001 - FastAPI handler
        """A database problem must never show internals to the public: log it, answer 503 and let clients retry."""
        logging.getLogger("exam_monitor").error("database error on %s %s: %s", request.method, request.url.path, type(exc).__name__)
        return JSONResponse({"detail": "The service is temporarily unavailable. Please try again shortly."}, status_code=503,
                            headers={"Retry-After": "30"})

    return app


app = create_app()
