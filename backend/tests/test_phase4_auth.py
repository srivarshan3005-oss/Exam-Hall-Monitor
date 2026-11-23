"""Phase 4: sessions, registration/activation, password recovery, administrator reset, throttling."""
import re
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select
from app import models
from app.config import settings
from app.security import create_access_token
from conftest import make_user, make_student, login, STRONG, REG1

NEW = "Another-Strong-Pass-77"


@pytest.fixture()
def mailbox(monkeypatch):
    sent = []
    monkeypatch.setattr("app.routers.auth.send_mail", lambda to, subject, body: sent.append((to, subject, body)) or "test")
    return sent


def token_in(mail, kind):
    return re.search(rf"\?{kind}=([\w-]+)", mail[2]).group(1)


def events(db, prefix=""):
    db.expire_all()
    return [e for e in db.scalars(select(models.SecurityEvent).order_by(models.SecurityEvent.id)).all()
            if e.event_type.startswith(prefix)]


# ------------------------------------------------------------------ sessions
def test_token_without_server_session_is_rejected(client, db):
    make_user(db, "adm1", "admin")
    forged = create_access_token("adm1", "admin", 0)            # validly signed, but no session record
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer " + forged}).status_code == 401


def test_logout_ends_only_this_session(client, db):
    make_user(db, "adm1", "admin")
    h1, h2 = login(client, "adm1"), login(client, "adm1")
    assert client.post("/api/auth/logout", headers=h1).status_code == 200
    assert client.get("/api/auth/me", headers=h1).status_code == 401
    assert client.get("/api/auth/me", headers=h2).status_code == 200


def test_logout_all_ends_every_session(client, db):
    make_user(db, "adm1", "admin")
    h1, h2 = login(client, "adm1"), login(client, "adm1")
    assert client.post("/api/auth/logout-all", headers=h1).status_code == 200
    assert client.get("/api/auth/me", headers=h1).status_code == 401
    assert client.get("/api/auth/me", headers=h2).status_code == 401


def test_idle_session_times_out(client, db):
    make_user(db, "adm1", "admin")
    h = login(client, "adm1")
    s = db.scalar(select(models.AuthSession))
    s.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=settings.session_idle_minutes + 1)
    db.commit()
    r = client.get("/api/auth/me", headers=h)
    assert r.status_code == 401 and "timed out" in r.json()["detail"]
    assert events(db, "auth.session_idle_timeout")


def test_only_newest_sessions_are_kept(client, db, monkeypatch):
    monkeypatch.setattr(settings, "max_sessions_per_user", 2)
    make_user(db, "adm1", "admin")
    hs = [login(client, "adm1") for _ in range(3)]
    assert client.get("/api/auth/me", headers=hs[0]).status_code == 401
    assert client.get("/api/auth/me", headers=hs[2]).status_code == 200


def test_session_list_and_revoke_and_idor(client, db):
    make_user(db, "adm1", "admin")
    make_user(db, "adm2", "admin")
    h1, h1b, h2 = login(client, "adm1"), login(client, "adm1"), login(client, "adm2")
    mine = client.get("/api/auth/sessions", headers=h1).json()
    assert len(mine) == 2 and sum(s["current"] for s in mine) == 1
    other = client.get("/api/auth/sessions", headers=h2).json()[0]["id"]
    assert client.delete(f"/api/auth/sessions/{other}", headers=h1).status_code == 404   # not another user's
    victim = next(s["id"] for s in mine if not s["current"])
    assert client.delete(f"/api/auth/sessions/{victim}", headers=h1).status_code == 200
    assert client.get("/api/auth/me", headers=h1b).status_code == 401


# ------------------------------------------------------------------ login events and protection
def test_failed_login_is_logged_without_the_password(client, db):
    make_user(db, "adm1", "admin")
    client.post("/api/auth/login", json={"username": "adm1", "password": "Wrong-Password-1"})
    client.post("/api/auth/login", json={"username": "ghost", "password": "Wrong-Password-2"})
    # a password typed into the username box must not be stored
    client.post("/api/auth/login", json={"username": "My Secret Pass 99!", "password": "x"})
    db.expire_all()
    rows = events(db, "auth.login_failed")
    assert len(rows) == 3
    dump = " ".join(f"{e.username} {e.detail} {e.path}" for e in rows)
    assert "Wrong-Password" not in dump and "Secret" not in dump
    assert any(e.username == "(invalid-format)" for e in rows)


