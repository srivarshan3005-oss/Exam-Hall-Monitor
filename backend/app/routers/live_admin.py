"""Management dashboard API for the live system (administrators and staff; writes need the administrator role).

Monitoring overview, manual scan, source health, discovered/downloaded PDFs, processing queue, failures, duplicates, parsed
allotment records, hall-location management, e-mail watch list + notification history + test e-mail, optional Supabase sync,
system health and a combined activity log. Every write is audited.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import audit, doc_models as dm, mailer, models, vsb_sources as vs
from ..config import settings
from ..database import SessionLocal, get_db
from ..deps import require_roles
from ..vsb_live import cycle, locations, notify, pipeline, render, supabase_sync
from .public_live import serialize

router = APIRouter(prefix="/api/live", tags=["Live monitoring (management)"])
STAFF, ADMIN = ("admin", "staff"), ("admin",)
iso = lambda d: d.isoformat() if d else None  # noqa: E731


def _counts(db: Session, col) -> dict:
    return {k: v for k, v in db.execute(select(col, func.count()).group_by(col)).all()}


# ----------------------------------------------------------------------------- overview / scan
@router.get("/overview")
def overview(db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    runs = db.scalars(select(dm.VsbCrawlRun).order_by(dm.VsbCrawlRun.id.desc()).limit(10)).all()
    return {
        **cycle.status_summary(db), "poll_minutes": settings.poll_minutes, "auto_enabled": settings.vsb_auto_discover_enabled,
        "poll_range_minutes": [settings.VSB_POLL_MIN_MINUTES, settings.VSB_POLL_MAX_MINUTES],
        "links": _counts(db, dm.VsbSourceLink.download_status),
        "documents": db.scalar(select(func.count()).select_from(dm.OfficialDocument).where(
            dm.OfficialDocument.doc_kind.in_(("hall_allotment", "seating_allotment")))) or 0,
        "queue": _counts(db, dm.LiveIngest.status),
        "allotments": {k: v for k, v in db.execute(select(dm.LiveAllotment.status, func.count()).where(
            dm.LiveAllotment.is_current == True).group_by(dm.LiveAllotment.status)).all()},  # noqa: E712
        "students_indexed": db.scalar(select(func.count(func.distinct(dm.LiveAllotment.register_number))).where(
            dm.LiveAllotment.is_current == True)) or 0,  # noqa: E712
        "revisions": db.scalar(select(func.count()).select_from(dm.LiveAllotment).where(dm.LiveAllotment.revision > 1)) or 0,
        "notifications": _counts(db, dm.LiveNotification.status),
        "runs": [vs.run_dict(r) for r in runs],
        "supabase": {"enabled": settings.supabase_enabled},
    }


_scan_state: dict = {"running": False, "last": None}


@router.post("/scan")
def scan_now(request: Request, wait: bool = Query(False), rebuild: bool = Query(False), db: Session = Depends(get_db),
             user: models.User = Depends(require_roles(*STAFF))):
    """Run Scan Now. By default it runs in the background (the website stays responsive); wait=true runs it inline."""
    audit.record(db, user.username, "live.scan", "manual", {"wait": wait}, request, user.role)
    db.commit()
    actor = user.username
    if wait:
        try:
            return cycle.run_cycle(trigger="manual", actor=actor, rebuild=rebuild)
        except RuntimeError:
            raise HTTPException(409, "A scan is already running. Try again in a moment.")
    if _scan_state["running"]:
        raise HTTPException(409, "A scan is already running.")

    def work():
        _scan_state["running"] = True
        try:
            _scan_state["last"] = cycle.run_cycle(trigger="manual", actor=actor, rebuild=rebuild)
        except RuntimeError:
            _scan_state["last"] = {"status": "busy"}
        except Exception:  # noqa: BLE001
            _scan_state["last"] = {"status": "failed", "message": "scan crashed; see server log"}
        finally:
            _scan_state["running"] = False
    threading.Thread(target=work, name="manual-scan", daemon=True).start()
    return {"started": True, "message": "Scan started. Refresh the overview in a minute."}


@router.get("/scan/state")
def scan_state(user: models.User = Depends(require_roles(*STAFF))):
    return {"running": _scan_state["running"], "last": _scan_state["last"]}


@router.post("/rebuild")
def rebuild(request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_roles(*ADMIN))):
    """Re-parse every current hall/seat PDF and rebuild the searchable index (history kept)."""
    pipeline.forget()
    for row in db.scalars(select(dm.LiveIngest).where(dm.LiveIngest.status == "failed")).all():
        row.status, row.attempts = "pending", 0
    db.commit()
    ing = pipeline.ingest_pending(db)
    r = pipeline.rebuild_index(db)
    audit.record(db, user.username, "live.rebuild", "index", r["stats"], request, user.role)
    db.commit()
    return {"ingest": ing, "index": r["stats"]}


# ----------------------------------------------------------------------------- sources, documents, queue
@router.get("/sources")
def sources(db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    return [{"method": h.method, "url": h.url, "status": h.last_status, "last_attempt_at": iso(h.last_attempt_at),
             "last_success_at": iso(h.last_success_at), "error": h.last_error, "http_status": h.last_http_status,
             "consecutive_failures": h.consecutive_failures, "items_found": h.items_found}
            for h in db.scalars(select(dm.VsbSourceHealth).order_by(dm.VsbSourceHealth.method, dm.VsbSourceHealth.url)).all()]


@router.get("/documents")
def documents(kind: str = Query("", max_length=30), status: str = Query("", max_length=20), limit: int = Query(100, ge=1, le=300),
              db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    stmt = select(dm.OfficialDocument).where(dm.OfficialDocument.doc_kind.in_(("hall_allotment", "seating_allotment")))
    if kind:
        stmt = stmt.where(dm.OfficialDocument.doc_kind == kind)
    out = []
    for d in db.scalars(stmt.order_by(dm.OfficialDocument.id.desc()).limit(limit)).all():
        versions = db.scalars(select(dm.DocumentVersion).where(dm.DocumentVersion.document_id == d.id)
                              .order_by(dm.DocumentVersion.version_no.desc())).all()
        cur = versions[0] if versions else None
        ing = db.scalar(select(dm.LiveIngest).where(dm.LiveIngest.version_id == cur.id)) if cur else None
        row = {"document_id": d.id, "title": d.title, "kind": d.doc_kind, "url": d.source_url, "filename": d.original_filename,
               "exam_date": iso(d.exam_date), "session": d.session, "versions": len(versions),
               "version_id": cur.id if cur else None, "sha256": cur.sha256 if cur else None, "pages": cur.page_count if cur else None,
               "downloaded_at": iso(cur.downloaded_at) if cur else None, "ingest_status": ing.status if ing else "not_processed",
               "ingest_error": ing.error if ing else None, "records": ing.records if ing else 0, "ocr_pages": ing.ocr_pages if ing else 0}
        if status and row["ingest_status"] != status:
            continue
        out.append(row)
    return out


@router.get("/queue")
def queue(db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    rows = db.scalars(select(dm.LiveIngest).order_by(dm.LiveIngest.id.desc()).limit(100)).all()
    return [{"id": r.id, "version_id": r.version_id, "status": r.status, "attempts": r.attempts, "records": r.records, "pages": r.pages,
             "ocr_pages": r.ocr_pages, "error": r.error, "created_at": iso(r.created_at), "processed_at": iso(r.processed_at)} for r in rows]


@router.post("/queue/{ingest_id}/retry")
def retry(ingest_id: int, request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_roles(*ADMIN))):
    r = db.get(dm.LiveIngest, ingest_id)
    if r is None:
        raise HTTPException(404, "Not found")
    r.status, r.attempts, r.error = "pending", 0, None
    pipeline.forget(r.version_id)
    audit.record(db, user.username, "live.retry", str(ingest_id), None, request, user.role)
    db.commit()
    return {"status": "pending"}


@router.get("/failures")
def failures(db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    links = db.scalars(select(dm.VsbSourceLink).where(dm.VsbSourceLink.download_status.in_(("failed", "blocked", "unavailable")))
                       .order_by(dm.VsbSourceLink.last_attempt_at.desc()).limit(100)).all()
    ing = db.scalars(select(dm.LiveIngest).where(dm.LiveIngest.status == "failed").order_by(dm.LiveIngest.id.desc()).limit(100)).all()
    return {"downloads": [{"url": l.url, "status": l.download_status, "http": l.last_http_status, "error": l.last_error,
                           "failures": l.failure_count, "last_attempt_at": iso(l.last_attempt_at)} for l in links],
            "processing": [{"id": r.id, "version_id": r.version_id, "error": r.error, "attempts": r.attempts} for r in ing]}


@router.get("/duplicates")
def duplicates(db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    links = db.scalars(select(dm.VsbSourceLink).where(dm.VsbSourceLink.download_status == "duplicate")
                       .order_by(dm.VsbSourceLink.id.desc()).limit(100)).all()
    return [{"url": l.url, "title": l.title, "note": l.note, "document_id": l.document_id} for l in links]


# ----------------------------------------------------------------------------- records
@router.get("/allotments")
def allotments(q: str = Query("", max_length=40), status: str = Query("", max_length=20), date: str = Query("", max_length=10),
               current: bool = True, limit: int = Query(100, ge=1, le=300), offset: int = Query(0, ge=0),
               db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    stmt = select(dm.LiveAllotment)
    if current:
        stmt = stmt.where(dm.LiveAllotment.is_current == True)  # noqa: E712
    if q.strip():
        stmt = stmt.where(or_(dm.LiveAllotment.register_number.like(f"%{q.strip().upper()}%"),
                              dm.LiveAllotment.subject_code.ilike(f"%{q.strip()}%"), dm.LiveAllotment.hall.ilike(f"%{q.strip()}%")))
    if status:
        stmt = stmt.where(dm.LiveAllotment.status == status)
    if date:
        stmt = stmt.where(dm.LiveAllotment.exam_date == date)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(dm.LiveAllotment.exam_date.desc(), dm.LiveAllotment.id.desc()).limit(limit).offset(offset)).all()
    return {"total": total, "items": [serialize(db, a) | {"flags": a.flags, "confidence": a.confidence, "is_current": a.is_current}
                                      for a in rows]}


# ----------------------------------------------------------------------------- hall locations
class LocationIn(BaseModel):
    display_name: str | None = Field(None, max_length=150)
    building: str | None = Field(None, max_length=100)
    block: str | None = Field(None, max_length=50)
    floor: str | None = Field(None, max_length=20)
    room: str | None = Field(None, max_length=50)
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    directions: str | None = Field(None, max_length=2000)
    location_source: str | None = Field(None, max_length=300)
    entrance_id: int | None = None
    notes: str | None = Field(None, max_length=2000)
    verified: bool = False


class HallCreate(LocationIn):
    code: str = Field(min_length=1, max_length=100)


@router.get("/halls")
def halls(q: str = Query("", max_length=40), db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    stmt = select(dm.Hall)
    if q.strip():
        stmt = stmt.where(dm.Hall.code.ilike(f"%{q.strip()}%"))
    used = {h for (h,) in db.execute(select(dm.LiveAllotment.hall).where(dm.LiveAllotment.is_current == True,  # noqa: E712
                                                                          dm.LiveAllotment.hall.is_not(None)).distinct()).all()}
    out = [locations.hall_dict(db, h) | {"in_use": locations._norm(h.code) in {locations._norm(x) for x in used}}
           for h in db.scalars(stmt.order_by(dm.Hall.code)).all()]
    known = {locations._norm(h["code"]) for h in out}
    missing = sorted(x for x in used if locations._norm(x) not in known)
    return {"halls": out, "halls_in_documents_without_record": missing}


def _apply(db: Session, h: dm.Hall, data: LocationIn, user: models.User) -> None:
    fields = data.model_dump(exclude={"verified", "code"} if hasattr(data, "code") else {"verified"})
    if data.verified:
        if not (data.location_source or h.location_source):
            raise HTTPException(422, "A source (official document, notice or the person who confirmed it) is required to mark a hall verified.")
        if not any([data.building, data.block, data.floor, data.room, h.building, h.block, h.floor, h.room, data.latitude is not None]):
            raise HTTPException(422, "Enter at least one location detail before verifying.")
    if (data.latitude is None) != (data.longitude is None):
        raise HTTPException(422, "Latitude and longitude must be given together.")
    if data.entrance_id is not None:
        ent = db.get(dm.CampusPoint, data.entrance_id)
        if ent is None:
            raise HTTPException(422, "Unknown campus entrance")
    for k, v in fields.items():
        setattr(h, k, v.strip() if isinstance(v, str) and v.strip() else (None if isinstance(v, str) else v))
    h.verified = bool(data.verified)
    h.verified_by = user.username if data.verified else None
    h.verified_at = datetime.now(timezone.utc) if data.verified else None


@router.post("/halls", status_code=201)
def add_hall(data: HallCreate, request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_roles(*ADMIN))):
    code = " ".join(data.code.upper().split())
    if locations.find_hall(db, code):
        raise HTTPException(409, "This hall already exists")
    h = dm.Hall(code=code)
    db.add(h)
    db.flush()
    _apply(db, h, data, user)
    locations.record_change(db, h, user.username, "create", None, data.location_source)
    audit.record(db, user.username, "live.hall.create", code, None, request, user.role)
    db.commit()
    return locations.hall_dict(db, h)


@router.put("/halls/{hall_id}/location")
def edit_hall(hall_id: int, data: LocationIn, request: Request, db: Session = Depends(get_db),
              user: models.User = Depends(require_roles(*ADMIN))):
    h = db.get(dm.Hall, hall_id)
    if h is None:
        raise HTTPException(404, "Hall not found")
    before = locations.snapshot(h)
    _apply(db, h, data, user)
    locations.record_change(db, h, user.username, "verify" if data.verified else "edit", before, data.location_source)
    audit.record(db, user.username, "live.hall.location", h.code, {"verified": data.verified}, request, user.role)
    db.commit()
    return locations.hall_dict(db, h)


@router.get("/halls/{hall_id}/history")
def hall_history(hall_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    return [{"actor": r.actor, "action": r.action, "before": r.before, "after": r.after, "source": r.source, "at": iso(r.created_at)}
            for r in db.scalars(select(dm.HallLocationHistory).where(dm.HallLocationHistory.hall_id == hall_id)
                                .order_by(dm.HallLocationHistory.id.desc()).limit(50)).all()]


class PointIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: str = Field("entrance", pattern="^(entrance|landmark)$")
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    source: str | None = Field(None, max_length=300)
    notes: str | None = Field(None, max_length=1000)
    verified: bool = False


@router.get("/campus-points")
def points(db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    return [{"id": p.id, "name": p.name, "kind": p.kind, "latitude": p.latitude, "longitude": p.longitude, "verified": p.verified,
             "source": p.source, "notes": p.notes} for p in db.scalars(select(dm.CampusPoint).order_by(dm.CampusPoint.name)).all()]


@router.post("/campus-points", status_code=201)
def add_point(data: PointIn, request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_roles(*ADMIN))):
    if data.verified and (data.latitude is None or data.longitude is None or not data.source):
        raise HTTPException(422, "Verified points need coordinates and a source.")
    if db.scalar(select(dm.CampusPoint.id).where(dm.CampusPoint.name == data.name.strip())):
        raise HTTPException(409, "A point with this name exists")
    p = dm.CampusPoint(name=data.name.strip(), kind=data.kind, latitude=data.latitude, longitude=data.longitude, source=data.source,
                       notes=data.notes, verified=data.verified, verified_by=user.username if data.verified else None,
                       verified_at=datetime.now(timezone.utc) if data.verified else None)
    db.add(p)
    audit.record(db, user.username, "live.point.create", data.name, None, request, user.role)
    db.commit()
    return {"id": p.id}


@router.delete("/campus-points/{point_id}")
def del_point(point_id: int, request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_roles(*ADMIN))):
    p = db.get(dm.CampusPoint, point_id)
    if p is None:
        raise HTTPException(404, "Not found")
    db.delete(p)
    audit.record(db, user.username, "live.point.delete", p.name, None, request, user.role)
    db.commit()
    return {"deleted": True}


# ----------------------------------------------------------------------------- e-mail watch + notifications
class WatchIn(BaseModel):
    register_number: str = Field(min_length=6, max_length=20)
    email: str = Field(min_length=5, max_length=200)


@router.get("/watches")
def watches(db: Session = Depends(get_db), user: models.User = Depends(require_roles(*ADMIN))):
    return [{"id": w.id, "register_number": w.register_number, "email": w.email, "active": w.active, "created_by": w.created_by}
            for w in db.scalars(select(dm.LiveWatch).order_by(dm.LiveWatch.id.desc())).all()]


@router.post("/watches", status_code=201)
def add_watch(data: WatchIn, request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_roles(*ADMIN))):
    from ..regno import normalize_register_number
    try:
        reg = normalize_register_number(data.register_number)
    except ValueError:
        raise HTTPException(422, "Invalid register number")
    if not notify.valid_email(data.email):
        raise HTTPException(422, "Invalid e-mail address")
    email = data.email.strip().lower()
    if db.scalar(select(dm.LiveWatch.id).where(dm.LiveWatch.register_number == reg, dm.LiveWatch.email == email)):
        raise HTTPException(409, "This watch already exists")
    w = dm.LiveWatch(register_number=reg, email=email, created_by=user.username)
    db.add(w)
    audit.record(db, user.username, "live.watch.create", reg, None, request, user.role)   # the address itself is not written to the log
    db.commit()
    return {"id": w.id}


@router.delete("/watches/{watch_id}")
def del_watch(watch_id: int, request: Request, db: Session = Depends(get_db), user: models.User = Depends(require_roles(*ADMIN))):
    w = db.get(dm.LiveWatch, watch_id)
    if w is None:
        raise HTTPException(404, "Not found")
    db.delete(w)
    audit.record(db, user.username, "live.watch.delete", w.register_number, None, request, user.role)
    db.commit()
    return {"deleted": True}


@router.get("/notifications")
def notifications(db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    rows = db.execute(select(dm.LiveNotification, dm.LiveWatch).join(dm.LiveWatch, dm.LiveWatch.id == dm.LiveNotification.watch_id)
                      .order_by(dm.LiveNotification.id.desc()).limit(100)).all()
    mask = lambda e: (e[:1] + "***" + e[e.find("@"):]) if "@" in e else "***"  # noqa: E731
    return {"mail": mailer.config_status(),
            "items": [{"id": n.id, "register_number": w.register_number, "to": mask(w.email), "event": n.event_type, "subject": n.subject,
                       "status": n.status, "attempts": n.attempts, "error": n.last_error, "sent_at": iso(n.sent_at),
                       "created_at": iso(n.created_at)} for n, w in rows]}


class TestMail(BaseModel):
    to: str = Field(min_length=5, max_length=200)


@router.post("/notifications/test-email")
def test_email(data: TestMail, request: Request, user: models.User = Depends(require_roles(*ADMIN))):
    from ..ratelimit import limiter
    ok, retry = limiter.check_and_record(f"livetestmail:{user.username}", settings.test_email_per_hour, 3600)
    if not ok:
        raise HTTPException(429, "Too many test e-mails. Try again later.", headers={"Retry-After": str(retry)})
    r = notify.send_test(data.to)
    if r["status"] == "invalid":
        raise HTTPException(422, r["message"])
    return r


@router.post("/notifications/process")
def process_notifications(db: Session = Depends(get_db), user: models.User = Depends(require_roles(*ADMIN))):
    return notify.process_due(db)


# ----------------------------------------------------------------------------- cloud sync, health, logs
@router.post("/sync/supabase")
def sync_supabase(request: Request, all: bool = Query(False), db: Session = Depends(get_db), user: models.User = Depends(require_roles(*ADMIN))):
    r = supabase_sync.sync(db, force_all=all)
    audit.record(db, user.username, "live.sync", "supabase", {"status": r["status"], "records": r["records"]}, request, user.role)
    db.commit()
    return r


@router.get("/sync/log")
def sync_log(db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    return {"enabled": settings.supabase_enabled,
            "items": [{"id": r.id, "status": r.status, "records": r.records, "error": r.error, "started_at": iso(r.started_at),
                       "finished_at": iso(r.finished_at)} for r in db.scalars(select(dm.LiveSyncLog).order_by(dm.LiveSyncLog.id.desc()).limit(30)).all()]}


@router.get("/health")
def health(db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    from .. import doc_extract as dx, scheduler
    from ..dbcheck import current_revision
    from . import docproc
    storage_ok = True
    try:
        t = docproc.storage_dir() / ".write-test"
        t.write_bytes(b"x")
        t.unlink()
    except OSError:
        storage_ok = False
    return {"database": {"ok": True, "revision": current_revision() if callable(current_revision) else None,
                         "engine": db.bind.dialect.name if db.bind else None},
            "storage_writable": storage_ok, "ocr_available": dx.ocr_available(),
            "scheduler_running": bool(scheduler._thread is not None and scheduler._thread.is_alive()),
            "mail": mailer.config_status()["mode"], "supabase_enabled": settings.supabase_enabled,
            "preview_cache_version": settings.preview_cache_version, "poll_minutes": settings.poll_minutes,
            **cycle.status_summary(db)}


@router.get("/logs")
def logs(limit: int = Query(80, ge=1, le=300), db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    items = []
    for r in db.scalars(select(dm.VsbCrawlRun).order_by(dm.VsbCrawlRun.id.desc()).limit(limit)).all():
        items.append({"at": iso(r.started_at), "type": "scan", "level": "error" if r.status == "failed" else "info",
                      "text": f"{r.trigger} scan {r.status}: {r.links_found} links, {r.new_links} new, {r.downloaded} downloaded, "
                              f"{r.failed} failed. {r.message or ''}".strip()})
    for e in db.scalars(select(dm.DocumentEvent).order_by(dm.DocumentEvent.id.desc()).limit(limit)).all():
        items.append({"at": iso(e.created_at), "type": "document", "level": "info", "text": f"version #{e.version_id}: {e.event} ({e.actor})"})
    for a in db.scalars(select(models.AuditLog).where(models.AuditLog.action.like("live.%")).order_by(models.AuditLog.id.desc()).limit(limit)).all():
        items.append({"at": iso(a.created_at), "type": "audit", "level": "info", "text": f"{a.actor}: {a.action} {a.target}"})
    items.sort(key=lambda x: x["at"] or "", reverse=True)
    return items[:limit]
