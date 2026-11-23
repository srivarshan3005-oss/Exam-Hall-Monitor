"""Phase 6: SMTP transport, delivery queue, retries, administrator controls. A REAL local SMTP server
(aiosmtpd) is used for the protocol-level tests; no external provider is contacted."""
import logging, socket, subprocess, ssl, threading
from datetime import datetime, timedelta, timezone
import pytest
from aiosmtpd.controller import Controller
from sqlalchemy import select
from app import delivery, mailer, models, notifications as nt
from app.config import settings
from conftest import make_user, make_student, login, REG1

PW = "smtp-secret-PASSWORD-9"


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Handler:
    def __init__(self):
        self.messages, self.reject, self.logins = [], set(), []

    async def handle_RCPT(self, server, session, envelope, address, rcpt_options):
        if address in self.reject:
            return "550 5.1.1 <" + address + "> user unknown"
        envelope.rcpt_tos.append(address)
        return "250 OK"

    async def handle_DATA(self, server, session, envelope):
        self.messages.append(envelope)
        return "250 Message accepted"


def _auth(server, session, envelope, mechanism, auth_data):
    from aiosmtpd.smtp import AuthResult, LoginPassword
    ok = isinstance(auth_data, LoginPassword) and auth_data.login == b"mailuser" and auth_data.password == PW.encode()
    return AuthResult(success=ok, handled=False if not ok else True)


@pytest.fixture()
def smtp(monkeypatch):
    h, port = Handler(), _free_port()
    ctl = Controller(h, hostname="127.0.0.1", port=port, authenticator=_auth, auth_required=True, auth_require_tls=False)
    ctl.start()
    for k, v in dict(smtp_host="127.0.0.1", smtp_port=port, smtp_security="none", smtp_user="mailuser", smtp_password=PW,
                     smtp_from="no-reply@college.example", smtp_timeout_seconds=3).items():
        monkeypatch.setattr(settings, k, v)
    yield h
    ctl.stop()


@pytest.fixture()
def admin_h(db, client):
    make_user(db, "adm", "admin").email = "adm@college.example"
    db.commit()
    return login(client, "adm")


def _queue(db, to="stu@college.example", subject="Hello", body="Body text", **kw):
    row = delivery.create(db, to=to, subject=subject, body=body, kind=kw.pop("kind", "notification"), **kw)
    db.commit()
    return row.id


def test_success_only_after_server_accepts(db, smtp):
    rid = _queue(db)
    out = delivery.process_queue()
    assert out["sent"] == 1
    row = db.get(models.EmailDelivery, rid); db.refresh(row)
    assert row.status == "sent" and row.mode == "smtp" and row.sent_at and row.attempts == 1 and row.error_code is None
    assert len(smtp.messages) == 1
    env = smtp.messages[0]
    assert env.rcpt_tos == ["stu@college.example"] and b"Subject: Hello" in env.content and b"Body text" in env.content
    assert b"Exam Monitor <no-reply@college.example>" in env.content


def test_sent_message_is_never_sent_twice(db, smtp):
    _queue(db)
    delivery.process_queue(); delivery.process_queue()
    assert len(smtp.messages) == 1


def test_wrong_password_is_a_permanent_failure_not_success(db, smtp, monkeypatch):
    monkeypatch.setattr(settings, "smtp_password", "wrong-password-value")
    rid = _queue(db)
    delivery.process_queue()
    row = db.get(models.EmailDelivery, rid); db.refresh(row)
    assert row.status == "failed" and row.error_code == "auth_failed" and row.sent_at is None and row.attempts == 1
    assert "wrong-password-value" not in (row.last_error or "") and not smtp.messages


def test_recipient_refused_is_permanent_and_address_is_redacted(db, smtp):
    smtp.reject.add("gone@college.example")
    rid = _queue(db, to="gone@college.example")
    delivery.process_queue()
    row = db.get(models.EmailDelivery, rid); db.refresh(row)
    assert row.status == "failed" and row.error_code == "recipient_refused" and "gone@college.example" not in (row.last_error or "")