def test_lockout_is_logged_and_critical(client, db, monkeypatch):
    monkeypatch.setattr(settings, "login_max_failures", 3)
    make_user(db, "adm1", "admin")
    for _ in range(3):
        client.post("/api/auth/login", json={"username": "adm1", "password": "bad-bad-bad-1"})
    assert client.post("/api/auth/login", json={"username": "adm1", "password": STRONG}).status_code == 429
    assert any(e.severity == "critical" for e in events(db, "auth.account_locked"))
    assert events(db, "auth.login_blocked")


def test_suspended_account_gets_the_generic_failure(client, db):
    make_user(db, "adm1", "admin", active=False)
    r = client.post("/api/auth/login", json={"username": "adm1", "password": STRONG})
    assert r.status_code == 401 and r.json()["detail"] == "Incorrect username or password"


# ------------------------------------------------------------------ registration + activation
def reg_payload(**kw):
    p = {"username": "newstud", "password": STRONG, "register_number": REG1, "email": "stud@example.edu"}
    p.update(kw)
    return p


def test_registration_requires_activation_and_responds_generically(client, db, mailbox):
    s = make_student(db, REG1)
    s.email = "stud@example.edu"
    db.commit()
    ok = client.post("/api/auth/register", json=reg_payload())
    unknown = client.post("/api/auth/register", json=reg_payload(register_number="990099999999", username="other"))
    wrong_mail = client.post("/api/auth/register", json=reg_payload(email="x@example.edu", username="third"))
    assert ok.status_code == unknown.status_code == wrong_mail.status_code == 202
    assert ok.json() == unknown.json() == wrong_mail.json()          # nothing to enumerate
    assert len(mailbox) == 1 and mailbox[0][0] == "stud@example.edu"
    # not usable before activation
    assert client.post("/api/auth/login", json={"username": "newstud", "password": STRONG}).status_code == 401
    token = token_in(mailbox[0], "activate")
    assert client.post("/api/auth/activate", json={"token": token}).status_code == 200
    assert client.post("/api/auth/activate", json={"token": token}).status_code == 400   # single use
    assert login(client, "newstud")
    u = db.scalar(select(models.User).where(models.User.username == "newstud"))
    assert u.role == "student" and u.student_id == s.id


def test_registration_rejects_weak_password_and_duplicates(client, db, mailbox):
    s = make_student(db, REG1)
    s.email = "stud@example.edu"
    db.commit()
    assert client.post("/api/auth/register", json=reg_payload(password="short1")).status_code == 422
    client.post("/api/auth/register", json=reg_payload())
    client.post("/api/auth/register", json=reg_payload(username="second"))     # same student again
    assert len(mailbox) == 1
    assert db.scalar(select(models.User).where(models.User.username == "second")) is None


def test_registration_can_be_disabled(client, db, mailbox, monkeypatch):
    monkeypatch.setattr(settings, "allow_self_registration", False)
    s = make_student(db, REG1)
    s.email = "stud@example.edu"
    db.commit()
    assert client.post("/api/auth/register", json=reg_payload()).status_code == 202
    assert not mailbox


def test_expired_activation_link_fails(client, db, mailbox):
    s = make_student(db, REG1)
    s.email = "stud@example.edu"
    db.commit()
    client.post("/api/auth/register", json=reg_payload())
    t = db.scalar(select(models.PasswordToken))
    t.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    assert client.post("/api/auth/activate", json={"token": token_in(mailbox[0], "activate")}).status_code == 400


def test_registration_is_rate_limited(client, db, monkeypatch):
    monkeypatch.setattr(settings, "register_per_hour", 2)
    codes = [client.post("/api/auth/register", json=reg_payload(username=f"user{i}x")).status_code for i in range(3)]
    assert codes == [202, 202, 429]


# ------------------------------------------------------------------ forgot / reset
def test_forgot_password_is_uniform_and_reset_is_single_use(client, db, mailbox):
    u = make_user(db, "adm1", "admin")
    u.email = "adm1@example.edu"
    db.commit()
    h_old = login(client, "adm1")
    hit = client.post("/api/auth/forgot-password", json={"identifier": "adm1"})
    by_mail = client.post("/api/auth/forgot-password", json={"identifier": "adm1@example.edu"})
    miss = client.post("/api/auth/forgot-password", json={"identifier": "nobody"})
    assert hit.status_code == by_mail.status_code == miss.status_code == 202
    assert hit.json() == miss.json()
    assert len(mailbox) == 2 and all(m[0] == "adm1@example.edu" for m in mailbox)
    token = token_in(mailbox[1], "reset")                           # the older link was invalidated
    assert client.post("/api/auth/reset-password", json={"token": token_in(mailbox[0], "reset"), "new_password": NEW}).status_code == 400
    assert client.post("/api/auth/reset-password", json={"token": token, "new_password": "weak"}).status_code == 422
    assert client.post("/api/auth/reset-password", json={"token": token, "new_password": NEW}).status_code == 200
    assert client.post("/api/auth/reset-password", json={"token": token, "new_password": NEW + "1"}).status_code == 400
    assert client.get("/api/auth/me", headers=h_old).status_code == 401             # sessions ended
    assert login(client, "adm1", NEW)


