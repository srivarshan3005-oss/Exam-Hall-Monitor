"""Phase 7: the Android app's view of the API.

Every endpoint the app calls (android/app/src/main/java/.../data/Api.kt) is exercised against the real application and the
JSON keys the app's validating mappers require (core/Dto.kt `Mappers`) are asserted. If a backend change would break the
app, one of these tests fails first. Also verifies the permission boundaries the app's role-based UI relies on.
"""
import re
from pathlib import Path

from sqlalchemy import select

from app import models, notifications as nt
from conftest import STRONG, REG1, REG2, login, make_exam, make_student, make_user

ANDROID = Path(__file__).resolve().parents[2] / "android/app/src/main/java/com/example/exammonitor"


def _allot(db, student, exam, hall="H1", seat="7"):
    db.add(models.Allotment(student_id=student.id, exam_id=exam.id, hall=hall, seat=seat))
    db.commit()


def _student_world(db, client):
    s1, s2 = make_student(db, REG1), make_student(db, REG2, "Second Student")
    make_user(db, "stud1", "student", student=s1)
    make_user(db, "stud2", "student", student=s2)
    e = make_exam(db)
    _allot(db, s1, e, "H1", "7")
    _allot(db, s2, e, "H1", "8")
    return s1, s2, e, login(client, "stud1"), login(client, "stud2")


def test_android_api_paths_exist_in_backend(client):
    """Every path template in Api.kt must be a real route (method + path)."""
    src = (ANDROID / "data/Api.kt").read_text()
    calls = re.findall(r'@(GET|POST|PUT)\("([^"]+)"\)', src)
    assert len(calls) >= 25
    served = {(m.upper(), re.sub(r"\{[^}]+\}", "{X}", path)) for path, ops in client.app.openapi()["paths"].items() for m in ops}
    for method, path in calls:
        tmpl = "/" + re.sub(r"\{[^}]+\}", "{X}", path)
        assert (method, tmpl) in served, f"{method} {tmpl} is not served by the backend"


def test_login_profile_and_logout_contract(db, client):
    s1 = make_student(db, REG1)
    make_user(db, "stud1", "student", student=s1)
    r = client.post("/api/auth/login", json={"username": "stud1", "password": STRONG})
    body = r.json()
    assert r.status_code == 200 and {"access_token", "role", "username", "role_label", "pw_change_required", "expires_in"} <= set(body)
    h = {"Authorization": "Bearer " + body["access_token"]}
    prof = client.get("/api/auth/profile", headers=h).json()
    assert prof["role"] == "student" and prof["register_number"] == REG1 and prof["pw_change_required"] is False
    assert client.post("/api/auth/logout", headers=h).status_code == 200
    r = client.get("/api/auth/profile", headers=h)          # the app maps 401 -> "session ended"
    assert r.status_code == 401 and isinstance(r.json()["detail"], str)


def test_bad_login_is_401_with_text_detail(db, client):
    make_user(db, "stud1", "student")
    r = client.post("/api/auth/login", json={"username": "stud1", "password": "wrong-password-1"})
    assert r.status_code == 401 and isinstance(r.json()["detail"], str)


def test_forced_password_change_blocks_everything_but_profile_and_change(db, client):
    u = make_user(db, "stud1", "student")
    u.must_change_password = True
    db.commit()
    h = login(client, "stud1")
    assert client.get("/api/auth/profile", headers=h).json()["pw_change_required"] is True
    r = client.get("/api/notifications/unread-count", headers=h)
    assert r.status_code == 403 and "Password change required" in r.json()["detail"]     # text the app's ErrorMapper keys on
    r = client.post("/api/auth/change-password", headers=h, json={"current_password": STRONG, "new_password": "Another-Strong-2027-pw"})
    assert r.status_code == 200 and r.json()["access_token"]
    new = {"Authorization": "Bearer " + r.json()["access_token"]}
    assert client.get("/api/auth/profile", headers=new).json()["pw_change_required"] is False
    assert client.get("/api/auth/profile", headers=h).status_code == 401      # old token revoked; app swaps tokens


