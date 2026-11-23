"""Phase 4: CSRF/origin defence, headers, CORS, startup configuration checks, 0007 upgrade path."""
import sqlite3
import pytest
from alembic import command
from app.config import settings
from app.main import _check_production_config
from app.dbcheck import alembic_config
from conftest import make_user, login, STRONG


def test_cross_site_write_is_refused_same_site_allowed(client, db):
    make_user(db, "adm1", "admin")
    body = {"username": "adm1", "password": STRONG}
    assert client.post("/api/auth/login", json=body, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/auth/login", json=body, headers={"Origin": "null"}).status_code == 403
    assert client.post("/api/auth/login", json=body, headers={"Origin": "http://testserver"}).status_code == 200
    assert client.post("/api/auth/login", json=body, headers={"Origin": "http://localhost:8000"}).status_code == 200  # CORS_ORIGINS
    assert client.post("/api/auth/login", json=body).status_code == 200                                              # non-browser client
    assert client.get("/api/health", headers={"Origin": "https://evil.example"}).status_code == 200                  # reads unaffected


def test_security_headers_and_no_store(client):
    r = client.get("/api/health")
    h = r.headers
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in h["content-security-policy"] and "default-src 'self'" in h["content-security-policy"]
    assert h["cross-origin-opener-policy"] == "same-origin" and h["cache-control"] == "no-store"


def test_cors_does_not_allow_other_origins(client):
    r = client.options("/api/auth/login", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in r.headers
    ok = client.options("/api/auth/login", headers={"Origin": "http://localhost:8000", "Access-Control-Request-Method": "POST"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:8000"
    assert "access-control-allow-credentials" not in ok.headers


def test_startup_refuses_wildcard_cors_and_http_in_production(monkeypatch):
    monkeypatch.setattr(settings, "cors_origins", "*")
    with pytest.raises(RuntimeError):
        _check_production_config()
    monkeypatch.setattr(settings, "cors_origins", "http://campus.example")
    monkeypatch.setattr(settings, "environment", "production")
    with pytest.raises(RuntimeError):
        _check_production_config()
    monkeypatch.setattr(settings, "cors_origins", "https://campus.example")
    monkeypatch.setattr(settings, "public_base_url", "http://campus.example")
    with pytest.raises(RuntimeError):
        _check_production_config()
    monkeypatch.setattr(settings, "public_base_url", "https://campus.example")
    _check_production_config()


def test_sql_injection_and_xss_input_are_handled_as_data(client, db):
    make_user(db, "adm1", "admin")
    h = login(client, "adm1")
    nasty = "x' OR '1'='1"
    assert client.get("/api/admin/users", headers=h, params={"q": nasty}).json() == []
    assert client.get("/api/admin/security/events", headers=h, params={"q": nasty, "username": nasty}).json() == []
    assert client.get("/api/admin/audit", headers=h, params={"q": "%", "action": "_"}).status_code == 200
    r = client.post("/api/auth/login", json={"username": "<script>alert(1)</script>", "password": "x"})
    assert r.status_code == 401 and "<script>" not in r.text


def test_secrets_never_appear_in_listings(client, db):
    make_user(db, "adm1", "admin")
    h = login(client, "adm1")
    client.post("/api/auth/login", json={"username": "adm1", "password": "Wrong-Password-1"})
    blob = " ".join(client.get(u, headers=h).text for u in
                    ("/api/admin/users", "/api/admin/security/events", "/api/admin/security/sessions", "/api/admin/audit"))
    assert "pbkdf2" not in blob and "Wrong-Password" not in blob and STRONG not in blob
    assert h["Authorization"].split()[1] not in blob


def test_0007_upgrade_keeps_existing_accounts(tmp_path):
    cfg = alembic_config("sqlite:///" + (tmp_path / "up.db").as_posix())
    command.upgrade(cfg, "0006")
    con = sqlite3.connect(tmp_path / "up.db")
    con.execute("INSERT INTO users (username,password_hash,role,active,failed_attempts,token_version) VALUES ('old','h','admin',1,0,0)")
    con.execute("INSERT INTO users (username,password_hash,role,active,failed_attempts,token_version) VALUES ('gone','h','staff',0,0,0)")
    con.commit()
    con.close()
    command.upgrade(cfg, "head")
    con = sqlite3.connect(tmp_path / "up.db")
    rows = dict((r[0], r[1:]) for r in con.execute("SELECT username, role, active, status, must_change_password FROM users"))
    assert rows["old"] == ("admin", 1, "active", 0) and rows["gone"] == ("staff", 0, "suspended", 0)
    command.downgrade(cfg, "0006")
    assert con.execute("SELECT count(*) FROM users").fetchone()[0] == 2
