"""Phase 2: allocation plans (preview -> approve -> commit), rules, conflicts, manual correction, history."""
from sqlalchemy import select
from app import models, doc_models
from conftest import REG1, REG2, REG3, make_student, make_exam


def hall(db, code="HALL-A", n=4, verified=True):
    h = doc_models.Hall(code=code, display_name=code, capacity=n, verified=verified)
    db.add(h); db.flush()
    db.add_all([models.HallSeat(hall_id=h.id, seat_label=str(i), active=True) for i in range(1, n + 1)])
    db.commit()
    return h


def plan(client, headers, exam, **kw):
    return client.post("/api/allotments/plans", headers=headers, json={"exam_id": exam.id, **kw})


def test_plan_preview_does_not_save_and_commit_needs_admin(client, db, staff, admin):
    make_student(db, REG1); make_student(db, REG2, name="Two")
    e = make_exam(db); hall(db)
    r = plan(client, staff, e)
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["summary"]["new_allocations"] == 2 and p["can_commit"] and db.query(models.Allotment).count() == 0
    assert client.post(f"/api/allotments/plans/{p['id']}/commit", headers=staff).status_code == 403
    c = client.post(f"/api/allotments/plans/{p['id']}/commit", headers=admin)
    assert c.status_code == 201 and c.json()["created"] == 2
    db.expire_all()
    assert db.query(models.Allotment).count() == 2
    assert db.query(models.AllotmentHistory).filter_by(action="auto_created").count() == 2
    assert db.scalar(select(models.AuditLog).where(models.AuditLog.action == "allocation.plan_committed"))
    assert client.post(f"/api/allotments/plans/{p['id']}/commit", headers=admin).status_code == 409   # already committed


def test_commit_detects_stale_plan(client, db, admin):
    make_student(db, REG1); make_student(db, REG2, name="Two")
    e = make_exam(db); hall(db)
    p = plan(client, admin, e).json()
    s = db.scalar(select(models.Student).where(models.Student.register_number == REG1))
    db.add(models.Allotment(student_id=s.id, exam_id=e.id, hall="HALL-A", seat="1")); db.commit()   # world changed
    r = client.post(f"/api/allotments/plans/{p['id']}/commit", headers=admin)
    assert r.status_code == 409
    assert client.get(f"/api/allotments/plans/{p['id']}", headers=admin).json()["status"] == "stale"


def test_insufficient_capacity_blocks_commit_unless_partial(client, db, admin):
    for i, r in enumerate((REG1, REG2, REG3)):
        make_student(db, r, name=f"S{i}")
    e = make_exam(db); hall(db, n=2)
    p = plan(client, admin, e).json()
    assert p["summary"]["capacity_sufficient"] is False and p["can_commit"] is False
    assert client.post(f"/api/allotments/plans/{p['id']}/commit", headers=admin).status_code == 409
    assert db.query(models.Allotment).count() == 0
    ok = client.post(f"/api/allotments/plans/{p['id']}/commit", headers=admin, json={"allow_partial": True})
    assert ok.status_code == 201 and ok.json()["created"] == 2 and ok.json()["unallocated"] == 1


def test_existing_allocations_preserved(client, db, admin):
    s1 = make_student(db, REG1); make_student(db, REG2, name="Two")
    e = make_exam(db); hall(db)
    db.add(models.Allotment(student_id=s1.id, exam_id=e.id, hall="HALL-A", seat="1")); db.commit()
    p = plan(client, admin, e).json()
    assert p["summary"]["already_allocated"] == 1 and p["assignments"][0]["seat"] != "1"
    client.post(f"/api/allotments/plans/{p['id']}/commit", headers=admin)
    db.expire_all()
    assert db.scalar(select(models.Allotment).where(models.Allotment.student_id == s1.id)).seat == "1"


def test_only_eligible_students_allocated(client, db, admin):
    make_student(db, REG1, dept="ECE"); make_student(db, REG2, name="Two", dept="CSE")
    e = make_exam(db); hall(db)
    client.put(f"/api/exams/{e.id}/eligibility", headers=admin, json={"rules": [{"department": "ECE"}]})
    p = plan(client, admin, e).json()
    assert [a["register_number"] for a in p["assignments"]] == [REG1]


def test_simultaneous_exams_cannot_share_students_or_seats(client, db, admin):
    make_student(db, REG1); make_student(db, REG2, name="Two")
    e1 = make_exam(db, code="E1"); e2 = make_exam(db, code="E2")        # same date/time => simultaneous
    hall(db, n=2)
    client.post(f"/api/allotments/plans/{plan(client, admin, e1).json()['id']}/commit", headers=admin)
    p2 = plan(client, admin, e2).json()                                # everyone is already seated in e1
    assert p2["summary"]["new_allocations"] == 0
    assert {u["reason"] for u in p2["unallocated"]} == {"simultaneous_exam"}
    # a brand-new student in e2 may not take e1's seats either
    make_student(db, REG3, name="Three")
    p3 = plan(client, admin, e2).json()
    assert p3["summary"]["new_allocations"] == 0 and p3["summary"]["capacity_sufficient"] is False


