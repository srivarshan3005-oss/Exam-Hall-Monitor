"""Phase 2: subject catalogue, academic years/terms, eligibility, publish workflow, filters."""
from datetime import date, timedelta
from sqlalchemy import select
from app import models
from conftest import REG1, REG2, make_student, make_exam

FUT = (date.today() + timedelta(days=60)).isoformat()


def exam_body(**kw):
    base = {"title": "Phase2 Exam", "subject_code": "P2101", "exam_date": FUT, "start_time": "09:30",
            "end_time": "12:30", "venue": "Block P", "status": "draft"}
    base.update(kw)
    return base


def test_subject_crud_and_unique_code(client, admin, staff):
    r = client.post("/api/admin/subjects", headers=admin, json={"code": "ec3452", "name": "Digital Electronics"})
    assert r.status_code == 201 and r.json()["code"] == "EC3452"
    assert client.post("/api/admin/subjects", headers=staff, json={"code": "EC3452", "name": "Dup"}).status_code == 409
    sid = r.json()["id"]
    assert client.patch(f"/api/admin/subjects/{sid}", headers=staff, json={"name": "Digital Electronics II"}).json()["name"] == "Digital Electronics II"
    assert client.get("/api/admin/subjects?q=digital", headers=staff).json()[0]["code"] == "EC3452"
    assert client.post("/api/admin/subjects", headers=admin, json={"code": "!!", "name": "Bad"}).status_code == 422


def test_subject_endpoints_require_staff(client, student_auth):
    assert client.get("/api/admin/subjects").status_code == 401
    assert client.get("/api/admin/subjects", headers=student_auth).status_code == 403


def test_exam_from_catalogue_sets_code_and_duration(client, admin, db):
    sid = client.post("/api/admin/subjects", headers=admin, json={"code": "CS101", "name": "Intro"}).json()["id"]
    r = client.post("/api/exams", headers=admin, json=exam_body(subject_code=None, subject_id=sid))
    assert r.status_code == 201, r.text
    e = db.get(models.Exam, r.json()["id"])
    assert e.subject_code == "CS101" and e.duration_minutes == 180
    row = client.get("/api/admin/exams", headers=admin).json()[0]
    assert row["duration_minutes"] == 180 and row["session"] == "FN" and row["subject_name"] == "Intro"


def test_exam_requires_subject_id_or_code(client, admin):
    assert client.post("/api/exams", headers=admin, json=exam_body(subject_code=None)).status_code == 422


def test_term_and_year_validation(client, admin):
    y = client.post("/api/admin/academic-years", headers=admin, json={"label": "2026-27", "start_date": "2026-06-01", "end_date": "2027-05-31", "is_current": True})
    assert y.status_code == 201
    assert client.post("/api/admin/academic-years", headers=admin, json={"label": "2027-28", "start_date": "2027-06-01", "end_date": "2027-01-01"}).status_code == 422
    t = client.post("/api/admin/terms", headers=admin, json={"academic_year_id": y.json()["id"], "name": "End Sem", "start_date": "2026-11-01", "end_date": "2026-12-20"})
    assert t.status_code == 201
    outside = client.post("/api/admin/terms", headers=admin, json={"academic_year_id": y.json()["id"], "name": "Bad", "start_date": "2025-01-01", "end_date": "2025-02-01"})
    assert outside.status_code == 422
    tid = t.json()["id"]
    assert client.post("/api/exams", headers=admin, json=exam_body(exam_date="2026-11-10", term_id=tid)).status_code == 201
    assert client.post("/api/exams", headers=admin, json=exam_body(title="Out", venue="X", exam_date="2027-03-10", term_id=tid)).status_code == 422


def test_staff_cannot_create_terms(client, staff):
    assert client.post("/api/admin/terms", headers=staff, json={"academic_year_id": 1, "name": "T", "start_date": "2026-01-01", "end_date": "2026-02-01"}).status_code == 403


