from sqlalchemy import select
from app import models
from conftest import STRONG, REG1, make_student, make_user, login


def new_user(role="staff", name="newuser", pw="Sturdy-Pass-2026-xyz", **kw):
    return {"username": name, "password": pw, "role": role, **kw}


def test_create_user_and_login(client, db, admin):
    r = client.post("/api/admin/users", headers=admin, json=new_user(name="NewUser"))
    assert r.status_code == 201 and r.json()["username"] == "newuser" and "password" not in r.text
    assert login(client, "newuser", "Sturdy-Pass-2026-xyz")
    assert client.post("/api/admin/users", headers=admin, json=new_user(name="newuser")).status_code == 409


def test_weak_password_and_bad_usernames_rejected(client, admin):
    assert client.post("/api/admin/users", headers=admin, json=new_user(pw="short1")).status_code == 422
    assert client.post("/api/admin/users", headers=admin, json=new_user(name="ab")).status_code == 422
    assert client.post("/api/admin/users", headers=admin, json=new_user(name="bad name")).status_code == 422
    assert client.post("/api/admin/users", headers=admin, json=new_user(role="root")).status_code == 422
    assert client.post("/api/admin/users", headers=admin, json=new_user(name="newuser", pw="newuser-password-9")).status_code == 422


def test_student_accounts_need_a_linked_student(client, db, admin):
    assert client.post("/api/admin/users", headers=admin, json=new_user("student")).status_code == 422
    assert client.post("/api/admin/users", headers=admin,
                       json=new_user("student", student_register_number=REG1)).status_code == 404
    make_student(db, REG1)
    r = client.post("/api/admin/users", headers=admin, json=new_user("student", student_register_number=REG1))
    assert r.status_code == 201
    assert client.post("/api/admin/users", headers=admin,
                       json=new_user("staff", name="other", student_register_number=REG1)).status_code == 422


def test_admin_cannot_lock_themselves_out(client, db, admin):
    assert client.patch("/api/admin/users/admin1", headers=admin, json={"active": False}).status_code == 409
    assert client.patch("/api/admin/users/admin1", headers=admin, json={"role": "staff"}).status_code == 409


def test_last_active_admin_protected(client, db, admin):
    other = make_user(db, "admin2", "admin")
    h2 = login(client, "admin2")
    assert client.patch("/api/admin/users/admin1", headers=h2, json={"active": False}).status_code == 200
    assert client.patch("/api/admin/users/admin2", headers=h2, json={"active": False}).status_code == 409


def test_deactivated_user_loses_access_immediately(client, db, admin, staff):
    assert client.get("/api/dashboard", headers=staff).status_code == 200
    assert client.patch("/api/admin/users/staff1", headers=admin, json={"active": False}).status_code == 200
    assert client.get("/api/dashboard", headers=staff).status_code == 401


def test_unlock_and_password_reset(client, db, admin):
    make_user(db, "locked1", "staff")
    for _ in range(5):
        client.post("/api/auth/login", json={"username": "locked1", "password": "wrong-password-1"})
    assert client.post("/api/auth/login", json={"username": "locked1", "password": STRONG}).status_code == 429
    assert client.patch("/api/admin/users/locked1", headers=admin, json={"unlock": True}).status_code == 200
    from app.ratelimit import limiter
    limiter.reset()
    assert client.post("/api/auth/login", json={"username": "locked1", "password": STRONG}).status_code == 200
    assert client.patch("/api/admin/users/locked1", headers=admin, json={"new_password": "weak"}).status_code == 422
    assert client.patch("/api/admin/users/locked1", headers=admin,
                        json={"new_password": "Reset-Sturdy-Pass-31"}).status_code == 200
    assert client.post("/api/auth/login", json={"username": "locked1", "password": "Reset-Sturdy-Pass-31"}).status_code == 200


def test_dashboard_counts(client, db, admin):
    from conftest import make_exam
    make_student(db, REG1)
    make_exam(db)
    d = client.get("/api/dashboard", headers=admin).json()
    assert d == {"students": 1, "exams": 1, "allotments": 0, "published_results": 0}


def test_audit_endpoint_filters_and_never_leaks_secrets(client, db, admin):
    client.post("/api/admin/users", headers=admin, json=new_user(name="auditme"))
    client.patch("/api/admin/users/auditme", headers=admin, json={"new_password": "Reset-Sturdy-Pass-31"})
    rows = client.get("/api/admin/audit?action=user.", headers=admin).json()
    assert {r["action"] for r in rows} == {"user.created", "user.updated"}
    assert all(r["actor"] == "admin1" and r["role"] == "admin" for r in rows)
    blob = client.get("/api/admin/audit", headers=admin).text
    assert "Sturdy-Pass" not in blob and "pbkdf2" not in blob
    assert len(client.get("/api/admin/audit?limit=1", headers=admin).json()) == 1
    assert client.get("/api/admin/audit?limit=0", headers=admin).status_code == 422
    assert all(r["actor"] == "admin1" for r in client.get("/api/admin/audit?actor=admin1", headers=admin).json())


def test_every_admin_write_is_audited(client, db, admin):
    from conftest import make_exam
    make_student(db, REG1)
    e = make_exam(db, "draft")
    client.post("/api/students", headers=admin, json={"register_number": "990025106020", "full_name": "Audit One",
                                                      "department": "CSE", "year": 1})
    client.patch(f"/api/students/{REG1}", headers=admin, json={"year": 3})
    client.post("/api/exams", headers=admin, json={"title": "Audit Exam", "subject_code": "AU1", "exam_date": "2027-01-01",
                                                   "start_time": "09:00", "end_time": "10:00"})
    client.patch(f"/api/exams/{e.id}", headers=admin, json={"venue": "X Block"})
    aid = client.post("/api/allotments", headers=admin, json={"register_number": REG1, "exam_id": e.id, "hall": "H", "seat": "1"}).json()["id"]
    client.delete(f"/api/allotments/{aid}", headers=admin)
    rid = client.post("/api/results", headers=admin, json={"register_number": REG1, "exam_id": e.id, "marks": 1, "max_marks": 2}).json()["id"]
    client.post(f"/api/results/{rid}/publish", headers=admin)
    client.post(f"/api/results/{rid}/unpublish", headers=admin)
    got = {a.action for a in db.scalars(select(models.AuditLog)).all()}
    assert {"auth.login", "student.created", "student.updated", "exam.created", "exam.updated", "allotment.created",
            "allotment.deleted", "result.created", "result.published", "result.unpublished"} <= got


def test_failed_write_leaves_no_audit_row(client, db, admin):
    client.post("/api/exams", headers=admin, json={"title": "x"})  # 422
    assert db.scalar(select(models.AuditLog).where(models.AuditLog.action == "exam.created")) is None
