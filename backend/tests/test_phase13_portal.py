"""Phase 13: reference-style public portal API, privacy guarantees, static-page contract and the operations overview.
All data is synthetic and created inside each test (the conftest empties every table between tests)."""
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app import doc_models as dm, models
from app.config import settings
from conftest import REG1, REG2, REG3, make_exam, make_student, make_user, login

STATIC = Path(__file__).resolve().parents[1] / "app" / "static" / "portal"
FUTURE = (date.today() + timedelta(days=400)).isoformat()
PAST = (date.today() - timedelta(days=400)).isoformat()


def seat(db, student, exam, hall="HALL-A", n="1"):
    db.add(models.Allotment(student_id=student.id, exam_id=exam.id, hall=hall, seat=n))
    db.commit()


def verified_hall(db, code="HALL-A", capacity=4, seats=4, **kw):
    h = dm.Hall(code=code, capacity=capacity, verified=True, **kw)
    db.add(h); db.flush()
    db.add_all([models.HallSeat(hall_id=h.id, seat_label=str(i), active=True) for i in range(1, seats + 1)])
    db.commit()
    return h


# ----------------------------------------------------------------------------- notices
def test_notices_empty_database(client):
    r = client.get("/api/portal/notices")
    assert r.status_code == 200
    d = r.json()
    assert d["dates"] == [] and d["announcements"] == [] and d["past_dates"] == 0


def test_notices_only_published_upcoming_dates_with_real_counts(client, db):
    s1, s2 = make_student(db, REG1), make_student(db, REG2, "Two")
    pub = make_exam(db, "published", "P", "P1", FUTURE)
    make_exam(db, "draft", "D", "D1", (date.today() + timedelta(days=401)).isoformat())
    make_exam(db, "published", "Old", "O1", PAST)
    seat(db, s1, pub, n="1"); seat(db, s2, pub, n="2")
    d = client.get("/api/portal/notices").json()
    assert [x["date"] for x in d["dates"]] == [FUTURE]            # draft hidden, past not listed
    sess = d["dates"][0]["sessions"]
    assert sess == [{"session": "FN", "exams": 1, "allotments": 2, "start_time": "09:30", "end_time": "12:30"}]
    assert d["past_dates"] == 1


def test_notices_includes_public_announcements_only(client, db):
    now = datetime.now(timezone.utc)
    db.add_all([models.Announcement(title="Public", body="b", published=True, created_by="a", publish_at=now - timedelta(hours=1)),
                models.Announcement(title="Draft", body="b", published=False, created_by="a"),
                models.Announcement(title="Targeted", body="b", published=True, created_by="a", publish_at=now, audience_department="CSE")])
    db.commit()
    titles = [a["title"] for a in client.get("/api/portal/notices").json()["announcements"]]
    assert titles == ["Public"]


def test_notices_rate_limited(client):
    for _ in range(120):
        assert client.get("/api/portal/notices").status_code == 200
    assert client.get("/api/portal/notices").status_code == 429


# ----------------------------------------------------------------------------- lookup
def test_portal_lookup_published_only_and_no_unpublished_count(client, db):
    s = make_student(db, REG1)
    pub = make_exam(db, "published", "Pub", "P1", FUTURE)
    drf = make_exam(db, "draft", "Draft", "D1", FUTURE)
    seat(db, s, pub, n="5"); seat(db, s, drf, n="6")
    d = client.get(f"/api/portal/lookup/{REG1}").json()
    assert [e["exam"] for e in d["entries"]] == ["Pub"]
    e = d["entries"][0]
    assert (e["hall"], e["seat"], e["session"], e["start_time"], e["end_time"], e["kind"], e["seat_map"]) == \
           ("HALL-A", "5", "FN", "09:30", "12:30", "allotment", True)
    assert "pending_unpublished" not in d              # unpublished allotments are not even counted for visitors
    assert "Draft" not in str(d)                       # the unpublished exam's details never leak


def test_portal_lookup_unknown_invalid_and_unallotted(client, db):
    make_student(db, REG1)
    assert client.get(f"/api/portal/lookup/{REG2}").status_code == 404
    assert client.get("/api/portal/lookup/!!").status_code == 422
    d = client.get(f"/api/portal/lookup/{REG1}").json()
    assert d["entries"] == [] and "pending_unpublished" not in d


