import pytest
from sqlalchemy import select
from app import models
from app.config import settings
from conftest import REG1, REG2, make_student, make_exam, make_user, login


def test_public_lookup_returns_minimal_fields_no_name(client, db):
    make_student(db, REG1)
    r = client.get(f"/api/students/{REG1}")
    assert r.status_code == 200
    assert r.json() == {"register_number": REG1, "department": "Electronics and Communication", "year": 2}
    assert "Demo Student" not in r.text and "email" not in r.text


def test_name_shown_only_when_enabled(client, db, monkeypatch):
    make_student(db, REG1)
    monkeypatch.setattr(settings, "public_show_names", True)
    assert client.get(f"/api/students/{REG1}").json()["full_name"] == "Demo Student One"


@pytest.mark.parametrize("raw", ["990025106001", " 9900 2510 6001 ", "9900-2510-6001"])
def test_register_number_normalisation(client, db, raw):
    make_student(db, REG1)
    assert client.get("/api/students/" + raw.replace(" ", "%20")).status_code == 200


def test_unknown_register_number_404(client, db):
    assert client.get("/api/students/990025106999").status_code == 404


@pytest.mark.parametrize("raw", ["abc", "12345", "99002510600!", "x" * 40])
def test_invalid_register_number_422(client, raw):
    assert client.get("/api/students/" + raw).status_code == 422


def test_inactive_student_not_publicly_visible(client, db):
    s = make_student(db, REG1)
    s.active = False
    db.commit()
    assert client.get(f"/api/students/{REG1}").status_code == 404


def test_enumeration_blocked_after_miss_budget(client, db, monkeypatch):
    monkeypatch.setattr(settings, "public_lookup_miss_limit", 3)
    make_student(db, REG1)
    codes = [client.get(f"/api/students/9900251060{i:02d}").status_code for i in range(10, 16)]
    assert codes[:3] == [404, 404, 404]
    assert set(codes[3:]) == {429}
    # while blocked even a valid number is refused (no oracle for an attacker)
    blocked = client.get(f"/api/students/{REG1}")
    assert blocked.status_code == 429 and "Retry-After" in blocked.headers


def test_per_minute_limit_on_public_lookup(client, db, monkeypatch):
    monkeypatch.setattr(settings, "public_lookup_per_minute", 3)
    make_student(db, REG1)
    assert [client.get(f"/api/students/{REG1}").status_code for _ in range(5)] == [200, 200, 200, 429, 429]


def test_combined_lookup_shape(client, db):
    s = make_student(db, REG1)
    e = make_exam(db)
    db.add(models.Allotment(student_id=s.id, exam_id=e.id, hall="DEMO HALL 01", seat="7"))
    db.commit()
    d = client.get(f"/api/lookup/{REG1}").json()
    assert d["student"]["register_number"] == REG1 and "full_name" not in d["student"]
    assert d["allotments"][0]["hall"] == "DEMO HALL 01" and d["allotments"][0]["seat"] == "7"
    assert d["results_available_without_signin"] is False
    assert client.get("/api/lookup/990025106777").status_code == 404


def test_admin_creates_student_and_duplicates_rejected(client, db, admin):
    body = {"register_number": REG2, "full_name": "  Demo   Two ", "department": "CSE", "year": 3,
            "email": "Two@Example.com"}
    r = client.post("/api/students", headers=admin, json=body)
    assert r.status_code == 201 and r.json()["register_number"] == REG2
    s = db.scalar(select(models.Student).where(models.Student.register_number == REG2))
    assert s.full_name == "Demo Two" and s.email == "two@example.com"
    assert client.post("/api/students", headers=admin, json=body).status_code == 409


@pytest.mark.parametrize("patch", [{"year": 0}, {"year": 7}, {"register_number": "bad"}, {"email": "nope"},
                                   {"full_name": "x"}])
def test_student_validation(client, admin, patch):
    body = {"register_number": REG2, "full_name": "Demo Two", "department": "CSE", "year": 3, **patch}
    assert client.post("/api/students", headers=admin, json=body).status_code == 422


def test_list_students_requires_staff_and_escapes_wildcards(client, db, staff):
    make_student(db, REG1)
    make_student(db, REG2, name="Other Person")
    assert client.get("/api/students").status_code == 401
    assert len(client.get("/api/students", headers=staff).json()) == 2
    assert len(client.get("/api/students?q=Other", headers=staff).json()) == 1
    assert client.get("/api/students?q=%25", headers=staff).json() == []  # '%' is literal, not a wildcard
    assert len(client.get("/api/students?limit=1&offset=1", headers=staff).json()) == 1
    assert client.get("/api/students?limit=999", headers=staff).status_code == 422


def test_patch_student_and_audit_has_field_names_only(client, db, admin):
    make_student(db, REG1)
    r = client.patch(f"/api/students/{REG1}", headers=admin, json={"full_name": "New Secret Name", "year": 4})
    assert r.status_code == 200 and r.json()["updated"] == ["full_name", "year"]
    log = db.scalar(select(models.AuditLog).where(models.AuditLog.action == "student.updated"))
    assert "New Secret Name" not in (log.details or "") and "full_name" in log.details
    assert client.patch("/api/students/990025106555", headers=admin, json={"year": 2}).status_code == 404
