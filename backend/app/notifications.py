"""Notification engine: audience resolution, preferences, de-duplication, in-app rows and queued e-mail.

Business routers call the notify_* helpers AFTER their own commit. A notification problem is logged and
swallowed so it can never undo or fail the administrative action that triggered it.
De-duplication: (user_id, event_key) is unique in `notifications` and `dedup_key` is unique in
`email_deliveries`, so repeating an action or re-running the scheduler cannot notify anybody twice."""
import logging, re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from . import delivery, models
from .config import settings
from .notify_templates import CATEGORIES, TEMPLATES, clean, render_text
from .services_allocation import eligible_students

log = logging.getLogger("exam_monitor.notify")
ALWAYS_IN_APP = {"account"}          # security notices cannot be switched off in-app
PRIORITY_RANK = {"low": 0, "normal": 1, "high": 2, "urgent": 3}


# ------------------------------------------------------------------ time
def local_tz() -> ZoneInfo:
    return ZoneInfo(settings.app_timezone)


def check_timezone() -> None:
    try:
        ZoneInfo(settings.app_timezone)
    except Exception:
        raise RuntimeError(f"APP_TIMEZONE '{settings.app_timezone}' is not a valid IANA time zone (e.g. Asia/Kolkata). "
                           "On Windows install the 'tzdata' package (pip install tzdata).")


def exam_start_utc(exam: models.Exam) -> datetime | None:
    try:
        h, m = (int(x) for x in exam.start_time.split(":")[:2])
        y, mo, d = (int(x) for x in str(exam.exam_date)[:10].split("-"))
        return datetime(y, mo, d, h, m, tzinfo=local_tz()).astimezone(timezone.utc)
    except Exception:
        return None


