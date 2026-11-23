"""Administrator communication controls: e-mail status, test e-mail, delivery log, retries, templates, statistics.
Administrator / super administrator only (enforced here, on the server)."""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .. import audit, delivery, mailer, models, notifications as nt, scheduler
from ..config import settings
from ..database import get_db
from ..deps import require_roles
from ..notify_templates import CATEGORIES, TEMPLATES, render_text, validate_template
from ..ratelimit import limiter

router = APIRouter(prefix="/api/admin/communications", tags=["Communications (administrators)"])
ADMIN = require_roles("admin")
STATUSES = ("queued", "sending", "sent", "retrying", "failed", "outbox", "not_configured")


def _rl(key: str, limit: int, window: int, what: str):
    ok, retry = limiter.check_and_record(key, limit, window)
    if not ok:
        raise HTTPException(status_code=429, detail=f"Too many {what}. Try again later.", headers={"Retry-After": str(max(1, retry))})


def _row(r: models.EmailDelivery) -> dict:
    iso = lambda d: d.isoformat() if d else None  # noqa: E731
    return {"id": r.id, "created_at": iso(r.created_at), "kind": r.kind, "recipient": delivery.mask(r.recipient),
            "subject": r.subject, "status": r.status, "mode": r.mode, "attempts": r.attempts, "max_attempts": r.max_attempts,
            "error_code": r.error_code, "last_error": r.last_error, "sent_at": iso(r.sent_at),
            "next_attempt_at": iso(r.next_attempt_at), "notification_id": r.notification_id,
            "retryable": (not r.sensitive) and r.status in ("failed", "retrying", "not_configured")}


@router.get("/email-status")
def email_status(db: Session = Depends(get_db), user: models.User = Depends(ADMIN)):
    E = models.EmailDelivery
    queue = dict(db.execute(select(E.status, func.count()).group_by(E.status)).all())
    return {**mailer.config_status(), "queue": {s: queue.get(s, 0) for s in STATUSES},
            "scheduler": {"enabled": settings.scheduler_enabled, "interval_seconds": settings.scheduler_interval_seconds,
                          "timezone": settings.app_timezone, "reminders_enabled": settings.reminders_enabled,
                          "exam_reminder_hours_before": settings.reminder_hours}}


class TestEmail(BaseModel):
    to: str | None = Field(default=None, max_length=150)


@router.post("/test-email")
def test_email(data: TestEmail, request: Request, db: Session = Depends(get_db), user: models.User = Depends(ADMIN)):
    """Sends one fixed message right now and reports what the SMTP server really answered."""
    _rl(f"test-email:{user.id}", settings.test_email_per_hour, 3600, "test e-mails")
    to = (data.to or user.email or "").strip().lower()
    if not to:
        raise HTTPException(status_code=422, detail="Your account has no e-mail address. Enter the address to test.")
    known = db.scalar(select(models.User.id).where(func.lower(models.User.email) == to)) or \
        db.scalar(select(models.Student.id).where(func.lower(models.Student.email) == to))
    if not known:
        raise HTTPException(status_code=422, detail="Test messages may only go to an address that belongs to a user or "
                                                     "student record (this endpoint is not a mail relay).")
    subj, body = render_text(*nt._template(db, "test_email"), {"college": settings.college_name})
    row = delivery.create(db, to=to, subject=subj, body=body, kind="test", user_id=user.id, created_by=user.username)
    status = delivery.deliver_row(db, row, allow_retry=False)
    audit.record(db, user.username, "email.test_sent", f"delivery:{row.id}", {"status": status, "mode": row.mode}, request, user.role)
    db.commit()
    ok = status == "sent"
    return {"delivery_id": row.id, "status": status, "mode": row.mode, "accepted_by_smtp_server": ok, "error_code": row.error_code,
            "detail": {"sent": "The SMTP server accepted the message for delivery.",
                       "outbox": "Written to the development outbox only. Nothing was e-mailed (SMTP_HOST is not set).",
                       "not_configured": "SMTP is not configured, so nothing was sent."}.get(status, row.last_error or "Delivery failed.")}