def test_portal_lookup_privacy_fields(client, db):
    s = make_student(db, REG1, name="Secret Name")
    s.email = "private@example.org"; db.commit()
    e = make_exam(db, "published", "Pub", "P1", FUTURE)
    seat(db, s, e)
    d = client.get(f"/api/portal/lookup/{REG1}").json()
    assert "full_name" not in d["student"] and "Secret Name" not in str(d) and "private@example.org" not in str(d)
    settings.public_show_names = True
    assert client.get(f"/api/portal/lookup/{REG1}").json()["student"]["full_name"] == "Secret Name"


def test_portal_lookup_location_only_for_verified_halls(client, db):
    s = make_student(db, REG1)
    e = make_exam(db, "published", "Pub", "P1", FUTURE)
    seat(db, s, e, hall="HALL-A")
    db.add(dm.Hall(code="HALL-A", building="Block X", room="12", verified=False)); db.commit()
    assert "location" not in client.get(f"/api/portal/lookup/{REG1}").json()["entries"][0]
    h = db.scalar(select(dm.Hall)); h.verified = True; db.commit()
    assert client.get(f"/api/portal/lookup/{REG1}").json()["entries"][0]["location"] == {"building": "Block X", "room": "12"}


def test_portal_lookup_adds_subject_name_and_semester_only_when_stored(client, db):
    s = make_student(db, REG1)
    sub = models.Subject(code="P1", name="Signals", semester=5); db.add(sub); db.flush()
    e = make_exam(db, "published", "Pub", "P1", FUTURE); e.subject_id = sub.id; db.commit()
    seat(db, s, e)
    row = client.get(f"/api/portal/lookup/{REG1}").json()["entries"][0]
    assert row["subject_name"] == "Signals" and row["semester"] == 5
    e2 = make_exam(db, "published", "NoSubject", "ZZ9", FUTURE); seat(db, s, e2, n="2")
    row2 = [x for x in client.get(f"/api/portal/lookup/{REG1}").json()["entries"] if x["exam"] == "NoSubject"][0]
    assert row2["subject_name"] is None and row2["semester"] is None      # never invented


def test_portal_lookup_rate_limit_and_miss_cap(client, db):
    settings.public_lookup_miss_limit = 3
    for _ in range(3):
        assert client.get(f"/api/portal/lookup/{REG3}").status_code == 404
    assert client.get(f"/api/portal/lookup/{REG3}").status_code == 429


def test_legacy_lookup_shape_unchanged(client, db):
    s = make_student(db, REG1); e = make_exam(db, "published", "Pub", "P1", FUTURE); seat(db, s, e)
    row = client.get(f"/api/lookup/{REG1}").json()["allotments"][0]
    assert set(row) <= {"exam", "subject_code", "date", "time", "hall", "seat", "location"}


# ----------------------------------------------------------------------------- seat map
def test_seatmap_with_inventory_shows_taken_vacant_and_never_identities(client, db):
    settings.public_show_names = True
    a, b = make_student(db, REG1, "Alpha Person"), make_student(db, REG2, "Beta Person")
    e = make_exam(db, "published", "Pub", "P1", FUTURE)
    verified_hall(db, capacity=4, seats=4)
    seat(db, a, e, n="2"); seat(db, b, e, n="3")
    r = client.get(f"/api/portal/seatmap/{REG1}?kind=allotment&ref={e.id}")
    assert r.status_code == 200
    m = r.json()
    assert [(x["l"], x["s"]) for x in m["seats"]] == [("1", "vacant"), ("2", "yours"), ("3", "taken"), ("4", "vacant")]
    assert (m["your_seat"], m["taken_count"], m["capacity"], m["vacant_count"], m["layout_source"]) == ("2", 2, 4, 2, "hall_inventory")
    blob = r.text
    assert "Beta Person" not in blob and REG2 not in blob and "Alpha Person" not in blob


def test_seatmap_without_inventory_lists_only_allotted_seats(client, db):
    a, b = make_student(db, REG1), make_student(db, REG2, "Two")
    e = make_exam(db, "published", "Pub", "P1", FUTURE)
    seat(db, a, e, n="10"); seat(db, b, e, n="2")
    m = client.get(f"/api/portal/seatmap/{REG1}?kind=allotment&ref={e.id}").json()
    assert [x["l"] for x in m["seats"]] == ["2", "10"] and m["layout_source"] == "allotted_seats_only"
    assert m["vacant_count"] is None and m["capacity"] is None


