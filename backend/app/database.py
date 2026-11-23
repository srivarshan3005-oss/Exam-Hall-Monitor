"""Engine, session factory and transaction helpers (SQLite for a single PC, PostgreSQL for production).

Phase 8.1 hardening
* `normalize_database_url` accepts the usual postgres:// / postgresql:// spellings and selects the psycopg 3 driver.
* SQLite: foreign keys ON, WAL journal, busy timeout, synchronous=NORMAL (safe with WAL) - set on every connection.
* PostgreSQL: bounded pool, pre-ping, recycle, UTC session time zone, optional statement timeout.
* `session_scope()` / `get_db()` always roll back on error and close the session.
"""
from contextlib import contextmanager
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from .config import settings


def normalize_database_url(url: str) -> str:
    """postgres://... and postgresql://... -> postgresql+psycopg://... (psycopg 3 is the supported driver)."""
    u = (url or "").strip()
    for prefix in ("postgres://", "postgresql://"):
        if u.startswith(prefix):
            return "postgresql+psycopg://" + u[len(prefix):]
    return u


def _is_sqlite_memory(url) -> bool:
    return url.get_backend_name() == "sqlite" and (not url.database or url.database == ":memory:")


def build_engine(database_url: str | None = None):
    url_text = normalize_database_url(database_url or settings.database_url)
    url = make_url(url_text)
    if url.get_backend_name() == "sqlite":
        eng = create_engine(url_text, pool_pre_ping=True,
                            connect_args={"check_same_thread": False,
                                          "timeout": max(settings.sqlite_busy_timeout_ms, 0) / 1000})
        use_wal = settings.sqlite_wal and not _is_sqlite_memory(url)

        @event.listens_for(eng, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):
            cur = dbapi_connection.cursor()
            cur.execute("PRAGMA foreign_keys=ON")                       # enforce FKs / ON DELETE rules
            cur.execute(f"PRAGMA busy_timeout={int(settings.sqlite_busy_timeout_ms)}")
            if use_wal:
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()
        return eng
    options = ["-c timezone=UTC"]
    if settings.db_statement_timeout_ms > 0:
        options.append(f"-c statement_timeout={int(settings.db_statement_timeout_ms)}")
    kwargs = dict(pool_pre_ping=True, pool_size=settings.db_pool_size, max_overflow=settings.db_max_overflow,
                  pool_timeout=settings.db_pool_timeout_seconds, pool_recycle=settings.db_pool_recycle_seconds)
    if url.get_backend_name() == "postgresql":
        kwargs["connect_args"] = {"options": " ".join(options)}
    return create_engine(url_text, **kwargs)


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    # Deliberately NO naming_convention: Alembic's op.create_table applies the target metadata's convention, which would
    # silently change what the already-released migrations produce on a fresh database (and make fresh and upgraded
    # databases differ). Constraint-name parity on PostgreSQL is handled in dbcheck._bootstrap_postgresql instead.
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def session_scope():
    """Unit of work for scripts and background jobs: commit on success, roll back on any error."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
