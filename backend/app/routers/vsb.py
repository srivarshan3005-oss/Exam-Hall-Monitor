"""Official V.S.B. Engineering College sources: confirmed links, PDF discovery/download, status and history.

Public: the confirmed official links and the titles/dates/addresses of discovered notices (no register data).
Admin + staff: discovery runs, downloads, link status, run and document history.
Downloaded PDFs are normal document versions, so processing/OCR/review/seating-import use the existing pages.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import audit, doc_models as dm, models, vsb_sources as vs
from ..config import settings
from ..database import get_db
from ..deps import require_roles
from . import docproc

router = APIRouter(prefix="/api/vsb", tags=["Official VSB sources"])
STAFF = ("admin", "staff")
iso = lambda d: d.isoformat() if d else None  # noqa: E731


class DiscoverRequest(BaseModel):
    download: bool = True
    auto_process: bool = True
    stage_drafts: bool = True        # after processing, parse new hall/seat PDFs into DRAFT allocation batches (never published)


def _link_dict(db: Session, l: dm.VsbSourceLink) -> dict:
    doc = db.get(dm.OfficialDocument, l.document_id) if l.document_id else None
    ver = vs._latest_version(db, doc.id) if doc else None
    return {"id": l.id, "url": l.url, "title": l.title, "kind": l.doc_kind, "exam_date": iso(l.exam_date), "session": l.session,
            "listing_url": l.listing_url, "upload_month": l.upload_month, "published_at": iso(l.published_at),
            "first_seen_at": iso(l.first_seen_at), "last_seen_at": iso(l.last_seen_at), "still_listed": l.still_listed,
            "status": l.download_status, "http_status": l.last_http_status, "error": l.last_error,
            "failure_count": l.failure_count, "last_attempt_at": iso(l.last_attempt_at),
            "last_downloaded_at": iso(l.last_downloaded_at), "note": l.note, "auto_download": l.doc_kind in vs.AUTO_KINDS,
            "document_id": doc.id if doc else None,
            "version": None if not ver else {"version_id": ver.id, "version_no": ver.version_no, "pages": ver.page_count,
                                              "size_bytes": ver.size_bytes, "sha256": ver.sha256[:16],
                                              "downloaded_at": iso(ver.downloaded_at),
                                              "processing_status": ver.processing_status, "review_status": ver.review_status}}


# ----------------------------------------------------------------------------- public
@router.get("/official-links")
def official_links(db: Session = Depends(get_db)):
    """Confirmed official pages plus the notice/timetable/allotment PDFs currently listed on the college's page.
    Addresses point to the college's own website; nothing is hosted or altered here."""
    rows = db.scalars(select(dm.VsbSourceLink).where(
        dm.VsbSourceLink.still_listed == True, dm.VsbSourceLink.doc_kind.in_(vs.AUTO_KINDS))  # noqa: E712
        .order_by(dm.VsbSourceLink.exam_date.desc(), dm.VsbSourceLink.id.desc()).limit(60)).all()
    return {"sources": [{k: s[k] for k in ("key", "title", "url", "purpose")} for s in vs.CONFIRMED_SOURCES],
            "documents": [{"title": r.title, "kind": r.doc_kind, "exam_date": iso(r.exam_date), "session": r.session,
                           "url": r.url, "upload_month": r.upload_month} for r in rows],
            "note": "Links open the V.S.B. Engineering College website. Always check the official page for the latest notices."}


# ----------------------------------------------------------------------------- staff
@router.get("/sources")
def sources(db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    last = db.scalar(select(dm.VsbCrawlRun).order_by(dm.VsbCrawlRun.id.desc()).limit(1))
    counts = dict(db.execute(select(dm.VsbSourceLink.download_status, func.count()).group_by(dm.VsbSourceLink.download_status)).all())
    return {"sources": vs.CONFIRMED_SOURCES, "listing_page": vs.coe_page_url(), "allowed_hosts": sorted(vs.ALLOWED_HOSTS),
            "auto_discover_enabled": settings.vsb_auto_discover_enabled,
            "auto_discover_interval_minutes": settings.poll_minutes,
            "auto_discover_interval_hours": round(settings.poll_minutes / 60, 2),
            "auto_download_kinds": list(vs.AUTO_KINDS), "counts": counts,
            "last_run": vs.run_dict(last) if last else None}


@router.get("/links")
def links(kind: str = Query("", max_length=30), status: str = Query("", max_length=20), q: str = Query("", max_length=80),
          listed: str = Query("", max_length=5), limit: int = Query(200, ge=1, le=500), offset: int = Query(0, ge=0),
          db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    stmt = select(dm.VsbSourceLink)
    if kind:
        stmt = stmt.where(dm.VsbSourceLink.doc_kind == kind)
    if status:
        stmt = stmt.where(dm.VsbSourceLink.download_status == status)
    if listed in ("yes", "no"):
        stmt = stmt.where(dm.VsbSourceLink.still_listed == (listed == "yes"))
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(dm.VsbSourceLink.title.ilike(like), dm.VsbSourceLink.url.ilike(like)))
    stmt = stmt.order_by(dm.VsbSourceLink.exam_date.desc(), dm.VsbSourceLink.id.desc()).limit(limit).offset(offset)
    return [_link_dict(db, l) for l in db.scalars(stmt).all()]


@router.get("/runs")
def runs(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db),
         user: models.User = Depends(require_roles(*STAFF))):
    return [vs.run_dict(r) for r in db.scalars(select(dm.VsbCrawlRun).order_by(dm.VsbCrawlRun.id.desc()).limit(limit)).all()]