@router.get("/deliveries")
def deliveries(response: Response, status: str = Query("", max_length=15), kind: str = Query("", max_length=20),
               q: str = Query("", max_length=80), days: int = Query(0, ge=0, le=365),
               limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0),
               db: Session = Depends(get_db), user: models.User = Depends(ADMIN)):
    E = models.EmailDelivery
    cond = []
    if status:
        if status not in STATUSES:
            raise HTTPException(status_code=422, detail="Unknown status")
        cond.append(E.status == status)
    if kind:
        cond.append(E.kind == kind)
    if q.strip():
        cond.append(E.subject.ilike("%" + q.strip().replace("%", "\\%").replace("_", "\\_") + "%", escape="\\"))
    if days:
        cond.append(E.created_at >= datetime.now(timezone.utc) - timedelta(days=days))
    response.headers["X-Total-Count"] = str(db.scalar(select(func.count()).select_from(E).where(*cond)) or 0)
    return [_row(r) for r in db.scalars(select(E).where(*cond).order_by(E.id.desc()).limit(limit).offset(offset))]


@router.post("/deliveries/{delivery_id}/retry")
def retry(delivery_id: int, request: Request, db: Session = Depends(get_db), user: models.User = Depends(ADMIN)):
    """Re-attempt a failed message once, now. A message already sent can never be sent again; messages that carry a
    one-time link are not retained, so the user must request a new link instead."""
    _rl(f"retry-email:{user.id}", 30, 3600, "retries")
    r = db.get(models.EmailDelivery, delivery_id)
    if not r:
        raise HTTPException(status_code=404, detail="Delivery not found")
    if r.sensitive:
        raise HTTPException(status_code=409, detail="This message contained a one-time link and was not retained. Ask the user to request a new one.")
    if r.status not in ("failed", "retrying", "not_configured"):
        raise HTTPException(status_code=409, detail=f"Only failed, retrying or unconfigured messages can be retried (this one is {r.status}).")
    claimed = db.execute(models.EmailDelivery.__table__.update().where(models.EmailDelivery.id == r.id,
                         models.EmailDelivery.status == r.status).values(status="sending", updated_at=models.utcnow()))
    db.commit()
    if claimed.rowcount != 1:
        raise HTTPException(status_code=409, detail="Another worker is already handling this message.")
    db.refresh(r)
    r.max_attempts = max(r.max_attempts, r.attempts + 1)
    status = delivery.deliver_row(db, r, allow_retry=False)
    audit.record(db, user.username, "email.retried", f"delivery:{r.id}", {"status": status}, request, user.role)
    db.commit()
    return _row(r)


@router.get("/stats")
def stats(days: int = Query(7, ge=1, le=90), db: Session = Depends(get_db), user: models.User = Depends(ADMIN)):
    E, N = models.EmailDelivery, models.Notification
    since = datetime.now(timezone.utc) - timedelta(days=days)
    by_status = dict(db.execute(select(E.status, func.count()).where(E.created_at >= since).group_by(E.status)).all())
    by_kind = dict(db.execute(select(E.kind, func.count()).where(E.created_at >= since).group_by(E.kind)).all())
    sent, failed = by_status.get("sent", 0), by_status.get("failed", 0)
    notes = dict(db.execute(select(N.category, func.count()).where(N.created_at >= since).group_by(N.category)).all())
    unread = db.scalar(select(func.count()).select_from(N).where(N.read_at.is_(None), N.archived_at.is_(None), N.deleted_at.is_(None))) or 0
    pending = db.scalar(select(func.count()).select_from(E).where(E.status.in_(("queued", "retrying", "sending")))) or 0
    return {"days": days, "emails_by_status": by_status, "emails_by_kind": by_kind, "emails_total": sum(by_status.values()),
            "success_rate": round(sent / (sent + failed), 3) if (sent + failed) else None, "pending": pending,
            "notifications_by_category": notes, "notifications_total": sum(notes.values()), "unread_notifications": unread}


