"""Phase 8.1: database architecture - initialisation, migrations (fresh + upgrade), constraints, transactions,
duplicates, concurrency and time-zone behaviour.

Runs on SQLite by default. Tests parametrised with `dbkind` also run on PostgreSQL when TEST_POSTGRES_URL points at a
server-level URL whose role may CREATE DATABASE (e.g. postgresql://em:pw@localhost/postgres); otherwise those cases are
SKIPPED (never reported as passed). Set TEST_DATABASE_URL to run the *entire* suite on PostgreSQL.
"""
import os
import shutil
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import bindparam, create_engine, inspect, select, text, func
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from app import dbcheck, models, doc_models
from app.config import settings
from app.dbtypes import UTCDateTime
from app.database import build_engine, normalize_database_url, session_scope, SessionLocal, engine as app_engine
from app.dbutil import lock_allocation
from conftest import make_student, make_exam, make_user, REG1, REG2, REG3

BACKEND = Path(__file__).resolve().parents[1]
PREVIOUS_HEAD = "0009"        # the schema shipped with Phase 7.1
HEAD = "0016"
PG_ADMIN = os.environ.get("TEST_POSTGRES_URL")


# ----------------------------------------------------------------------------------------------- helpers
def _drop_pg_database(admin, name, attempts=20):
    """DROP DATABASE ... WITH (FORCE) can be refused for a moment when PostgreSQL's own autovacuum worker (a different
    role) is attached to the database. That is a clean-up race, not a test failure: retry, then give up loudly."""
    from sqlalchemy.exc import ProgrammingError
    for attempt in range(attempts):
        try:
            with admin.connect() as c:
                c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            return
        except ProgrammingError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.5)


@pytest.fixture(params=["sqlite", "postgres"])
def dbkind(request):
    if request.param == "postgres" and not PG_ADMIN:
        pytest.skip("no PostgreSQL available (set TEST_POSTGRES_URL)")
    return request.param


