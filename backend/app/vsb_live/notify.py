"""Optional e-mail notifications for register numbers on an administrator-managed watch list.

* One message per (watch, allotment fingerprint): the unique constraint makes duplicates impossible, even across restarts.
* A revised allotment has a new fingerprint, so it produces exactly one new "revised" message.
* The message states the status honestly (hall only / conflict / manual verification) and attaches the official PDF and the
  ORIGINAL UNMASKED page image (highlighted for the watched number).
* SMTP settings come from the environment (see mailer.py). Failure never raises into the lookup or the scan: it is recorded
  with a clear, redacted message and retried with back-off while the error is transient.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import doc_models as dm, mailer
from ..config import settings
from . import render

log = logging.getLogger("exam_monitor.notify")
EMAIL_OK = __import__("re").compile(r"^[^@\s\r\n]{1,64}@[^@\s\r\n]{1,190}\.[A-Za-z]{2,}$")


def now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(d):
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


def valid_email(v: str) -> bool:
    return bool(EMAIL_OK.match((v or "").strip()))


def enqueue_events(db: Session, events: list) -> int:
    """Create pending notifications for new/revised allotments of watched register numbers. Idempotent."""
    if not settings.notify_watch_enabled or not events:
        return 0
    created = 0
    for ev in events:
        a = db.get(dm.LiveAllotment, ev.allotment_id)
        if a is None:
            continue
        for w in db.scalars(select(dm.LiveWatch).where(dm.LiveWatch.register_number == a.register_number,
                                                       dm.LiveWatch.active == True)).all():  # noqa: E712
            if db.scalar(select(dm.LiveNotification.id).where(dm.LiveNotification.watch_id == w.id,
                                                              dm.LiveNotification.fingerprint == a.fingerprint)):
                continue
            kind = "revised" if ev.kind == "revised" else "new"
            subj = f"VSB exam allotment {'REVISED' if kind == 'revised' else 'published/updated'}: {a.exam_date.isoformat()} {a.session}"
            db.add(dm.LiveNotification(watch_id=w.id, allotment_id=a.id, event_type=kind, fingerprint=a.fingerprint,
                                       subject=subj[:200], status="pending", attempts=0, next_attempt_at=now()))
            created += 1
    db.commit()
    return created


def _body(a: dm.LiveAllotment, kind: str) -> str:
    from .pipeline import weekday_name
    lines = [f"Register number: {a.register_number}",
             f"Exam date: {a.exam_date.strftime('%d-%m-%Y')} ({weekday_name(a.exam_date)})  Session: {a.session}"]
    t = settings.session_time_map.get(a.session)
    if t:
        lines.append(f"Session time (configured, not printed in the PDF): {t}")
    lines.append(f"Subject: {a.subject_code or '-'} {a.subject_name or ''}".rstrip())
    if a.status == "CONFIRMED":
        lines += [f"Hall: {a.hall}", f"Seat: {a.seat}", "Hall and seat were found in both official PDFs and agree."]
    elif a.status == "HALL_ONLY":
        lines += [f"Hall: {a.hall}", "Seat: not published / not verified yet (the seating chart does not list this number)."]
    elif a.status == "SEAT_ONLY":
        lines += [f"Seat sheet hall: {a.hall or '-'}", f"Seat: {a.seat or '-'}", "The hall-allotment list has not been matched yet."]
    elif a.status == "CONFLICT":
        lines.append("CONFLICT: the official documents disagree. Do not rely on a single value; check the attached pages "
                     "and the Controller of Examinations.")
    else:
        lines.append("MANUAL VERIFICATION REQUIRED: the automatic reading was uncertain. Check the attached original page.")
    if kind == "revised":
        lines.append("This replaces an earlier allotment for the same examination.")
    lines += ["", f"Source: {a.hall_filename or a.seat_filename or '-'}", "Attached: the official PDF and the original, unmasked page image.",
              "Always verify against the official notice of the Controller of Examinations."]
    return "\n".join(lines)


def _attach(msg: EmailMessage, db: Session, a: dm.LiveAllotment) -> None:
    from ..routers import docproc
    seen = set()
    for vid, page in ((a.hall_version_id, a.hall_page), (a.seat_version_id, a.seat_page)):
        v = db.get(dm.DocumentVersion, vid) if vid else None
        if v is None or v.id in seen:
            continue
        seen.add(v.id)
        path = docproc.stored_path(v)
        try:
            doc = db.get(dm.OfficialDocument, v.document_id)
            fn = (doc.original_filename if doc and doc.original_filename else f"allotment-{v.id}.pdf")
            if path.stat().st_size <= 15 * 1024 * 1024:
                msg.add_attachment(path.read_bytes(), maintype="application", subtype="pdf", filename=fn[:120])
            if page is not None:
                r = render.render_original_page(path, page, a.register_number, highlight=True, cache_key=v.sha256)
                msg.add_attachment(r.png, maintype="image", subtype="png", filename=f"original-page-{v.id}-p{page + 1}.png")
        except Exception:  # noqa: BLE001 - an attachment problem must not stop the text from going out
            log.warning("attachment skipped for version %s", v.id)


def process_due(db: Session, at: datetime | None = None, limit: int = 25) -> dict:
    at = at or now()
    sent = failed = retried = 0
    rows = db.scalars(select(dm.LiveNotification).where(
        dm.LiveNotification.status == "pending", or_(dm.LiveNotification.next_attempt_at.is_(None), dm.LiveNotification.next_attempt_at <= at))
        .order_by(dm.LiveNotification.id).limit(limit)).all()
    for n in rows:
        w, a = db.get(dm.LiveWatch, n.watch_id), (db.get(dm.LiveAllotment, n.allotment_id) if n.allotment_id else None)
        if w is None or a is None or not w.active:
            n.status, n.last_error = "skipped", "watch removed/disabled or allotment no longer available"
            continue
        try:
            msg = mailer.build_message(w.email, n.subject, _body(a, n.event_type))
            _attach(msg, db, a)
            status, code, err, _mode = mailer.attempt_message(msg)
        except Exception as e:  # noqa: BLE001
            status, code, err = "error:transient", "unexpected", "Unexpected error: " + type(e).__name__
        n.attempts = (n.attempts or 0) + 1
        if status in ("sent", "outbox"):
            n.status, n.sent_at, n.last_error, n.next_attempt_at = status, now(), None, None
            sent += 1
        elif status == "error:transient" and n.attempts < max(1, settings.mail_max_attempts):
            n.last_error = mailer.redact(err or code or "temporary failure")
            n.next_attempt_at = at + timedelta(seconds=settings.mail_retry_backoff_seconds * (2 ** (n.attempts - 1)))
            retried += 1
        else:
            n.status, n.last_error, n.next_attempt_at = "failed", mailer.redact(err or code or "delivery failed"), None
            failed += 1
    db.commit()
    return {"sent": sent, "failed": failed, "retry_scheduled": retried}


def send_test(to: str) -> dict:
    if not valid_email(to):
        return {"status": "invalid", "message": "Enter a valid e-mail address."}
    msg = mailer.build_message(to, "Exam Monitor - e-mail test", "This is a test message from Exam Monitor Ultimate. "
                                                                  "If you can read it, e-mail delivery works. No allotment data is included.")
    status, code, err, mode = mailer.attempt_message(msg)
    ok = status in ("sent", "outbox")
    return {"status": "sent" if ok else "failed", "mode": mode, "code": code,
            "message": ("Test message delivered to the " + ("SMTP server." if mode == "smtp" else "development outbox folder.")) if ok
            else mailer.redact(err or "delivery failed")}