@router.post("/run-scheduler")
def run_scheduler(request: Request, db: Session = Depends(get_db), user: models.User = Depends(ADMIN)):
    """Runs one worker cycle now (scheduled announcements, reminders, e-mail queue). Idempotent."""
    _rl(f"run-scheduler:{user.id}", 20, 3600, "manual runs")
    out = scheduler.run_cycle()
    audit.record(db, user.username, "communications.scheduler_run", "manual", out, request, user.role)
    db.commit()
    return out


# ------------------------------------------------------------------ templates
class TemplateInput(BaseModel):
    subject: str = Field(max_length=300)
    body: str = Field(max_length=4000)


def _tview(db: Session, key: str) -> dict:
    spec, row = TEMPLATES[key], db.get(models.EmailTemplate, key)
    return {"key": key, "label": spec["label"], "category": spec["category"], "category_label": CATEGORIES[spec["category"]],
            "placeholders": spec["placeholders"] + ["college"], "customized": bool(row),
            "subject": row.subject if row else spec["subject"], "body": row.body if row else spec["body"],
            "default_subject": spec["subject"], "default_body": spec["body"],
            "updated_by": row.updated_by if row else None, "updated_at": row.updated_at.isoformat() if row else None}


@router.get("/templates")
def templates(db: Session = Depends(get_db), user: models.User = Depends(ADMIN)):
    return [_tview(db, k) for k in TEMPLATES]


def _tkey(key: str) -> str:
    if key not in TEMPLATES:
        raise HTTPException(status_code=404, detail="Unknown template")
    return key


@router.put("/templates/{key}")
def save_template(key: str, data: TemplateInput, request: Request, db: Session = Depends(get_db), user: models.User = Depends(ADMIN)):
    _rl(f"tpl:{user.id}", 30, 3600, "template changes")
    _tkey(key)
    errs = validate_template(key, data.subject, data.body)
    if errs:
        raise HTTPException(status_code=422, detail="; ".join(errs))
    row = db.get(models.EmailTemplate, key)
    if row:
        row.subject, row.body, row.updated_by = data.subject.strip(), data.body.strip(), user.username
    else:
        db.add(models.EmailTemplate(key=key, subject=data.subject.strip(), body=data.body.strip(), updated_by=user.username))
    audit.record(db, user.username, "email_template.updated", key, {"subject_length": len(data.subject)}, request, user.role)
    db.commit()
    return _tview(db, key)


@router.delete("/templates/{key}")
def reset_template(key: str, request: Request, db: Session = Depends(get_db), user: models.User = Depends(ADMIN)):
    _tkey(key)
    row = db.get(models.EmailTemplate, key)
    if row:
        db.delete(row)
        audit.record(db, user.username, "email_template.reset", key, request=request, role=user.role)
        db.commit()
    return _tview(db, key)


_SAMPLE = {"exam_title": "Sample Examination", "subject_code": "CS3501", "exam_date": "2027-01-15", "exam_time": "09:30–12:30",
           "venue": "Main Block", "hall": "A101", "seat": "12", "old_hall": "A100", "old_seat": "4", "changes": "date, venue",
           "time_left": "in about 24 hours", "seat_line": "Hall A101, Seat 12", "announcement_title": "Sample announcement",
           "announcement_body": "This is sample announcement text."}


@router.post("/templates/{key}/preview")
def preview_template(key: str, data: TemplateInput, db: Session = Depends(get_db), user: models.User = Depends(ADMIN)):
    _tkey(key)
    errs = validate_template(key, data.subject, data.body)
    if errs:
        raise HTTPException(status_code=422, detail="; ".join(errs))
    subject, body = render_text(data.subject, data.body, {**_SAMPLE, "college": settings.college_name})
    return {"subject": subject, "body": body}
