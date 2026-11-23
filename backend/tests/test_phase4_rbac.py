"""Phase 4: role matrix enforced by the backend, department scope, account management, dashboard."""
import json
import pytest
from sqlalchemy import select
from app import models
from conftest import make_user, make_student, make_exam, login, STRONG, REG1, REG2, REG3

ROLES = ["super_admin", "admin", "staff", "invigilator", "student"]


@pytest.fixture()
def auth(db, client):
    """One signed-in user per role."""
    s = make_student(db, REG1)
    out = {}
    for r in ROLES:
        make_user(db, f"u-{r}".replace("_", "-"), r, student=s if r == "student" else None)
        out[r] = login(client, f"u-{r}".replace("_", "-"))
    return out


def status_of(client, method, url, h, **kw):
    return getattr(client, method)(url, headers=h, **kw).status_code


@pytest.mark.parametrize("role,expected", [("super_admin", 200), ("admin", 200), ("staff", 403), ("invigilator", 403), ("student", 403)])
def test_account_list_is_administrator_only(client, auth, role, expected):
    assert status_of(client, "get", "/api/admin/users", auth[role]) == expected


@pytest.mark.parametrize("role,expected", [("super_admin", 200), ("admin", 200), ("staff", 200), ("invigilator", 200), ("student", 403)])
def test_exam_list_roles(client, auth, role, expected):
    assert status_of(client, "get", "/api/admin/exams", auth[role]) == expected


@pytest.mark.parametrize("role,expected", [("super_admin", 200), ("admin", 200), ("staff", 403), ("invigilator", 403), ("student", 403)])
def test_security_dashboard_roles(client, auth, role, expected):
    for url in ("/api/admin/security/summary", "/api/admin/security/events", "/api/admin/audit"):
        assert status_of(client, "get", url, auth[role]) == expected


def test_invigilator_is_read_only(client, db, auth):
    e = make_exam(db)
    assert status_of(client, "get", f"/api/allotments/exam/{e.id}", auth["invigilator"]) == 200
    assert status_of(client, "post", "/api/exams", auth["invigilator"],
                     json={"title": "X", "subject_code": "X1", "exam_date": "2027-02-01", "start_time": "09:00", "end_time": "12:00"}) == 403
    assert status_of(client, "post", "/api/allotments", auth["invigilator"],
                     json={"register_number": REG1, "exam_id": e.id, "hall": "H1", "seat": "1"}) == 403
    assert status_of(client, "get", "/api/documents", auth["invigilator"]) in (403, 404)
    assert status_of(client, "get", "/api/students", auth["invigilator"]) == 403


def test_super_admin_passes_every_admin_check(client, db, auth):
    e = make_exam(db, status="draft")
    assert status_of(client, "delete", f"/api/exams/{e.id}", auth["super_admin"]) == 200
    assert status_of(client, "get", "/api/admin/documents", auth["super_admin"]) == 200


def test_student_cannot_touch_admin_apis_or_other_results(client, db, auth):
    assert status_of(client, "get", "/api/students", auth["student"]) == 403
    assert status_of(client, "get", "/api/admin/halls", auth["student"]) == 403
    make_student(db, REG2, "Other Student")
    assert status_of(client, "get", f"/api/results/{REG2}", auth["student"]) == 403     # IDOR


def test_unauthenticated_requests_are_refused(client):
    for url in ("/api/students", "/api/admin/users", "/api/admin/security/summary", "/api/admin/reports/exams", "/api/dashboard"):
        assert client.get(url).status_code == 401


def test_permission_denied_is_explained_and_logged(client, db, auth):
    r = client.get("/api/admin/users", headers=auth["staff"])
    assert r.status_code == 403 and "Examination administrator" in r.json()["detail"]
    ev = db.scalars(select(models.SecurityEvent).where(models.SecurityEvent.event_type == "authz.denied")).all()
    assert ev and ev[0].username == "u-staff" and ev[0].severity == "warning"