def test_seatmap_refuses_other_students_unpublished_and_bad_input(client, db):
    a, b = make_student(db, REG1), make_student(db, REG2, "Two")
    pub = make_exam(db, "published", "Pub", "P1", FUTURE); drf = make_exam(db, "draft", "D", "D1", FUTURE)
    seat(db, a, pub); seat(db, a, drf, n="2")
    assert client.get(f"/api/portal/seatmap/{REG2}?kind=allotment&ref={pub.id}").status_code == 404   # b has no seat in that exam
    assert client.get(f"/api/portal/seatmap/{REG1}?kind=allotment&ref={drf.id}").status_code == 404   # unpublished
    assert client.get(f"/api/portal/seatmap/{REG1}?kind=bogus&ref=1").status_code == 422
    assert client.get(f"/api/portal/seatmap/{REG1}?kind=allotment&ref=0").status_code == 422
    assert client.get(f"/api/portal/seatmap/990025109999?kind=allotment&ref={pub.id}").status_code == 404


def _vsb_batch(db, status="published", review="approved", published=True):
    b = dm.VsbAllocBatch(exam_date=date.fromisoformat(FUTURE), session="AN", exam_name="VSB Nov", status=status, created_by="t")
    db.add(b); db.flush()
    return b


def _vsb_rec(db, batch, reg, student, seat_no, hall="H-9", review="approved", published=True):
    db.add(dm.VsbAllocRecord(batch_id=batch.id, register_number=reg, student_id=student.id if student else None, subject_code="CS1",
                             subject_title="Compilers", hall=hall, seat=seat_no, review_status=review, published=published,
                             verification_status="FULLY_VERIFIED"))
    db.commit()


def test_vsb_entries_and_seatmap_only_when_approved_and_published(client, db):
    a, b = make_student(db, REG1), make_student(db, REG2, "Two")
    batch = _vsb_batch(db)
    _vsb_rec(db, batch, REG1, a, "4"); _vsb_rec(db, batch, REG2, b, "5"); _vsb_rec(db, batch, "990025106003", None, "6")
    d = client.get(f"/api/portal/lookup/{REG1}").json()
    v = [e for e in d["entries"] if e["kind"] == "vsb"]
    assert len(v) == 1 and v[0]["session"] == "AN" and v[0]["hall"] == "H-9" and v[0]["seat"] == "4" and v[0]["seat_map"] is True
    m = client.get(f"/api/portal/seatmap/{REG1}?kind=vsb&ref={v[0]['ref']}").json()
    assert [(x["l"], x["s"]) for x in m["seats"]] == [("4", "yours"), ("5", "taken"), ("6", "taken")]
    assert REG2 not in str(m)
    notices = client.get("/api/portal/notices").json()["dates"][0]["sessions"]
    assert notices[0]["session"] == "AN" and notices[0]["allotments"] == 3


def test_vsb_draft_batch_or_unapproved_record_is_invisible(client, db):
    a = make_student(db, REG1)
    draft = _vsb_batch(db, status="draft")
    _vsb_rec(db, draft, REG1, a, "4", published=False)
    assert client.get(f"/api/portal/lookup/{REG1}").json()["entries"] == []
    assert client.get("/api/portal/notices").json()["dates"] == []
    assert client.get(f"/api/portal/seatmap/{REG1}?kind=vsb&ref={draft.id}").status_code == 404


# ----------------------------------------------------------------------------- static page contract
def test_portal_page_default_is_clean_and_csp_compatible(client):
    r = client.get("/portal/")
    assert r.status_code == 200
    html = r.text
    assert "922525106" not in html and "value=" not in re.search(r'<input id="regInput"[^>]*>', html).group(0)
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), "inline scripts are blocked by the CSP"
    assert not re.search(r"\son[a-z]+\s*=", html), "inline event handlers are blocked by the CSP"
    csp = r.headers["content-security-policy"]
    assert "script-src" not in csp and "default-src 'self'" in csp
    for asset in ("portal.css", "portal.js"):
        assert client.get("/portal/" + asset).status_code == 200


def test_portal_sources_never_contain_the_example_register_number():
    for f in STATIC.iterdir():
        if f.is_file():
            assert "922525106" not in f.read_text(encoding="utf-8"), f.name


def test_portal_redirect_and_reg_parameter_served(client):
    assert client.get("/portal", follow_redirects=False).headers["location"] == "/portal/"
    assert client.get("/portal/?reg=990025106001").status_code == 200