def test_connection_failure_retries_with_backoff_then_gives_up(db, monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "127.0.0.1"); monkeypatch.setattr(settings, "smtp_port", _free_port())  # nothing listens
    monkeypatch.setattr(settings, "smtp_security", "none"); monkeypatch.setattr(settings, "smtp_user", "")
    monkeypatch.setattr(settings, "mail_retry_backoff_seconds", 60); monkeypatch.setattr(settings, "mail_max_attempts", 3)
    rid = _queue(db)
    now = datetime.now(timezone.utc)
    delivery.process_queue(now=now)
    row = db.get(models.EmailDelivery, rid); db.refresh(row)
    assert row.status == "retrying" and row.attempts == 1 and row.error_code == "connection_error" and row.sent_at is None
    assert delivery.process_queue(now=now + timedelta(seconds=10))["attempted"] == 0       # not due yet
    delivery.process_queue(now=now + timedelta(seconds=61)); db.refresh(row)
    assert row.status == "retrying" and row.attempts == 2
    delivery.process_queue(now=now + timedelta(seconds=61 + 121)); db.refresh(row)
    assert row.status == "failed" and row.attempts == 3 and row.next_attempt_at is None


def test_timeout_is_reported_as_timeout(db, monkeypatch):
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)           # accepts the TCP connection, never speaks SMTP
    monkeypatch.setattr(settings, "smtp_host", "127.0.0.1"); monkeypatch.setattr(settings, "smtp_port", srv.getsockname()[1])
    monkeypatch.setattr(settings, "smtp_security", "none"); monkeypatch.setattr(settings, "smtp_user", ""); monkeypatch.setattr(settings, "smtp_timeout_seconds", 1)
    try:
        rid = _queue(db)
        delivery.process_queue()
        row = db.get(models.EmailDelivery, rid); db.refresh(row)
        assert row.status == "retrying" and row.error_code in ("timeout", "connection_error") and row.sent_at is None
    finally:
        srv.close()


def test_tls_validation_failure_is_not_success(db, smtp, monkeypatch, tmp_path):
    """SMTP_SECURITY=ssl against a server with a self-signed certificate must fail certificate verification."""
    key, crt = tmp_path / "k.pem", tmp_path / "c.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(crt), "-days", "1",
                    "-subj", "/CN=localhost"], check=True, capture_output=True)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(str(crt), str(key))
    port = _free_port()
    ctl = Controller(Handler(), hostname="127.0.0.1", port=port, ssl_context=ctx)
    ctl.start()
    try:
        monkeypatch.setattr(settings, "smtp_port", port); monkeypatch.setattr(settings, "smtp_security", "ssl"); monkeypatch.setattr(settings, "smtp_user", "")
        rid = _queue(db)
        delivery.process_queue()
        row = db.get(models.EmailDelivery, rid); db.refresh(row)
        assert row.status == "failed" and row.error_code == "tls_error" and row.sent_at is None
    finally:
        ctl.stop()


def test_header_injection_is_neutralised(db, smtp):
    _queue(db, subject="Hi\r\nBcc: attacker@evil.example", to="stu@college.example")
    delivery.process_queue()
    assert smtp.messages
    headers = smtp.messages[0].content.split(b"\r\n\r\n")[0].split(b"\r\n")
    assert not any(h.lower().startswith(b"bcc:") for h in headers)         # the CR/LF could not start a new header
    assert smtp.messages[0].rcpt_tos == ["stu@college.example"]


