"""Alembic migrations: empty -> head, model/schema parity, downgrade, and the legacy 0.1.0 upgrade path."""
import re, sqlite3
from pathlib import Path
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text, inspect
from app.database import Base
from app.dbcheck import alembic_config

FIXTURE = Path(__file__).parent / "fixtures" / "original_schema.sql"


def _legacy_sql() -> str:
    """The 0.1.0 schema dump, with tables created before their indexes."""
    stmts = [x.strip() for x in re.split(r"(?<=\))\n(?=CREATE)", FIXTURE.read_text()) if x.strip()]
    stmts.sort(key=lambda x: 0 if x.startswith("CREATE TABLE") else 1)
    return ";\n".join(stmts) + ";"


def _engine(tmp_path, name="m.db"):
    return create_engine("sqlite:///" + (tmp_path / name).as_posix())


def _cfg(tmp_path, name="m.db"):
    return alembic_config("sqlite:///" + (tmp_path / name).as_posix())


def test_upgrade_head_matches_models_exactly(tmp_path):
    command.upgrade(_cfg(tmp_path), "head")
    eng = _engine(tmp_path)
    with eng.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    assert diff == [], f"migrations and models disagree: {diff}"


def test_all_expected_tables_exist(tmp_path):
    command.upgrade(_cfg(tmp_path), "head")
    names = set(inspect(_engine(tmp_path)).get_table_names())
    assert {"users", "students", "exams", "allotments", "results", "audit_logs", "official_documents",
            "document_versions", "pdf_pages", "exam_sessions", "halls", "seating_sheets", "seat_positions",
            "register_entries", "sheet_subjects", "review_issues", "alembic_version"} <= names


def test_downgrade_to_base_and_back(tmp_path):
    cfg = _cfg(tmp_path)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0001")
    assert "official_documents" not in set(inspect(_engine(tmp_path)).get_table_names())
    command.downgrade(cfg, "base")
    assert set(inspect(_engine(tmp_path)).get_table_names()) <= {"alembic_version"}
    command.upgrade(cfg, "head")


def test_baseline_0001_matches_original_starter_schema(tmp_path):
    """0001 must reproduce what the 0.1.0 create_all() produced (so legacy DBs can be stamped safely)."""
    command.upgrade(_cfg(tmp_path), "0001")
    ref = sqlite3.connect(":memory:")
    ref.executescript(_legacy_sql())

    def shape(conn):
        out = {}
        tables = [r[0] for r in conn.execute("select name from sqlite_master where type='table' and name != 'alembic_version'")]
        for t in tables:
            cols = [(c[1], c[2].upper(), c[3], c[5]) for c in conn.execute(f"pragma table_info('{t}')")]
            fks = sorted((f[2], f[3], f[4]) for f in conn.execute(f"pragma foreign_key_list('{t}')"))
            idx = sorted((i[1], i[2]) for i in conn.execute(f"pragma index_list('{t}')") if not i[1].startswith("sqlite_autoindex"))
            out[t] = (cols, fks, idx)
        return out

    mig = sqlite3.connect((tmp_path / "m.db").as_posix())
    assert shape(mig) == shape(ref)


def _legacy_db(tmp_path):
    """Build a database the way the 0.1.0 starter did (no alembic_version) and add a row."""
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path.as_posix())
    conn.executescript(_legacy_sql())
    conn.execute("insert into students(register_number, full_name, department, year, active) values ('990025106001','Legacy One','ECE',2,1)")
    conn.execute("insert into users(username, password_hash, role, active) values ('admin','pbkdf2_sha256$1$aa$bb','admin',1)")
    conn.execute("insert into audit_logs(actor, action, target, created_at) values ('admin','x','y','2026-01-01 00:00:00')")
    conn.commit()
    conn.close()
    return path


def test_legacy_database_is_stamped_then_upgraded_keeping_data(tmp_path, monkeypatch):
    path = _legacy_db(tmp_path)
    url = "sqlite:///" + path.as_posix()
    import app.dbcheck as dbcheck
    monkeypatch.setattr(dbcheck, "engine", create_engine(url))
    monkeypatch.setattr(dbcheck, "alembic_config", lambda u=None: alembic_config(url))
    assert dbcheck.is_legacy_database()
    dbcheck.migrate()
    with create_engine(url).connect() as conn:
        assert conn.execute(text("select full_name from students")).scalar() == "Legacy One"
        assert conn.execute(text("select token_version from users")).scalar() == 0
        assert conn.execute(text("select count(*) from audit_logs")).scalar() == 1
        assert conn.execute(text("select version_num from alembic_version")).scalar() == dbcheck.head_revision()
    assert not dbcheck.is_legacy_database()


def test_migrating_twice_is_a_noop(tmp_path):
    cfg = _cfg(tmp_path)
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")


def test_duplicate_results_in_legacy_data_block_migration_loudly(tmp_path):
    path = _legacy_db(tmp_path)
    conn = sqlite3.connect(path.as_posix())
    conn.execute("insert into exams(title, subject_code, exam_date, start_time, end_time, venue, status) values ('E','C','2027-01-01','09:00','10:00','V','draft')")
    for _ in range(2):
        conn.execute("insert into results(student_id, exam_id, marks, max_marks, grade, published) values (1,1,50,100,'B',0)")
    conn.commit(); conn.close()
    cfg = alembic_config("sqlite:///" + path.as_posix())
    command.stamp(cfg, "0001")
    with pytest.raises(Exception):
        command.upgrade(cfg, "head")
