"""Background worker: scheduled announcements, reminders, and the e-mail queue.

One daemon thread inside the API process (no extra service to install). Everything it does is idempotent:
notifications are unique per (user, event key) and e-mail rows are claimed atomically, so running two
workers, restarting the server or calling run_cycle() by hand cannot duplicate a message.
Disable with SCHEDULER_ENABLED=false and run `python -m app.cli run-scheduler` from your own scheduler instead."""
import logging, threading
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from . import delivery, models, notifications as nt
from .config import settings
from .database import SessionLocal
from .services_allocation import eligible_students

log = logging.getLogger("exam_monitor.scheduler")
_wake = threading.Event()
_stop = threading.Event()
_thread: threading.Thread | None = None
_startup_pending = True          # the first cycle after the server starts always scans (VSB_SCAN_ON_STARTUP)


def kick() -> None:
    """Ask the worker to run now (new e-mail was queued). No-op when the worker is not running."""
    if _thread is not None and _thread.is_alive():
        _wake.set()


def run_announcements(db: Session, now: datetime) -> dict:
    sent = reminded = 0
    for a in db.scalars(select(models.Announcement).where(models.Announcement.published == True)).all():  # noqa: E712
        if a.notify and a.notified_at is None and nt.dispatch_announcement(db, a, now) is not None:
            sent += 1
        aware = lambda d: d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)  # noqa: E731
        if (a.remind_at and a.reminded_at is None and aware(a.remind_at) <= now and nt.announcement_visible(a, now)):
            a.reminded_at = now
            nt.notify_users(db, nt.announcement_audience(db, a), "announcement_reminder",
                            {"announcement_title": a.title, "announcement_body": a.body},
                            event_key=f"announcement:{a.id}:reminder", priority=a.priority or "normal",
                            link="#/notifications", created_by=a.created_by)
            reminded += 1
    db.commit()
    return {"announcements_sent": sent, "announcement_reminders": reminded}


def run_exam_reminders(db: Session, now: datetime) -> dict:
    """For every published exam that starts within a configured window, remind each eligible student once.
    The text states the real time left, so an exam published late is never told '24 hours' falsely."""
    if not settings.reminders_enabled:
        return {"exam_reminders": 0}
    hours = settings.reminder_hours
    if not hours:
        return {"exam_reminders": 0}
    created = 0
    horizon = max(hours)
    for exam in db.scalars(select(models.Exam).where(models.Exam.status == "published")).all():
        start = nt.exam_start_utc(exam)
        if not start or start <= now or start - now > timedelta(hours=horizon):
            continue
        applicable = [h for h in hours if start - now <= timedelta(hours=h)]
        if not applicable:
            continue
        h = min(applicable)                                     # most imminent window already open
        seats = {a.student_id: a for a in db.scalars(select(models.Allotment).where(models.Allotment.exam_id == exam.id))}
        studs = eligible_students(db, exam)
        users = nt._users_for_students(db, [s.id for s in studs])
        left = nt.human_left(start - now)

        def ctx(u, exam=exam, seats=seats, left=left):
            a = seats.get(u.student_id)
            return nt.exam_ctx(exam) | {"time_left": left, "seat_line": f"Hall {a.hall}, Seat {a.seat}" if a else
                                        "Your seat will be shown in the portal once allotted."}
        key = f"reminder:exam:{exam.id}:{h}h:{exam.exam_date}T{exam.start_time}"
        r = nt.notify_users(db, users, "exam_reminder", ctx, event_key=key, link="#/my-exams")
        created += r["in_app"]
        db.commit()
    return {"exam_reminders": created}


def run_cycle(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    out: dict = {}
    with SessionLocal() as db:
        out |= run_announcements(db, now)
        out |= run_exam_reminders(db, now)
    out["email"] = delivery.process_queue(now=now)
    try:
        global _startup_pending
        from . import vsb_sources
        with SessionLocal() as vdb:
            due = vsb_sources.scheduled_due(vdb, now, startup=_startup_pending)
        if due:
            _startup_pending = False
            from .vsb_live import cycle
            r = cycle.run_cycle(trigger="scheduler", actor="scheduler")
            out["vsb_cycle"] = {k: r.get(k) for k in ("status", "discovery", "ingest", "index", "notifications")}
    except RuntimeError:
        out["vsb_cycle"] = {"status": "busy"}
    except Exception:
        log.exception("scheduled VSB cycle failed")
        out["vsb_cycle"] = {"error": "cycle failed; inspect server logs"}
    try:
        from .data_management import run_scheduled_backup
        backup = run_scheduled_backup(now)
        if backup:
            out["database_backup"] = {"filename": backup["filename"], "size_bytes": backup["size_bytes"]}
    except Exception:
        log.exception("scheduled database backup failed")
        out["database_backup"] = {"error": "backup failed; inspect server logs"}
    return out


def _loop() -> None:
    while not _stop.is_set():
        _wake.wait(timeout=settings.scheduler_interval_seconds)
        _wake.clear()
        if _stop.is_set():
            break
        try:
            run_cycle()
        except Exception:  # noqa: BLE001 - the worker must survive any single failure
            log.exception("scheduler cycle failed")


def start() -> None:
    global _thread
    if not settings.scheduler_enabled or (_thread is not None and _thread.is_alive()):
        return
    global _startup_pending
    _startup_pending = True
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="exam-monitor-scheduler", daemon=True)
    _thread.start()
    _wake.set()


def stop() -> None:
    global _thread
    _stop.set()
    _wake.set()
    if _thread is not None:
        _thread.join(timeout=5)
    _thread = None