def test_outbox_is_not_reported_as_sent_and_production_without_smtp_is_not_configured(db, tmp_path, monkeypatch):
    monkeypatch.setattr(mailer, "OUTBOX", tmp_path / "outbox")
    rid = _queue(db)
    delivery.process_queue()
    row = db.get(models.EmailDelivery, rid); db.refresh(row)
    assert row.status == "outbox" and row.mode == "outbox" and len(list((tmp_path / "outbox").glob("*.txt"))) == 1
    monkeypatch.setattr(settings, "environment", "production")
    rid2 = _queue(db, subject="Other")
    delivery.process_queue()
    row2 = db.get(models.EmailDelivery, rid2); db.refresh(row2)
    assert row2.status == "not_configured" and row2.sent_at is None and len(list((tmp_path / "outbox").glob("*.txt"))) == 1


def test_logs_contain_no_credentials_addresses_or_content(db, smtp, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    _queue(db, to="private.person@college.example", subject="Topsecret subject", body="Topsecret body")
    delivery.process_queue()
    monkeypatch.setattr(settings, "smtp_password", "wrong-password-value")
    _queue(db, to="private.person@college.example", subject="Topsecret subject 2", body="Topsecret body 2")
    delivery.process_queue()
    ours = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("exam_monitor"))   # the test SMTP server logs its own traffic
    assert "mail delivery id=" in ours                                                          # we do log delivery outcomes...
    for needle in (PW, "wrong-password-value", "private.person@college.example", "Topsecret", "mailuser"):
        assert needle not in ours                                                               # ...but never secrets, addresses or content


def test_account_mail_is_recorded_without_its_one_time_link(db, smtp):
    assert mailer.send_mail("stu@college.example", "Reset", "https://x/?reset=TOKEN123") == "smtp"
    row = db.scalar(select(models.EmailDelivery))
    assert row.sensitive is True and row.body is None and row.status == "sent" and row.kind == "account"
    assert b"TOKEN123" in smtp.messages[0].content                       # delivered...
    assert "TOKEN123" not in (row.subject + (row.last_error or ""))      # ...but never stored


def test_account_mail_never_raises_when_smtp_is_down(db, monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "127.0.0.1"); monkeypatch.setattr(settings, "smtp_port", _free_port()); monkeypatch.setattr(settings, "smtp_user", "")
    monkeypatch.setattr(settings, "smtp_security", "none")
    assert mailer.send_mail("a@b.co", "Reset", "link") == "not-configured"
    row = db.scalar(select(models.EmailDelivery))
    assert row.status == "failed" and row.sent_at is None


def test_activation_and_reset_flow_still_sends_through_the_new_service(db, client, smtp):
    s = make_student(db, REG1); s.email = "stud@college.example"; db.commit()
    r = client.post("/api/auth/register", json={"username": "newstud", "register_number": REG1, "email": "stud@college.example", "password": "Sturdy-Pass-2026-xyz"})
    assert r.status_code in (200, 201, 202)
    assert len(smtp.messages) == 1 and b"?activate=" in smtp.messages[0].content
    tok = smtp.messages[0].content.decode().split("?activate=")[1].split()[0].strip()
    assert client.post("/api/auth/activate", json={"token": tok}).status_code == 200
    h = login(client, "newstud")
    assert any(n["title"].startswith("Your Exam Monitor account is active") for n in client.get("/api/notifications", headers=h).json())
    client.post("/api/auth/forgot-password", json={"identifier": "newstud"})
    assert len(smtp.messages) >= 2 and b"?reset=" in smtp.messages[-1].content
    sent_rows = db.scalars(select(models.EmailDelivery).where(models.EmailDelivery.kind == "account")).all()
    assert len(sent_rows) >= 2 and all(r.body is None and r.status == "sent" for r in sent_rows)