def test_publish_unpublish_and_past_date_guard(client, admin, db):
    eid = client.post("/api/exams", headers=admin, json=exam_body()).json()["id"]
    assert client.post(f"/api/exams/{eid}/publish", headers=admin).json()["status"] == "published"
    assert client.post(f"/api/exams/{eid}/publish", headers=admin).status_code == 409
    assert len(client.get("/api/exams").json()) == 1
    assert client.post(f"/api/exams/{eid}/unpublish", headers=admin).json()["status"] == "draft"
    assert client.get("/api/exams").json() == []
    past = client.post("/api/exams", headers=admin, json=exam_body(title="Old", venue="Old", exam_date="2020-01-10")).json()["id"]
    assert client.post(f"/api/exams/{past}/publish", headers=admin).status_code == 422
    actions = {a.action for a in db.scalars(select(models.AuditLog)).all()}
    assert {"exam.published", "exam.unpublished"} <= actions


def test_delete_only_draft_without_allotments(client, admin, db, staff):
    e = make_exam(db, "draft")
    assert client.delete(f"/api/exams/{e.id}", headers=staff).status_code == 403
    s = make_student(db, REG1)
    db.add(models.Allotment(student_id=s.id, exam_id=e.id, hall="H", seat="1")); db.commit()
    assert client.delete(f"/api/exams/{e.id}", headers=admin).status_code == 409
    e2 = make_exam(db, "draft", code="DEL2")
    assert client.delete(f"/api/exams/{e2.id}", headers=admin).status_code == 200


def test_admin_exam_filters(client, admin):
    client.post("/api/exams", headers=admin, json=exam_body(title="Alpha Test", subject_code="AAA1", venue="V1"))
    client.post("/api/exams", headers=admin, json=exam_body(title="Beta Test", subject_code="BBB1", venue="V2", start_time="14:00", end_time="16:00", status="published"))
    r = client.get("/api/admin/exams?q=alpha", headers=admin)
    assert [e["subject_code"] for e in r.json()] == ["AAA1"] and r.headers["X-Total-Count"] == "1"
    assert [e["subject_code"] for e in client.get("/api/admin/exams?session=AN", headers=admin).json()] == ["BBB1"]
    assert [e["subject_code"] for e in client.get("/api/admin/exams?status=published", headers=admin).json()] == ["BBB1"]
    assert client.get("/api/admin/exams?status=bogus", headers=admin).status_code == 422


def test_eligibility_rules_drive_audience(client, admin, db):
    make_student(db, REG1, dept="ECE", year=2); make_student(db, REG2, name="Two", dept="CSE", year=2)
    eid = client.post("/api/exams", headers=admin, json=exam_body()).json()["id"]
    assert client.get(f"/api/exams/{eid}/eligibility", headers=admin).json()["eligible_count"] == 2
    r = client.put(f"/api/exams/{eid}/eligibility", headers=admin, json={"rules": [{"department": "ece", "year": 2}]})
    assert r.status_code == 200 and r.json()["eligible_count"] == 1
    r = client.put(f"/api/exams/{eid}/eligibility", headers=admin, json={"rules": [{"department": "ECE"}], "include": [REG2]})
    assert r.json()["eligible_count"] == 2
    assert client.put(f"/api/exams/{eid}/eligibility", headers=admin, json={"rules": [{}]}).status_code == 422
    assert client.put(f"/api/exams/{eid}/eligibility", headers=admin, json={"include": [REG1], "exclude": [REG1]}).status_code == 422
    assert client.put(f"/api/exams/{eid}/eligibility", headers=admin, json={"include": ["990099999999"]}).status_code == 422


def test_overlapping_exam_for_same_audience_rejected(client, admin):
    a = client.post("/api/exams", headers=admin, json=exam_body(venue="V1")).json()["id"]
    b = client.post("/api/exams", headers=admin, json=exam_body(title="Second", subject_code="P2102", venue="V2")).json()["id"]
    rule = {"rules": [{"department": "ECE", "year": 2}]}
    assert client.put(f"/api/exams/{a}/eligibility", headers=admin, json=rule).status_code == 200
    assert client.put(f"/api/exams/{b}/eligibility", headers=admin, json=rule).status_code == 409
    other = {"rules": [{"department": "CSE", "year": 2}]}
    assert client.put(f"/api/exams/{b}/eligibility", headers=admin, json=other).status_code == 200
    # moving exam b onto a's audience is irrelevant (different audiences) but the time can still clash for the same venue
    assert client.patch(f"/api/exams/{b}", headers=admin, json={"venue": "V1"}).status_code == 409