def human_left(delta: timedelta) -> str:
    mins = max(0, int(delta.total_seconds() // 60))
    if mins < 90:
        return f"in {max(mins, 1)} minute{'s' if mins != 1 else ''}"
    hours = round(mins / 60)
    if hours < 48:
        return f"in about {hours} hours"
    return f"in about {round(hours / 24)} days"


# ------------------------------------------------------------------ templates and preferences
def _template(db: Session, key: str) -> tuple[str, str]:
    row = db.get(models.EmailTemplate, key)
    spec = TEMPLATES[key]
    return (row.subject, row.body) if row else (spec["subject"], spec["body"])


def prefs_for(db: Session, user_id: int) -> dict[str, tuple[bool, bool]]:
    out = {c: (True, True) for c in CATEGORIES}
    for p in db.scalars(select(models.NotificationPreference).where(models.NotificationPreference.user_id == user_id)):
        if p.category in out:
            out[p.category] = (bool(p.in_app) or p.category in ALWAYS_IN_APP, bool(p.email))
    return out


def user_email(db: Session, user: models.User) -> str | None:
    e = (user.email or "").strip()
    if not e and user.student_id:
        st = db.get(models.Student, user.student_id)
        e = ((st.email if st else "") or "").strip()
    return e if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", e) else None


def _internal_link(link: str | None) -> str | None:
    return link if link and link.startswith("#/") and len(link) <= 190 else None


# ------------------------------------------------------------------ core
def notify_users(db: Session, users, template_key: str, ctx, *, event_key: str, link: str | None = None,
                 priority: str | None = None, queue_email: bool = True, created_by: str | None = None) -> dict:
    """`ctx` is a dict or a callable(user) -> dict. Returns counts. Caller commits."""
    spec = TEMPLATES[template_key]
    category, prio = spec["category"], priority or spec["priority"]
    subj_t, body_t = _template(db, template_key)
    res = {"in_app": 0, "emails": 0, "duplicates": 0, "opted_out": 0}
    base = {"college": settings.college_name}
    for u in users:
        in_app, mail = prefs_for(db, u.id)[category]
        c = {**base, **(ctx(u) if callable(ctx) else ctx)}
        title, body = render_text(subj_t, body_t, c)
        note = None
        if db.scalar(select(models.Notification.id).where(models.Notification.user_id == u.id,
                                                          models.Notification.event_key == event_key)):
            res["duplicates"] += 1
            continue
        if in_app:
            note = models.Notification(user_id=u.id, category=category, priority=prio, title=title[:200], body=body,
                                       link=_internal_link(link), event_key=event_key[:150])
            try:
                with db.begin_nested():
                    db.add(note)
                    db.flush()
                res["in_app"] += 1
            except IntegrityError:
                res["duplicates"] += 1
                continue
        else:
            res["opted_out"] += 1
        addr = user_email(db, u) if (queue_email and mail) else None
        if addr:
            row = delivery.create(db, to=addr, subject=title, body=body, kind="notification", user_id=u.id,
                                  notification_id=note.id if note else None,
                                  dedup_key=f"{event_key}|{u.id}"[:190], created_by=created_by)
            res["emails"] += 1 if row else 0
    return res


def _safe(fn):
    """Run a notification step after the main commit; never let it break the caller."""
    def wrapper(*a, **k):
        db = a[0]
        try:
            out = fn(*a, **k)
            db.commit()
            from . import scheduler
            scheduler.kick()
            return out
        except Exception:  # noqa: BLE001
            db.rollback()
            log.exception("notification step %s failed", fn.__name__)
            return None
    wrapper.__name__ = fn.__name__
    return wrapper


# ------------------------------------------------------------------ audiences
def _users_for_students(db: Session, student_ids: list[int]) -> list[models.User]:
    out: list[models.User] = []
    for i in range(0, len(student_ids), 400):
        out += db.scalars(select(models.User).where(models.User.student_id.in_(student_ids[i:i + 400]),
                          models.User.active == True, models.User.status == "active")).all()  # noqa: E712
    return out


def exam_audience(db: Session, exam: models.Exam, *, include_staff: bool = True, exclude: str | None = None) -> list[models.User]:
    """Students eligible for the exam, department staff whose department is represented, and invigilators."""
    studs = eligible_students(db, exam)
    users = _users_for_students(db, [s.id for s in studs])
    if include_staff:
        depts = {(s.department or "").strip().casefold() for s in studs}
        for u in db.scalars(select(models.User).where(models.User.role.in_(("staff", "invigilator")),
                                                      models.User.active == True, models.User.status == "active")):  # noqa: E712
            if u.role == "invigilator" or not (u.department or "").strip() or (u.department or "").strip().casefold() in depts:
                users.append(u)
    seen, out = set(), []
    for u in users:
        if u.id not in seen and u.username != exclude:
            seen.add(u.id)
            out.append(u)
    return out


def exam_ctx(exam: models.Exam) -> dict:
    return {"exam_title": exam.title, "subject_code": exam.subject_code, "exam_date": exam.exam_date,
            "exam_time": f"{exam.start_time}–{exam.end_time}", "venue": exam.venue}


def exam_snapshot(exam: models.Exam) -> dict:
    return {"title": exam.title, "exam_date": exam.exam_date, "start_time": exam.start_time,
            "end_time": exam.end_time, "venue": exam.venue, "status": exam.status}


# ------------------------------------------------------------------ examination events
@_safe
def notify_exam_transition(db: Session, exam: models.Exam, old: dict, actor: str | None = None):
    """Call after an examination was created/updated/published/unpublished. `old` = exam_snapshot() BEFORE the change.
    Only published examinations are visible to anyone, so drafts never notify."""
    was, now = old.get("status") == "published", exam.status == "published"
    stamp = (exam.updated_at or models.utcnow()).strftime("%Y%m%d%H%M%S%f")
    if now and not was:
        return notify_users(db, exam_audience(db, exam, exclude=actor), "exam_published", exam_ctx(exam),
                            event_key=f"exam:{exam.id}:published:{stamp}", link="#/my-exams", created_by=actor)
    if was and not now:
        return notify_users(db, exam_audience(db, exam, exclude=actor), "exam_withdrawn", exam_ctx(exam) | {"exam_date": old["exam_date"]},
                            event_key=f"exam:{exam.id}:withdrawn:{stamp}", link="#/my-exams", created_by=actor)
    if was and now:
        labels = {"title": "title", "exam_date": "date", "start_time": "start time", "end_time": "end time", "venue": "venue"}
        changed = [labels[k] for k in labels if old.get(k) != getattr(exam, k)]
        if changed:
            return notify_users(db, exam_audience(db, exam, exclude=actor), "exam_updated",
                                exam_ctx(exam) | {"changes": ", ".join(changed)},
                                event_key=f"exam:{exam.id}:updated:{stamp}", link="#/my-exams", created_by=actor)
    return None


# ------------------------------------------------------------------ seating events
def _seat_ctx(exam: models.Exam, hall=None, seat=None, old_hall=None, old_seat=None) -> dict:
    return exam_ctx(exam) | {"hall": hall or "", "seat": seat or "", "old_hall": old_hall or "", "old_seat": old_seat or ""}


@_safe
def notify_seat_events(db: Session, exam: models.Exam, events: list[dict], actor: str | None = None):
    """events: [{student_id, kind: allocated|corrected|removed, hall, seat, old_hall, old_seat}] -> only those students.
    Draft examinations are invisible to students, so nothing is sent for them (the publish notice covers it)."""
    if exam.status != "published" or not events:
        return None
    by_student = {e["student_id"]: e for e in events}
    users = _users_for_students(db, list(by_student))
    hist = {sid: db.query(models.AllotmentHistory).filter_by(exam_id=exam.id, student_id=sid).count() for sid in by_student}
    total = {"in_app": 0, "emails": 0, "duplicates": 0, "opted_out": 0}
    for u in users:
        ev = by_student[u.student_id]
        key = {"allocated": "seat_allocated", "corrected": "seat_corrected", "removed": "seat_removed"}[ev["kind"]]
        r = notify_users(db, [u], key, _seat_ctx(exam, ev.get("hall"), ev.get("seat"), ev.get("old_hall"), ev.get("old_seat")),
                         event_key=f"seat:{exam.id}:{u.student_id}:{ev['kind']}:{ev.get('hall')}:{ev.get('seat')}:{hist[u.student_id]}",
                         link="#/my-exams", created_by=actor)
        for k in total:
            total[k] += r[k]
    return total


# ------------------------------------------------------------------ results
@_safe
def notify_result_published(db: Session, result: models.Result, actor: str | None = None):
    users = _users_for_students(db, [result.student_id])
    exam = db.get(models.Exam, result.exam_id)
    if not users or not exam:
        return None
    stamp = (result.published_at or models.utcnow()).strftime("%Y%m%d%H%M%S%f")
    return notify_users(db, users, "result_published", exam_ctx(exam), event_key=f"result:{result.id}:published:{stamp}",
                        link="#/my-results", created_by=actor)   # never contains marks or grade


# ------------------------------------------------------------------ account events
@_safe
def notify_account_event(db: Session, user: models.User, template_key: str, event_key: str):
    return notify_users(db, [user], template_key, {}, event_key=event_key, link="#/account")


# ------------------------------------------------------------------ announcements
def announcement_audience(db: Session, a: models.Announcement) -> list[models.User]:
    roles = {r.strip() for r in (a.audience_roles or "").split(",") if r.strip()}
    dept = (a.audience_department or "").strip().casefold()
    year = a.audience_year
    users = db.scalars(select(models.User).where(models.User.active == True, models.User.status == "active")).all()  # noqa: E712
    out = []
    for u in users:
        if roles and not (u.role in roles or (u.role == "super_admin" and "admin" in roles)):
            continue
        if dept or year:
            if u.role == "student" and u.student_id:
                st = db.get(models.Student, u.student_id)
                if not st or (dept and (st.department or "").strip().casefold() != dept) or (year and st.year != year):
                    continue
            elif u.role == "staff" and dept and not year:
                if (u.department or "").strip().casefold() != dept:
                    continue
            else:
                continue
        out.append(u)
    return out


def announcement_visible(a: models.Announcement, now: datetime) -> bool:
    aware = lambda d: d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)  # noqa: E731
    return bool(a.published and (aware(a.publish_at) is None or aware(a.publish_at) <= now)
                and (aware(a.expires_at) is None or aware(a.expires_at) > now))


def dispatch_announcement(db: Session, a: models.Announcement, now: datetime | None = None) -> dict | None:
    """Fan an announcement out once. Marks notified_at; later edits never re-notify. Caller commits."""
    now = now or models.utcnow()
    if not (a.notify and a.notified_at is None and announcement_visible(a, now)):
        return None
    a.notified_at = now
    return notify_users(db, announcement_audience(db, a), "announcement",
                        {"announcement_title": a.title, "announcement_body": a.body},
                        event_key=f"announcement:{a.id}", priority=a.priority or "normal", link="#/notifications",
                        created_by=a.created_by)


@_safe
def notify_announcement(db: Session, a: models.Announcement):
    return dispatch_announcement(db, a)
