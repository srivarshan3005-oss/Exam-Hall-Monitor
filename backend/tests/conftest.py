"""Test harness: isolated temp database built by the real Alembic migrations."""
import os, shutil, tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="exam_monitor_tests_")
# Opt-in: TEST_DATABASE_URL=postgresql://user:pw@host/emptydb runs the WHOLE suite on that (empty) PostgreSQL database.
# Without it the suite uses a throw-away SQLite file, exactly as before.
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or ("sqlite:///" + Path(_TMP, "test.db").as_posix())
os.environ["SECRET_KEY"] = "unit-test-secret-key-0123456789-abcdefghijklmnop"
os.environ["ENVIRONMENT"] = "test"
os.environ["DOCUMENT_STORAGE_DIR"] = Path(_TMP, "documents").as_posix()
os.environ["PBKDF2_ROUNDS"] = "1000"      # speed only; refused outside ENVIRONMENT=test
os.environ["SEED_DEMO"] = "false"
os.environ["PORTAL_PAST_DAYS"] = "-1"   # existing fixtures use fixed past dates; the cutoff has its own test
os.environ["SCHEDULER_ENABLED"] = "false"   # tests drive the worker explicitly
os.environ["VSB_AUTO_DISCOVER_ENABLED"] = "false"   # the test suite must NEVER touch the real college website (fixtures only)
os.environ.pop("PUBLIC_SHOW_NAMES", None)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app import models, doc_models  # noqa: F401
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.dbcheck import migrate
from app.main import create_app
from app.ratelimit import limiter
from app.security import hash_password

STRONG = "Sturdy-Pass-2026-xyz"
REG1, REG2, REG3 = "990025106001", "990025106002", "990025205001"   # synthetic 12-digit numbers


@pytest.fixture(scope="session", autouse=True)
def _migrated_db():
    migrate()
    yield
    engine.dispose()
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture(autouse=True)
def _clean(_migrated_db):
    """Empty every table and reset limiters/settings between tests."""
    limiter.reset()
    saved = {k: getattr(settings, k) for k in (
        "public_show_names", "public_results_enabled", "login_max_failures", "login_lockout_minutes",
        "login_ip_max_attempts", "public_lookup_per_minute", "public_lookup_miss_limit",
        "access_token_minutes", "trust_proxy", "environment", "secret_key", "max_upload_mb")}
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
    yield
    for k, v in saved.items():
        setattr(settings, k, v)


@pytest.fixture()
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def client():
    with TestClient(create_app()) as c:
        yield c


def make_user(db, username, role="admin", password=STRONG, student=None, active=True):
    u = models.User(username=username, password_hash=hash_password(password), role=role,
                    student_id=student.id if student else None, active=active)
    db.add(u)
    db.commit()
    return u


def make_student(db, reg=REG1, name="Demo Student One", dept="Electronics and Communication", year=2):
    s = models.Student(register_number=reg, full_name=name, department=dept, year=year)
    db.add(s)
    db.commit()
    return s


def make_exam(db, status="published", title="DEMO Exam", code="DEMO101", date="2027-01-15"):
    e = models.Exam(title=title, subject_code=code, exam_date=date, start_time="09:30", end_time="12:30",
                    venue="DEMO", status=status)
    db.add(e)
    db.commit()
    return e


def login(client, username, password=STRONG):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


@pytest.fixture()
def admin(db, client):
    make_user(db, "admin1", "admin")
    return login(client, "admin1")


@pytest.fixture()
def staff(db, client):
    make_user(db, "staff1", "staff")
    return login(client, "staff1")


@pytest.fixture()
def student_auth(db, client):
    s = db.scalar(select(models.Student).where(models.Student.register_number == REG1)) or make_student(db, REG1)
    make_user(db, "stud1", "student", student=s)
    return login(client, "stud1")


@pytest.fixture(autouse=True)
def _no_cycle_leaks_between_tests():
    """A test (e.g. the role-matrix audit calling POST /api/live/scan) may start a background scan thread. Wait for it to
    finish so the single-cycle lock is free for the next test."""
    import time
    from app.vsb_live import cycle
    deadline = time.time() + 240
    while time.time() < deadline:
        if cycle._lock.acquire(blocking=False):
            cycle._lock.release()
            break
        time.sleep(0.5)
    yield
