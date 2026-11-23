"""Phase 4: seating-allotment PDF import. extract -> human correction -> admin approval -> plan -> confirmed import.
Nothing is written to `allotments` without an explicit administrator confirmation, and only for rows that are
approved, complete and pass the same checks as a manual allocation."""
import hashlib, json
from datetime import datetime, timezone
from .. import notifications as notify
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .. import models, doc_models, audit
from ..database import get_db
from ..dbutil import lock_allocation
from ..deps import require_roles
from ..seating_parse import parse_pages, find_internal_conflicts
from ..services_allocation import check_placement, log_history

router = APIRouter(prefix="/api/admin/seating-import", tags=["Seating-allotment PDF import"])
STAFF = ("admin", "staff")
ADMIN = ("admin",)


class EntryEdit(BaseModel):
    register_number: str | None = Field(default=None, pattern=r"^\d{12}$")
    hall: str | None = Field(default=None, max_length=100)
    seat: str | None = Field(default=None, max_length=30)
    reason: str = Field(min_length=3, max_length=200)


class Review(BaseModel):
    decision: str = Field(pattern="^(approve|reject|reset)$")


class PlanRequest(BaseModel):
    exam_id: int = Field(ge=1)


class ImportRequest(BaseModel):
    exam_id: int = Field(ge=1)
    signature: str = Field(min_length=64, max_length=64)
    confirm: bool
    skip_blocked: bool = False


def _version(db: Session, vid: int) -> doc_models.DocumentVersion:
    v = db.get(doc_models.DocumentVersion, vid)
    if not v:
        raise HTTPException(status_code=404, detail="Document version not found")
    return v


def _dict(e: models.SeatingEntry, problems: list[str] | None = None) -> dict:
    return {"id": e.id, "row_no": e.row_no, "page_number": e.page_index + 1, "register_number": e.register_number,
            "hall": e.hall, "seat": e.seat, "raw_text": e.raw_text, "source": e.source, "confidence": e.confidence,
            "flags": json.loads(e.flags or "[]"), "edited": e.edited, "review_status": e.review_status,
            "reviewed_by": e.reviewed_by, "needs_attention": bool(json.loads(e.flags or "[]")) and not e.edited,
            "conflicts": problems or []}


def _entries(db, vid):
    return db.scalars(select(models.SeatingEntry).where(models.SeatingEntry.version_id == vid)
                      .order_by(models.SeatingEntry.row_no)).all()


def _conflicts(entries):
    live = [{"id": e.id, "register_number": e.register_number, "hall": e.hall, "seat": e.seat}
            for e in entries if e.review_status != "rejected"]
    return find_internal_conflicts(live)


@router.post("/{version_id}/extract")
def extract(version_id: int, request: Request, db: Session = Depends(get_db),
            user: models.User = Depends(require_roles(*STAFF))):
    """Read register numbers, halls and seats from the page text already extracted for this document
    (run 'Process' / OCR in the Document processing panel first). Re-running replaces un-imported rows."""
    _version(db, version_id)
    pages = db.scalars(select(doc_models.PdfPage).where(doc_models.PdfPage.version_id == version_id)
                       .order_by(doc_models.PdfPage.page_index)).all()
    if not pages or not any(p.text_content for p in pages):
        raise HTTPException(status_code=409, detail="No page text yet. Process the document (with OCR if it is scanned) first.")
    if db.scalar(select(func.count()).select_from(models.SeatingEntry).where(
            models.SeatingEntry.version_id == version_id, models.SeatingEntry.review_status == "imported")):
        raise HTTPException(status_code=409, detail="Rows of this document were already imported; extraction is locked")
    for old in _entries(db, version_id):
        db.delete(old)
    db.flush()
    rows = parse_pages([{"index": p.page_index, "text": p.text_content or "", "method": p.extraction_method,
                         "confidence": p.ocr_confidence} for p in pages])
    for r in rows[:20000]:
        db.add(models.SeatingEntry(version_id=version_id, row_no=r.row_no, page_index=r.page_index,
                                   register_number=r.register_number, hall=r.hall, seat=r.seat, raw_text=r.raw_text,
                                   source=r.source, confidence=r.confidence, flags=json.dumps(r.flags)))
    audit.record(db, user.username, "seating_import.extracted", str(version_id), {"rows": len(rows)}, request, user.role)
    db.commit()
    return {"rows": len(rows), "needing_attention": sum(1 for r in rows if r.flags)}