# ----------------------------------------------------------------------------- operations overview
def test_operations_requires_staff_or_admin(client, db, student_auth):
    assert client.get("/api/operations/overview").status_code == 401
    assert client.get("/api/operations/overview", headers=student_auth).status_code == 403


def test_operations_empty_database(client, admin):
    d = client.get("/api/operations/overview", headers=admin).json()
    assert d["totals"]["students"] == 0 and d["examinations"] == [] and d["halls"] == []
    assert "recent_activity" in d


def test_operations_flags_real_problems_with_explainable_codes(client, db, admin):
    a, b = make_student(db, REG1), make_student(db, REG2, "Two")
    e1 = make_exam(db, "published", "One", "C1", FUTURE)
    e2 = models.Exam(title="Two", subject_code="C2", exam_date=FUTURE, start_time="10:00", end_time="13:00", venue="V", status="draft")
    e0 = make_exam(db, "draft", "Empty", "C0", FUTURE); e0.start_time, e0.end_time = "12:00", "11:00"
    db.add(e2); db.commit()
    dm_hall = verified_hall(db, "SMALL", capacity=1, seats=1)
    seat(db, a, e1, hall="SMALL", n="1"); seat(db, b, e1, hall="NOWHERE", n="1")
    seat(db, a, e2, hall="SMALL", n="1")
    d = client.get("/api/operations/overview", headers=admin).json()
    by = {x["title"]: {i["code"] for i in x["issues"]} for x in d["examinations"]}
    assert "unknown_hall" in by["One"] and "student_clash" in by["One"] and "student_clash" in by["Two"]
    assert {"no_allotments", "bad_time"} <= by["Empty"]
    assert next(x for x in d["examinations"] if x["title"] == "Empty")["readiness"] == "blocked"
    hall = next(h for h in d["halls"] if h["hall"] == "SMALL")
    assert hall["capacity"] == 1 and hall["utilization_percent"] == 100.0
    assert any(i["severity"] == "error" for i in d["insights"])


def test_operations_over_capacity_detected(client, db, admin):
    a, b = make_student(db, REG1), make_student(db, REG2, "Two")
    e = make_exam(db, "published", "One", "C1", FUTURE)
    verified_hall(db, "TINY", capacity=1, seats=0)
    seat(db, a, e, hall="TINY", n="1"); seat(db, b, e, hall="TINY", n="2")
    issues = client.get("/api/operations/overview", headers=admin).json()["examinations"][0]["issues"]
    oc = next(i for i in issues if i["code"] == "over_capacity")
    assert oc["severity"] == "error" and "TINY (2/1)" in oc["detail"]


def test_operations_completeness_percentage_uses_only_real_eligible_students(client, db, admin):
    a = make_student(db, REG1); make_student(db, REG2, "Two")
    e = make_exam(db, "published", "One", "C1", FUTURE)
    seat(db, a, e)
    row = client.get("/api/operations/overview", headers=admin).json()["examinations"][0]
    assert (row["eligible"], row["allocated"], row["completion_percent"]) == (2, 1, 50.0)
    assert "incomplete_allocation" in {i["code"] for i in row["issues"]}


def test_operations_staff_scope_and_no_audit_for_staff(client, db):
    from app import models as m
    make_student(db, REG1, dept="CSE"); make_student(db, REG2, "Two", dept="ECE")
    u = make_user(db, "dept1", "staff"); u.department = "CSE"; db.commit()
    h = login(client, "dept1")
    d = client.get("/api/operations/overview", headers=h).json()
    assert d["totals"]["students"] == 1 and d["scope_department"] == "CSE"
    assert "recent_activity" not in d and "publication_history" not in d


def test_operations_publication_history_for_admin(client, db, admin):
    e = make_exam(db, "draft", "One", "C1", FUTURE)
    assert client.post(f"/api/exams/{e.id}/publish", headers=admin).status_code == 200
    d = client.get("/api/operations/overview", headers=admin).json()
    assert [(h["action"], h["title"]) for h in d["publication_history"]] == [("exam.published", "One")]


def test_operations_super_admin_sees_activity(client, db):
    make_user(db, "root1", "super_admin")
    h = login(client, "root1")
    d = client.get("/api/operations/overview", headers=h).json()
    assert "recent_activity" in d and "publication_history" in d
