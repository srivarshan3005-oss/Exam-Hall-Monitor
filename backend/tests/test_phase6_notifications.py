"""Phase 6: in-app notifications, preferences, isolation (IDOR)."""
import pytest
from sqlalchemy import select
from app import models, notifications as nt
from conftest import make_user, make_student, login, STRONG, REG1, REG2


def _note(db, user, key, title_ctx=None, template="exam_published", **kw):
    ctx = {"exam_title": "Maths", "subject_code": "MA1", "exam_date": "2027-02-01", "exam_time": "09:00–12:00", "venue": "Main"}
    r = nt.notify_users(db, [user], template, title_ctx or ctx, event_key=key, **kw)
    db.commit()
    return r


@pytest.fixture()
def two_users(db, client):
    a, b = make_user(db, "alice", "student", student=make_student(db, REG1)), make_user(db, "bob", "student", student=make_student(db, REG2, "Bob"))
    return a, b, login(client, "alice"), login(client, "bob")


def test_requires_authentication(client):
    for path in ("/api/notifications", "/api/notifications/unread-count", "/api/notifications/preferences"):
        assert client.get(path).status_code == 401


def test_create_list_unread_count_and_fields(db, client, two_users):
    a, b, ha, hb = two_users
    for i in range(3):
        _note(db, a, f"k{i}")
    _note(db, b, "bobs")
    r = client.get("/api/notifications", headers=ha)
    assert r.status_code == 200 and len(r.json()) == 3 and r.headers["X-Total-Count"] == "3"
    first = r.json()[0]
    assert {"id", "category", "priority", "title", "body", "link", "created_at", "read", "archived"} <= set(first)
    assert first["read"] is False and first["category"] == "exam" and first["link"] == "#/my-exams" or first["link"] is None
    assert client.get("/api/notifications/unread-count", headers=ha).json() == {"unread": 3}
    assert client.get("/api/notifications/unread-count", headers=hb).json() == {"unread": 1}


def test_mark_read_unread_all_archive_delete(db, client, two_users):
    a, _b, ha, _hb = two_users
    for i in range(4):
        _note(db, a, f"k{i}")
    ids = [n["id"] for n in client.get("/api/notifications", headers=ha).json()]
    r = client.post(f"/api/notifications/{ids[0]}/read", headers=ha)
    assert r.json()["read"] is True and r.json()["unread"] == 3
    assert client.post(f"/api/notifications/{ids[0]}/unread", headers=ha).json()["unread"] == 4
    assert client.post(f"/api/notifications/{ids[1]}/archive", headers=ha).json()["archived"] is True
    assert len(client.get("/api/notifications", headers=ha).json()) == 3                      # archived leave the inbox
    assert len(client.get("/api/notifications?status=archived", headers=ha).json()) == 1
    assert client.post(f"/api/notifications/{ids[1]}/unarchive", headers=ha).json()["archived"] is False
    assert client.delete(f"/api/notifications/{ids[2]}", headers=ha).json()["deleted"] == ids[2]
    assert client.get(f"/api/notifications/{ids[2]}", headers=ha).status_code == 404
    assert client.post("/api/notifications/read-all", headers=ha).json() == {"marked_read": 3, "unread": 0}
    assert len(client.get("/api/notifications?status=unread", headers=ha).json()) == 0
    assert len(client.get("/api/notifications?status=read", headers=ha).json()) == 3


def test_deleted_notification_is_not_recreated_by_a_repeat(db, client, two_users):
    a, _b, ha, _ = two_users
    _note(db, a, "same")
    nid = client.get("/api/notifications", headers=ha).json()[0]["id"]
    client.delete(f"/api/notifications/{nid}", headers=ha)
    r = _note(db, a, "same")
    assert r["duplicates"] == 1 and client.get("/api/notifications", headers=ha).json() == []


def test_duplicate_event_key_creates_one_notification(db, client, two_users):
    a, *_ = two_users
    assert _note(db, a, "dup")["in_app"] == 1
    assert _note(db, a, "dup")["duplicates"] == 1
    assert db.query(models.Notification).filter_by(user_id=a.id).count() == 1


