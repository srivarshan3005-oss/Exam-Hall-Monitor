import re
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app import main
from app.config import settings
from app.main import create_app

STATIC = Path(main.__file__).parent / "static"


def test_homepage_served_with_security_headers(client):
    r = client.get("/")
    assert r.status_code == 200 and "Exam Monitor Ultimate" in r.text
    assert "EXAMINATION INTELLIGENCE PLATFORM" in (STATIC / "js" / "main.js").read_text()
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"


def test_api_responses_not_cacheable(client):
    assert client.get("/api/health").headers["cache-control"] == "no-store"


def test_swagger_docs_exempt_from_csp(client):
    r = client.get("/docs")
    assert r.status_code == 200 and "content-security-policy" not in r.headers
    assert client.get("/openapi.json").status_code == 200


def _all_js():
    return {f.name: f.read_text() for f in sorted((STATIC / "js").glob("*.js"))}


def test_no_prefilled_credentials_in_ui():
    # Phase 5: the sign-in form is rendered by js/main.js (the old single-page index.html was replaced)
    html = (STATIC / "index.html").read_text() + "".join(_all_js().values())
    assert 'value="admin"' not in html and "ChangeMe" not in html and "demo credentials" not in html.lower()
    login = _all_js()["main.js"]
    assert 'type: "password"' in login and 'autocomplete="current-password"' in login
    assert not re.search(r'name: "password"[^}]*value:', login)


def test_account_role_options_come_from_backend_not_a_ui_alias():
    """Phase 5 replaced the old 'administrator' label alias: role options are loaded from /api/admin/roles."""
    from app.schemas import UserCreate
    js = _all_js()["pages-people.js"]
    assert "/api/admin/roles" in js and "administrator'" not in js and "d.role='admin'" not in js
    assert UserCreate.model_fields["role"].annotation.__args__ == ("super_admin", "admin", "staff", "invigilator", "student")


def test_ui_has_numeric_keyboard_and_clear_button():
    js = _all_js()["main.js"]
    assert 'inputmode="numeric"' in js and 'id="clearBtn"' in js


def test_frontend_never_uses_local_storage_for_tokens():
    js = _all_js()
    assert "sessionStorage" in js["main.js"]
    for name, text in js.items():
        # localStorage is used only for the light/dark preference, never for credentials
        for m in re.finditer(r"localStorage\.\w+Item\(([^)]*)\)", text):
            assert "token" not in m.group(1).lower() and "em_token" not in m.group(1), name


def test_health_and_config(client):
    assert client.get("/api/health").json()["status"] == "ok"
    cfg = client.get("/api/config").json()
    assert cfg["product_name"] == "Exam Monitor Ultimate" and "secret" not in str(cfg).lower()


def test_cors_only_for_configured_origins(client):
    ok = client.get("/api/health", headers={"Origin": "http://localhost:8000"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:8000"
    evil = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in evil.headers


def test_app_refuses_to_start_with_weak_secret(monkeypatch):
    monkeypatch.setattr(settings, "secret_key", "REPLACE_WITH_A_LONG_RANDOM_SECRET_BEFORE_DEPLOYMENT")
    with pytest.raises(RuntimeError):
        with TestClient(create_app()):
            pass


def test_app_refuses_to_start_without_secret(monkeypatch):
    monkeypatch.setattr(settings, "secret_key", "")
    with pytest.raises(RuntimeError):
        with TestClient(create_app()):
            pass


def test_app_refuses_unmigrated_database(monkeypatch):
    monkeypatch.setattr(main, "assert_database_current", lambda: (_ for _ in ()).throw(RuntimeError("not migrated")))
    with pytest.raises(RuntimeError):
        with TestClient(create_app()):
            pass


def test_demo_seed_off_by_default_and_blocked_in_production(db, monkeypatch):
    from sqlalchemy import select, func
    from app import models
    assert settings.seed_demo is False
    with TestClient(create_app()):
        pass
    assert db.scalar(select(func.count()).select_from(models.Student)) == 0
    assert db.scalar(select(func.count()).select_from(models.User)) == 0
    monkeypatch.setattr(settings, "seed_demo", True)
    monkeypatch.setattr(settings, "environment", "production")
    with pytest.raises(RuntimeError):
        with TestClient(create_app()):
            pass