def test_department_separation_and_gap_rules(client, db, admin):
    for i in range(3):
        make_student(db, f"99002510610{i}", name=f"C{i}", dept="CSE")
        make_student(db, f"99002520610{i}", name=f"E{i}", dept="ECE")
    e = make_exam(db); hall(db, n=6)
    p = plan(client, admin, e, strategy="sequential", department_separation="strict").json()
    depts = {int(a["seat"]): a["department"] for a in p["assignments"]}
    assert len(depts) == 6 and all(depts[i] != depts[i + 1] for i in range(1, 6))
    p = plan(client, admin, e, strategy="sequential", seat_gap=1).json()
    assert [a["seat"] for a in p["assignments"]] == ["1", "3", "5"] and not p["summary"]["capacity_sufficient"]


def test_plan_validation(client, db, admin):
    e = make_exam(db)
    assert plan(client, admin, e, seat_gap=9).status_code == 422
    assert plan(client, admin, e, strategy="x").status_code == 422
    assert client.post("/api/allotments/plans", headers=admin, json={"exam_id": 999}).status_code == 404


def test_discard_plan(client, db, admin):
    make_student(db, REG1); e = make_exam(db); hall(db)
    p = plan(client, admin, e).json()
    assert client.post(f"/api/allotments/plans/{p['id']}/discard", headers=admin).json()["status"] == "discarded"
    assert client.post(f"/api/allotments/plans/{p['id']}/commit", headers=admin).status_code == 409


def test_manual_allocation_checks_eligibility_and_simultaneous_clash(client, db, staff, admin):
    make_student(db, REG1, dept="ECE")
    e1 = make_exam(db, code="E1"); e2 = make_exam(db, code="E2"); hall(db, n=3)
    body = lambda e, seat: {"register_number": REG1, "exam_id": e.id, "hall": "HALL-A", "seat": seat}  # noqa: E731
    assert client.post("/api/allotments", headers=staff, json=body(e1, "1")).status_code == 201
    assert client.post("/api/allotments", headers=staff, json=body(e2, "2")).status_code == 409        # same student, same time
    client.put(f"/api/exams/{e1.id}/eligibility", headers=admin, json={"rules": [{"department": "CSE"}]})
    make_student(db, REG2, name="Two", dept="ECE")
    r = client.post("/api/allotments", headers=staff, json={**body(e1, "3"), "register_number": REG2})
    assert r.status_code == 409 and "eligible" in r.json()["detail"]


def test_move_requires_reason_and_writes_history(client, db, staff):
    make_student(db, REG1); e = make_exam(db); hall(db, n=3)
    aid = client.post("/api/allotments", headers=staff, json={"register_number": REG1, "exam_id": e.id, "hall": "HALL-A", "seat": "1"}).json()["id"]
    assert client.patch(f"/api/allotments/{aid}", headers=staff, json={"hall": "HALL-A", "seat": "2"}).status_code == 422
    r = client.patch(f"/api/allotments/{aid}", headers=staff, json={"hall": "HALL-A", "seat": "2", "reason": "wheelchair access"})
    assert r.status_code == 200 and r.json()["seat"] == "2"
    assert client.patch(f"/api/allotments/{aid}", headers=staff, json={"hall": "HALL-A", "seat": "99", "reason": "bad seat"}).status_code == 422
    h = client.get(f"/api/allotments/history?exam_id={e.id}", headers=staff).json()
    assert [x["action"] for x in h][0] == "moved" and h[0]["from"] == "HALL-A/1" and h[0]["reason"] == "wheelchair access"
    assert db.scalar(select(models.AuditLog).where(models.AuditLog.action == "allotment.moved"))
    client.delete(f"/api/allotments/{aid}?reason=withdrawn", headers=staff)
    assert db.query(models.AllotmentHistory).filter_by(action="deleted").count() == 1


def test_exam_allotment_list_requires_staff(client, db, student_auth, staff):
    e = make_exam(db)
    assert client.get(f"/api/allotments/exam/{e.id}", headers=student_auth).status_code == 403
    assert client.get(f"/api/allotments/exam/{e.id}", headers=staff).status_code == 200


def test_public_lookup_stays_privacy_safe(client, db, admin):
    make_student(db, REG1); e = make_exam(db); hall(db)
    client.post(f"/api/allotments/plans/{plan(client, admin, e).json()['id']}/commit", headers=admin)
    body = client.get(f"/api/lookup/{REG1}").json()
    assert "full_name" not in body["student"]
    assert set(body["allotments"][0]) <= {"exam", "subject_code", "date", "time", "hall", "seat", "location"}