@pytest.fixture()
def scratch_url(dbkind, tmp_path):
    """URL of a brand-new, empty database of the requested kind (dropped afterwards)."""
    if dbkind == "sqlite":
        yield "sqlite:///" + (tmp_path / "scratch.db").as_posix()
        return
    name = "em_t_" + uuid.uuid4().hex[:10]
    admin = create_engine(normalize_database_url(PG_ADMIN), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    url = make_url(normalize_database_url(PG_ADMIN)).set(database=name).render_as_string(hide_password=False)
    try:
        yield url
    finally:
        _drop_pg_database(admin, name)
        admin.dispose()


@contextmanager
def use_database(url):
    """Point app.dbcheck (migrate/audit/current_revision) at another database for the duration of a test."""
    eng = build_engine(url)
    old_engine, old_url = dbcheck.engine, settings.database_url
    dbcheck.engine, settings.database_url = eng, url
    try:
        yield eng
    finally:
        dbcheck.engine, settings.database_url = old_engine, old_url
        eng.dispose()


def upgrade_to(url, revision):
    command.upgrade(dbcheck.alembic_config(url), revision)


def at_previous_schema(url):
    """A database that has already applied revisions up to PREVIOUS_HEAD (0009).
    SQLite: genuine - the released migrations 0001..0009 are really executed.
    PostgreSQL: SIMULATED - no released build can create a PostgreSQL database at 0009 (the released chain cannot run
    there), so the head schema is created and migration 0010 is downgraded away, which leaves exactly the 0009 shape
    with alembic_version = 0009. Must be called inside use_database()."""
    if url.startswith("sqlite"):
        upgrade_to(url, PREVIOUS_HEAD)
    else:
        dbcheck.migrate()
        command.downgrade(dbcheck.alembic_config(url), PREVIOUS_HEAD)
    assert dbcheck.current_revision() == PREVIOUS_HEAD


def structure(eng):
    """Dialect-neutral description of a schema (names, nullability, keys, indexes, ON DELETE rules, checks)."""
    insp = inspect(eng)
    out = {}
    for t in sorted(insp.get_table_names()):
        out[t] = {
            "columns": sorted((c["name"], bool(c["nullable"])) for c in insp.get_columns(t)),
            "pk": tuple(insp.get_pk_constraint(t)["constrained_columns"]),
            "fks": sorted((tuple(f["constrained_columns"]), f["referred_table"], tuple(f["referred_columns"]),
                           f["options"].get("ondelete")) for f in insp.get_foreign_keys(t)),
            "unique": sorted((u["name"], tuple(u["column_names"])) for u in insp.get_unique_constraints(t)),
            # PostgreSQL also lists the unique index that backs each unique constraint; SQLite does not. Skip those so
            # both dialects are described the same way (the constraint itself is listed under "unique").
            "indexes": sorted((i["name"], tuple(i["column_names"]), bool(i["unique"]))
                              for i in insp.get_indexes(t) if not i.get("duplicates_constraint")),
            "checks": sorted(c["name"] for c in insp.get_check_constraints(t) if c.get("name")),
        }
    return out


# SHA-256 of the released revision files, taken from the Phase 7.1 archive. Released migrations are history:
# they must never be edited (add a new revision instead).
RELEASED_MIGRATION_SHA256 = {
    '0001_baseline_starter_schema.py': 'ceb3451fb99c4704b5faaf040ed4989921a86a4dc7c586f46ce295585e4aa1e7',
    '0002_security_and_hall_finder.py': 'b08447e90185e43b0c98d715802ab7af22a043ab41ed6c342a9a88e2be0913f9',
    '0003_announcements.py': '5ab99e36c92ffe0aa972235b78e78afbea9b194f614a0f24e9805e173915510c',
    '0004_normalized_hall_inventory.py': '2bf3899193779735cd95a57ae13ffc7277b53600bfbcf7e8132ab0149ed2cf3c',
    '0005_exam_management_and_allocation.py': '26c80c3b791433fef9824efd209f0e6d78320aa883e4d2ab2ac2dad3dfcecb4a',
    '0006_document_processing.py': '6019711b263300c3b6a1869e58167682ce684d103f9e153176bf0aeb0c68812b',
    '0007_auth_security_rbac.py': 'e60fe1ea47936a9625e2372e5775201c3bc2d030d2e1c588b5b2d7c1b7a69bbb',
    '0008_seating_import.py': '471dc598c7b33bcd533268e94424ae031fb3130c0a6a79e84e1755a1ac65f71b',
    '0009_notifications_email.py': '56b00b3c17563ea83114b1f76485841d2e04052ce244c8667bafb7a761e4ba39'
}


def rows(conn, table):
    return [dict(r._mapping) for r in conn.execute(text(f"SELECT * FROM {table} ORDER BY id"))]


NOW = datetime(2026, 11, 14, 9, 0, tzinfo=timezone.utc)


def seed_previous_schema(eng, *, dirty=False):
    """Representative data written at the Phase 7.1 schema (0009), using plain SQL like an old release would."""
    with eng.begin() as c:
        for i, (reg, name) in enumerate([(REG1, "Asha Menon"), (REG2, "Ravi Kumar"), (REG3, "Meera Nair")], 1):
            c.execute(text("INSERT INTO students (id, register_number, full_name, department, year, active) "
                           "VALUES (:i,:r,:n,'ECE',2,:a)"), {"i": i, "r": reg, "n": name, "a": True})
        c.execute(text("INSERT INTO users (id, username, password_hash, role, active, student_id, status) "
                       "VALUES (1,'admin1','x','admin',:a,NULL,'active'),(2,'stud1','x','student',:a,1,'active')"), {"a": True})
        c.execute(text("INSERT INTO exams (id, title, subject_code, exam_date, start_time, end_time, venue, status) VALUES "
                       "(1,'Maths','MA101','2027-01-15','09:30','12:30','Main','published'),"
                       "(2,'Physics','PH101','2027-01-16','09:30','12:30','Main','draft')"))
        c.execute(text("INSERT INTO allotments (id, student_id, exam_id, hall, seat) VALUES "
                       "(1,1,1,'HALL-A','1'),(2,2,1,'HALL-A','2')"))
        c.execute(text("INSERT INTO results (id, student_id, exam_id, marks, max_marks, grade, published) "
                       "VALUES (1,1,1,81.5,100,'A',:p)"), {"p": True})
        c.execute(text("INSERT INTO audit_logs (id, actor, action, target, created_at) VALUES (1,'admin1','seed','x',:t)")
                  .bindparams(bindparam("t", type_=UTCDateTime)), {"t": NOW})
        c.execute(text("INSERT INTO announcements (id, title, body, published, created_by, created_at, updated_at) "
                       "VALUES (1,'Hello','World',:p,'admin1',:t,:t)").bindparams(bindparam("t", type_=UTCDateTime)),
                  {"p": True, "t": NOW})
        c.execute(text("INSERT INTO notifications (id, user_id, category, priority, title, body, event_key, created_at) "
                       "VALUES (1,2,'exam','normal','Seat','Hall A','k1',:t)").bindparams(bindparam("t", type_=UTCDateTime)),
                  {"t": NOW})
        if dirty:   # data an older release could have accepted although today's rules would reject it
            c.execute(text("INSERT INTO users (id, username, password_hash, role, active, student_id, status) "
                           "VALUES (3,'stud1b','x','student',:a,1,'active'),(4,'odd','x','wizard',:a,NULL,'active')"), {"a": True})
            c.execute(text("INSERT INTO results (id, student_id, exam_id, marks, max_marks, grade, published) "
                           "VALUES (2,2,1,120,100,'?',:p)"), {"p": False})
            c.execute(text("INSERT INTO exams (id, title, subject_code, exam_date, start_time, end_time, venue, status) "
                           "VALUES (3,'Legacy','LG1','2027-01-17','09:30','12:30','Main','archived')"))
    return ["students", "users", "exams", "allotments", "results", "audit_logs", "announcements", "notifications"]


# ------------------------------------------------------------------------------------------- initialisation
def test_url_normalisation():
    assert normalize_database_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_database_url("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_database_url("postgresql+psycopg://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_database_url("sqlite:///x.db") == "sqlite:///x.db"


def test_sqlite_connection_pragmas(tmp_path):
    eng = build_engine("sqlite:///" + (tmp_path / "p.db").as_posix())
    with eng.connect() as c:
        pragma = lambda name: c.execute(text(f"PRAGMA {name}")).scalar()  # noqa: E731
        assert pragma("foreign_keys") == 1
        assert str(pragma("journal_mode")).lower() == "wal"
        assert pragma("busy_timeout") == settings.sqlite_busy_timeout_ms
        assert pragma("synchronous") == 1          # NORMAL
    eng.dispose()


def test_sqlite_memory_database_skips_wal():
    eng = build_engine("sqlite://")
    with eng.connect() as c:
        assert c.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert str(c.execute(text("PRAGMA journal_mode")).scalar()).lower() == "memory"
    eng.dispose()


def test_postgres_connection_uses_utc_session_timezone():
    if not PG_ADMIN:
        pytest.skip("no PostgreSQL available (set TEST_POSTGRES_URL)")
    eng = build_engine(PG_ADMIN)
    with eng.connect() as c:
        assert c.execute(text("SHOW timezone")).scalar() == "UTC"
    eng.dispose()


# ----------------------------------------------------------------------------------- fresh creation + schema shape
def test_fresh_database_reaches_head_and_matches_models(scratch_url):
    with use_database(scratch_url) as eng:
        assert dbcheck.migrate() == HEAD
        assert dbcheck.current_revision() == HEAD
        report = dbcheck.audit_schema()
        assert report["drift"] == [] and report["ok"], report
        tables = set(inspect(eng).get_table_names())
        assert {"users", "students", "exams", "allotments", "results", "notifications", "alembic_version"} <= tables
        with eng.connect() as c:
            assert c.execute(text("SELECT COUNT(*) FROM alembic_version")).scalar() == 1


def test_every_table_has_primary_key_and_every_fk_column_is_indexed(scratch_url):
    with use_database(scratch_url) as eng:
        dbcheck.migrate()
        insp = inspect(eng)
        unindexed = []
        for t in insp.get_table_names():
            assert insp.get_pk_constraint(t)["constrained_columns"], f"{t} has no primary key"
            led = [x["column_names"] for x in insp.get_indexes(t)] + \
                  [u["column_names"] for u in insp.get_unique_constraints(t)] + [insp.get_pk_constraint(t)["constrained_columns"]]
            for fk in insp.get_foreign_keys(t):
                cols = fk["constrained_columns"]
                if not any(x[:len(cols)] == cols for x in led):
                    unindexed.append((t, cols))
        assert unindexed == []


def test_expected_constraints_exist_after_migration(scratch_url):
    with use_database(scratch_url) as eng:
        dbcheck.migrate()
        insp = inspect(eng)
        uniq = lambda t: {u["name"] for u in insp.get_unique_constraints(t)}  # noqa: E731
        assert "uq_allotments_student_exam" in uniq("allotments") and "uq_allotments_exam_hall_seat" in uniq("allotments")
        assert "uq_results_student_exam" in uniq("results")
        assert "uq_notifications_user_event" in uniq("notifications")
        users_idx = {i["name"]: i for i in insp.get_indexes("users")}
        assert users_idx["uq_users_student_id"]["unique"]
        assert {c["name"] for c in insp.get_check_constraints("results")} == {"ck_results_marks_range"}
        assert {"ck_users_role", "ck_users_status"} <= {c["name"] for c in insp.get_check_constraints("users")}
        by_name = {fk["referred_table"]: fk["options"].get("ondelete") for fk in insp.get_foreign_keys("auth_sessions")}
        assert by_name["users"] == "CASCADE"


# ----------------------------------------------------------------------------------- upgrade from previous schema
def test_upgrade_from_previous_schema_preserves_every_row(scratch_url):
    with use_database(scratch_url) as eng:
        at_previous_schema(scratch_url)
        tables = seed_previous_schema(eng)
        with eng.connect() as c:
            before = {t: rows(c, t) for t in tables}
        assert dbcheck.migrate() == HEAD
        with eng.connect() as c:
            after = {t: rows(c, t) for t in tables}
        assert after == before, "an upgrade must not change a single existing row"
        assert dbcheck.audit_schema()["ok"]
        # new structures are present
        insp = inspect(eng)
        assert any(i["name"] == "uq_users_student_id" and i["unique"] for i in insp.get_indexes("users"))
        assert "ck_exams_status" in {c["name"] for c in insp.get_check_constraints("exams")}
        # repeat = no-op
        assert dbcheck.migrate() == HEAD


def test_upgrade_makes_a_consistent_safety_copy_of_a_sqlite_file(tmp_path):
    url = "sqlite:///" + (tmp_path / "live.db").as_posix()
    with use_database(url) as eng:
        upgrade_to(url, PREVIOUS_HEAD)
        seed_previous_schema(eng)
        dbcheck.migrate()
        copies = list(tmp_path.glob("live.db.pre-migration-*.bak"))
        assert len(copies) == 1 and f"-{PREVIOUS_HEAD}-to-{HEAD}-" in copies[0].name
        con = sqlite3.connect(copies[0])
        try:
            assert con.execute("SELECT COUNT(*) FROM students").fetchone()[0] == 3
            assert con.execute("SELECT version_num FROM alembic_version").fetchone()[0] == PREVIOUS_HEAD
        finally:
            con.close()
        dbcheck.migrate()                                           # already current -> no second copy
        assert len(list(tmp_path.glob("live.db.pre-migration-*.bak"))) == 1


def test_fresh_sqlite_database_makes_no_safety_copy(tmp_path):
    url = "sqlite:///" + (tmp_path / "new.db").as_posix()
    with use_database(url):
        dbcheck.migrate()
    assert list(tmp_path.glob("*.bak")) == []


def test_snapshot_can_be_disabled(tmp_path, monkeypatch):
    url = "sqlite:///" + (tmp_path / "live.db").as_posix()
    with use_database(url) as eng:
        upgrade_to(url, PREVIOUS_HEAD)
        monkeypatch.setattr(settings, "migration_snapshot", False)
        dbcheck.migrate()
    assert list(tmp_path.glob("*.bak")) == []


def test_legacy_starter_database_is_stamped_then_upgraded(tmp_path):
    """A 0.1.0 database (tables but no alembic_version) must be adopted, with its data intact."""
    url = "sqlite:///" + (tmp_path / "legacy.db").as_posix()
    with use_database(url) as eng:
        upgrade_to(url, "0001")
        with eng.begin() as c:
            c.execute(text("INSERT INTO students (id, register_number, full_name, department, year, active) "
                           "VALUES (1,:r,'Legacy Student','ECE',1,:a)"), {"r": REG1, "a": True})
            c.execute(text("DROP TABLE alembic_version"))
        assert dbcheck.is_legacy_database()
        assert dbcheck.migrate() == HEAD
        with eng.connect() as c:
            assert c.execute(text("SELECT full_name FROM students WHERE id=1")).scalar() == "Legacy Student"
        assert list(tmp_path.glob("legacy.db.pre-migration-legacy-to-*.bak"))


def test_dirty_legacy_data_is_kept_and_unsatisfiable_constraints_are_skipped(scratch_url):
    with use_database(scratch_url) as eng:
        at_previous_schema(scratch_url)
        tables = seed_previous_schema(eng, dirty=True)
        with eng.connect() as c:
            before = {t: rows(c, t) for t in tables}
        assert dbcheck.migrate() == HEAD                      # still succeeds
        with eng.connect() as c:
            assert {t: rows(c, t) for t in tables} == before   # nothing edited or deleted
        insp = inspect(eng)
        users_idx = {i["name"]: i for i in insp.get_indexes("users")}
        assert "uq_users_student_id" not in users_idx and not users_idx["ix_users_student_id"]["unique"]
        have = {c["name"] for t in ("users", "exams", "results", "allotments") for c in insp.get_check_constraints(t)}
        assert "ck_users_role" not in have and "ck_results_marks_range" not in have and "ck_exams_status" not in have
        assert "ck_users_status" in have and "ck_allotments_hall_seat_nonblank" in have   # satisfiable ones are added
        report = dbcheck.audit_schema()
        assert not report["ok"]
        assert report["duplicate_student_links"] == [1]
        assert report["violations"] == {"ck_users_role": 1, "ck_exams_status": 1, "ck_results_marks_range": 1}


def test_skipped_constraints_can_be_reapplied_after_the_data_is_corrected(scratch_url):
    """Documented recovery path (docs/MIGRATIONS.md): fix the reported rows, `alembic downgrade 0009`, `migrate`."""
    with use_database(scratch_url) as eng:
        at_previous_schema(scratch_url)
        tables = seed_previous_schema(eng, dirty=True)
        dbcheck.migrate()
        assert not dbcheck.audit_schema()["ok"]
        with eng.begin() as c:                                        # the administrator corrects the reported rows
            c.execute(text("UPDATE users SET student_id = NULL WHERE id = 3"))
            c.execute(text("UPDATE users SET role = 'staff' WHERE id = 4"))
            c.execute(text("UPDATE results SET marks = 100 WHERE id = 2"))
            c.execute(text("UPDATE exams SET status = 'draft' WHERE id = 3"))
        with eng.connect() as c:
            fixed = {t: rows(c, t) for t in tables}
        command.downgrade(dbcheck.alembic_config(scratch_url), PREVIOUS_HEAD)
        assert dbcheck.migrate() == HEAD
        report = dbcheck.audit_schema()
        assert report["ok"] and report["violations"] == {} and report["duplicate_student_links"] == [], report
        insp = inspect(eng)
        assert any(i["name"] == "uq_users_student_id" and i["unique"] for i in insp.get_indexes("users"))
        assert {"ck_users_role", "ck_users_status"} <= {c["name"] for c in insp.get_check_constraints("users")}
        with eng.connect() as c:
            assert {t: rows(c, t) for t in tables} == fixed            # re-applying changed no row


def test_downgrade_then_upgrade_round_trip_keeps_data(scratch_url):
    with use_database(scratch_url) as eng:
        at_previous_schema(scratch_url)
        tables = seed_previous_schema(eng)
        dbcheck.migrate()
        command.downgrade(dbcheck.alembic_config(scratch_url), PREVIOUS_HEAD)
        assert dbcheck.current_revision() == PREVIOUS_HEAD
        assert not [i for i in inspect(eng).get_indexes("users") if i["name"] == "uq_users_student_id"]
        with eng.connect() as c:
            assert [r["register_number"] for r in rows(c, "students")] == [REG1, REG2, REG3]
        assert dbcheck.migrate() == HEAD


# ------------------------------------------------------------------- migration failure, atomicity, duplicate runs
def _failing_script_dir(tmp_path):
    scripts = tmp_path / "migrations_with_failure"
    shutil.copytree(BACKEND / "migrations", scripts, ignore=shutil.ignore_patterns("__pycache__"))
    (scripts / "versions" / "0099_fails_halfway.py").write_text(
        'import sqlalchemy as sa\nfrom alembic import op\n'
        'revision = "0099"\ndown_revision = "0016"\nbranch_labels = None\ndepends_on = None\n\n'
        'def upgrade():\n'
        '    op.create_table("half_done", sa.Column("id", sa.Integer, primary_key=True))\n'
        '    op.add_column("students", sa.Column("temp_flag", sa.Integer, nullable=True))\n'
        '    raise RuntimeError("simulated failure in the middle of a migration")\n\n'
        'def downgrade():\n    pass\n')
    return scripts


def test_failed_migration_leaves_database_at_last_good_revision(scratch_url, tmp_path):
    with use_database(scratch_url) as eng:
        dbcheck.migrate()
        with eng.begin() as c:
            c.execute(text("INSERT INTO students (id, register_number, full_name, department, year, active) "
                           "VALUES (1,:r,'Keep Me','ECE',1,:a)"), {"r": REG1, "a": True})
        cfg = dbcheck.alembic_config(scratch_url)
        cfg.set_main_option("script_location", str(_failing_script_dir(tmp_path)))
        with pytest.raises(RuntimeError, match="simulated failure"):
            command.upgrade(cfg, "head")
        assert dbcheck.current_revision() == HEAD                      # version table not advanced
        insp = inspect(eng)
        assert "half_done" not in insp.get_table_names()                # DDL rolled back
        assert "temp_flag" not in {c["name"] for c in insp.get_columns("students")}
        with eng.connect() as c:
            assert c.execute(text("SELECT full_name FROM students WHERE id=1")).scalar() == "Keep Me"
        assert dbcheck.audit_schema()["ok"]


def test_concurrent_migrations_run_once(scratch_url, monkeypatch):
    calls = []                                   # every real schema build: ordered upgrade OR PostgreSQL bootstrap
    real_upgrade, real_boot = dbcheck.command.upgrade, dbcheck._bootstrap_postgresql
    monkeypatch.setattr(dbcheck.command, "upgrade", lambda *a, **k: (calls.append("upgrade"), real_upgrade(*a, **k))[1])
    monkeypatch.setattr(dbcheck, "_bootstrap_postgresql", lambda *a, **k: (calls.append("bootstrap"), real_boot(*a, **k))[1])
    with use_database(scratch_url) as eng:
        results, errors = [], []
        barrier = threading.Barrier(4)

        def worker():
            try:
                barrier.wait()
                results.append(dbcheck.migrate())
            except Exception as exc:       # noqa: BLE001
                errors.append(exc)
        threads = [threading.Thread(target=worker) for _ in range(4)]
        [t.start() for t in threads]
        [t.join(120) for t in threads]
        assert errors == [] and results == [HEAD] * 4
        assert len(calls) == 1, f"only one caller may actually build the schema, got {calls}"
        with eng.connect() as c:
            assert c.execute(text("SELECT COUNT(*) FROM alembic_version")).scalar() == 1


def test_application_refuses_unmigrated_database(scratch_url):
    with use_database(scratch_url):
        with pytest.raises(RuntimeError, match="python -m app.cli migrate"):
            dbcheck.assert_database_current()
        dbcheck.migrate()
        dbcheck.assert_database_current()


# ----------------------------------------------- a REAL database file written by the released Phase 7.1 build
REAL_RELEASE_DB = BACKEND / "tests" / "fixtures" / "phase71_release.sqlite3"


def _dump_all(path):
    con = sqlite3.connect(path)
    try:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN ('alembic_version') ORDER BY 1")]
        return {t: con.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall() for t in tables}
    finally:
        con.close()


def test_upgrade_of_a_real_phase71_database_file(tmp_path):
    """tests/fixtures/phase71_release.sqlite3 was produced by the untouched Phase 7.1 code (its own migrations and ORM):
    30 students, accounts, 3 exams, a verified hall with 40 seats, 30 allotments, 10 published results, announcement,
    audit row, notification. It is upgraded as a COPY, exactly like an installed system would be."""
    live = tmp_path / "exam_monitor.db"
    shutil.copy(REAL_RELEASE_DB, live)
    before = _dump_all(live)
    assert sum(len(v) for v in before.values()) > 100 and len(before["allotments"]) == 30
    con = sqlite3.connect(live)
    assert con.execute("SELECT version_num FROM alembic_version").fetchone()[0] == PREVIOUS_HEAD
    con.close()
    url = "sqlite:///" + live.as_posix()
    with use_database(url) as eng:
        structure_before = structure(eng)
        assert dbcheck.migrate() == HEAD
        after = _dump_all(live)
        # later additive migrations append nullable columns (e.g. 0016 adds map columns to halls): compare the ORIGINAL columns only
        trimmed = {t: ([tuple(r[:len(before[t][0])]) for r in after[t]] if before[t] else after[t]) for t in before}
        assert trimmed == before, "every row of every pre-existing table must be unchanged"
        # tables added by 0012/0013 (VSB integration) are new and must start empty
        assert all(after[t] == [] for t in set(after) - set(before)), "newly added tables must be empty"
        report = dbcheck.audit_schema()
        assert report["ok"] and report["drift"] == [] and report["foreign_key_violations"] == [], report
        structure_after = structure(eng)
        for table, old in structure_before.items():          # nothing that existed was changed or renamed
            new = structure_after[table]
            for key in ("columns", "pk", "fks", "unique"):
                if key == "columns":        # additive migrations may add nullable columns; every original column must be unchanged
                    assert [c for c in new[key] if c in old[key]] == old[key], (table, key)
                elif key == "fks":          # ... and new foreign keys (0016: halls.entrance_id) may be added, never removed/changed
                    assert all(f in new[key] for f in old[key]), (table, key)
                else:
                    assert new[key] == old[key], (table, key)
            assert set(old["indexes"]) <= set(new["indexes"]) and set(old["checks"]) <= set(new["checks"]), table
        assert dbcheck.migrate() == HEAD                        # idempotent
    copies = list(tmp_path.glob("exam_monitor.db.pre-migration-0009-to-0016-*.bak"))
    assert len(copies) == 1 and _dump_all(copies[0]) == before     # the safety copy is the original data
    con = sqlite3.connect(copies[0])
    assert con.execute("SELECT version_num FROM alembic_version").fetchone()[0] == PREVIOUS_HEAD
    con.close()
    con = sqlite3.connect(live)
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    con.close()


def _full_structure(eng):
    """structure() plus the SQL text of every CHECK (names alone would not notice a changed rule)."""
    insp = inspect(eng)
    out = structure(eng)
    for t in out:
        out[t]["checks"] = sorted((c["name"], " ".join(c["sqltext"].split())) for c in insp.get_check_constraints(t))
    return out


def test_replaying_released_migrations_reproduces_the_released_schema_exactly(tmp_path):
    """Regression: a metadata naming convention would silently rename constraints created by the released migrations
    (Alembic applies it inside op.create_table), making fresh and upgraded databases differ. Compares EVERY table of a
    database built by replaying 0001-0009 now with the database file written by the released Phase 7.1 build
    (column names/nullability, keys, foreign keys with ON DELETE, unique constraint names, indexes, CHECK name+SQL)."""
    released_copy = tmp_path / "released.db"
    shutil.copy(REAL_RELEASE_DB, released_copy)
    replay_url = "sqlite:///" + (tmp_path / "replay.db").as_posix()
    released_url = "sqlite:///" + released_copy.as_posix()
    with use_database(replay_url) as replayed:
        upgrade_to(replay_url, PREVIOUS_HEAD)
        replay_structure = _full_structure(replayed)
    with use_database(released_url) as released:
        released_structure = _full_structure(released)
    assert set(replay_structure) == set(released_structure)
    for table in released_structure:
        assert replay_structure[table] == released_structure[table], table
    # the specific names that a naming convention would have changed:
    assert [n for n, _ in replay_structure["halls"]["unique"]] == [None]
    assert "uq_subjects_code" in [n for n, _ in replay_structure["subjects"]["unique"]]


# ------------------------------------------------------- released history is immutable; ordering; PostgreSQL path
def test_released_migrations_are_byte_for_byte_unchanged():
    import hashlib
    for name, expected in RELEASED_MIGRATION_SHA256.items():
        actual = hashlib.sha256((BACKEND / "migrations" / "versions" / name).read_bytes()).hexdigest()
        assert actual == expected, f"{name} was edited. Released migrations are history - add a new revision instead."
    on_disk = {f.name for f in (BACKEND / "migrations" / "versions").glob("00*.py")}
    assert on_disk == set(RELEASED_MIGRATION_SHA256) | {"0010_schema_hardening.py", "0011_phase83_query_indexes.py", "0012_vsb_official_sources.py", "0013_vsb_allocation_workflow.py", "0014_vsb_verification_status.py", "0015_verification_status_rename_and_legacy.py", "0016_v7_live_monitoring.py"}


def test_migration_chain_is_linear_and_ordered():
    from alembic.script import ScriptDirectory
    script = ScriptDirectory.from_config(dbcheck.alembic_config())
    assert script.get_heads() == [HEAD]
    order = [r.revision for r in script.walk_revisions()][::-1]          # base -> head
    assert order == [f"{i:04d}" for i in range(1, 17)]
    for prev, rev in zip(order, order[1:]):
        assert script.get_revision(rev).down_revision == prev


def test_postgresql_empty_database_is_initialised_at_head_in_one_step():
    if not PG_ADMIN:
        pytest.skip("no PostgreSQL available (set TEST_POSTGRES_URL)")
    name = "em_t_" + uuid.uuid4().hex[:10]
    admin = create_engine(normalize_database_url(PG_ADMIN), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    url = make_url(normalize_database_url(PG_ADMIN)).set(database=name).render_as_string(hide_password=False)
    try:
        with use_database(url) as eng:
            assert inspect(eng).get_table_names() == []
            assert dbcheck.migrate() == HEAD
            assert dbcheck.current_revision() == HEAD
            assert dbcheck.audit_schema()["ok"]
            command.upgrade(dbcheck.alembic_config(url), "head")             # alembic agrees it is current: no-op
            command.downgrade(dbcheck.alembic_config(url), PREVIOUS_HEAD)    # 0010 is reversible on PostgreSQL too
            assert dbcheck.migrate() == HEAD
    finally:
        _drop_pg_database(admin, name)
        admin.dispose()


def test_postgresql_schema_is_equivalent_to_the_sqlite_migration_chain(tmp_path, scratch_url, dbkind):
    """The PostgreSQL bootstrap and the replayed SQLite history must yield the same structure."""
    if dbkind != "postgres":
        pytest.skip("compares the PostgreSQL schema with the SQLite chain")
    lite_url = "sqlite:///" + (tmp_path / "chain.db").as_posix()
    with use_database(lite_url) as lite:
        dbcheck.migrate()
        lite_structure = structure(lite)
    with use_database(scratch_url) as pg:
        dbcheck.migrate()
        pg_structure = structure(pg)
    assert set(lite_structure) == set(pg_structure)
    for table in lite_structure:
        lite_t, pg_t = dict(lite_structure[table]), dict(pg_structure[table])
        # The released SQLite revisions left a few unique constraints unnamed (SQLite cannot report a name for them);
        # for those compare the columns only. Every constraint that HAS a name in the chain must have the same name.
        named = {n for n, _ in lite_t.pop("unique") if n}
        pg_unique = pg_t.pop("unique")
        lite_unique = lite_structure[table]["unique"]
        assert sorted(c for _, c in lite_unique) == sorted(c for _, c in pg_unique), table
        assert named <= {n for n, _ in pg_unique}, (table, named, pg_unique)
        assert pg_t == lite_t, table


def test_raw_alembic_on_empty_postgresql_is_refused_with_guidance(scratch_url, dbkind):
    if dbkind != "postgres":
        pytest.skip("PostgreSQL-only")
    with use_database(scratch_url) as eng:
        with pytest.raises(RuntimeError, match="python -m app.cli migrate"):
            command.upgrade(dbcheck.alembic_config(scratch_url), "head")
        assert inspect(eng).get_table_names() == []                         # nothing half-created


def test_postgresql_tables_without_history_are_refused_and_left_untouched(scratch_url, dbkind):
    if dbkind != "postgres":
        pytest.skip("PostgreSQL-only")
    with use_database(scratch_url) as eng:
        with eng.begin() as c:
            c.execute(text("CREATE TABLE stray (id integer primary key, note text)"))
            c.execute(text("INSERT INTO stray VALUES (1, 'keep me')"))
        with pytest.raises(RuntimeError, match="no migration history"):
            dbcheck.migrate()
        with eng.connect() as c:
            assert c.execute(text("SELECT note FROM stray")).scalar() == "keep me"
        assert set(inspect(eng).get_table_names()) == {"stray"}


def test_postgresql_bootstrap_is_atomic(scratch_url, dbkind, monkeypatch):
    """If stamping fails after the tables were created, NOTHING may remain (otherwise the next start would find tables
    without history and refuse to run)."""
    if dbkind != "postgres":
        pytest.skip("PostgreSQL-only")
    with use_database(scratch_url) as eng:
        real = dbcheck.MigrationContext.configure
        monkeypatch.setattr(dbcheck.MigrationContext, "configure",
                            classmethod(lambda cls, *a, **k: (_ for _ in ()).throw(RuntimeError("stamp failed"))))
        with pytest.raises(RuntimeError, match="stamp failed"):
            dbcheck.migrate()
        assert inspect(eng).get_table_names() == []
        monkeypatch.setattr(dbcheck.MigrationContext, "configure", real)
        assert dbcheck.migrate() == HEAD


# ----------------------------------------------------------------------- constraints and relationships (suite DB)
def _hall(db, code="HALL-A", n=4, capacity=None):
    h = doc_models.Hall(code=code, display_name=code, capacity=capacity if capacity is not None else n, verified=True)
    db.add(h)
    db.flush()
    db.add_all([models.HallSeat(hall_id=h.id, seat_label=str(i), active=True) for i in range(1, n + 1)])
    db.commit()
    return h


def test_unique_constraints_reject_duplicates(db):
    s1, s2 = make_student(db, REG1), make_student(db, REG2)
    e = make_exam(db)
    db.add(models.Allotment(student_id=s1.id, exam_id=e.id, hall="H", seat="1"))
    db.commit()
    for student, hall, seat in ((s1, "H", "2"), (s2, "H", "1")):     # same student twice / same seat twice
        db.add(models.Allotment(student_id=student.id, exam_id=e.id, hall=hall, seat=seat))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    with pytest.raises(IntegrityError):                                # duplicate register number
        db.add(models.Student(register_number=REG1, full_name="Dup", department="X"))
        db.commit()
    db.rollback()
    make_user(db, "dupuser", "staff")
    with pytest.raises(IntegrityError):
        db.add(models.User(username="dupuser", password_hash="x", role="staff"))
        db.commit()
    db.rollback()
    db.add(models.Result(student_id=s1.id, exam_id=e.id, marks=1, max_marks=10))
    db.commit()
    with pytest.raises(IntegrityError):
        db.add(models.Result(student_id=s1.id, exam_id=e.id, marks=2, max_marks=10))
        db.commit()
    db.rollback()


def test_seat_spelling_is_canonical_so_case_variants_cannot_duplicate(db):
    s1, s2 = make_student(db, REG1), make_student(db, REG2)
    e = make_exam(db)
    a = models.Allotment(student_id=s1.id, exam_id=e.id, hall=" hall-a ", seat=" a12 ")
    db.add(a)
    db.commit()
    assert (a.hall, a.seat) == ("HALL-A", "A12")
    db.add(models.Allotment(student_id=s2.id, exam_id=e.id, hall="Hall-A", seat="a12"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_check_constraints_reject_impossible_values(db):
    s, e = make_student(db, REG1), make_exam(db)
    bad = [models.Result(student_id=s.id, exam_id=e.id, marks=120, max_marks=100),
           models.Result(student_id=s.id, exam_id=e.id, marks=-1, max_marks=100),
           models.Result(student_id=s.id, exam_id=e.id, marks=5, max_marks=0),
           models.Exam(title="x", subject_code="X", exam_date="2027-01-01", start_time="09:00", end_time="10:00", status="bogus"),
           models.User(username="r", password_hash="x", role="wizard"),
           models.User(username="r2", password_hash="x", role="staff", status="frozen"),
           models.Allotment(student_id=s.id, exam_id=e.id, hall="   ", seat="1"),
           models.Allotment(student_id=s.id, exam_id=e.id, hall="H", seat="  ")]
    for obj in bad:
        db.add(obj)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_foreign_keys_are_enforced_and_deletes_follow_declared_rules(db):
    s, e = make_student(db, REG1), make_exam(db)
    db.add(models.Allotment(student_id=9999, exam_id=e.id, hall="H", seat="1"))     # unknown student
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.add(models.Allotment(student_id=s.id, exam_id=e.id, hall="H", seat="1"))
    db.commit()
    db.delete(e)                                    # RESTRICT: an exam with allotments cannot vanish
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    u = make_user(db, "casc", "staff")              # CASCADE: a user's sessions and notifications go with the user
    now = datetime.now(timezone.utc)
    db.add(models.AuthSession(id="sid" + "0" * 29, user_id=u.id, expires_at=now + timedelta(hours=1)))
    db.add(models.Notification(user_id=u.id, category="exam", title="t", body="b", event_key="k"))
    db.commit()
    uid = u.id
    db.delete(u)
    db.commit()
    assert db.scalar(select(func.count()).select_from(models.AuthSession).where(models.AuthSession.user_id == uid)) == 0
    assert db.scalar(select(func.count()).select_from(models.Notification).where(models.Notification.user_id == uid)) == 0


def test_relationships_load(db):
    s, e = make_student(db, REG1), make_exam(db)
    a = models.Allotment(student_id=s.id, exam_id=e.id, hall="H", seat="1")
    db.add(a)
    db.commit()
    db.expire_all()
    got = db.get(models.Allotment, a.id)
    assert got.student.register_number == REG1 and got.exam.subject_code == "DEMO101"


def test_one_login_account_per_student_db_and_api(client, db, admin):
    s = make_student(db, REG1)
    make_user(db, "first", "student", student=s)
    db.add(models.User(username="second", password_hash="x", role="student", student_id=s.id))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    r = client.post("/api/admin/users", headers=admin, json={
        "username": "third", "password": "Sturdy-Pass-2026-xyz", "role": "student", "student_register_number": REG1})
    assert r.status_code == 409 and "already has a login account" in r.json()["detail"]


# ------------------------------------------------------------------------------------------------ transactions
def test_session_scope_commits_on_success_and_rolls_back_on_error():
    with session_scope() as s:
        s.add(models.Student(register_number=REG1, full_name="Committed", department="X"))
    with pytest.raises(RuntimeError):
        with session_scope() as s:
            s.add(models.Student(register_number=REG2, full_name="Rolled back", department="X"))
            s.flush()
            raise RuntimeError("boom")
    with SessionLocal() as s:
        assert [x.full_name for x in s.scalars(select(models.Student))] == ["Committed"]


def test_failed_flush_is_all_or_nothing(db):
    s1, s2 = make_student(db, REG1), make_student(db, REG2)
    e = make_exam(db)
    db.add_all([models.Allotment(student_id=s1.id, exam_id=e.id, hall="H", seat="1"),
                models.Allotment(student_id=s2.id, exam_id=e.id, hall="H", seat="1")])   # second collides with first
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    assert db.scalar(select(func.count()).select_from(models.Allotment)) == 0


def test_savepoint_isolates_a_duplicate_inside_a_larger_transaction(db):
    s1, s2 = make_student(db, REG1), make_student(db, REG2)
    e = make_exam(db)
    db.add(models.Allotment(student_id=s1.id, exam_id=e.id, hall="H", seat="1"))
    db.flush()
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(models.Allotment(student_id=s2.id, exam_id=e.id, hall="H", seat="1"))
    db.commit()                                      # the outer work survives
    assert db.scalar(select(func.count()).select_from(models.Allotment)) == 1


def test_api_rolls_back_a_failed_request_completely(client, db, staff):
    make_student(db, REG1)
    e = make_exam(db)
    _hall(db, n=2)
    body = {"register_number": REG1, "exam_id": e.id, "hall": "HALL-A", "seat": "1"}
    assert client.post("/api/allotments", headers=staff, json=body).status_code == 201
    assert client.post("/api/allotments", headers=staff, json=body).status_code == 409
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(models.Allotment)) == 1
        assert s.scalar(select(func.count()).select_from(models.AllotmentHistory)) == 1   # no orphan history row


# ------------------------------------------------------------------------------ concurrency (seat allocation)
def _race(client, headers, bodies, rounds=1):
    """Fire all requests at the same instant; returns the list of status codes."""
    codes = []
    barrier = threading.Barrier(len(bodies))

    def go(body):
        barrier.wait()
        codes.append(client.post("/api/allotments", headers=headers, json=body).status_code)
    threads = [threading.Thread(target=go, args=(b,)) for b in bodies]
    [t.start() for t in threads]
    [t.join(120) for t in threads]
    return sorted(codes)


def _students(db, n):
    out = []
    for i in range(n):
        out.append(make_student(db, f"99002510{6001 + i:04d}", f"Student {i}"))
    return out


def test_concurrent_requests_for_one_seat_yield_exactly_one_allotment(client, db, staff):
    studs, e = _students(db, 6), make_exam(db)
    _hall(db, n=4)
    bodies = [{"register_number": s.register_number, "exam_id": e.id, "hall": "HALL-A", "seat": "1"} for s in studs]
    assert _race(client, staff, bodies) == [201] + [409] * 5
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(models.Allotment)) == 1


def test_concurrent_requests_cannot_exceed_hall_capacity(client, db, staff):
    studs, e = _students(db, 6), make_exam(db)
    _hall(db, n=6, capacity=2)                       # 6 seats exist, but the hall may only hold 2 students
    bodies = [{"register_number": s.register_number, "exam_id": e.id, "hall": "HALL-A", "seat": str(i + 1)}
              for i, s in enumerate(studs)]
    codes = _race(client, staff, bodies)
    assert codes == [201, 201] + [409] * 4, codes
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(models.Allotment)) == 2


def test_concurrent_requests_cannot_double_book_a_student_across_simultaneous_exams(client, db, staff):
    s = make_student(db, REG1)
    e1, e2 = make_exam(db, code="E1"), make_exam(db, code="E2")        # same date and time = simultaneous
    _hall(db, n=4)
    bodies = [{"register_number": REG1, "exam_id": e1.id, "hall": "HALL-A", "seat": "1"},
              {"register_number": REG1, "exam_id": e2.id, "hall": "HALL-A", "seat": "2"}]
    assert _race(client, staff, bodies) == [201, 409]


def test_concurrent_requests_cannot_share_a_seat_across_simultaneous_exams(client, db, staff):
    s1, s2 = make_student(db, REG1), make_student(db, REG2)
    e1, e2 = make_exam(db, code="E1"), make_exam(db, code="E2")
    _hall(db, n=4)
    bodies = [{"register_number": REG1, "exam_id": e1.id, "hall": "HALL-A", "seat": "3"},
              {"register_number": REG2, "exam_id": e2.id, "hall": "HALL-A", "seat": "3"}]
    assert _race(client, staff, bodies) == [201, 409]


def test_database_unique_constraint_is_the_backstop_without_the_lock(db):
    """Even if a code path forgot lock_allocation(), two writers can never both own a seat."""
    studs, e = _students(db, 5), make_exam(db)
    ids, exam_id = [s.id for s in studs], e.id      # plain values: ORM objects of the main session must not cross threads
    outcomes = []
    barrier = threading.Barrier(len(ids))

    def writer(student_id):
        with SessionLocal() as s:
            barrier.wait()
            try:
                s.add(models.Allotment(student_id=student_id, exam_id=exam_id, hall="H", seat="1"))
                s.commit()
                outcomes.append("ok")
            except IntegrityError:
                s.rollback()
                outcomes.append("conflict")
            except Exception as exc:       # noqa: BLE001  - anything else must be visible in the assertion message
                s.rollback()
                outcomes.append(f"UNEXPECTED {type(exc).__name__}: {str(exc)[:200]}")
    threads = [threading.Thread(target=writer, args=(i,)) for i in ids]
    [t.start() for t in threads]
    [t.join(120) for t in threads]
    assert sorted(outcomes) == ["conflict"] * 4 + ["ok"], outcomes


def test_allocation_lock_makes_second_caller_wait_until_commit():
    held, waited = threading.Event(), {}

    def holder():
        with SessionLocal() as s:
            lock_allocation(s)
            held.set()
            time.sleep(0.8)
            s.commit()

    def waiter():
        held.wait(10)
        with SessionLocal() as s:
            t0 = time.monotonic()
            lock_allocation(s)
            waited["seconds"] = time.monotonic() - t0
            s.commit()
    a, b = threading.Thread(target=holder), threading.Thread(target=waiter)
    a.start(); b.start(); a.join(30); b.join(30)
    assert waited["seconds"] >= 0.5, waited


# ------------------------------------------------------------------------------------------- time zones
def test_timestamps_round_trip_as_aware_utc(db):
    instant = datetime(2026, 11, 14, 9, 0, tzinfo=timezone.utc)
    ist = instant.astimezone(timezone(timedelta(hours=5, minutes=30)))
    db.add_all([models.SecurityEvent(event_type="aware_utc", created_at=instant),
                models.SecurityEvent(event_type="aware_ist", created_at=ist),
                models.SecurityEvent(event_type="naive_means_utc", created_at=instant.replace(tzinfo=None))])
    db.commit()
    db.expire_all()
    got = {e.event_type: e.created_at for e in db.scalars(select(models.SecurityEvent))}
    for k, v in got.items():
        assert v.tzinfo is not None and v.utcoffset() == timedelta(0), k
        assert v == instant, k
    window = db.scalars(select(models.SecurityEvent).where(
        models.SecurityEvent.created_at >= instant - timedelta(minutes=1),
        models.SecurityEvent.created_at <= instant + timedelta(minutes=1))).all()
    assert len(window) == 3
    assert models.utcnow().tzinfo is not None


def test_aware_and_stored_values_compare_without_naive_aware_errors(db):
    u = make_user(db, "tz", "staff")
    u.locked_until = datetime.now(timezone.utc) + timedelta(minutes=5)
    db.commit()
    db.expire_all()
    assert db.get(models.User, u.id).locked_until > datetime.now(timezone.utc)     # would raise with a naive value


def test_postgres_timestamp_columns_are_timestamptz():
    if app_engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL-only check")
    with app_engine.connect() as c:
        kinds = {r[0] for r in c.execute(text(
            "SELECT DISTINCT data_type FROM information_schema.columns WHERE table_name='audit_logs' AND column_name='created_at'"))}
    assert kinds == {"timestamp with time zone"}


# --------------------------------------------------------------------------- PostgreSQL portability regressions
def test_admin_search_is_case_insensitive_on_every_database(client, db, admin):
    client.post("/api/admin/subjects", headers=admin, json={"code": "EC3452", "name": "Digital Electronics"})
    assert [s["code"] for s in client.get("/api/admin/subjects?q=DIGITAL", headers=admin).json()] == ["EC3452"]
    assert [s["code"] for s in client.get("/api/admin/subjects?q=digital", headers=admin).json()] == ["EC3452"]
    assert [s["code"] for s in client.get("/api/admin/subjects?q=ec34", headers=admin).json()] == ["EC3452"]


# ----------------------------------------------------------------------------------------------- migration 0015 audit policy
# Migration 0015 must fail closed: an audit trail that cannot be written must stop the migration, never be skipped.
# Each migration runs in its own transaction, so a raised error leaves the database at revision 0014, unchanged.

def _at_0014(url):
    """A database at revision 0014. SQLite: the real revisions are applied. PostgreSQL: simulated (the released chain
    cannot replay there), so the head schema is created and migration 0015 is downgraded away (see at_previous_schema)."""
    cfg = dbcheck.alembic_config(url)
    if url.startswith("sqlite"):
        command.upgrade(cfg, "0014")
    else:
        with use_database(url):
            dbcheck.migrate()
            command.downgrade(cfg, "0014")
    return cfg


def _insert_row(conn, table, values):
    row = dict(values)
    for c in inspect(conn).get_columns(table):
        if c["name"] in row or c.get("nullable", True) or c.get("default") is not None:
            continue
        t = str(c["type"]).upper()
        row[c["name"]] = False if "BOOL" in t else 0 if any(x in t for x in ("INT", "FLOAT")) else \
            "2026-11-17 00:00:00" if any(x in t for x in ("DATE", "TIME")) else "x"
    conn.execute(text(f"INSERT INTO {table} ({','.join(row)}) VALUES ({','.join(':' + k for k in row)})"), row)


def _seed_0014_legacy_rows(eng):
    """One FULLY_VERIFIED, two legacy published+approved+UNRESOLVED rows, one HALL_LIST_ONLY row."""
    with eng.begin() as c:
        _insert_row(c, "vsb_alloc_batches", {"id": 1, "exam_date": "2026-11-17", "session": "AN",
                                             "status": "published", "exam_name": "X"})
        rows = [(1, "FULLY_VERIFIED"), (2, "UNRESOLVED"), (3, "UNRESOLVED"), (4, "HALL_LIST_ONLY")]
        for rid, status in rows:
            _insert_row(c, "vsb_alloc_records", {
                "id": rid, "batch_id": 1, "register_number": f"99002510640{rid}", "hall": "MB III 103",
                "seat": str(rid), "subject_code": "23ECT307", "review_status": "approved",
                "published": True, "verification_status": status})


def _migration_state(eng):
    with eng.connect() as c:
        version = c.execute(text("SELECT version_num FROM alembic_version")).scalar()
        status = dict(c.execute(text("SELECT id, verification_status FROM vsb_alloc_records ORDER BY id")).fetchall())
        audits = c.execute(text("SELECT target FROM audit_logs WHERE action='vsb_alloc.legacy_unresolved_hidden' "
                                "ORDER BY target")).fetchall()
    return version, status, [a[0] for a in audits]


def test_migration_0015_upgrade_writes_one_audit_row_per_legacy_record(dbkind, scratch_url):
    cfg = _at_0014(scratch_url)
    eng = create_engine(scratch_url)
    _seed_0014_legacy_rows(eng)
    command.upgrade(cfg, "head")
    version, status, audited = _migration_state(eng)
    assert version == HEAD
    assert status == {1: "FULLY_VERIFIED", 2: "UNRESOLVED", 3: "UNRESOLVED", 4: "HALL_LIST_CONFIRMED"}
    assert audited == ["2", "3"]                       # exactly the two legacy records, once each
    eng.dispose()


def test_migration_0015_rerun_after_downgrade_never_duplicates_audit_rows(dbkind, scratch_url):
    cfg = _at_0014(scratch_url)
    eng = create_engine(scratch_url)
    _seed_0014_legacy_rows(eng)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0014")
    command.upgrade(cfg, "head")
    _, _, audited = _migration_state(eng)
    assert audited == ["2", "3"]
    eng.dispose()


def test_migration_0015_audit_write_failure_rolls_back_the_whole_migration(dbkind, scratch_url):
    """An error while writing the audit trail must not leave a renamed status with a missing audit row."""
    cfg = _at_0014(scratch_url)
    eng = create_engine(scratch_url)
    _seed_0014_legacy_rows(eng)
    with eng.begin() as c:
        if dbkind == "sqlite":
            c.execute(text("CREATE TRIGGER fail_audit BEFORE INSERT ON audit_logs "
                           "BEGIN SELECT RAISE(ABORT, 'injected audit failure'); END"))
        else:
            c.execute(text("CREATE FUNCTION fail_audit() RETURNS trigger AS $$ BEGIN "
                           "RAISE EXCEPTION 'injected audit failure'; END $$ LANGUAGE plpgsql"))
            c.execute(text("CREATE TRIGGER fail_audit BEFORE INSERT ON audit_logs FOR EACH ROW "
                           "EXECUTE FUNCTION fail_audit()"))
    with pytest.raises(Exception, match="injected audit failure|audit"):
        command.upgrade(cfg, "head")
    version, status, audited = _migration_state(eng)
    assert version == "0014"                           # nothing from 0015 was committed
    assert status == {1: "FULLY_VERIFIED", 2: "UNRESOLVED", 3: "UNRESOLVED", 4: "HALL_LIST_ONLY"}
    assert audited == []
    eng.dispose()


def test_migration_0015_refuses_when_audit_table_is_unusable_and_legacy_rows_exist(dbkind, scratch_url):
    cfg = _at_0014(scratch_url)
    eng = create_engine(scratch_url)
    _seed_0014_legacy_rows(eng)
    with eng.begin() as c:
        c.execute(text("DROP TABLE audit_logs"))
    with pytest.raises(Exception, match="audit_logs"):
        command.upgrade(cfg, "head")
    version, status, _ = _migration_state_without_audit(eng)
    assert version == "0014"
    assert status[4] == "HALL_LIST_ONLY"               # the status rename did not happen
    eng.dispose()


def _migration_state_without_audit(eng):
    with eng.connect() as c:
        version = c.execute(text("SELECT version_num FROM alembic_version")).scalar()
        status = dict(c.execute(text("SELECT id, verification_status FROM vsb_alloc_records ORDER BY id")).fetchall())
    return version, status, None
