from sqlalchemy import select
from app import models
from app.config import settings
from conftest import REG1, REG2, make_student, make_exam, make_user, login


def rbody(exam_id, reg=REG1, **kw):
    return {"register_number": reg, "exam_id": exam_id, "marks": 78.5, "max_marks": 100, "grade": "A", **kw}


def test_admin_creates_result_and_marks_not_in_audit(client, db, admin):
    make_student(db, REG1)
    e = make_exam(db)
    r = client.post("/api/results", headers=admin, json=rbody(e.id))
    assert r.status_code == 201 and r.json()["published"] is False
    log = db.scalar(select(models.AuditLog).where(models.AuditLog.action == "result.created"))
    assert "78.5" not in (log.details or "")


def test_validation_and_duplicates(client, db, admin):
    make_student(db, REG1)
    e = make_exam(db)
    assert client.post("/api/results", headers=admin, json={**rbody(e.id), "marks": 101}).status_code == 422
    assert client.post("/api/results", headers=admin, json={**rbody(e.id), "marks": -1}).status_code == 422
    assert client.post("/api/results", headers=admin, json={**rbody(e.id), "max_marks": 0}).status_code == 422
    assert client.post("/api/results", headers=admin, json=rbody(e.id, "990025106999")).status_code == 404
    assert client.post("/api/results", headers=admin, json=rbody(e.id)).status_code == 201
    assert client.post("/api/results", headers=admin, json=rbody(e.id)).status_code == 409


def test_results_require_sign_in_by_default(client, db):
    make_student(db, REG1)
    assert client.get(f"/api/results/{REG1}").status_code == 401


def test_student_sees_only_own_published_results(client, db, admin, student_auth):
    make_student(db, REG2, name="Two")
    e1, e2 = make_exam(db, code="A1"), make_exam(db, code="B1")
    client.post("/api/results", headers=admin, json=rbody(e1.id, published=True))
    client.post("/api/results", headers=admin, json=rbody(e2.id))  # unpublished
    client.post("/api/results", headers=admin, json=rbody(e1.id, REG2, published=True))
    own = client.get(f"/api/results/{REG1}", headers=student_auth)
    assert own.status_code == 200 and [r["subject_code"] for r in own.json()] == ["A1"]
    assert client.get(f"/api/results/{REG2}", headers=student_auth).status_code == 403


def test_staff_can_read_results(client, db, admin, staff):
    make_student(db, REG1)
    e = make_exam(db)
    client.post("/api/results", headers=admin, json=rbody(e.id, published=True))
    assert len(client.get(f"/api/results/{REG1}", headers=staff).json()) == 1


def test_publish_and_unpublish_flow(client, db, admin, staff, student_auth):
    e = make_exam(db)
    rid = client.post("/api/results", headers=admin, json=rbody(e.id)).json()["id"]
    assert client.get(f"/api/results/{REG1}", headers=student_auth).json() == []
    assert client.post(f"/api/results/{rid}/publish", headers=staff).status_code == 403
    assert client.post(f"/api/results/{rid}/publish", headers=admin).json()["published"] is True
    assert len(client.get(f"/api/results/{REG1}", headers=student_auth).json()) == 1
    assert client.post(f"/api/results/{rid}/unpublish", headers=admin).json()["published"] is False
    assert client.get(f"/api/results/{REG1}", headers=student_auth).json() == []
    actions = [a.action for a in db.scalars(select(models.AuditLog)).all()]
    assert "result.published" in actions and "result.unpublished" in actions
    assert client.post("/api/results/9999/publish", headers=admin).status_code == 404


def test_public_results_switch(client, db, admin, monkeypatch):
    make_student(db, REG1)
    e = make_exam(db)
    client.post("/api/results", headers=admin, json=rbody(e.id, published=True))
    monkeypatch.setattr(settings, "public_results_enabled", True)
    assert len(client.get(f"/api/results/{REG1}").json()) == 1
    assert client.get("/api/results/990025106999").status_code == 404
    assert client.get("/api/lookup/" + REG1).json()["results_available_without_signin"] is True


def test_unlinked_student_account_gets_nothing(client, db):
    make_student(db, REG1)
    make_user(db, "orphan", "student")
    assert client.get(f"/api/results/{REG1}", headers=login(client, "orphan")).status_code == 403
