"""Alembic helpers: run migrations safely, verify the database is up to date, audit the schema.

Safety properties of `migrate()` (Phase 8.1)
* One migration at a time: a PostgreSQL advisory lock / an exclusive lock file next to the SQLite database makes a
  second process (a second worker, a CLI call during start-up) wait, then find the database already current.
* Each revision is atomic (see migrations/env.py): a failure leaves the database at the last good revision.
* SQLite file databases are copied next to themselves before any upgrade of an existing database
  (`<name>.pre-migration-<from>-to-<to>-<UTC time>.bak`, disable with MIGRATION_SNAPSHOT=false).
"""
import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.autogenerate import compare_metadata
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from .config import settings
from .database import engine, Base

log = logging.getLogger("exam_monitor.dbcheck")
BACKEND_DIR = Path(__file__).resolve().parent.parent
BASELINE_REVISION = "0001"
_PG_MIGRATION_LOCK_KEY = 8_100_002
_LOCK_TIMEOUT_SECONDS = 300
_thread_lock = threading.Lock()          # in-process guard (also covers in-memory SQLite)


def alembic_config(url: str | None = None) -> Config:
    from .database import normalize_database_url
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", normalize_database_url(url or settings.database_url).replace("%", "%%"))
    return cfg


def head_revision() -> str:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def current_revision() -> str | None:
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def is_legacy_database() -> bool:
    """Tables created by the 0.1.0 starter (create_all) but never migrated."""
    names = set(inspect(engine).get_table_names())
    return "students" in names and "alembic_version" not in names


def _sqlite_path() -> Path | None:
    url = make_url(str(engine.url))
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return None
    p = Path(url.database)
    return p if p.is_absolute() else (Path.cwd() / p)


@contextmanager
def _migration_lock():
    """Cross-process mutual exclusion for schema changes."""
    deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
    if not _thread_lock.acquire(timeout=_LOCK_TIMEOUT_SECONDS):
        raise RuntimeError("Timed out waiting for another migration in this process to finish")
    try:
        if engine.dialect.name == "postgresql":
            with engine.connect() as conn:
                conn.exec_driver_sql("SELECT pg_advisory_lock(%s)" % _PG_MIGRATION_LOCK_KEY)
                try:
                    yield
                finally:
                    conn.exec_driver_sql("SELECT pg_advisory_unlock(%s)" % _PG_MIGRATION_LOCK_KEY)
                    conn.commit()
            return
        path = _sqlite_path()
        if path is None:
            yield
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = path.with_name(path.name + ".migrate.lock")
        with open(lock_path, "a+b") as fh:
            while True:
                try:
                    _try_lock(fh)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise RuntimeError(f"Timed out waiting for another process to finish migrating {path.name}. "
                                           f"If no migration is running, delete {lock_path.name} and retry.")
                    time.sleep(0.2)
            try:
                yield
            finally:
                _unlock(fh)
    finally:
        _thread_lock.release()


def _try_lock(fh) -> None:
    if os.name == "nt":
        import msvcrt
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(fh) -> None:
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def snapshot_sqlite(from_rev: str | None, to_rev: str) -> Path | None:
    """Consistent copy of the SQLite file (uses SQLite's online backup API, safe while the file is in use)."""
    path = _sqlite_path()
    if path is None or not path.is_file() or not settings.migration_snapshot:
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = path.with_name(f"{path.name}.pre-migration-{from_rev or 'legacy'}-to-{to_rev}-{stamp}.bak")
    src = sqlite3.connect(str(path))
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    log.warning("Database copied to %s before upgrading %s -> %s", target.name, from_rev or "legacy", to_rev)
    return target


def _bootstrap_postgresql(head: str) -> None:
    """Create the CURRENT schema in an empty PostgreSQL database and stamp it as `head`, in one transaction.

    Why not replay 0001..0009? Those released revisions were written and only ever run on SQLite (they use integer
    boolean defaults, `active = 1`, SQLite batch rebuilds) and cannot complete on PostgreSQL - so no PostgreSQL database
    can exist at a revision below 0010, and an empty one has no history to preserve. Released migration files are never
    edited. The result is verified equal to the models by `audit_schema()` / `db-audit` and by the test-suite."""
    from . import models, doc_models  # noqa: F401  (register every table)
    script = ScriptDirectory.from_config(alembic_config())
    with engine.begin() as conn:                       # DDL is transactional on PostgreSQL: all or nothing
        Base.metadata.create_all(conn)
        # PostgreSQL names an unnamed UNIQUE '<table>_<col>_key'; the released migrations named most of them
        # 'uq_<table>_<col>'. Use that spelling everywhere so a later migration can refer to them by name on any database.
        insp = inspect(conn)
        for table in insp.get_table_names():
            for uq in insp.get_unique_constraints(table):
                cols = uq["column_names"]
                if len(cols) == 1 and uq["name"] == f"{table}_{cols[0]}_key":
                    conn.exec_driver_sql(f'ALTER TABLE "{table}" RENAME CONSTRAINT "{uq["name"]}" TO "uq_{table}_{cols[0]}"')
        MigrationContext.configure(conn).stamp(script, head)
    log.warning("Empty PostgreSQL database initialised directly at revision %s", head)


