"""E-mail delivery queue: create rows, attempt them, retry with back-off, never double-send."""
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from . import mailer, models
from .config import settings
from .database import SessionLocal

log = logging.getLogger("exam_monitor.delivery")
STUCK_AFTER = timedelta(minutes=10)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt):
    return None if dt is None else (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt)


def mask(address: str) -> str:
    local, _, domain = (address or "").partition("@")
    return (local[:1] + "***@" + domain) if domain else "***"


def create(db: Session, *, to: str, subject: str, body: str, kind: str, sensitive: bool = False, user_id: int | None = None,
           notification_id: int | None = None, dedup_key: str | None = None, created_by: str | None = None):
    """Insert a queued row (not committed). Returns None when dedup_key already exists (duplicate suppressed)."""
    if dedup_key and db.scalar(select(models.EmailDelivery.id).where(models.EmailDelivery.dedup_key == dedup_key)):
        return None
    row = models.EmailDelivery(kind=kind, user_id=user_id, notification_id=notification_id, recipient=to[:150],
                               subject=mailer.build_message(to, subject, "").get("Subject")[:200],
                               body=None if sensitive else body, sensitive=sensitive, status="queued",
                               attempts=0, max_attempts=settings.mail_max_attempts, dedup_key=dedup_key, created_by=created_by)
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        return None
    # the in-memory body is needed for an immediate attempt even when it is not persisted
    row._plain_body = body  # type: ignore[attr-defined]
    return row


def deliver_row(db: Session, row, allow_retry: bool = True) -> str:
    """Attempt one delivery and record the true outcome. Caller commits. Returns the resulting status."""
    body = getattr(row, "_plain_body", None) or row.body
    if body is None:
        row.status, row.error_code, row.last_error = "failed", "body_not_kept", "Message body is not retained; request a new message"
        return row.status
    row.attempts += 1
    status, code, err, mode = mailer.attempt(row.recipient, row.subject, body)
    row.mode, row.updated_at = mode, _now()
    if status in ("sent", "outbox"):
        row.status, row.sent_at, row.error_code, row.last_error, row.next_attempt_at = status, _now(), None, None, None
    elif status == "not_configured":
        row.status, row.error_code, row.last_error = "not_configured", code, err
    else:
        row.error_code, row.last_error = code, err
        if status == "error:transient" and allow_retry and row.attempts < row.max_attempts:
            row.status = "retrying"
            row.next_attempt_at = _now() + timedelta(seconds=settings.mail_retry_backoff_seconds * 2 ** (row.attempts - 1))
        else:
            row.status, row.next_attempt_at = "failed", None
    log.info("mail delivery id=%s status=%s attempts=%s code=%s", row.id, row.status, row.attempts, row.error_code or "-")
    return row.status


def process_queue(limit: int = 50, now: datetime | None = None) -> dict:
    """Send what is due. Each row is claimed with an atomic UPDATE, so two workers can never send the same row."""
    now = now or _now()
    out = {"attempted": 0, "sent": 0, "outbox": 0, "retrying": 0, "failed": 0, "not_configured": 0}
    with SessionLocal() as db:
        db.execute(update(models.EmailDelivery).where(models.EmailDelivery.status == "sending",
                                                      models.EmailDelivery.updated_at < now - STUCK_AFTER)
                   .values(status="retrying", next_attempt_at=now))
        db.commit()
        due = select(models.EmailDelivery.id).where(models.EmailDelivery.status.in_(("queued", "retrying")))
        ids = [i for (i,) in db.execute(due.order_by(models.EmailDelivery.id).limit(limit * 2)).all()]
        for rid in ids:
            if out["attempted"] >= limit:
                break
            row = db.get(models.EmailDelivery, rid)
            if row and row.status == "retrying" and _aware(row.next_attempt_at) and _aware(row.next_attempt_at) > now:
                continue
            claimed = db.execute(update(models.EmailDelivery).where(models.EmailDelivery.id == rid,
                                 models.EmailDelivery.status.in_(("queued", "retrying"))).values(status="sending", updated_at=now))
            db.commit()
            if claimed.rowcount != 1:
                continue
            row = db.get(models.EmailDelivery, rid)
            db.refresh(row)
            res = deliver_row(db, row)
            db.commit()
            out["attempted"] += 1
            out[res] = out.get(res, 0) + 1
    return out