def test_reset_token_expires(client, db, mailbox):
    u = make_user(db, "adm1", "admin")
    u.email = "adm1@example.edu"
    db.commit()
    client.post("/api/auth/forgot-password", json={"identifier": "adm1"})
    t = db.scalar(select(models.PasswordToken))
    t.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    assert client.post("/api/auth/reset-password", json={"token": token_in(mailbox[0], "reset"), "new_password": NEW}).status_code == 400


def test_tokens_are_stored_hashed(client, db, mailbox):
    u = make_user(db, "adm1", "admin")
    u.email = "adm1@example.edu"
    db.commit()
    client.post("/api/auth/forgot-password", json={"identifier": "adm1"})
    raw = token_in(mailbox[0], "reset")
    assert raw not in db.scalar(select(models.PasswordToken)).token_hash


def test_suspended_user_cannot_reset(client, db, mailbox):
    u = make_user(db, "adm1", "admin", active=False)
    u.email, u.status = "adm1@example.edu", "suspended"
    db.commit()
    client.post("/api/auth/forgot-password", json={"identifier": "adm1"})
    assert not mailbox


def test_forgot_password_rate_limit(client, db, monkeypatch):
    monkeypatch.setattr(settings, "forgot_password_per_hour", 2)
    codes = [client.post("/api/auth/forgot-password", json={"identifier": f"user{i}x"}).status_code for i in range(3)]
    assert codes == [202, 202, 429]


# ------------------------------------------------------------------ administrator reset
def test_admin_reset_gives_one_time_password_and_forces_change(client, db, admin):
    make_user(db, "stf", "staff")
    victim = login(client, "stf")
    r = client.post("/api/admin/users/stf/reset-password", headers=admin, json={"reason": "forgot password, ID checked"})
    assert r.status_code == 200
    temp = r.json()["temporary_password"]
    assert client.get("/api/auth/me", headers=victim).status_code == 401           # old session gone
    h = login(client, "stf", temp)
    assert client.get("/api/admin/exams", headers=h).status_code == 403           # blocked until changed
    assert client.get("/api/auth/me", headers=h).status_code == 200
    ch = client.post("/api/auth/change-password", headers=h, json={"current_password": temp, "new_password": NEW})
    assert ch.status_code == 200
    h2 = {"Authorization": "Bearer " + ch.json()["access_token"]}
    assert client.get("/api/admin/exams", headers=h2).status_code == 200
    audit = client.get("/api/admin/audit?action=user.password_reset_by_admin", headers=admin).json()
    assert audit and temp not in str(audit)


def test_admin_reset_needs_reason_and_not_self(client, db, admin):
    make_user(db, "stf", "staff")
    assert client.post("/api/admin/users/stf/reset-password", headers=admin, json={"reason": "x"}).status_code == 422
    assert client.post("/api/admin/users/admin1/reset-password", headers=admin, json={"reason": "my own account"}).status_code == 409


def test_staff_cannot_reset_passwords(client, db, staff):
    make_user(db, "stf2", "staff")
    assert client.post("/api/admin/users/stf2/reset-password", headers=staff, json={"reason": "because I can"}).status_code == 403


def test_admin_reset_is_rate_limited(client, db, admin):
    for i in range(11):
        make_user(db, f"s{i:02d}", "student" if False else "staff")
    codes = [client.post(f"/api/admin/users/s{i:02d}/reset-password", headers=admin, json={"reason": "bulk test run"}).status_code
             for i in range(11)]
    assert codes[:10] == [200] * 10 and codes[10] == 429


def test_expired_password_forces_change(client, db, monkeypatch):
    monkeypatch.setattr(settings, "password_max_age_days", 30)
    u = make_user(db, "adm1", "admin")
    u.password_changed_at = datetime.now(timezone.utc) - timedelta(days=31)
    db.commit()
    r = client.post("/api/auth/login", json={"username": "adm1", "password": STRONG})
    assert r.json()["pw_change_required"] is True
    h = {"Authorization": "Bearer " + r.json()["access_token"]}
    assert client.get("/api/admin/audit", headers=h).status_code == 403