def test_user_isolation_idor(db, client, two_users):
    a, b, ha, hb = two_users
    _note(db, a, "secret")
    nid = db.scalar(select(models.Notification.id).where(models.Notification.user_id == a.id))
    for method, path in (("get", f"/api/notifications/{nid}"), ("post", f"/api/notifications/{nid}/read"),
                         ("post", f"/api/notifications/{nid}/unread"), ("post", f"/api/notifications/{nid}/archive"),
                         ("delete", f"/api/notifications/{nid}")):
        r = getattr(client, method)(path, headers=hb)
        assert r.status_code == 404, (method, path, r.status_code)      # same answer as a missing id
    assert client.get("/api/notifications", headers=hb).json() == []
    assert client.post("/api/notifications/read-all", headers=hb).json()["marked_read"] == 0
    n = db.get(models.Notification, nid); db.refresh(n)
    assert n.read_at is None and n.archived_at is None and n.deleted_at is None


def test_filters_search_pagination(db, client, two_users):
    a, *_rest, = two_users
    ha = _rest[1]
    _note(db, a, "e1")
    _note(db, a, "e2", {"exam_title": "Physics lab", "subject_code": "PH1", "exam_date": "2027-02-02", "exam_time": "1–2", "venue": "Lab", "changes": "date"}, template="exam_updated")
    for i in range(30):
        _note(db, a, f"bulk{i}")
    r = client.get("/api/notifications?limit=10&offset=10", headers=ha)
    assert len(r.json()) == 10 and r.headers["X-Total-Count"] == "32"
    assert len(client.get("/api/notifications?category=timetable", headers=ha).json()) == 1
    assert len(client.get("/api/notifications?priority=high", headers=ha).json()) == 1
    assert len(client.get("/api/notifications?q=physics", headers=ha).json()) == 1
    assert client.get("/api/notifications?q=%25", headers=ha).json() == []                  # wildcard characters are literals
    assert client.get("/api/notifications?category=nope", headers=ha).status_code == 422
    assert client.get("/api/notifications?limit=1000", headers=ha).status_code == 422


def test_preferences_defaults_update_and_effect(db, client, two_users):
    a, _b, ha, _ = two_users
    r = client.get("/api/notifications/preferences", headers=ha).json()["preferences"]
    assert {p["category"] for p in r} == set(nt.CATEGORIES) and all(p["in_app"] and p["email"] for p in r)
    assert [p for p in r if p["category"] == "account"][0]["in_app_locked"] is True
    r = client.put("/api/notifications/preferences", headers=ha, json={"preferences": [
        {"category": "exam", "in_app": False, "email": False}, {"category": "result", "in_app": True, "email": False}]})
    assert r.status_code == 200
    got = {p["category"]: p for p in r.json()["preferences"]}
    assert got["exam"]["in_app"] is False and got["result"]["email"] is False and got["seating"]["in_app"] is True
    assert _note(db, a, "optout")["opted_out"] == 1                                         # exam notice suppressed in-app
    assert client.get("/api/notifications", headers=ha).json() == []
    # security notices cannot be switched off
    assert client.put("/api/notifications/preferences", headers=ha, json={"preferences": [
        {"category": "account", "in_app": False, "email": True}]}).status_code == 422
    assert client.put("/api/notifications/preferences", headers=ha, json={"preferences": [
        {"category": "bogus", "in_app": True, "email": True}]}).status_code == 422
    # preferences are per user
    other = make_user(db, "carol", "student")
    assert all(p["in_app"] for p in client.get("/api/notifications/preferences", headers=login(client, "carol")).json()["preferences"])


def test_template_values_are_sanitised_and_links_internal_only(db, two_users):
    a, *_ = two_users
    nt.notify_users(db, [a], "announcement", {"announcement_title": "Hi\r\nBcc: x@y.z", "announcement_body": "line1\x00\nline2"},
                    event_key="san", link="https://evil.example/x")
    db.commit()
    n = db.scalar(select(models.Notification))
    assert "\n" not in n.title and "\r" not in n.title and "\x00" not in n.body and n.link is None


def test_notification_text_never_contains_marks_or_register_numbers(db, client, two_users):
    a, *_ = two_users
    exam = models.Exam(title="Final", subject_code="X1", exam_date="2027-03-01", start_time="09:00", end_time="12:00", venue="V", status="published")
    db.add(exam); db.commit()
    r = models.Result(student_id=a.student_id, exam_id=exam.id, marks=91.5, max_marks=100, grade="O", published=True)
    db.add(r); db.commit()
    nt.notify_result_published(db, r)
    n = db.scalar(select(models.Notification))
    text = n.title + n.body
    assert "91" not in text and REG1 not in text and "Grade" not in text and n.category == "result"
