import re
from sqlalchemy import select, func
from app import models, cli
from app.config import settings
from app.security import verify_password
from conftest import STRONG


def test_gen_secret_is_acceptable_to_the_validator(capsys):
    from app.security import check_secret_key
    assert cli.main(["gen-secret"]) == 0
    key = capsys.readouterr().out.strip()
    assert len(key) >= 48 and check_secret_key(key) == []


def test_create_admin_via_env_password(db, monkeypatch, capsys):
    monkeypatch.setenv("EM_ADMIN_PASSWORD", STRONG)
    assert cli.main(["create-admin", "--username", "Boss"]) == 0
    u = db.scalar(select(models.User).where(models.User.username == "boss"))
    assert u.role == "admin" and verify_password(STRONG, u.password_hash)
    assert db.scalar(select(models.AuditLog).where(models.AuditLog.action == "user.created", models.AuditLog.actor == "cli"))
    assert cli.main(["create-admin", "--username", "boss"]) == 1     # already exists


def test_create_admin_rejects_weak_password(db, monkeypatch):
    monkeypatch.setenv("EM_ADMIN_PASSWORD", "ChangeMe123!")
    assert cli.main(["create-admin", "--username", "weak"]) == 1
    assert db.scalar(select(func.count()).select_from(models.User)) == 0


def test_unlock_user(db, monkeypatch):
    from conftest import make_user
    u = make_user(db, "lockme", "staff")
    from datetime import datetime, timedelta, timezone
    u.locked_until = datetime.now(timezone.utc) + timedelta(hours=1)
    db.commit()
    assert cli.main(["unlock-user", "lockme"]) == 0
    db.refresh(u)
    assert u.locked_until is None
    assert cli.main(["unlock-user", "nobody"]) == 1


def test_seed_demo_is_synthetic_idempotent_and_creates_no_login(db):
    assert cli.main(["seed-demo"]) == 0
    assert cli.main(["seed-demo"]) == 0
    regs = [r for r in db.scalars(select(models.Student.register_number)).all()]
    assert len(regs) == 4
    assert all(re.fullmatch(r"\d{12}", r) and r.startswith("9900") for r in regs)   # 12-digit, non-VSB prefix
    assert db.scalar(select(func.count()).select_from(models.User)) == 0
    assert db.scalar(select(func.count()).select_from(models.Allotment)) == 2


def test_seed_demo_refused_in_production(db, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    assert cli.main(["seed-demo"]) == 1


def test_demo_data_visible_through_public_api(client, db):
    cli.main(["seed-demo"])
    d = client.get("/api/lookup/990025106001").json()
    assert d["allotments"][0]["hall"] == "DEMO HALL 01" and d["allotments"][0]["seat"] == "1"


def test_check_config(capsys, monkeypatch):
    assert cli.main(["check-config"]) == 0
    monkeypatch.setattr(settings, "secret_key", "short")
    assert cli.main(["check-config"]) == 1


def test_reset_password_cli(db, monkeypatch):
    from conftest import make_user
    u = make_user(db, "resetme", "admin")
    monkeypatch.setenv("EM_NEW_PASSWORD", "Fresh-Sturdy-Pass-55")
    assert cli.main(["reset-password", "resetme"]) == 0
    db.refresh(u)
    assert verify_password("Fresh-Sturdy-Pass-55", u.password_hash) and u.token_version == 1
    monkeypatch.setenv("EM_NEW_PASSWORD", "weak")
    assert cli.main(["reset-password", "resetme"]) == 1
    assert cli.main(["reset-password", "ghost"]) == 1


def test_app_refuses_to_start_with_legacy_default_admin_password(db):
    import pytest
    from fastapi.testclient import TestClient
    from app.main import create_app
    from conftest import make_user
    make_user(db, "admin", "admin", password="ChangeMe123!")
    with pytest.raises(RuntimeError, match="reset-password"):
        with TestClient(create_app()):
            pass


def test_init_env_creates_env_once_with_valid_secret(tmp_path, monkeypatch, capsys):
    from pathlib import Path
    import app.cli as cli_mod
    from app.security import check_secret_key
    root = Path(cli_mod.__file__).resolve().parent.parent
    target = root / ".env"
    assert not target.exists(), "tests must not run next to a real .env"
    try:
        assert cli.main(["init-env"]) == 0
        line = [l for l in target.read_text().splitlines() if l.startswith("SECRET_KEY=")][0]
        assert check_secret_key(line.split("=", 1)[1]) == []
        before = target.read_text()
        assert cli.main(["init-env"]) == 0 and target.read_text() == before   # never overwrites
    finally:
        target.unlink(missing_ok=True)
