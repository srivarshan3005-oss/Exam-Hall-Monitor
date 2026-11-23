from sqlalchemy import select
from app import models
from app.config import settings
from conftest import REG1, REG2, make_student, make_exam


def body(reg=REG1, exam_id=1, hall="demo hall 01", seat="5"):
    return {"register_number": reg, "exam_id": exam_id, "hall": hall, "seat": seat}


def test_create_allotment_and_public_view(client, db, staff):
    make_student(db, REG1)
    e = make_exam(db)
    r = client.post("/api/allotments", headers=staff, json=body(exam_id=e.id))
    assert r.status_code == 201 and r.json()["hall"] == "DEMO HALL 01"
    rows = client.get(f"/api/allotments/{REG1}").json()
    assert rows == [{"exam": "DEMO Exam", "subject_code": "DEMO101", "date": "2027-01-15", "time": "09:30",
                     "hall": "DEMO HALL 01", "seat": "5"}]
    assert db.scalar(select(models.AuditLog).where(models.AuditLog.action == "allotment.created"))



def test_public_allotment_omits_empty_location_for_verified_hall(client, db, staff):
    """Verified inventory without hierarchy data must not leak location: {} or null fields."""
    from app import doc_models
    student = make_student(db, REG1)
    exam = make_exam(db)
    hall = doc_models.Hall(code="BARE-HALL", display_name="Bare Hall", capacity=1, verified=True)
    db.add(hall)
    db.commit()
    response = client.post("/api/allotments", headers=staff,
                           json=body(exam_id=exam.id, hall="BARE-HALL", seat="A1"))
    assert response.status_code == 201, response.text
    row = client.get(f"/api/allotments/{REG1}").json()[0]
    assert "location" not in row


def test_conflicts_rejected(client, db, staff):
    make_student(db, REG1); make_student(db, REG2, name="Two")
    e = make_exam(db)
    assert client.post("/api/allotments", headers=staff, json=body(exam_id=e.id)).status_code == 201
    assert client.post("/api/allotments", headers=staff, json=body(exam_id=e.id, seat="6")).status_code == 409  # same student
    assert client.post("/api/allotments", headers=staff, json=body(REG2, e.id)).status_code == 409             # same seat


def test_unknown_student_or_exam(client, db, staff):
    make_student(db, REG1)
    assert client.post("/api/allotments", headers=staff, json=body(exam_id=999)).status_code == 404
    assert client.post("/api/allotments", headers=staff, json=body("990025106888", 1)).status_code == 404


def test_allotment_validation(client, staff):
    assert client.post("/api/allotments", headers=staff, json=body(seat="<script>")).status_code == 422
    assert client.post("/api/allotments", headers=staff, json=body(reg="x")).status_code == 422
    assert client.post("/api/allotments", headers=staff, json=body(hall="")).status_code == 422


def test_public_view_hides_unpublished_exams(client, db, staff):
    s = make_student(db, REG1)
    for status in ("draft", "completed"):
        e = make_exam(db, status, code=status.upper())
        db.add(models.Allotment(student_id=s.id, exam_id=e.id, hall="H", seat="1"))
    db.commit()
    assert client.get(f"/api/allotments/{REG1}").json() == []


def test_unknown_register_returns_empty_list_not_404(client, db):
    make_student(db, REG1)
    assert client.get("/api/allotments/990025106999").json() == []
    assert client.get(f"/api/allotments/{REG1}").json() == []


def test_public_allotment_endpoint_is_rate_limited(client, monkeypatch):
    monkeypatch.setattr(settings, "public_lookup_per_minute", 2)
    assert [client.get(f"/api/allotments/{REG1}").status_code for _ in range(3)] == [200, 200, 429]


def test_delete_allotment_audited(client, db, staff):
    make_student(db, REG1)
    e = make_exam(db)
    aid = client.post("/api/allotments", headers=staff, json=body(exam_id=e.id)).json()["id"]
    assert client.delete(f"/api/allotments/{aid}", headers=staff).status_code == 200
    assert client.delete(f"/api/allotments/{aid}", headers=staff).status_code == 404
    assert db.scalar(select(models.AuditLog).where(models.AuditLog.action == "allotment.deleted"))
    assert client.get(f"/api/allotments/{REG1}").json() == []


def _verified_inventory(db, code="HALL-A", capacity=2):
    from app import doc_models
    hall = doc_models.Hall(code=code, display_name=code, capacity=capacity, verified=True)
    db.add(hall); db.flush()
    db.add_all([models.HallSeat(hall_id=hall.id, seat_label=str(n), active=True)
                for n in range(1, capacity + 1)])
    db.commit()
    return hall


def test_auto_allocation_preview_is_non_mutating_and_balanced(client, db, staff):
    from app import doc_models
    make_student(db, REG1, dept="CSE")
    make_student(db, REG2, name="Two", dept="ECE")
    exam = make_exam(db)
    h1 = _verified_inventory(db, "HALL-A", 1)
    h2 = _verified_inventory(db, "HALL-B", 1)
    response = client.post("/api/allotments/auto-preview", headers=staff,
                           json={"exam_id": exam.id, "hall_ids": [h1.id, h2.id]})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["new_allocations"] == 2
    assert {a["hall"] for a in payload["assignments"]} == {"HALL-A", "HALL-B"}
    assert db.query(models.Allotment).count() == 0


def test_auto_allocation_requires_confirmation_and_admin_commit(client, db, staff, admin):
    make_student(db, REG1)
    exam = make_exam(db)
    hall = _verified_inventory(db, "HALL-C", 2)
    body = {"exam_id": exam.id, "hall_ids": [hall.id]}
    denied = client.post("/api/allotments/auto-allocate", headers=staff, json=body)
    assert denied.status_code == 403
    committed = client.post("/api/allotments/auto-allocate", headers=admin, json=body)
    assert committed.status_code == 201, committed.text
    assert committed.json()["created"] == 1
    assert db.query(models.Allotment).count() == 1
    repeated = client.post("/api/allotments/auto-allocate", headers=admin, json=body)
    assert repeated.status_code == 201
    assert repeated.json()["created"] == 0


def test_auto_allocation_fails_without_enough_verified_seats(client, db, admin):
    make_student(db, REG1)
    make_student(db, REG2, name="Two")
    exam = make_exam(db)
    hall = _verified_inventory(db, "HALL-D", 1)
    response = client.post("/api/allotments/auto-preview", headers=admin,
                           json={"exam_id": exam.id, "hall_ids": [hall.id]})
    assert response.status_code == 409
    assert db.query(models.Allotment).count() == 0


def test_auto_allocation_rejects_unverified_or_unknown_halls(client, db, admin):
    make_student(db, REG1)
    exam = make_exam(db)
    from app import doc_models
    hall = doc_models.Hall(code="UNVERIFIED", capacity=1, verified=False)
    db.add(hall); db.commit()
    response = client.post("/api/allotments/auto-preview", headers=admin,
                           json={"exam_id": exam.id, "hall_ids": [hall.id]})
    assert response.status_code == 422