def _auto_process(request: Request, user: models.User):
    def cb(db: Session, v: dm.DocumentVersion):
        try:
            docproc.process(v.id, request, force_ocr=False, lang="", db=db, user=user)
        except HTTPException as e:
            return f"Version #{v.id} was downloaded; automatic processing reported: {e.detail}"
        return None
    return cb


@router.post("/discover")
def discover(data: DiscoverRequest, request: Request, db: Session = Depends(get_db),
             user: models.User = Depends(require_roles(*STAFF))):
    """Read the official COE page now; record links; download relevant new/changed PDFs; optionally process them."""
    try:
        run = vs.run_discovery(db, actor=user.username, trigger="manual", download=data.download,
                               auto_process=_auto_process(request, user) if data.download and data.auto_process else None)
    except RuntimeError:
        raise HTTPException(409, "A discovery or download is already running. Try again in a moment.")
    if data.download and data.auto_process and data.stage_drafts and run["status"] != "failed":
        from ..vsb_alloc import service as alloc_svc
        try:
            run["staging"] = alloc_svc.auto_stage(db, user.username)
        except Exception:  # noqa: BLE001 - staging problems must not hide the discovery result
            db.rollback()
            run["staging"] = ["Draft staging failed; use the VSB allocation page to build a batch manually."]
    audit.record(db, user.username, "vsb.discover", str(run["id"]),
                 {k: run[k] for k in ("status", "links_found", "new_links", "downloaded", "duplicates", "unavailable", "failed")},
                 request, user.role)
    db.commit()
    return run


@router.post("/links/{link_id}/download")
def download(link_id: int, request: Request, process: bool = Query(False), db: Session = Depends(get_db),
             user: models.User = Depends(require_roles(*STAFF))):
    """Download (or re-check) one listed PDF, including kinds that are not downloaded automatically."""
    try:
        link, outcome, v = vs.download_one(db, link_id, user.username)
    except LookupError:
        raise HTTPException(404, "Link not found")
    except ValueError:
        raise HTTPException(422, "This address is not on the official college host")
    except RuntimeError:
        raise HTTPException(409, "A discovery or download is already running. Try again in a moment.")
    note = None
    if process and v is not None and outcome == "downloaded":
        note = _auto_process(request, user)(db, v)
    audit.record(db, user.username, "vsb.download", str(link_id), {"outcome": outcome, "url": link.url}, request, user.role)
    db.commit()
    return {"outcome": outcome, "process_note": note, "link": _link_dict(db, db.get(dm.VsbSourceLink, link_id))}


@router.get("/links/{link_id}/history")
def history(link_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    l = db.get(dm.VsbSourceLink, link_id)
    if not l:
        raise HTTPException(404, "Link not found")
    versions, events = [], []
    if l.document_id:
        for v in db.scalars(select(dm.DocumentVersion).where(dm.DocumentVersion.document_id == l.document_id)
                            .order_by(dm.DocumentVersion.version_no.desc())).all():
            versions.append({"version_id": v.id, "version_no": v.version_no, "sha256": v.sha256, "size_bytes": v.size_bytes,
                             "pages": v.page_count, "downloaded_at": iso(v.downloaded_at), "is_current": v.is_current,
                             "http_last_modified": v.http_last_modified, "processing_status": v.processing_status,
                             "review_status": v.review_status})
            for e in db.scalars(select(dm.DocumentEvent).where(dm.DocumentEvent.version_id == v.id)
                                .order_by(dm.DocumentEvent.id.desc()).limit(50)).all():
                events.append({"version_id": v.id, "event": e.event, "actor": e.actor, "detail": e.detail, "at": iso(e.created_at)})
    events.sort(key=lambda e: e["at"] or "", reverse=True)
    return {"link": _link_dict(db, l), "versions": versions, "events": events[:100]}