def test_password_reset_endpoints_are_generic(db, client):
    make_user(db, "stud1", "student")
    r = client.post("/api/auth/forgot-password", json={"identifier": "stud1"})
    r2 = client.post("/api/auth/forgot-password", json={"identifier": "nobody-here"})
    assert r.status_code == r2.status_code == 202 and r.json() == r2.json()
    bad = client.post("/api/auth/reset-password", json={"token": "x" * 30, "new_password": "Another-Strong-2027-pw"})
    assert bad.status_code == 400 and isinstance(bad.json()["detail"], str)


def test_student_endpoints_shape_and_isolation(db, client):
    s1, s2, e, h1, h2 = _student_world(db, client)
    lk = client.get(f"/api/lookup/{REG1}", headers=h1).json()
    assert {"register_number", "department", "year"} <= set(lk["student"])
    a = lk["allotments"][0]
    assert {"exam", "subject_code", "date", "time", "hall", "seat"} <= set(a) and a["seat"] == "7"
    assert all(x["seat"] != "8" for x in lk["allotments"])
    # results: own only (the app never sends another number; the server also refuses it)
    assert client.get(f"/api/results/{REG1}", headers=h1).status_code == 200
    r = client.get(f"/api/results/{REG2}", headers=h1)
    assert r.status_code == 403 and isinstance(r.json()["detail"], str)
    ex = client.get("/api/exams", headers=h1).json()
    assert {"id", "title", "subject_code", "exam_date", "start_time", "end_time", "venue", "status"} <= set(ex[0])
    ann = client.get("/api/announcements", headers=h1)
    assert ann.status_code == 200 and isinstance(ann.json(), list)


def test_student_cannot_use_staff_endpoints_the_app_hides(db, client):
    s1, s2, e, h1, h2 = _student_world(db, client)
    for method, path in (("get", "/api/dashboard"), ("get", "/api/admin/exams"), ("get", f"/api/admin/reports/exams/{e.id}/summary"),
                         ("get", f"/api/admin/reports/exams/{e.id}/halls"), ("get", f"/api/allotments/exam/{e.id}"),
                         ("get", "/api/admin/reports/students/seats?q=ab"), ("post", f"/api/exams/{e.id}/unpublish")):
        assert getattr(client, method)(path, headers=h1).status_code == 403, path


def test_staff_endpoint_shapes_and_role_matrix(db, client):
    s1, s2, e, h1, h2 = _student_world(db, client)
    make_user(db, "inv1", "invigilator"); make_user(db, "staff1", "staff"); make_user(db, "adm1", "admin")
    inv, staff, adm = login(client, "inv1"), login(client, "staff1"), login(client, "adm1")
    # invigilator: read-only exam/roster/halls, nothing else
    assert client.get("/api/admin/exams", headers=inv).status_code == 200
    assert client.get(f"/api/allotments/exam/{e.id}", headers=inv).status_code == 200
    assert client.get(f"/api/admin/reports/exams/{e.id}/halls", headers=inv).status_code == 200
    for method, path in (("get", "/api/dashboard"), ("get", f"/api/admin/reports/exams/{e.id}/summary"),
                         ("get", "/api/admin/reports/students/seats?q=ab"), ("post", f"/api/exams/{e.id}/unpublish")):
        assert getattr(client, method)(path, headers=inv).status_code == 403, path
    # staff/admin shapes used by the app's mappers
    assert {"students", "exams", "allotments", "published_results"} <= set(client.get("/api/dashboard", headers=staff).json())
    exams = client.get("/api/admin/exams", headers=staff, params={"q": "", "status": "", "limit": 100, "offset": 0}).json()
    assert {"id", "title", "exam_date", "start_time", "status"} <= set(exams[0])
    summ = client.get(f"/api/admin/reports/exams/{e.id}/summary", headers=staff).json()
    assert {"exam_id", "eligible_students", "allotted", "unallocated", "halls_used"} <= set(summ)
    halls = client.get(f"/api/admin/reports/exams/{e.id}/halls", headers=staff).json()
    assert isinstance(halls, list) and {"hall", "verified", "allocated"} <= set(halls[0])
    roster = client.get(f"/api/allotments/exam/{e.id}", headers=staff, params={"q": "", "limit": 200, "offset": 0}).json()
    assert {"register_number", "student_name", "department", "hall", "seat"} <= set(roster[0])
    seats = client.get("/api/admin/reports/students/seats", headers=staff, params={"q": REG1[:6]}).json()
    assert {"register_number", "student_name", "department", "year", "allotments"} <= set(seats[0])
    assert {"exam_id", "exam", "subject_code", "date", "start_time", "status", "hall", "seat"} <= set(seats[0]["allotments"][0])
    # publish / unpublish round trip returns the exam shape the app maps
    r = client.post(f"/api/exams/{e.id}/unpublish", headers=adm)
    assert r.status_code == 200 and r.json()["status"] == "draft"
    r = client.post(f"/api/exams/{e.id}/unpublish", headers=adm)
    assert r.status_code == 409 and isinstance(r.json()["detail"], str)         # shown verbatim by the app


