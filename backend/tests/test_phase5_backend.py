"""Phase 5: additive backend support for the web front end (student profile record, admin results list)."""
import pytest
from conftest import make_user, make_student, make_exam, login, REG1, REG2

ROLES = ["super_admin", "admin", "staff", "invigilator", "student"]


@pytest.fixture()
def auth(db, client):
    s = make_student(db, REG1)
    out = {}
    for r in ROLES:
        n = "u-" + r.replace("_", "-")
        make_user(db, n, r, student=s if r == "student" else None)
        out[r] = login(client, n)
    return out


def test_student_profile_exposes_only_own_record(client, auth):
    p = client.get("/api/auth/profile", headers=auth["student"]).json()
    assert p["register_number"] == REG1 and p["student_name"]
    for r in ("admin", "staff", "invigilator"):
        assert "register_number" not in client.get("/api/auth/profile", headers=auth[r]).json()


def test_student_without_linked_record_has_no_register_number(db, client):
    make_user(db, "loose-student", "student")
    h = login(client, "loose-student")
    assert "register_number" not in client.get("/api/auth/profile", headers=h).json()


@pytest.mark.parametrize("role,expected", [("super_admin", 200), ("admin", 200), ("staff", 403), ("invigilator", 403), ("student", 403)])
def test_admin_results_list_roles(client, auth, role, expected):
    assert client.get("/api/results/admin/list", headers=auth[role]).status_code == expected


def test_admin_results_list_requires_sign_in(client):
    assert client.get("/api/results/admin/list").status_code == 401


def test_admin_results_list_shows_unpublished_and_filters(db, client, auth):
    e = make_exam(db)
    make_student(db, REG2)
    a = client.post("/api/results", headers=auth["admin"], json={"register_number": REG1, "exam_id": e.id, "marks": 50, "max_marks": 100, "grade": "B"})
    b = client.post("/api/results", headers=auth["admin"], json={"register_number": REG2, "exam_id": e.id, "marks": 70, "max_marks": 100, "grade": "A", "published": True})
    assert a.status_code == 201 and b.status_code == 201
    rows = client.get("/api/results/admin/list", headers=auth["admin"])
    assert rows.headers["X-Total-Count"] == "2" and len(rows.json()) == 2
    assert [r["register_number"] for r in client.get("/api/results/admin/list?published=false", headers=auth["admin"]).json()] == [REG1]
    assert len(client.get(f"/api/results/admin/list?q={REG2}", headers=auth["admin"]).json()) == 1
    rid = a.json()["id"]
    assert client.post(f"/api/results/{rid}/publish", headers=auth["admin"]).json()["published"] is True
    assert client.get("/api/results/admin/list?published=false", headers=auth["admin"]).json() == []


def test_public_results_route_still_resolves_register_numbers(client):
    # the new /admin/list path must not shadow the register-number route
    assert client.get(f"/api/results/{REG1}").status_code in (401, 404)
