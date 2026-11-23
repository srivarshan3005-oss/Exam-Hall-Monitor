"""Role matrix: every protected endpoint x {anonymous, student, staff, admin}."""
import pytest
from conftest import REG1, make_student, make_exam

EXAM = {"title": "Authz Exam", "subject_code": "AZ101", "exam_date": "2027-03-01",
        "start_time": "09:00", "end_time": "11:00"}

# (method, path, json, {role: expected status})  -- expected for a *well-formed* request
CASES = [
    ("GET",  "/api/dashboard",        None, dict(anon=401, student=403, staff=200, admin=200)),
    ("GET",  "/api/students",         None, dict(anon=401, student=403, staff=200, admin=200)),
    ("POST", "/api/students",         {"register_number": "990025106010", "full_name": "Authz One", "department": "CSE", "year": 1},
                                           dict(anon=401, student=403, staff=403, admin=201)),
    ("PATCH", f"/api/students/{REG1}", {"year": 3}, dict(anon=401, student=403, staff=403, admin=200)),
    ("GET",  "/api/admin/exams",      None, dict(anon=401, student=403, staff=200, admin=200)),
    ("POST", "/api/exams",            EXAM, dict(anon=401, student=403, staff=201, admin=201)),
    ("PATCH", "/api/exams/{exam}",    {"venue": "Block Z"}, dict(anon=401, student=403, staff=200, admin=200)),
    ("POST", "/api/allotments",       {"register_number": REG1, "exam_id": "{exam}", "hall": "AZ HALL", "seat": "{seat}"},
                                           dict(anon=401, student=403, staff=201, admin=201)),
    ("POST", "/api/results",          {"register_number": REG1, "exam_id": "{exam}", "marks": 50, "max_marks": 100},
                                           dict(anon=401, student=403, staff=403, admin=201)),
    ("GET",  "/api/admin/audit",      None, dict(anon=401, student=403, staff=403, admin=200)),
    ("GET",  "/api/admin/users",      None, dict(anon=401, student=403, staff=403, admin=200)),
    ("POST", "/api/admin/users",      {"username": "newstaff", "password": "Sturdy-Pass-2026-xyz", "role": "staff"},
                                           dict(anon=401, student=403, staff=403, admin=201)),
    ("PATCH", "/api/admin/users/stud1", {"unlock": True}, dict(anon=401, student=403, staff=403, admin=200)),
]


@pytest.mark.parametrize("method,path,payload,expected", CASES, ids=[f"{c[0]} {c[1]}" for c in CASES])
@pytest.mark.parametrize("role", ["anon", "student", "staff", "admin"])
def test_role_matrix(client, db, admin, staff, student_auth, role, method, path, payload, expected):
    exam = make_exam(db, code="AZ0")
    heads = {"anon": {}, "student": student_auth, "staff": staff, "admin": admin}[role]
    seat = {"anon": "1", "student": "2", "staff": "3", "admin": "4"}[role]
    path = path.replace("{exam}", str(exam.id))
    if isinstance(payload, dict):
        payload = {k: (exam.id if v == "{exam}" else seat if v == "{seat}" else v) for k, v in payload.items()}
        if role == "staff" and "register_number" in payload and path == "/api/allotments":
            payload["register_number"] = REG1
    r = client.request(method, path, headers=heads, json=payload)
    assert r.status_code == expected[role], f"{role} {method} {path}: {r.status_code} {r.text}"


def test_forbidden_request_does_not_modify_data(client, db, staff):
    from sqlalchemy import select, func
    from app import models
    before = db.scalar(select(func.count()).select_from(models.Student))
    r = client.post("/api/students", headers=staff, json={"register_number": "990025106011", "full_name": "Nope Nope",
                                                          "department": "CSE", "year": 1})
    assert r.status_code == 403
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(models.Student)) == before