def migrate() -> str:
    """Bring the database to head. Safe to call repeatedly and from several processes at once.
    * SQLite: a legacy 0.1.0 database is stamped as the baseline first; then the ordered revisions run
      (each atomic), after a safety copy of an existing file.
    * PostgreSQL: an empty database is initialised at head (see _bootstrap_postgresql); a database that already has
      migration history is upgraded through the ordered revisions."""
    cfg = alembic_config()
    with _migration_lock():
        head = head_revision()
        if engine.dialect.name == "postgresql":
            tables = set(inspect(engine).get_table_names())
            if not tables:
                _bootstrap_postgresql(head)
            elif "alembic_version" not in tables:
                raise RuntimeError(
                    "This PostgreSQL database contains tables but no migration history (alembic_version). Nothing was "
                    "changed. Restore a backup taken before the problem, or see docs/MIGRATIONS.md.")
        elif is_legacy_database():
            snapshot_sqlite(None, head)
            command.stamp(cfg, BASELINE_REVISION)
        cur = current_revision()
        if cur != head:
            if cur is not None:                      # an existing database is being upgraded (not a fresh one)
                snapshot_sqlite(cur, head)
            command.upgrade(cfg, "head")
    engine.dispose()    # AFTER the lock is released: drop pooled connections that predate the schema change
    return head


def assert_database_current() -> None:
    cur, head = current_revision(), head_revision()
    if cur != head:
        raise RuntimeError(
            f"Database schema is at revision {cur or 'none'} but the application needs {head}. "
            "Run:  python -m app.cli migrate")


# ---------------------------------------------------------------------------------------------- audit
_RULES = [  # (table, constraint, predicate every valid row satisfies) - keep in step with migration 0010
    ("users", "ck_users_role", "role IN ('super_admin','admin','staff','invigilator','student')"),
    ("users", "ck_users_status", "status IN ('active','pending','suspended')"),
    ("exams", "ck_exams_status", "status IN ('draft','published','completed')"),
    ("results", "ck_results_marks_range", "marks >= 0 AND max_marks > 0 AND marks <= max_marks"),
    ("allotments", "ck_allotments_hall_seat_nonblank", "length(trim(hall)) > 0 AND length(trim(seat)) > 0"),
]


def audit_schema() -> dict:
    """Read-only report: revision, drift between the database and the models, constraints that could not be added
    because existing rows violate them, and duplicate student/account links. Never modifies anything."""
    from . import models, doc_models  # noqa: F401  (register every table)
    report: dict = {"revision": current_revision(), "head": head_revision(), "drift": [], "missing_constraints": [],
                    "violations": {}, "duplicate_student_links": [], "foreign_key_violations": []}
    with engine.connect() as conn:
        mc = MigrationContext.configure(conn, opts={"compare_type": True})
        report["drift"] = [repr(d) for d in compare_metadata(mc, Base.metadata)]
        insp = inspect(conn)
        for table, name, predicate in _RULES:
            if name not in {c["name"] for c in insp.get_check_constraints(table)}:
                bad = conn.execute(text(f"SELECT COUNT(*) FROM {table} WHERE NOT ({predicate})")).scalar() or 0
                report["missing_constraints"].append(name)
                if bad:
                    report["violations"][name] = bad
        report["duplicate_student_links"] = [r[0] for r in conn.execute(text(
            "SELECT student_id FROM users WHERE student_id IS NOT NULL GROUP BY student_id HAVING COUNT(*) > 1"))]
        if conn.dialect.name == "sqlite":
            report["foreign_key_violations"] = [tuple(r) for r in conn.execute(text("PRAGMA foreign_key_check"))]
    report["ok"] = not (report["revision"] != report["head"] or report["drift"] or report["missing_constraints"]
                        or report["duplicate_student_links"] or report["foreign_key_violations"])
    return report