# ---------------------------------------------------------------- administrator controls
def test_admin_endpoints_are_admin_only(db, client, staff):
    for method, path in (("get", "/api/admin/communications/email-status"), ("post", "/api/admin/communications/test-email"),
                         ("get", "/api/admin/communications/deliveries"), ("get", "/api/admin/communications/stats"),
                         ("get", "/api/admin/communications/templates"), ("post", "/api/admin/communications/run-scheduler"),
                         ("post", "/api/admin/communications/deliveries/1/retry")):
        assert getattr(client, method)(path, headers=staff, **({"json": {}} if method == "post" else {})).status_code == 403
        assert getattr(client, method)(path).status_code == 401
    make_user(db, "stu", "student"); make_user(db, "inv", "invigilator")
    for u in ("stu", "inv"):
        assert client.get("/api/admin/communications/email-status", headers=login(client, u)).status_code == 403


def test_email_status_never_exposes_secrets(client, admin_h, smtp):
    body = client.get("/api/admin/communications/email-status", headers=admin_h).text
    assert PW not in body and "mailuser" not in body
    j = client.get("/api/admin/communications/email-status", headers=admin_h).json()
    assert j["mode"] == "smtp" and j["smtp_configured"] and j["password_set"] and j["username_set"] and "smtp_password" not in j


def test_test_email_reports_the_real_smtp_answer(db, client, admin_h, smtp):
    r = client.post("/api/admin/communications/test-email", headers=admin_h, json={})
    assert r.status_code == 200 and r.json()["status"] == "sent" and r.json()["accepted_by_smtp_server"] is True
    assert smtp.messages[0].rcpt_tos == ["adm@college.example"]
    smtp.reject.add("adm@college.example")
    r = client.post("/api/admin/communications/test-email", headers=admin_h, json={})
    assert r.json()["status"] == "failed" and r.json()["accepted_by_smtp_server"] is False
    assert db.scalar(select(models.AuditLog).where(models.AuditLog.action == "email.test_sent")) is not None


def test_test_email_is_not_an_open_relay_and_is_rate_limited(db, client, admin_h, smtp):
    r = client.post("/api/admin/communications/test-email", headers=admin_h, json={"to": "victim@elsewhere.example"})
    assert r.status_code == 422 and not smtp.messages
    make_student(db, REG1).email = "stud@college.example"; db.commit()
    assert client.post("/api/admin/communications/test-email", headers=admin_h, json={"to": "stud@college.example"}).status_code == 200
    codes = [client.post("/api/admin/communications/test-email", headers=admin_h, json={}).status_code for _ in range(8)]
    assert 429 in codes


def test_test_email_without_smtp_in_development_is_outbox_not_sent(client, admin_h, tmp_path, monkeypatch):
    monkeypatch.setattr(mailer, "OUTBOX", tmp_path / "o")
    j = client.post("/api/admin/communications/test-email", headers=admin_h, json={}).json()
    assert j["status"] == "outbox" and j["accepted_by_smtp_server"] is False and "development outbox" in j["detail"].lower()


def test_delivery_log_filters_masking_and_retry(db, client, admin_h, monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "127.0.0.1"); monkeypatch.setattr(settings, "smtp_port", _free_port())
    monkeypatch.setattr(settings, "smtp_security", "none"); monkeypatch.setattr(settings, "smtp_user", ""); monkeypatch.setattr(settings, "mail_max_attempts", 1)
    rid = _queue(db, to="someone@college.example", subject="Needs retry")
    sens = delivery.create(db, to="x@college.example", subject="Reset", body="tok", kind="account", sensitive=True); db.commit()
    delivery.process_queue()
    delivery.deliver_row(db, sens, allow_retry=False); db.commit()
    lst = client.get("/api/admin/communications/deliveries?status=failed", headers=admin_h)
    assert lst.status_code == 200 and lst.headers["X-Total-Count"] == "2"
    row = [r for r in lst.json() if r["id"] == rid][0]
    assert row["recipient"] == "s***@college.example" and row["retryable"] is True and "someone@" not in lst.text
    assert [r for r in lst.json() if r["id"] == sens.id][0]["retryable"] is False
    assert client.post(f"/api/admin/communications/deliveries/{sens.id}/retry", headers=admin_h).status_code == 409     # one-time link not kept
    assert client.get("/api/admin/communications/deliveries?status=bogus", headers=admin_h).status_code == 422
    assert len(client.get("/api/admin/communications/deliveries?q=needs", headers=admin_h).json()) == 1
    # SMTP comes back: retry delivers exactly once
    h, port = Handler(), _free_port()
    ctl = Controller(h, hostname="127.0.0.1", port=port); ctl.start()
    try:
        monkeypatch.setattr(settings, "smtp_port", port)
        r = client.post(f"/api/admin/communications/deliveries/{rid}/retry", headers=admin_h)
        assert r.status_code == 200 and r.json()["status"] == "sent" and len(h.messages) == 1
        assert client.post(f"/api/admin/communications/deliveries/{rid}/retry", headers=admin_h).status_code == 409   # already sent
        assert len(h.messages) == 1
    finally:
        ctl.stop()
    assert client.post("/api/admin/communications/deliveries/99999/retry", headers=admin_h).status_code == 404