# ------------------------------------------------------------------ department scope / IDOR
def test_department_staff_only_see_their_department(client, db):
    make_student(db, REG1, "Ece Student", "Electronics and Communication")
    make_student(db, REG3, "Cse Student", "Computer Science")
    u = make_user(db, "deptstaff", "staff")
    u.department = "Computer Science"
    db.commit()
    h = login(client, "deptstaff")
    listed = client.get("/api/students", headers=h).json()
    assert [s["register_number"] for s in listed] == [REG3]
    e = make_exam(db)
    ece = db.scalar(select(models.Student).where(models.Student.register_number == REG1))
    db.add(models.Allotment(student_id=ece.id, exam_id=e.id, hall="H1", seat="1"))
    db.commit()
    assert client.get(f"/api/allotments/exam/{e.id}", headers=h).json() == []
    aid = db.scalar(select(models.Allotment)).id
    assert client.delete(f"/api/allotments/{aid}", headers=h).status_code == 403
    assert client.get(f"/api/admin/reports/exams/{e.id}/seating", headers=h).status_code == 403
    assert client.get(f"/api/admin/reports/students/seats?q={REG1[-4:]}", headers=h).json() == []


def test_staff_without_department_keep_institution_wide_access(client, db, staff):
    make_student(db, REG1)
    make_student(db, REG3, "Cse Student", "Computer Science")
    assert len(client.get("/api/students", headers=staff).json()) == 2


# ------------------------------------------------------------------ role assignment rules
def test_legacy_admins_keep_phase1_powers_until_a_super_admin_exists(client, db, admin):
    r = client.post("/api/admin/users", headers=admin, json={"username": "boss2", "password": STRONG, "role": "admin"})
    assert r.status_code == 201
    assert client.post("/api/admin/users", headers=admin, json={"username": "root2", "password": STRONG, "role": "super_admin"}).status_code == 403


def test_with_a_super_admin_only_super_admin_manages_administrators(client, db, auth):
    body = {"username": "newadm", "password": STRONG, "role": "admin"}
    assert client.post("/api/admin/users", headers=auth["admin"], json=body).status_code == 403
    assert client.post("/api/admin/users", headers=auth["super_admin"], json=body).status_code == 201
    assert client.patch("/api/admin/users/u-staff", headers=auth["admin"], json={"role": "admin"}).status_code == 403
    assert client.patch("/api/admin/users/u-super-admin", headers=auth["admin"], json={"active": False}).status_code == 403
    assert client.post("/api/admin/users/u-super-admin/suspend", headers=auth["admin"], json={}).status_code == 403
    # an exam administrator can still manage ordinary roles
    assert client.patch("/api/admin/users/u-staff", headers=auth["admin"], json={"role": "invigilator"}).status_code == 200
    ev = db.scalars(select(models.SecurityEvent).where(models.SecurityEvent.event_type == "authz.denied")).all()
    assert len(ev) >= 3


def test_last_super_admin_cannot_be_removed(client, db, auth):
    assert client.patch("/api/admin/users/u-super-admin", headers=auth["super_admin"], json={"role": "staff"}).status_code == 409   # self
    make_user(db, "root2", "super_admin")
    h2 = login(client, "root2")
    assert client.patch("/api/admin/users/u-super-admin", headers=h2, json={"role": "admin"}).status_code == 200
    assert client.patch("/api/admin/users/root2", headers=h2, json={"role": "admin"}).status_code == 409


def test_role_change_signs_the_user_out_and_is_audited(client, db, auth):
    assert client.patch("/api/admin/users/u-staff", headers=auth["super_admin"], json={"role": "invigilator"}).status_code == 200
    assert client.get("/api/auth/me", headers=auth["staff"]).status_code == 401
    ev = db.scalars(select(models.SecurityEvent).where(models.SecurityEvent.event_type == "account.role_changed")).all()
    assert ev and "staff -> invigilator" in ev[0].detail


