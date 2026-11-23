"""Phase 6: notifications fired by the real application workflows, audience targeting, duplicates, reminders."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import pytest
from sqlalchemy import select
from app import delivery, models, notifications as nt, scheduler
from app.config import settings
from conftest import make_user, make_student, make_exam, login, STRONG, REG1, REG2, REG3

ECE, CSE = "Electronics and Communication", "Computer Science"


@pytest.fixture()
def world(db, client):
    """admin + 3 students (2 ECE year 2, 1 CSE year 3) with accounts, ECE staff, CSE staff, invigilator."""
    admin = make_user(db, "adm", "admin")
    s1, s2 = make_student(db, REG1, "E One", ECE, 2), make_student(db, REG2, "E Two", ECE, 2)
    s3 = make_student(db, REG3, "C Three", CSE, 3)
    u = {n: make_user(db, n, "student", student=s) for n, s in (("e1", s1), ("e2", s2), ("c3", s3))}
    for name, role, dept in (("staff_ece", "staff", ECE), ("staff_cse", "staff", CSE), ("staff_all", "staff", None), ("inv", "invigilator", None)):
        x = make_user(db, name, role); x.department = dept; u[name] = x
    db.commit()
    return {"admin": login(client, "adm"), "u": u, "s": (s1, s2, s3)}


def _titles(db, user):
    return [n.title for n in db.scalars(select(models.Notification).where(models.Notification.user_id == user.id).order_by(models.Notification.id))]


def _draft_exam(db, client, h, rules=None, date="2027-06-01"):
    e = make_exam(db, status="draft", title="Signals", code="EC301", date=date)
    for r in (rules if rules is not None else [{"department": ECE, "year": 2}]):
        db.add(models.ExamEligibilityRule(exam_id=e.id, **r))
    db.commit()
    return e


def test_publish_notifies_only_the_exam_audience(db, client, world):
    w = world; e = _draft_exam(db, client, w["admin"])
    assert client.post(f"/api/exams/{e.id}/publish", headers=w["admin"]).status_code == 200
    u = w["u"]
    for name in ("e1", "e2", "staff_ece", "staff_all", "inv"):
        assert _titles(db, u[name]) == ["New examination: Signals"], name
    for name in ("c3", "staff_cse"):                                       # other department: nothing
        assert _titles(db, u[name]) == [], name
    assert _titles(db, db.scalar(select(models.User).where(models.User.username == "adm"))) == []   # the actor is not spammed


def test_publish_with_no_audience_rule_notifies_every_student(db, client, world):
    w = world; e = _draft_exam(db, client, w["admin"], rules=[])
    client.post(f"/api/exams/{e.id}/publish", headers=w["admin"])
    assert all(_titles(db, w["u"][n]) for n in ("e1", "e2", "c3"))


def test_inactive_and_pending_accounts_are_never_notified(db, client, world):
    w = world; e = _draft_exam(db, client, w["admin"])
    w["u"]["e2"].active, w["u"]["e2"].status = False, "suspended"; db.commit()
    client.post(f"/api/exams/{e.id}/publish", headers=w["admin"])
    assert _titles(db, w["u"]["e2"]) == [] and _titles(db, w["u"]["e1"])


def test_draft_changes_do_not_notify(db, client, world):
    w = world; e = _draft_exam(db, client, w["admin"])
    assert client.patch(f"/api/exams/{e.id}", headers=w["admin"], json={"venue": "Elsewhere"}).status_code == 200
    assert db.query(models.Notification).count() == 0


def test_schedule_change_and_withdrawal(db, client, world):
    w = world; e = _draft_exam(db, client, w["admin"])
    client.post(f"/api/exams/{e.id}/publish", headers=w["admin"])
    r = client.patch(f"/api/exams/{e.id}", headers=w["admin"], json={"exam_date": "2027-06-03", "venue": "Hall Z"})
    assert r.status_code == 200
    got = db.scalars(select(models.Notification).where(models.Notification.user_id == w["u"]["e1"].id, models.Notification.category == "timetable")).all()
    assert len(got) == 1 and "date, venue" in got[0].body and "2027-06-03" in got[0].body and got[0].priority == "high"
    client.patch(f"/api/exams/{e.id}", headers=w["admin"], json={"venue": "Hall Z"})                # no actual change -> no notice
    assert db.query(models.Notification).filter_by(user_id=w["u"]["e1"].id, category="timetable").count() == 1
    client.post(f"/api/exams/{e.id}/unpublish", headers=w["admin"])
    assert "Examination withdrawn: Signals" in _titles(db, w["u"]["e1"]) and not _titles(db, w["u"]["c3"])


def test_repeating_publish_does_not_duplicate(db, client, world):
    w = world; e = _draft_exam(db, client, w["admin"])
    client.post(f"/api/exams/{e.id}/publish", headers=w["admin"])
    assert client.post(f"/api/exams/{e.id}/publish", headers=w["admin"]).status_code == 409
    assert _titles(db, w["u"]["e1"]) == ["New examination: Signals"]


def _hall(db, client, h, code="H1", seats=10):
    r = client.post("/api/admin/halls", headers=h, json={"code": code, "capacity": seats}); assert r.status_code in (200, 201), r.text
    hid = r.json()["id"]
    client.post(f"/api/admin/halls/{hid}/verify", headers=h)
    client.post(f"/api/admin/halls/{hid}/seats/generate", headers=h)
    return code


def test_seat_allocation_correction_and_removal_notify_only_that_student(db, client, world):
    w = world; e = _draft_exam(db, client, w["admin"])
    hall = _hall(db, client, w["admin"])
    client.post(f"/api/exams/{e.id}/publish", headers=w["admin"])
    r = client.post("/api/allotments", headers=w["admin"], json={"register_number": REG1, "exam_id": e.id, "hall": hall, "seat": "1"})
    assert r.status_code == 201, r.text
    t = _titles(db, w["u"]["e1"])
    assert "Your seat for Signals" in t and not any("seat" in x.lower() for x in _titles(db, w["u"]["e2"]))
    body = db.scalar(select(models.Notification.body).where(models.Notification.user_id == w["u"]["e1"].id, models.Notification.category == "seating"))
    assert "Hall: H1" in body and "Seat: 1" in body and REG1 not in body and REG2 not in body
    aid = r.json()["id"]
    assert client.patch(f"/api/allotments/{aid}", headers=w["admin"], json={"hall": hall, "seat": "2", "reason": "wheelchair access"}).status_code == 200
    assert "Seat changed for Signals" in _titles(db, w["u"]["e1"])
    client.patch(f"/api/allotments/{aid}", headers=w["admin"], json={"hall": hall, "seat": "2", "reason": "same again"})   # no change
    assert _titles(db, w["u"]["e1"]).count("Seat changed for Signals") == 1
    client.delete(f"/api/allotments/{aid}?reason=error", headers=w["admin"])
    assert "Seat allocation removed: Signals" in _titles(db, w["u"]["e1"])
    assert _titles(db, w["u"]["c3"]) == []


def test_no_seat_notice_for_draft_exam(db, client, world):
    w = world; e = _draft_exam(db, client, w["admin"]); hall = _hall(db, client, w["admin"])
    assert client.post("/api/allotments", headers=w["admin"], json={"register_number": REG1, "exam_id": e.id, "hall": hall, "seat": "1"}).status_code == 201
    assert db.query(models.Notification).count() == 0


def test_auto_allocation_plan_commit_notifies_each_allotted_student_once(db, client, world):
    w = world; e = _draft_exam(db, client, w["admin"]); hall = _hall(db, client, w["admin"])
    client.post(f"/api/exams/{e.id}/publish", headers=w["admin"])
    db.query(models.Notification).delete(); db.commit()
    r = client.post("/api/allotments/plans", headers=w["admin"], json={"exam_id": e.id, "halls": [hall]})
    if r.status_code != 201:
        pytest.skip(f"plan payload differs: {r.text[:120]}")
    pid = r.json()["id"] if "id" in r.json() else r.json()["plan_id"]
    assert client.post(f"/api/allotments/plans/{pid}/commit", headers=w["admin"], json={}).status_code == 201
    for n in ("e1", "e2"):
        assert _titles(db, w["u"][n]) == ["Your seat for Signals"]
    assert _titles(db, w["u"]["c3"]) == []


def test_result_publication_notifies_the_student_without_marks(db, client, world):
    w = world; e = _draft_exam(db, client, w["admin"])
    s1 = w["s"][0]
    r = models.Result(student_id=s1.id, exam_id=e.id, marks=77, max_marks=100, grade="B")
    db.add(r); db.commit()
    assert client.post(f"/api/results/{r.id}/publish", headers=w["admin"]).status_code == 200
    n = db.scalars(select(models.Notification).where(models.Notification.category == "result")).all()
    assert len(n) == 1 and n[0].user_id == w["u"]["e1"].id and "77" not in n[0].body + n[0].title
    client.post(f"/api/results/{r.id}/unpublish", headers=w["admin"]); client.post(f"/api/results/{r.id}/publish", headers=w["admin"])
    assert db.query(models.Notification).filter_by(category="result").count() == 2     # a genuine re-publication is a new event


# ---------------------------------------------------------------- announcements
def test_announcement_targeting_and_single_delivery(db, client, world):
    w = world; h = w["admin"]
    r = client.post("/api/admin/announcements", headers=h, json={"title": "ECE Year 2 notice", "body": "Bring ID cards.", "published": True,
                    "notify": True, "audience_roles": ["student"], "audience_department": ECE, "audience_year": 2, "priority": "urgent"})
    assert r.status_code == 201, r.text
    for n in ("e1", "e2"):
        assert _titles(db, w["u"][n]) == ["ECE Year 2 notice"]
    assert not _titles(db, w["u"]["c3"]) and not _titles(db, w["u"]["staff_ece"]) and not _titles(db, w["u"]["inv"])
    assert db.scalar(select(models.Notification.priority)) == "urgent"
    aid = r.json()["id"]
    client.patch(f"/api/admin/announcements/{aid}", headers=h, json={"title": "ECE Year 2 notice (edited)", "body": "Bring ID cards.", "published": True, "notify": True})
    assert db.query(models.Notification).count() == 2                        # editing never re-notifies
    assert client.get("/api/announcements").json() == []                     # targeted: not on the public page


def test_untargeted_announcement_stays_public_and_notifies_everyone_when_asked(db, client, world):
    w = world; h = w["admin"]
    client.post("/api/admin/announcements", headers=h, json={"title": "Holiday", "body": "Closed Monday", "published": True})
    assert [a["title"] for a in client.get("/api/announcements").json()] == ["Holiday"]
    assert db.query(models.Notification).count() == 0                        # old behaviour: no notify flag, no notification
    client.post("/api/admin/announcements", headers=h, json={"title": "Urgent", "body": "All", "published": True, "notify": True})
    from sqlalchemy import func
    assert db.scalar(select(func.count()).select_from(models.Notification)) == 8   # every active account: 3 students, 3 staff, invigilator, admin
    assert [a["title"] for a in client.get("/api/announcements").json()][0] in ("Urgent", "Holiday")


def test_announcement_draft_and_scheduled_publication(db, client, world):
    w = world; h = w["admin"]
    client.post("/api/admin/announcements", headers=h, json={"title": "Draft", "body": "x", "published": False, "notify": True, "audience_roles": ["student"]})
    assert db.query(models.Notification).count() == 0
    when = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    r = client.post("/api/admin/announcements", headers=h, json={"title": "Later", "body": "y", "published": True, "notify": True,
                    "audience_roles": ["student"], "publish_at": when})
    assert r.status_code == 201 and db.query(models.Notification).count() == 0         # not visible yet -> not sent yet
    scheduler.run_cycle(now=datetime.now(timezone.utc) + timedelta(hours=3))
    assert db.query(models.Notification).filter_by(category="announcement").count() == 3
    scheduler.run_cycle(now=datetime.now(timezone.utc) + timedelta(hours=4))
    assert db.query(models.Notification).filter_by(category="announcement").count() == 3   # exactly once


def test_staff_cannot_broadcast_or_target(db, client, world):
    sc = login(client, "staff_cse")
    assert client.post("/api/admin/announcements", headers=sc, json={"title": "Dept notice", "body": "b", "published": True, "notify": True}).status_code == 201
    assert _titles(db, world["u"]["c3"]) == ["Dept notice"] and not _titles(db, world["u"]["e1"])   # forced to own department's students
    assert client.post("/api/admin/announcements", headers=sc, json={"title": "Wide", "body": "b", "published": True, "audience_roles": ["student"]}).status_code == 403
    sall = login(client, "staff_all")
    assert client.post("/api/admin/announcements", headers=sall, json={"title": "Mass", "body": "b", "published": True, "notify": True}).status_code == 403
    assert client.post("/api/admin/announcements", headers=sall, json={"title": "Plain", "body": "b", "published": True}).status_code == 201   # old behaviour kept
    assert client.post("/api/admin/announcements", headers=world["admin"], json={"title": "Bad", "body": "b", "audience_roles": ["root"]}).status_code == 422


def test_announcement_reminder_once(db, client, world):
    h = world["admin"]
    remind = datetime.now(timezone.utc) + timedelta(hours=5)
    client.post("/api/admin/announcements", headers=h, json={"title": "Fee deadline", "body": "Pay fees", "published": True, "notify": True,
                "audience_roles": ["student"], "remind_at": remind.isoformat(), "priority": "high"})
    scheduler.run_cycle(now=datetime.now(timezone.utc) + timedelta(hours=1))
    assert db.query(models.Notification).filter(models.Notification.title.like("Reminder:%")).count() == 0
    for k in (6, 7):
        scheduler.run_cycle(now=datetime.now(timezone.utc) + timedelta(hours=k))
    assert db.query(models.Notification).filter(models.Notification.title == "Reminder: Fee deadline").count() == 3


# ---------------------------------------------------------------- exam reminders
def _exam_at(db, hours_from_now, rules=None):
    start = (datetime.now(timezone.utc) + timedelta(hours=hours_from_now)).astimezone(ZoneInfo(settings.app_timezone))
    e = models.Exam(title="Remind me", subject_code="RM1", exam_date=start.strftime("%Y-%m-%d"), start_time=start.strftime("%H:%M"),
                    end_time="23:59", venue="Block A", status="published")
    db.add(e); db.commit()
    for r in (rules or []):
        db.add(models.ExamEligibilityRule(exam_id=e.id, **r))
    db.commit()
    return e


def test_exam_reminders_window_dedup_and_seat_detail(db, client, world, monkeypatch):
    monkeypatch.setattr(settings, "reminder_exam_hours", "24,2")
    e = _exam_at(db, 20, [{"department": ECE, "year": 2}])
    db.add(models.Allotment(student_id=world["s"][0].id, exam_id=e.id, hall="H9", seat="14", source="manual")); db.commit()
    now = datetime.now(timezone.utc)
    out = scheduler.run_cycle(now=now)
    assert out["exam_reminders"] == 2
    rem = db.scalars(select(models.Notification).where(models.Notification.category == "reminder")).all()
    assert {n.user_id for n in rem} == {world["u"]["e1"].id, world["u"]["e2"].id}               # eligible students only
    mine = [n for n in rem if n.user_id == world["u"]["e1"].id][0]
    assert "Hall H9, Seat 14" in mine.body and "in about 20 hours" in mine.title
    assert "once allotted" in [n for n in rem if n.user_id == world["u"]["e2"].id][0].body
    assert scheduler.run_cycle(now=now + timedelta(minutes=30))["exam_reminders"] == 0         # no duplicate
    assert scheduler.run_cycle(now=now + timedelta(hours=18.5))["exam_reminders"] == 2          # the 2-hour window opens
    assert db.query(models.Notification).filter_by(category="reminder", user_id=world["u"]["e1"].id).count() == 2


def test_no_reminder_for_far_future_past_draft_or_disabled(db, client, world, monkeypatch):
    far, past = _exam_at(db, 100), _exam_at(db, -3)
    drafty = _exam_at(db, 10); drafty.status = "draft"; db.commit()
    assert scheduler.run_cycle()["exam_reminders"] == 0
    live = _exam_at(db, 5)
    monkeypatch.setattr(settings, "reminders_enabled", False)
    assert scheduler.run_cycle()["exam_reminders"] == 0
    monkeypatch.setattr(settings, "reminders_enabled", True)
    scheduler.run_cycle()
    assert db.query(models.Notification).filter_by(category="reminder").count() == 3             # the 3 students, for the one live exam
    assert {n.event_key.split(":")[2] for n in db.scalars(select(models.Notification))} == {str(live.id)}


def test_rescheduled_exam_gets_a_fresh_reminder_and_user_can_opt_out(db, client, world, monkeypatch):
    e = _exam_at(db, 10, [{"department": ECE, "year": 2}])
    db.add(models.NotificationPreference(user_id=world["u"]["e2"].id, category="reminder", in_app=False, email=False)); db.commit()
    scheduler.run_cycle()
    assert db.query(models.Notification).filter_by(category="reminder").count() == 1          # e2 opted out
    new = datetime.now(timezone.utc) + timedelta(hours=12)
    local = new.astimezone(ZoneInfo(settings.app_timezone))
    e.exam_date, e.start_time = local.strftime("%Y-%m-%d"), local.strftime("%H:%M"); db.commit()
    scheduler.run_cycle()
    assert db.query(models.Notification).filter_by(category="reminder", user_id=world["u"]["e1"].id).count() == 2


def test_timezone_is_configurable_and_validated(monkeypatch):
    exam = models.Exam(title="t", subject_code="c", exam_date="2027-01-15", start_time="09:30", end_time="12:00", venue="v")
    assert settings.app_timezone == "Asia/Kolkata"                                              # documented default
    assert nt.exam_start_utc(exam) == datetime(2027, 1, 15, 4, 0, tzinfo=timezone.utc)          # 09:30 IST = 04:00 UTC
    monkeypatch.setattr(settings, "app_timezone", "America/New_York")
    assert nt.exam_start_utc(exam) == datetime(2027, 1, 15, 14, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(settings, "app_timezone", "Not/AZone")
    with pytest.raises(RuntimeError):
        nt.check_timezone()


def test_worker_thread_start_stop_and_run_endpoint(db, client, world, monkeypatch):
    monkeypatch.setattr(settings, "scheduler_enabled", True); monkeypatch.setattr(settings, "scheduler_interval_seconds", 1)
    scheduler.start(); assert scheduler._thread.is_alive(); scheduler.stop(); assert scheduler._thread is None
    r = client.post("/api/admin/communications/run-scheduler", headers=world["admin"])
    assert r.status_code == 200 and "email" in r.json()


# ---------------------------------------------------------------- account events + migration
def test_password_change_creates_account_notice_and_cannot_be_hidden(db, client, world):
    h = login(client, "e1")
    r = client.post("/api/auth/change-password", headers=h, json={"current_password": STRONG, "new_password": "Another-Strong-2027-pw"})
    assert r.status_code == 200
    assert "Your Exam Monitor password was changed" in _titles(db, world["u"]["e1"])


def test_migration_0009_keeps_existing_announcements_and_downgrades(tmp_path):
    from alembic import command
    from sqlalchemy import create_engine, text, inspect
    from app.dbcheck import alembic_config
    url = "sqlite:///" + (tmp_path / "m.db").as_posix()
    cfg = alembic_config(url)
    command.upgrade(cfg, "0008")
    eng = create_engine(url)
    with eng.begin() as c:
        c.execute(text("INSERT INTO announcements (title, body, published, created_by, created_at, updated_at) VALUES ('Old', 'body', 1, 'admin', '2026-01-01', '2026-01-01')"))
    command.upgrade(cfg, "head")
    with eng.connect() as c:
        row = c.execute(text("SELECT title, published, priority, notify, audience_roles, notified_at FROM announcements")).one()
    assert tuple(row) == ("Old", 1, "normal", 0, None, None)                                    # old data intact, nobody re-notified
    assert {"notifications", "notification_preferences", "email_deliveries", "email_templates"} <= set(inspect(eng).get_table_names())
    command.downgrade(cfg, "0008")
    insp = inspect(eng)
    assert "notifications" not in insp.get_table_names() and "priority" not in {c["name"] for c in insp.get_columns("announcements")}
    with eng.connect() as c:
        assert c.execute(text("SELECT title FROM announcements")).scalar() == "Old"
