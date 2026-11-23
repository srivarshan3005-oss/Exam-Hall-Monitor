"""V7: printable slip, e-mail notifications, optional Supabase mirror, hall locations/map, management API, security.
FIXTURE tests (see test_v7_live.py)."""
import json
import smtplib
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from app import doc_models as dm, mailer
from app.config import settings
from app.vsb_live import cycle, notify, pipeline, supabase_sync
from v7_fakesite import HALL_URL, SEAT_URL, standard_site
from v7_pdfs import hall_pages, seat_pages, write_hall_pdf, write_seat_pdf

REG = "922523105015"


@pytest.fixture(autouse=True)
def _fresh(monkeypatch, tmp_path):
    pipeline.forget()
    monkeypatch.setattr(mailer, "OUTBOX", tmp_path / "outbox")
    monkeypatch.setattr(mailer, "OUTBOX_PROBLEM", None)
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "environment", "test")
    yield


@pytest.fixture()
def pdfs(tmp_path):
    return write_hall_pdf(tmp_path / "hall.pdf"), write_seat_pdf(tmp_path / "seat.pdf")


@pytest.fixture()
def live(pdfs, monkeypatch, client):
    site = standard_site(*pdfs, monkeypatch)
    cycle.run_cycle(trigger="manual", actor="t")
    return site


def hdr_login(db, client, role="admin", name="adm"):
    from conftest import login, make_user
    make_user(db, name, role)
    return login(client, name)


# ----------------------------------------------------------------------------- slip
def test_printable_slip_shows_the_verified_record_and_escapes_everything(live, client, db):
    r = client.get(f"/api/public/slip/{REG}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html") and "no-store" in r.headers["cache-control"]
    t = r.text
    for needle in (REG, "2026-11-20", "Friday", "AN", "23EET301", "MB III 02", "ELECTROMAGNETIC FIELDS", "20.11.26-AN-HALL.pdf p.2",
                   "20.11.26-AN-SEAT.pdf p.1", "not an official hall ticket", "/portal/slip.js"):
        assert needle in t, needle
    assert "922524105045" not in t                                              # no other student on the slip
    a = db.scalar(select(dm.LiveAllotment).where(dm.LiveAllotment.register_number == REG))
    a.subject_name = '<script>alert(1)</script>"><img src=x>'
    db.commit()
    t = client.get(f"/api/public/slip/{REG}").text
    assert "<script>alert" not in t and "&lt;script&gt;" in t and "<img src=x>" not in t
    assert client.get("/api/public/slip/12").status_code == 422


def test_slip_for_unknown_number_says_so(live, client):
    t = client.get("/api/public/slip/999999999999").text
    assert "No allotment was found" in t


# ----------------------------------------------------------------------------- e-mail
def add_watch(db, client, hdr, reg=REG, email="parent@example.org"):
    return client.post("/api/live/watches", json={"register_number": reg, "email": email}, headers=hdr)


def test_watch_validation_and_privacy(live, client, db):
    hdr = hdr_login(db, client)
    assert add_watch(db, client, hdr, "12", "a@b.org").status_code == 422
    assert add_watch(db, client, hdr, REG, "not-an-email").status_code == 422
    assert add_watch(db, client, hdr).status_code == 201 and add_watch(db, client, hdr).status_code == 409
    assert client.get("/api/live/watches").status_code == 401                       # never public
    staff = hdr_login(db, client, "staff", "stf")
    assert client.get("/api/live/watches", headers=staff).status_code == 403          # addresses are administrator-only
    assert "parent@example.org" not in json.dumps(client.get("/api/live/notifications", headers=staff).json())