# ------------------------------------------------------------------ account management
def test_suspend_restore_cycle(client, db, auth):
    assert client.post("/api/admin/users/u-staff/suspend", headers=auth["admin"], json={"reason": "left the department"}).status_code == 200
    assert client.get("/api/auth/me", headers=auth["staff"]).status_code == 401
    assert client.post("/api/auth/login", json={"username": "u-staff", "password": STRONG}).status_code == 401
    u = client.get("/api/admin/users?status=suspended", headers=auth["admin"]).json()
    assert [x["username"] for x in u] == ["u-staff"] and u[0]["status_reason"] == "left the department"
    assert client.post("/api/admin/users/u-staff/restore", headers=auth["admin"], json={}).status_code == 200
    assert login(client, "u-staff")
    assert client.post("/api/admin/users/u-staff/restore", headers=auth["admin"], json={}).status_code == 409   # already active


def test_cannot_suspend_self_or_last_admin(client, db, admin):
    assert client.post("/api/admin/users/admin1/suspend", headers=admin, json={}).status_code == 409


def test_pending_registration_can_be_approved_by_admin(client, db, admin):
    s = make_student(db, REG1)
    u = make_user(db, "pending1", "student", student=s, active=False)
    u.status = "pending"
    db.commit()
    assert client.post("/api/admin/users/pending1/restore", headers=admin, json={}).status_code == 200
    assert login(client, "pending1")
    assert any(e.event_type == "account.approved" for e in db.scalars(select(models.SecurityEvent)).all())


def test_user_filters_and_activity_history(client, db, auth):
    r = client.get("/api/admin/users?role=staff", headers=auth["admin"])
    assert [u["username"] for u in r.json()] == ["u-staff"] and r.headers["X-Total-Count"] == "1"
    assert len(client.get("/api/admin/users?q=u-inv", headers=auth["admin"]).json()) == 1
    assert client.get("/api/admin/users?role=root", headers=auth["admin"]).status_code == 422
    act = client.get("/api/admin/users/u-staff/activity", headers=auth["admin"]).json()
    assert any(e["event_type"] == "auth.login" for e in act["security_events"])
    assert "password_hash" not in json.dumps(act)


def test_force_logout_and_unknown_user(client, db, auth):
    assert client.post("/api/admin/users/u-staff/force-logout", headers=auth["admin"]).status_code == 200
    assert client.get("/api/auth/me", headers=auth["staff"]).status_code == 401
    assert client.post("/api/admin/users/ghost-user/force-logout", headers=auth["admin"]).status_code == 404


def test_dashboard_summary_and_event_filters(client, db, auth):
    client.post("/api/auth/login", json={"username": "u-staff", "password": "wrong-wrong-12"})
    client.get("/api/admin/users", headers=auth["staff"])
    s = client.get("/api/admin/security/summary", headers=auth["admin"]).json()
    assert s["successful_logins"] >= 5 and s["failed_logins"] == 1 and s["permission_denials"] == 1
    assert s["accounts_by_role"]["staff"] == 1 and s["active_sessions"] >= 5
    ev = client.get("/api/admin/security/events?type=auth.login_failed&username=u-staff", headers=auth["admin"])
    assert len(ev.json()) == 1 and ev.headers["X-Total-Count"] == "1"
    assert client.get("/api/admin/security/events?severity=warning&q=GET", headers=auth["admin"]).json()
    assert client.get("/api/admin/security/events?since=2999-01-01", headers=auth["admin"]).json() == []
    assert client.get("/api/admin/security/events?severity=bogus", headers=auth["admin"]).status_code == 422
    assert client.get("/api/admin/security/sessions", headers=auth["admin"]).json()


def test_audit_search_and_secret_redaction(client, db, auth):
    from app import audit
    audit.record(db, "x", "demo.action", "t", {"password": "hunter2", "api_token": "abc", "ok": 1})
    db.commit()
    rows = client.get("/api/admin/audit?q=demo", headers=auth["admin"]).json()
    assert rows and "hunter2" not in rows[0]["details"] and "abc" not in rows[0]["details"] and '"ok": 1' in rows[0]["details"]


def test_role_catalogue(client, auth):
    r = client.get("/api/admin/roles", headers=auth["admin"]).json()["roles"]
    assert [x["role"] for x in r] == ROLES
    assert {x["role"]: x["assignable"] for x in r}["super_admin"] is False