def test_notification_workflow_as_used_by_the_app(db, client):
    s1 = make_student(db, REG1)
    u = make_user(db, "stud1", "student", student=s1)
    other = make_user(db, "stud2", "student", student=make_student(db, REG2, "Other"))
    ctx = {"exam_title": "Maths", "subject_code": "MA1", "exam_date": "2027-02-01", "exam_time": "09:00", "venue": "Main"}
    for i in range(3):
        nt.notify_users(db, [u], "exam_published", ctx, event_key=f"k{i}")
    nt.notify_users(db, [other], "exam_published", ctx, event_key="theirs")
    db.commit()
    h, ho = login(client, "stud1"), login(client, "stud2")
    page = client.get("/api/notifications", headers=h, params={"status": "inbox", "limit": 2, "offset": 0})
    assert page.status_code == 200 and len(page.json()) == 2 and page.headers["X-Total-Count"] == "3"
    nid = page.json()[0]["id"]
    assert {"id", "category", "category_label", "priority", "title", "body", "link", "created_at", "read", "archived"} <= set(page.json()[0])
    assert client.get("/api/notifications/unread-count", headers=h).json() == {"unread": 3}
    r = client.post(f"/api/notifications/{nid}/read", headers=h).json()
    assert r["read"] is True and r["unread"] == 2                                  # app takes the count from this response
    assert client.post(f"/api/notifications/{nid}/unread", headers=h).json()["unread"] == 3
    assert client.post(f"/api/notifications/{nid}/archive", headers=h).json()["unread"] == 2
    assert client.get("/api/notifications", headers=h, params={"status": "unread", "limit": 25, "offset": 0}).json()
    # isolation: another account can neither read nor modify it
    assert client.get(f"/api/notifications/{nid}", headers=ho).status_code == 404
    assert client.post(f"/api/notifications/{nid}/read", headers=ho).status_code == 404
    assert client.post("/api/notifications/read-all", headers=h).json()["unread"] == 0
    prefs = client.get("/api/notifications/preferences", headers=h).json()
    assert {"category", "label", "in_app", "email", "in_app_locked"} <= set(prefs["preferences"][0]) and "has_email" in prefs
    body = {"preferences": [{"category": p["category"], "in_app": p["in_app"], "email": False} for p in prefs["preferences"]]}
    assert client.put("/api/notifications/preferences", headers=h, json=body).status_code == 200
    body["preferences"][-1]["in_app"] = False        # account notices cannot be switched off (the app disables that switch)
    acct = [p for p in prefs["preferences"] if p["in_app_locked"]]
    assert acct and client.put("/api/notifications/preferences", headers=h, json={"preferences": [
        {"category": acct[0]["category"], "in_app": False, "email": True}]}).status_code == 422


def test_dto_field_names_in_android_match_backend_keys(db, client):
    """The app's DTO property names ARE the JSON keys (no annotations). Spot-check that login/profile DTOs are spelled right."""
    src = (ANDROID / "core/Dto.kt").read_text()
    for key in ("access_token", "pw_change_required", "register_number", "student_name", "published_results", "in_app_locked",
                "eligible_students", "halls_used", "occupancy_percent", "category_label", "published_at"):
        assert re.search(rf"\bval {key}\b", src), key