def test_new_and_revised_allotments_are_e_mailed_once_with_original_pdf_and_unmasked_page(tmp_path, pdfs, monkeypatch, client, db):
    site = standard_site(*pdfs, monkeypatch)
    hdr = hdr_login(db, client)
    add_watch(db, client, hdr)
    cycle.run_cycle(trigger="manual", actor="t")                                   # first publication
    out = tmp_path / "outbox"
    texts = sorted(out.glob("*.txt"))
    assert len(texts) == 1
    body = texts[0].read_text()
    assert "Hall: MB III 02" in body and "Seat: 2" in body and "Friday" in body
    assert "Attachments: 20.11.26-AN-HALL.pdf" in body and ".png" in body
    assert any(p.suffix == ".png" and p.read_bytes()[:4] == b"\x89PNG" for p in out.iterdir())
    assert any(p.name.endswith("HALL.pdf") and p.read_bytes()[:5] == b"%PDF-" for p in out.iterdir())
    # re-scanning, rebuilding, even restarting the cycle never sends it again
    cycle.run_cycle(trigger="manual", actor="t", rebuild=True)
    cycle.run_cycle(trigger="manual", actor="t", rebuild=True)
    assert len(list(out.glob("*.txt"))) == 1
    n = db.scalars(select(dm.LiveNotification)).all()
    assert len(n) == 1 and n[0].status == "outbox" and n[0].attempts == 1 and n[0].event_type == "new"
    # a revised allotment produces exactly one more message
    site.add_pdf(HALL_URL, write_hall_pdf(tmp_path / "h2.pdf", [t.replace("MB III 02", "MB III 09") for t in hall_pages()]), etag='"h2"')
    site.add_pdf(SEAT_URL, write_seat_pdf(tmp_path / "s2.pdf", [t.replace("MB III 02", "MB III 09") for t in seat_pages()]), etag='"s2"')
    cycle.run_cycle(trigger="manual", actor="t")
    notes = db.scalars(select(dm.LiveNotification).order_by(dm.LiveNotification.id)).all()
    assert [x.event_type for x in notes] == ["new", "revised"]
    assert "REVISED" in notes[1].subject and "Hall: MB III 09" in sorted(out.glob("*.txt"))[-1].read_text()


def test_email_failure_never_breaks_lookup_retries_transient_and_hides_secrets(tmp_path, pdfs, monkeypatch, client, db):
    standard_site(*pdfs, monkeypatch)
    monkeypatch.setattr(settings, "smtp_host", "smtp.invalid.example")
    monkeypatch.setattr(settings, "smtp_password", "S3cr3t-Pass-Word")
    monkeypatch.setattr(settings, "mail_retry_backoff_seconds", 1)
    monkeypatch.setattr(settings, "mail_max_attempts", 2)

    def boom(msg):
        raise mailer.MailError("connect_failed", "could not connect to smtp.invalid.example as parent@example.org S3cr3t-Pass-Word", transient=True)
    monkeypatch.setattr(mailer, "smtp_submit", boom)
    hdr = hdr_login(db, client)
    add_watch(db, client, hdr)
    r = cycle.run_cycle(trigger="manual", actor="t")
    assert r["notifications"]["retry_scheduled"] == 1
    assert client.get(f"/api/public/lookup/{REG}").json()["status"] == "found"      # lookup unaffected
    n = db.scalar(select(dm.LiveNotification))
    assert n.status == "pending" and n.attempts == 1 and n.next_attempt_at is not None
    assert "S3cr3t" not in (n.last_error or "") and "parent@example.org" not in (n.last_error or "")
    later = datetime(2100, 1, 1, tzinfo=timezone.utc)
    assert notify.process_due(db, at=later)["failed"] == 1                           # attempts exhausted -> failed, clear status
    db.refresh(n)
    assert n.status == "failed" and n.attempts == 2
    # success after the outage is possible for a NEW event, and the failed one is not resent automatically
    assert notify.process_due(db, at=later) == {"sent": 0, "failed": 0, "retry_scheduled": 0}


def test_smtp_delivery_path_and_test_email_button(tmp_path, pdfs, monkeypatch, client, db):
    sent = []
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.org")
    monkeypatch.setattr(mailer, "smtp_submit", lambda msg: sent.append(msg))
    hdr = hdr_login(db, client)
    r = client.post("/api/live/notifications/test-email", json={"to": "me@example.org"}, headers=hdr)
    assert r.status_code == 200 and r.json()["status"] == "sent" and r.json()["mode"] == "smtp" and len(sent) == 1
    assert client.post("/api/live/notifications/test-email", json={"to": "bad"}, headers=hdr).status_code == 422
    assert client.post("/api/live/notifications/test-email", json={"to": "me@example.org"}).status_code == 401
    monkeypatch.setattr(mailer, "smtp_submit", lambda m: (_ for _ in ()).throw(mailer.MailError("auth", "535 bad login", transient=False)))
    r = client.post("/api/live/notifications/test-email", json={"to": "me@example.org"}, headers=hdr)
    assert r.json()["status"] == "failed" and "535" in r.json()["message"]


