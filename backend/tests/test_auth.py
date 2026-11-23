from sqlalchemy import select
from app import models
from app.config import settings
from conftest import STRONG, make_user, login


def bad(client, u="admin1", p="wrong-password-1"):
    return client.post("/api/auth/login", json={"username": u, "password": p})


def test_login_success_and_me(client, db):
    make_user(db, "admin1", "admin")
    r = client.post("/api/auth/login", json={"username": "admin1", "password": STRONG})
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "admin" and body["token_type"] == "bearer" and body["expires_in"] > 0
    me = client.get("/api/auth/me", headers={"Authorization": "Bearer " + body["access_token"]})
    assert me.json() == {"username": "admin1", "role": "admin"}


def test_username_is_case_insensitive(client, db):
    make_user(db, "admin1", "admin")
    assert client.post("/api/auth/login", json={"username": " ADMIN1 ", "password": STRONG}).status_code == 200


def test_invalid_login_is_generic(client, db):
    make_user(db, "admin1", "admin")
    wrong_pw, unknown = bad(client), bad(client, "nobody")
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json() == unknown.json()


def test_inactive_user_cannot_login(client, db):
    make_user(db, "gone", "admin", active=False)
    assert bad(client, "gone", STRONG).status_code == 401


def test_missing_and_garbage_token(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer abc.def.ghi"}).status_code == 401


def test_lockout_after_repeated_failures_even_with_correct_password(client, db):
    make_user(db, "admin1", "admin")
    for _ in range(settings.login_max_failures):
        assert bad(client).status_code == 401
    locked = client.post("/api/auth/login", json={"username": "admin1", "password": STRONG})
    assert locked.status_code == 429 and int(locked.headers["Retry-After"]) > 0
    u = db.scalar(select(models.User).where(models.User.username == "admin1"))
    assert u.locked_until is not None
    actions = [a.action for a in db.scalars(select(models.AuditLog)).all()]
    assert "auth.account_locked" in actions and "auth.login_failed" in actions


def test_lockout_is_identical_for_unknown_usernames(client):
    codes = [bad(client, "ghost").status_code for _ in range(settings.login_max_failures + 1)]
    assert codes == [401] * settings.login_max_failures + [429]


def test_db_lock_survives_limiter_reset(client, db):
    from app.ratelimit import limiter
    make_user(db, "admin1", "admin")
    for _ in range(settings.login_max_failures):
        bad(client)
    limiter.reset()  # simulates a restart / another worker
    assert client.post("/api/auth/login", json={"username": "admin1", "password": STRONG}).status_code == 429


def test_successful_login_resets_failure_counter(client, db):
    make_user(db, "admin1", "admin")
    for _ in range(settings.login_max_failures - 1):
        bad(client)
    login(client, "admin1")
    for _ in range(settings.login_max_failures - 1):
        assert bad(client).status_code == 401


def test_per_ip_login_throttle(client, db, monkeypatch):
    monkeypatch.setattr(settings, "login_ip_max_attempts", 3)
    monkeypatch.setattr(settings, "login_max_failures", 100)
    codes = [bad(client, f"user{i}").status_code for i in range(5)]
    assert codes == [401, 401, 401, 429, 429]


def test_forwarded_header_ignored_unless_trusted(client, db, monkeypatch):
    monkeypatch.setattr(settings, "login_ip_max_attempts", 2)
    monkeypatch.setattr(settings, "login_max_failures", 100)
    codes = [client.post("/api/auth/login", json={"username": f"u{i}", "password": "x"},
                         headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code for i in range(4)]
    assert codes == [401, 401, 429, 429]


def test_change_password_revokes_old_tokens(client, db):
    make_user(db, "admin1", "admin")
    old = login(client, "admin1")
    new_pw = "Another-Sturdy-Pass-77"
    r = client.post("/api/auth/change-password", headers=old,
                    json={"current_password": STRONG, "new_password": new_pw})
    assert r.status_code == 200
    assert client.get("/api/auth/me", headers=old).status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer " + r.json()["access_token"]}).status_code == 200
    assert client.post("/api/auth/login", json={"username": "admin1", "password": new_pw}).status_code == 200


def test_change_password_validations(client, db):
    make_user(db, "admin1", "admin")
    h = login(client, "admin1")
    assert client.post("/api/auth/change-password", headers=h,
                       json={"current_password": "nope-nope-nope1", "new_password": "Another-Sturdy-Pass-77"}).status_code == 403
    assert client.post("/api/auth/change-password", headers=h,
                       json={"current_password": STRONG, "new_password": "short1"}).status_code == 422
    assert client.post("/api/auth/change-password", headers=h,
                       json={"current_password": STRONG, "new_password": STRONG}).status_code == 422


def test_logout_revokes_token(client, db):
    make_user(db, "admin1", "admin")
    h = login(client, "admin1")
    assert client.post("/api/auth/logout", headers=h).status_code == 200
    assert client.get("/api/auth/me", headers=h).status_code == 401


def test_role_change_invalidates_token(client, db):
    make_user(db, "admin1", "admin")
    make_user(db, "boss", "admin")
    boss = login(client, "boss")
    h1 = login(client, "admin1")
    assert client.patch("/api/admin/users/admin1", headers=boss, json={"role": "staff"}).status_code == 200
    assert client.get("/api/auth/me", headers=h1).status_code == 401


def test_login_never_returns_password_hash(client, db):
    make_user(db, "admin1", "admin")
    r = client.post("/api/auth/login", json={"username": "admin1", "password": STRONG})
    assert "pbkdf2" not in r.text and "password" not in r.text.lower().replace("incorrect username or password", "")
