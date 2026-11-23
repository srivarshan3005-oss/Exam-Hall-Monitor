import pytest
from sqlalchemy import select
from app import models
from conftest import make_exam

GOOD = {"title": "End Semester", "subject_code": "ec3452", "exam_date": "2027-02-01",
        "start_time": "09:30", "end_time": "12:30", "venue": "Main Block", "status": "draft"}


def test_public_list_only_published(client, db):
    make_exam(db, "published", code="PUB1")
    make_exam(db, "draft", code="DRAFT1")
    make_exam(db, "completed", code="DONE1")
    assert [e["subject_code"] for e in client.get("/api/exams").json()] == ["PUB1"]


def test_admin_list_requires_staff(client, db, admin):
    make_exam(db, "draft")
    assert client.get("/api/admin/exams").status_code == 401
    assert len(client.get("/api/admin/exams", headers=admin).json()) == 1


def test_create_exam_normalises_and_audits(client, db, staff):
    r = client.post("/api/exams", headers=staff, json=GOOD)
    assert r.status_code == 201
    e = db.get(models.Exam, r.json()["id"])
    assert e.subject_code == "EC3452"
    log = db.scalar(select(models.AuditLog).where(models.AuditLog.action == "exam.created"))
    assert log.actor == "staff1" and log.actor_role == "staff" and log.target == str(e.id) and log.ip_address


@pytest.mark.parametrize("patch", [{"end_time": "09:30"}, {"end_time": "08:00"}, {"exam_date": "2027-02-30"},
                                   {"exam_date": "01-02-2027"}, {"start_time": "25:00"}, {"status": "archived"},
                                   {"subject_code": "!!"}, {"title": "x"}])
def test_create_exam_validation(client, admin, patch):
    assert client.post("/api/exams", headers=admin, json={**GOOD, **patch}).status_code == 422


def test_patch_exam_status_audited_and_revalidated(client, db, admin):
    e = make_exam(db, "draft")
    r = client.patch(f"/api/exams/{e.id}", headers=admin, json={"status": "published"})
    assert r.status_code == 200 and r.json()["status"] == "published"
    log = db.scalar(select(models.AuditLog).where(models.AuditLog.action == "exam.updated"))
    assert "draft->published" in log.details
    assert client.patch(f"/api/exams/{e.id}", headers=admin, json={"end_time": "08:00"}).status_code == 422
    assert client.patch("/api/exams/99999", headers=admin, json={"status": "draft"}).status_code == 404
    assert client.get("/api/exams").json()[0]["id"] == e.id


def test_same_venue_overlapping_exam_is_rejected_but_adjacent_is_allowed(client, admin):
    first = client.post("/api/exams", headers=admin, json=GOOD)
    assert first.status_code == 201
    overlap = {**GOOD, "title": "Overlapping", "start_time": "11:00", "end_time": "13:00"}
    assert client.post("/api/exams", headers=admin, json=overlap).status_code == 409
    adjacent = {**GOOD, "title": "Adjacent", "start_time": "12:30", "end_time": "14:00"}
    assert client.post("/api/exams", headers=admin, json=adjacent).status_code == 201


def test_exam_update_checks_venue_conflicts(client, admin):
    one = client.post("/api/exams", headers=admin, json=GOOD).json()
    two = client.post("/api/exams", headers=admin,
                      json={**GOOD, "title": "Second", "start_time": "13:00", "end_time": "15:00"}).json()
    response = client.patch(f"/api/exams/{two['id']}", headers=admin,
                            json={"start_time": "10:00", "end_time": "11:00"})
    assert response.status_code == 409
    assert client.get("/api/admin/exams", headers=admin).status_code == 200