def test_unconfigured_production_mail_is_reported_not_faked(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    r = notify.send_test("a@example.org")
    assert r["status"] == "failed" and "not configured" in r["message"].lower()


# ----------------------------------------------------------------------------- Supabase (optional)
def test_supabase_is_optional_and_skips_cleanly(live, db):
    assert not settings.supabase_enabled
    assert supabase_sync.sync(db)["status"] == "skipped"


def test_supabase_sync_upserts_in_batches_logs_failures_and_retries(live, db, monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co")
    monkeypatch.setattr(settings, "supabase_service_key", "service-role-key-xyz")
    posts = []
    monkeypatch.setattr(supabase_sync, "BATCH", 200)
    monkeypatch.setattr(supabase_sync, "_post", lambda rows: posts.append(rows))
    r = supabase_sync.sync(db)
    assert r["status"] == "ok" and r["records"] == 390 and sum(len(p) for p in posts) == 390 and len(posts) == 2
    row = posts[0][0]
    assert {"register_number", "hall", "seat", "fingerprint", "status"} <= set(row) and "service" not in json.dumps(row)
    assert supabase_sync.sync(db)["records"] == 0                                   # nothing new since the last success
    # outage: failure is logged, nothing is lost, the next run sends the backlog
    a = db.scalar(select(dm.LiveAllotment))
    a.is_current, a.superseded_at = False, datetime.now(timezone.utc)
    db.commit()

    def down(rows):
        raise OSError("network down")
    monkeypatch.setattr(supabase_sync, "_post", down)
    assert supabase_sync.sync(db)["status"] == "failed"
    monkeypatch.setattr(supabase_sync, "_post", lambda rows: posts.append(rows))
    posts.clear()
    r = supabase_sync.sync(db)
    assert r["status"] == "ok" and r["records"] == 1
    assert [x.status for x in db.scalars(select(dm.LiveSyncLog).order_by(dm.LiveSyncLog.id)).all()] == ["ok", "ok", "failed", "ok"]


def test_supabase_rls_sql_denies_public_access():
    import pathlib
    sql = (pathlib.Path(__file__).resolve().parents[2] / "supabase" / "schema.sql").read_text()
    assert "enable row level security" in sql.lower()
    low = sql.lower()
    assert "to anon" not in low and "to authenticated" not in low and "for insert" not in low.replace("-- ", "")
    assert "revoke all" in low and "unique" in low


# ----------------------------------------------------------------------------- hall location / map
def test_location_is_hidden_until_an_administrator_verifies_it_with_a_source(live, client, db):
    hdr = hdr_login(db, client)
    assert client.get(f"/api/public/lookup/{REG}").json()["records"][0]["location"] is None
    r = client.post("/api/live/halls", json={"code": "MB III 02", "building": "Main Block", "block": "III", "floor": "Ground", "room": "02"}, headers=hdr)
    assert r.status_code == 201
    hid = r.json()["id"]
    rec = client.get(f"/api/public/lookup/{REG}").json()["records"][0]
    assert rec["location"] is None and rec["location_message"] == "Building/floor location has not yet been verified."   # unverified -> hidden
    bad = client.put(f"/api/live/halls/{hid}/location", json={"building": "Main Block", "verified": True}, headers=hdr)
    assert bad.status_code == 422                                                   # no source -> cannot verify
    bad = client.put(f"/api/live/halls/{hid}/location", json={"latitude": 10.9, "verified": False}, headers=hdr)
    assert bad.status_code == 422                                                   # lat without lon
    ok = client.put(f"/api/live/halls/{hid}/location", json={
        "building": "Main Block", "block": "III", "floor": "Ground", "room": "02", "location_source": "COE office, 21-Nov-2026",
        "verified": True}, headers=hdr)
    assert ok.status_code == 200 and ok.json()["verified_by"] == "adm"
    loc = client.get(f"/api/public/lookup/{REG}").json()["records"][0]["location"]
    assert (loc["building"], loc["block"], loc["floor"], loc["room"]) == ("Main Block", "III", "Ground", "02")
    assert "map" not in loc and "directions" not in loc                             # nothing invented beyond what was entered
    hist = client.get(f"/api/live/halls/{hid}/history", headers=hdr).json()
    assert [h["action"] for h in hist][:2] == ["verify", "create"] and hist[0]["source"] == "COE office, 21-Nov-2026"


def test_map_needs_verified_coordinates_and_an_entrance_is_optional(live, client, db):
    hdr = hdr_login(db, client)
    hid = client.post("/api/live/halls", json={"code": "MB III 02", "building": "Main Block"}, headers=hdr).json()["id"]
    pid = client.post("/api/live/campus-points", json={"name": "Main Gate", "latitude": 10.9001, "longitude": 78.0801,
                                                        "source": "Site plan", "verified": True}, headers=hdr).json()["id"]
    assert client.post("/api/live/campus-points", json={"name": "X", "verified": True}, headers=hdr).status_code == 422
    r = client.put(f"/api/live/halls/{hid}/location", json={"building": "Main Block", "latitude": 10.9005, "longitude": 78.0809,
                   "directions": "Enter by the main gate, straight to the Main Block.", "entrance_id": pid,
                   "location_source": "Site plan", "verified": True}, headers=hdr)
    assert r.status_code == 200
    loc = client.get(f"/api/public/lookup/{REG}").json()["records"][0]["location"]
    assert loc["map"]["latitude"] == 10.9005 and loc["map"]["entrance"]["name"] == "Main Gate" and "openstreetmap.org" in loc["map"]["osm_url"]
    assert loc["directions"].startswith("Enter by")
    # un-verifying removes everything from the student view again
    client.put(f"/api/live/halls/{hid}/location", json={"building": "Main Block", "verified": False}, headers=hdr)
    assert client.get(f"/api/public/lookup/{REG}").json()["records"][0]["location"] is None


def test_halls_without_a_record_are_listed_for_the_administrator(live, client, db):
    hdr = hdr_login(db, client)
    d = client.get("/api/live/halls", headers=hdr).json()
    assert "MB III 02" in d["halls_in_documents_without_record"]
    assert client.post("/api/live/halls", json={"code": "mb  iii 02"}, headers=hdr).status_code == 201
    assert client.post("/api/live/halls", json={"code": "MB III 02"}, headers=hdr).status_code == 409


# ----------------------------------------------------------------------------- management API
def test_management_endpoints_require_authentication_and_roles(live, client, db):
    gets = ["overview", "sources", "documents", "queue", "failures", "duplicates", "allotments", "halls", "campus-points",
            "notifications", "sync/log", "health", "logs", "scan/state"]
    for g in gets:
        assert client.get(f"/api/live/{g}").status_code == 401, g
    staff = hdr_login(db, client, "staff", "stf")
    for g in gets:
        assert client.get(f"/api/live/{g}", headers=staff).status_code == 200, g
    for method, path, body in (("post", "/api/live/rebuild", None), ("post", "/api/live/halls", {"code": "X"}),
                               ("post", "/api/live/sync/supabase", None), ("post", "/api/live/watches", {"register_number": REG, "email": "a@b.org"})):
        assert getattr(client, method)(path, headers=staff, **({"json": body} if body else {})).status_code == 403, path


def test_overview_scan_and_dashboard_data(live, client, db):
    hdr = hdr_login(db, client)
    o = client.get("/api/live/overview", headers=hdr).json()
    assert o["poll_minutes"] == 5 and o["students_indexed"] == 390 and o["allotments"] == {"CONFIRMED": 390}
    assert o["queue"] == {"ok": 2} and o["documents"] == 2 and o["last_success_at"]
    docs = client.get("/api/live/documents", headers=hdr).json()
    assert {d["kind"] for d in docs} == {"hall_allotment", "seating_allotment"} and all(d["ingest_status"] == "ok" for d in docs)
    assert any(s["method"] == "html" and s["status"] == "ok" for s in client.get("/api/live/sources", headers=hdr).json())
    r = client.post("/api/live/scan?wait=true", headers=hdr)
    assert r.status_code == 200 and r.json()["discovery"]["status"] in ("ok", "partial")
    rows = client.get("/api/live/allotments?q=922523105015", headers=hdr).json()
    assert rows["total"] == 1 and rows["items"][0]["hall"] == "MB III 02"
    assert client.get("/api/live/allotments?status=CONFLICT", headers=hdr).json()["total"] == 0
    h = client.get("/api/live/health", headers=hdr).json()
    assert h["database"]["ok"] and h["storage_writable"] and h["mail"] == "outbox"
    assert any(x["type"] == "scan" for x in client.get("/api/live/logs", headers=hdr).json())
    # rebuild and retry endpoints
    assert client.post("/api/live/rebuild", headers=hdr).json()["index"]["unchanged"] == 390
    q = client.get("/api/live/queue", headers=hdr).json()
    assert client.post(f"/api/live/queue/{q[0]['id']}/retry", headers=hdr).json()["status"] == "pending"


# ----------------------------------------------------------------------------- security & abuse
def test_public_endpoints_have_no_bulk_listing_and_rate_limits(live, client):
    for path in ("/api/public/lookup", "/api/public/lookup/", "/api/public/records", "/api/public/export", "/api/public/slip"):
        assert client.get(path).status_code in (404, 405), path
    assert "uploads" not in client.get("/api/public/status").text.lower()
    seen = {client.get(f"/api/public/lookup/9999999999{i:02d}").status_code for i in range(40)}
    assert 429 in seen                                                              # guessing numbers is throttled


def test_public_status_exposes_only_safe_facts(live, client):
    s = client.get("/api/public/status").json()
    assert s["poll_minutes"] == 5 and s["last_success_at"] and s["documents_processed"] == 2
    assert set(s["official_pages"]) == {"https://vsbec.edu.in/controller-of-examination/", "https://coe.vsbec.edu.in/"}
    text = json.dumps(s)
    assert "smtp" not in text.lower() and "secret" not in text.lower() and "/mnt/" not in text


def test_env_file_and_database_are_not_served(client):
    for p in ("/.env", "/backend/.env", "/exam_monitor.db", "/uploads/x.pdf", "/api/../.env", "/portal/../../.env"):
        assert client.get(p).status_code in (404, 400, 401, 403, 307), p


def test_republished_pdfs_do_not_notify_students_whose_allotment_did_not_change(tmp_path, pdfs, monkeypatch, client, db):
    """Only the MB III 02 hall changes; a watcher of a student in another hall must NOT get a message, and that row keeps its history."""
    site = standard_site(*pdfs, monkeypatch)
    hdr = hdr_login(db, client)
    from vsb import independent_compare as IC
    other = next(r for r, (hall, _seat) in sorted(IC.report()["assignments"].items()) if hall != "MB III 02")   # not in the changed hall
    add_watch(db, client, hdr, other, "other@example.org")
    cycle.run_cycle(trigger="manual", actor="t")
    out = tmp_path / "outbox"
    first = len(list(out.glob("*.txt")))
    assert first == 1
    row = db.scalar(select(dm.LiveAllotment).where(dm.LiveAllotment.register_number == other))
    row_id, hv_before = row.id, row.hall_version_id
    site.add_pdf(HALL_URL, write_hall_pdf(tmp_path / "h2.pdf", [t.replace("MB III 02", "MB III 09") for t in hall_pages()]), etag='"h2"')
    site.add_pdf(SEAT_URL, write_seat_pdf(tmp_path / "s2.pdf", [t.replace("MB III 02", "MB III 09") for t in seat_pages()]), etag='"s2"')
    r = cycle.run_cycle(trigger="manual", actor="t")
    assert r["index"]["revised"] == 25 and r["index"]["new"] == 0 and r["index"]["unchanged"] == 365
    assert len(list(out.glob("*.txt"))) == first                              # no spurious message
    db.expire_all()
    rows = db.scalars(select(dm.LiveAllotment).where(dm.LiveAllotment.register_number == other)).all()
    assert len(rows) == 1 and rows[0].id == row_id and rows[0].revision == 1  # same row, repointed at the new PDF version
    assert rows[0].hall_version_id != hv_before          # now points at the NEW hall PDF version