def test_stats(db, client, admin_h, smtp):
    _queue(db); delivery.process_queue()
    s = client.get("/api/admin/communications/stats", headers=admin_h).json()
    assert s["emails_by_status"].get("sent") == 1 and s["success_rate"] == 1.0 and s["pending"] == 0


def test_templates_validation_preview_reset_and_use(db, client, admin_h, smtp):
    base = "/api/admin/communications/templates/exam_published"
    assert len(client.get("/api/admin/communications/templates", headers=admin_h).json()) >= 10
    bad = client.put(base, headers=admin_h, json={"subject": "Hi {register_number}", "body": "Your password is {password}"})
    assert bad.status_code == 422 and "Unknown placeholder" in bad.json()["detail"]
    assert client.put(base, headers=admin_h, json={"subject": "Line1\nBcc: x", "body": "valid body {exam_title}"}).status_code == 422
    assert client.put("/api/admin/communications/templates/nope", headers=admin_h, json={"subject": "abc", "body": "abcdef"}).status_code == 404
    ok = client.put(base, headers=admin_h, json={"subject": "NEW: {exam_title}", "body": "Custom text for {exam_title} on {exam_date}"})
    assert ok.status_code == 200 and ok.json()["customized"] is True
    pv = client.post(base + "/preview", headers=admin_h, json={"subject": "NEW: {exam_title}", "body": "On {exam_date}"}).json()
    assert pv == {"subject": "NEW: Sample Examination", "body": "On 2027-01-15"}
    u = make_user(db, "s9", "student")
    nt.notify_users(db, [u], "exam_published", {"exam_title": "Chem", "exam_date": "2027-05-05"}, event_key="tpl"); db.commit()
    n = db.scalar(select(models.Notification))
    assert n.title == "NEW: Chem" and n.body == "Custom text for Chem on 2027-05-05"
    assert client.delete(base, headers=admin_h).json()["customized"] is False
    assert db.scalar(select(models.AuditLog).where(models.AuditLog.action == "email_template.updated")) is not None


def test_notification_email_respects_preferences_and_missing_address(db, smtp):
    a, b, c = make_user(db, "ua", "student"), make_user(db, "ub", "student"), make_user(db, "uc", "student")
    a.email, b.email = "a@college.example", "b@college.example"
    db.add(models.NotificationPreference(user_id=b.id, category="exam", in_app=True, email=False)); db.commit()
    r = nt.notify_users(db, [a, b, c], "exam_published", {"exam_title": "T", "exam_date": "2027-01-01"}, event_key="mail1"); db.commit()
    assert r["in_app"] == 3 and r["emails"] == 1                      # b opted out of e-mail, c has no address
    delivery.process_queue()
    assert [m.rcpt_tos for m in smtp.messages] == [["a@college.example"]]
    nt.notify_users(db, [a], "exam_published", {"exam_title": "T"}, event_key="mail1"); db.commit()
    delivery.process_queue()
    assert len(smtp.messages) == 1                                    # same event: no second e-mail
