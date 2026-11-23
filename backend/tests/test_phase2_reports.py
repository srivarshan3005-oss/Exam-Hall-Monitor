"""Phase 2: seating charts, allocation lists, unallocated and occupancy reports, exports."""
import io
from app import models, doc_models
from conftest import REG1, REG2, REG3, make_student, make_exam


def setup(db, with_third=True):
    make_student(db, REG2, name="Bravo")
    existing = db.query(models.Student).filter_by(register_number=REG1).first()
    if existing:  # the student_auth fixture may already have created REG1
        existing.full_name = "Alpha"; db.commit()
    else:
        make_student(db, REG1, name="Alpha")
    if with_third:
        make_student(db, REG3, name="Charlie", dept="CSE")
    e = make_exam(db)
    h = doc_models.Hall(code="HALL-R", capacity=3, verified=True); db.add(h); db.flush()
    db.add_all([models.HallSeat(hall_id=h.id, seat_label=str(i), active=(i != 3)) for i in range(1, 4)])
    for reg, seat in ((REG2, "2"), (REG1, "1")):
        s = db.query(models.Student).filter_by(register_number=reg).one()
        db.add(models.Allotment(student_id=s.id, exam_id=e.id, hall="HALL-R", seat=seat))
    db.commit()
    return e


def test_allocation_list_orders(client, db, staff):
    e = setup(db)
    reg = client.get(f"/api/admin/reports/exams/{e.id}/allocations?order=register", headers=staff).json()
    assert [r["register_number"] for r in reg] == [REG1, REG2]
    name = client.get(f"/api/admin/reports/exams/{e.id}/allocations?order=name", headers=staff).json()
    assert [r["student_name"] for r in name] == ["Alpha", "Bravo"]
    assert client.get(f"/api/admin/reports/exams/{e.id}/allocations?hall=nope", headers=staff).json() == []


def test_unallocated_report(client, db, staff):
    e = setup(db)
    rows = client.get(f"/api/admin/reports/exams/{e.id}/unallocated", headers=staff).json()
    assert [r["register_number"] for r in rows] == [REG3]


def test_hall_occupancy_and_summary(client, db, staff):
    e = setup(db)
    h = client.get(f"/api/admin/reports/exams/{e.id}/halls", headers=staff).json()[0]
    assert h["capacity"] == 2 and h["allocated"] == 2 and h["free"] == 0 and h["occupancy_percent"] == 100.0
    s = client.get(f"/api/admin/reports/exams/{e.id}/summary", headers=staff).json()
    assert s["eligible_students"] == 3 and s["allotted"] == 2 and s["unallocated"] == 1


def test_seating_chart_marks_unavailable_seats(client, db, staff):
    e = setup(db)
    chart = client.get(f"/api/admin/reports/exams/{e.id}/seating?hall=hall-r", headers=staff).json()[0]
    states = {s["seat"]: s["state"] for s in chart["seats"]}
    assert states == {"1": "allocated", "2": "allocated", "3": "unavailable"}


def test_exports_have_correct_types(client, db, staff):
    e = setup(db)
    base = f"/api/admin/reports/exams/{e.id}/allocations"
    csv = client.get(base + "?format=csv", headers=staff)
    assert csv.headers["content-type"].startswith("text/csv") and REG1 in csv.text and "attachment" in csv.headers["content-disposition"]
    x = client.get(base + "?format=xlsx", headers=staff)
    pdf = client.get(f"/api/admin/reports/exams/{e.id}/seating?format=pdf", headers=staff)
    for r, magic in ((x, b"PK"), (pdf, b"%PDF")):
        assert r.status_code in (200, 501)
        if r.status_code == 200:
            assert r.content[:len(magic)] == magic
    assert client.get(base + "?format=exe", headers=staff).status_code == 422


def test_csv_neutralises_formula_injection(client, db, staff):
    make_student(db, REG1, name="=HYPERLINK(\"http://x\")")
    e = make_exam(db)
    s = db.query(models.Student).one()
    db.add(models.Allotment(student_id=s.id, exam_id=e.id, hall="H", seat="1")); db.commit()
    text = client.get(f"/api/admin/reports/exams/{e.id}/allocations?format=csv", headers=staff).text
    assert "'=HYPERLINK" in text


def test_student_wise_lookup_is_staff_only(client, db, staff, student_auth):
    e = setup(db)
    r = client.get("/api/admin/reports/students/seats?q=alpha", headers=staff).json()
    assert r[0]["register_number"] == REG1 and r[0]["allotments"][0]["seat"] == "1"
    assert client.get("/api/admin/reports/students/seats?q=alpha", headers=student_auth).status_code == 403
    assert client.get("/api/admin/reports/students/seats?q=alpha").status_code == 401


def test_reports_require_staff_role(client, db, student_auth):
    e = setup(db)
    for path in ("allocations", "unallocated", "halls", "seating", "summary"):
        assert client.get(f"/api/admin/reports/exams/{e.id}/{path}", headers=student_auth).status_code == 403
        assert client.get(f"/api/admin/reports/exams/{e.id}/{path}").status_code == 401


def test_exam_overview_report(client, db, staff):
    setup(db)
    rows = client.get("/api/admin/reports/exams", headers=staff).json()
    assert rows[0]["allotted"] == 2 and rows[0]["unallocated"] == 1