@router.get("/{version_id}")
def review(version_id: int, only_uncertain: bool = False, limit: int = Query(500, ge=1, le=2000),
           db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    _version(db, version_id)
    entries = _entries(db, version_id)
    conf = _conflicts(entries)
    items = [_dict(e, conf.get(e.id)) for e in entries]
    if only_uncertain:
        items = [i for i in items if i["needs_attention"] or i["conflicts"]]
    counts = {}
    for e in entries:
        counts[e.review_status] = counts.get(e.review_status, 0) + 1
    return {"version_id": version_id, "total": len(entries), "counts": counts,
            "uncertain": sum(1 for e in entries if (json.loads(e.flags or "[]") and not e.edited) or e.id in conf),
            "entries": items[:limit]}


@router.patch("/entries/{entry_id}")
def edit_entry(entry_id: int, data: EntryEdit, request: Request, db: Session = Depends(get_db),
               user: models.User = Depends(require_roles(*ADMIN))):
    e = db.get(models.SeatingEntry, entry_id)
    if not e:
        raise HTTPException(status_code=404, detail="Row not found")
    if e.review_status == "imported":
        raise HTTPException(status_code=409, detail="Row already imported")
    before = {"register_number": e.register_number, "hall": e.hall, "seat": e.seat}
    for k in ("register_number", "hall", "seat"):
        v = getattr(data, k)
        if v is not None:
            setattr(e, k, v.strip().upper() if k != "register_number" else v)
    e.edited, e.review_status = True, "pending"
    e.reviewed_by = e.reviewed_at = None
    audit.record(db, user.username, "seating_import.entry_edited", str(e.id),
                 {"before": before, "after": {"register_number": e.register_number, "hall": e.hall, "seat": e.seat},
                  "reason": data.reason}, request, user.role)
    db.commit()
    return _dict(e)


@router.post("/entries/{entry_id}/review")
def review_entry(entry_id: int, data: Review, request: Request, db: Session = Depends(get_db),
                 user: models.User = Depends(require_roles(*ADMIN))):
    e = db.get(models.SeatingEntry, entry_id)
    if not e:
        raise HTTPException(status_code=404, detail="Row not found")
    if e.review_status == "imported":
        raise HTTPException(status_code=409, detail="Row already imported")
    if data.decision == "approve":
        if not e.hall or not e.seat:
            raise HTTPException(status_code=422, detail="Hall and seat are required before a row can be approved; correct it first")
        e.review_status = "approved"
    else:
        e.review_status = "rejected" if data.decision == "reject" else "pending"
    e.reviewed_by, e.reviewed_at = user.username, datetime.now(timezone.utc)
    audit.record(db, user.username, f"seating_import.entry_{data.decision}", str(e.id), None, request, user.role)
    db.commit()
    return _dict(e)


@router.post("/{version_id}/approve-confident")
def approve_confident(version_id: int, request: Request, db: Session = Depends(get_db),
                      user: models.User = Depends(require_roles(*ADMIN))):
    """Bulk-approve only rows that are complete, unflagged, text-layer and conflict-free. Everything else stays for review."""
    _version(db, version_id)
    entries = _entries(db, version_id)
    conf, n = _conflicts(entries), 0
    for e in entries:
        if (e.review_status == "pending" and e.hall and e.seat and not json.loads(e.flags or "[]")
                and e.source == "text" and e.id not in conf):
            e.review_status, e.reviewed_by, e.reviewed_at = "approved", user.username, datetime.now(timezone.utc)
            n += 1
    audit.record(db, user.username, "seating_import.bulk_approved", str(version_id), {"rows": n}, request, user.role)
    db.commit()
    return {"approved": n}


def _plan(db: Session, version_id: int, exam: models.Exam) -> dict:
    entries = _entries(db, version_id)
    conf = _conflicts(entries)
    items, ready = [], []
    for e in entries:
        if e.review_status == "imported":
            continue
        reasons = list(conf.get(e.id, []))
        if e.review_status != "approved":
            state = "rejected" if e.review_status == "rejected" else "not_approved"
        else:
            state = "ready"
            s = db.scalar(select(models.Student).where(models.Student.register_number == e.register_number))
            if not s:
                reasons.append("no student with this register number")
            else:
                existing = db.scalar(select(models.Allotment).where(models.Allotment.exam_id == exam.id,
                                                                    models.Allotment.student_id == s.id))
                if existing:
                    same = existing.hall.upper() == (e.hall or "").upper() and existing.seat.upper() == (e.seat or "").upper()
                    reasons.append("already allotted the same seat" if same else
                                   f"conflicts with existing allotment {existing.hall}/{existing.seat}")
                else:
                    try:
                        check_placement(db, exam, s, e.hall or "", e.seat or "")
                    except HTTPException as ex:
                        reasons.append(str(ex.detail) if isinstance(ex.detail, str) else json.dumps(ex.detail)[:200])
            if reasons:
                state = "blocked"
        items.append({**_dict(e, conf.get(e.id)), "state": state, "reasons": reasons})
        if state == "ready":
            ready.append(e)
    sig = hashlib.sha256(json.dumps([exam.id, [(e.id, e.register_number, e.hall, e.seat) for e in ready]]).encode()).hexdigest()
    summary = {k: sum(1 for i in items if i["state"] == k) for k in ("ready", "blocked", "not_approved", "rejected")}
    return {"exam_id": exam.id, "summary": summary, "signature": sig, "items": items[:1000]}


@router.post("/{version_id}/preview")
def preview(version_id: int, data: PlanRequest, db: Session = Depends(get_db),
            user: models.User = Depends(require_roles(*STAFF))):
    _version(db, version_id)
    exam = db.get(models.Exam, data.exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Examination not found")
    return _plan(db, version_id, exam)


@router.post("/{version_id}/import", status_code=201)
def do_import(version_id: int, data: ImportRequest, request: Request, db: Session = Depends(get_db),
              user: models.User = Depends(require_roles(*ADMIN))):
    lock_allocation(db)   # no other seat decision may interleave with the re-check + import below
    _version(db, version_id)
    exam = db.get(models.Exam, data.exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Examination not found")
    if not data.confirm:
        raise HTTPException(status_code=422, detail="Administrator confirmation is required")
    plan = _plan(db, version_id, exam)
    if plan["signature"] != data.signature:
        raise HTTPException(status_code=409, detail="The data changed since the preview; review it again")
    if plan["summary"]["blocked"] and not data.skip_blocked:
        raise HTTPException(status_code=409, detail="Some approved rows are blocked; fix them or choose to skip them")
    ready = {i["id"] for i in plan["items"] if i["state"] == "ready"}
    if not ready:
        raise HTTPException(status_code=409, detail="No approved, conflict-free rows to import")
    created = 0
    new_events: list[dict] = []
    for e in _entries(db, version_id):
        if e.id not in ready:
            continue
        s = db.scalar(select(models.Student).where(models.Student.register_number == e.register_number))
        a = models.Allotment(student_id=s.id, exam_id=exam.id, hall=e.hall.strip().upper(), seat=e.seat.strip(), source="pdf")
        db.add(a)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="A seat was taken meanwhile; nothing was imported. Preview again.")
        log_history(db, exam_id=exam.id, student_id=s.id, action="created", actor=user.username, allotment_id=a.id,
                    new=(a.hall, a.seat), reason=f"seating PDF import (document version {version_id})")
        e.review_status, e.imported_allotment_id = "imported", a.id
        created += 1
        new_events.append({"student_id": s.id, "kind": "allocated", "hall": a.hall, "seat": a.seat})
    audit.record(db, user.username, "seating_import.imported", str(version_id),
                 {"exam_id": exam.id, "created": created, "skipped_blocked": plan["summary"]["blocked"]}, request, user.role)
    db.commit()
    notify.notify_seat_events(db, exam, new_events, user.username)
    return {"created": created, "skipped_blocked": plan["summary"]["blocked"]}
