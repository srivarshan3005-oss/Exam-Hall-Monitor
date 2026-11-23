"""Public student portal API (served to /portal/).

Everything here is read-only, rate limited and built from real stored records only:

* GET /api/portal/notices                      published exam dates/sessions + public announcements
* GET /api/portal/lookup/{register_number}     the student's PUBLISHED seats with the extra detail the portal shows
* GET /api/portal/seatmap/{register_number}    seat-number map of the student's own hall (no other student's identity)

Privacy rules (identical to /api/lookup, which is left unchanged):
* only PUBLISHED examinations / PUBLISHED + approved VSB records are ever returned;
* hall location is returned only for administrator-verified halls;
* the student's name is returned only when PUBLIC_SHOW_NAMES=true;
* the seat map lists seat NUMBERS and whether each is taken - never a name or a register number;
* nothing is invented: a field that is not stored is simply absent.
"""
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import doc_models as dm, models
from ..config import settings
from ..database import get_db
from ..deps_ip import client_ip
from ..notifications import local_tz
from ..ratelimit import limiter
from ..services_allocation import session_of
from ..vsb_alloc import visibility as vis
from .campus import public_announcements
from .students import find_student, parse_register, note_miss, public_guard, public_source_records, public_student, verified_location

router = APIRouter(prefix="/api/portal", tags=["Public student portal"])
MAX_MAP_SEATS = 600


def _iso(d) -> str | None:
    return d.isoformat() if d else None


def _natural(label: str):
    """Sort 2 before 10, and 'A2' before 'A10'."""
    digits = "".join(c for c in label if c.isdigit())
    return (0, int(digits), label) if digits else (1, 0, label)


def _term_semester(db: Session, exam: models.Exam) -> int | None:
    term = db.get(models.ExamTerm, exam.term_id) if exam.term_id else None
    if term and term.semester_no:
        return term.semester_no
    subject = db.get(models.Subject, exam.subject_id) if exam.subject_id else None
    return subject.semester if subject else None


def _subject_name(db: Session, exam: models.Exam) -> str | None:
    subject = db.get(models.Subject, exam.subject_id) if exam.subject_id else None
    if subject is None and exam.subject_code:
        subject = db.scalar(select(models.Subject).where(func.upper(models.Subject.code) == exam.subject_code.upper()))
    return subject.name if subject else None


# ----------------------------------------------------------------------------- notices
@router.get("/notices")
def notices(request: Request, db: Session = Depends(get_db)):
    """Published examination dates (with FN/AN sessions) and public announcements for the portal banner."""
    ok, retry = limiter.check_and_record(f"pubn:{client_ip(request)}", 120, 60)
    if not ok:
        raise HTTPException(429, "Too many requests. Please wait and try again.", headers={"Retry-After": str(retry)})
    today = datetime.now(local_tz()).date().isoformat()
    by_date: dict[str, dict[str, dict]] = {}

    def bucket(date_s: str, sess: str) -> dict:
        return by_date.setdefault(date_s, {}).setdefault(sess, {"session": sess, "exams": 0, "allotments": 0,
                                                                "start_time": None, "end_time": None, "_times": set()})

    exam_counts = dict(db.execute(select(models.Allotment.exam_id, func.count()).group_by(models.Allotment.exam_id)).all())
    for e in db.scalars(select(models.Exam).where(models.Exam.status == "published")).all():
        b = bucket(e.exam_date, session_of(e.start_time))
        b["exams"] += 1
        b["allotments"] += exam_counts.get(e.id, 0)
        b["_times"].add((e.start_time, e.end_time))
    v_counts = dict(db.execute(select(dm.VsbAllocRecord.batch_id, func.count()).where(
        vis.public_filter())
        .group_by(dm.VsbAllocRecord.batch_id)).all())
    for batch in db.scalars(select(dm.VsbAllocBatch).where(dm.VsbAllocBatch.status == "published")).all():
        b = bucket(batch.exam_date.isoformat(), batch.session)
        b["exams"] += 1
        b["allotments"] += v_counts.get(batch.id, 0)

    dates, past = [], 0
    for date_s in sorted(by_date):
        if date_s < today:
            past += 1
            continue
        sessions = []
        for sess in sorted(by_date[date_s]):
            b = by_date[date_s][sess]
            times = b.pop("_times")
            if len(times) == 1:                       # show a time only when every record agrees on it
                b["start_time"], b["end_time"] = next(iter(times))
            sessions.append(b)
        dates.append({"date": date_s, "sessions": sessions})
    return {"today": today, "dates": dates, "past_dates": past,
            "announcements": public_announcements(db)[:5], "college_name": settings.college_name}


# ----------------------------------------------------------------------------- lookup
@router.get("/lookup/{register_number}")
def portal_lookup(register_number: str, request: Request, db: Session = Depends(get_db)):
    ip = public_guard(request)
    reg = parse_register(register_number, ip)
    s = find_student(db, reg)
    if not s:
        note_miss(ip)
        raise HTTPException(404, "No matching student record")
    entries: list[dict] = []
    rows = db.execute(select(models.Allotment, models.Exam).join(models.Exam, models.Exam.id == models.Allotment.exam_id)
                      .where(models.Allotment.student_id == s.id, models.Exam.status == "published")
                      .order_by(models.Exam.exam_date, models.Exam.start_time)).all()
    for a, e in rows:
        item = {"kind": "allotment", "ref": e.id, "exam": e.title, "subject_code": e.subject_code,
                "subject_name": _subject_name(db, e), "semester": _term_semester(db, e), "date": e.exam_date,
                "session": session_of(e.start_time), "start_time": e.start_time, "end_time": e.end_time,
                "hall": a.hall, "seat": a.seat, "seat_map": True}
        loc = verified_location(db, a.hall)
        if loc:
            item["location"] = loc
        entries.append(item)
    from .vsb_alloc import published_for_student
    if settings.vsb_public_lookup:
        batch_ids = {(b.exam_date.isoformat(), b.session, b.exam_name): b.id for b in db.scalars(
            select(dm.VsbAllocBatch).where(dm.VsbAllocBatch.status == "published")).all()}
        for v in published_for_student(db, s):
            ref = batch_ids.get((v["date"], v["session"], v["exam"]))
            item = {"kind": "vsb", "ref": ref, "exam": v["exam"], "subject_code": v["subject_code"],
                    "subject_name": v["subject"], "date": v["date"], "session": v["session"],
                    "hall": v["hall"], "seat": v["seat"], "seat_map": bool(ref and v["hall"] and v["seat"]),
                    "verification_status": v["verification_status"], "verification_label": v["verification_label"],
                    "source": v["source"], "verify_note": v["verify_note"], "published_at": v["published_at"],
                    "pdf_pages": [{**{k: pg[k] for k in ("source", "page", "label", "official_url")},
                                   "preview_url": f"/api/portal/pdf-page/{reg}?ref={ref}&source={pg['source']}"}
                                  for pg in v["pdf_pages"]] if ref else []}
            loc = verified_location(db, v["hall"] or "")
            if loc:
                item["location"] = loc
            entries.append(item)
    entries.sort(key=lambda x: (x["date"] or "", x["session"] or "", x["subject_code"] or ""))
    # Unpublished allotments are deliberately NOT counted or mentioned: an unauthenticated caller must not learn that one exists.
    return {"student": public_student(s), "entries": entries, "verification_note": vis.UNAVAILABLE_NOTE,
            "source_documents": public_source_records(db, reg), "college_name": settings.college_name}


# ----------------------------------------------------------------------------- seat map
@router.get("/seatmap/{register_number}")
def seatmap(register_number: str, request: Request, kind: Literal["allotment", "vsb"] = Query(...),
            ref: int = Query(..., ge=1), db: Session = Depends(get_db)):
    """Seat-number map of the hall of ONE of the caller's own published allotments."""
    ip = public_guard(request)
    reg = parse_register(register_number, ip)
    s = find_student(db, reg)
    if not s:
        note_miss(ip)
        raise HTTPException(404, "No matching student record")
    if kind == "allotment":
        row = db.execute(select(models.Allotment, models.Exam).join(models.Exam, models.Exam.id == models.Allotment.exam_id).where(
            models.Allotment.student_id == s.id, models.Allotment.exam_id == ref, models.Exam.status == "published")).first()
        if not row:
            raise HTTPException(404, "No published allotment found")
        a, e = row
        hall_code, mine = a.hall, a.seat
        taken = [x for x in db.scalars(select(models.Allotment.seat).where(
            models.Allotment.exam_id == ref, models.Allotment.hall == hall_code)).all() if x]
        head = {"exam": e.title, "date": e.exam_date, "session": session_of(e.start_time)}
    else:
        row = db.execute(select(dm.VsbAllocRecord, dm.VsbAllocBatch).join(dm.VsbAllocBatch, dm.VsbAllocBatch.id == dm.VsbAllocRecord.batch_id).where(
            dm.VsbAllocRecord.student_id == s.id, dm.VsbAllocRecord.batch_id == ref, vis.seat_public_filter(),
            dm.VsbAllocBatch.status == "published")).first()
        if not row or not row[0].hall or not row[0].seat:
            raise HTTPException(404, "No published allotment found")
        r, b = row
        hall_code, mine = r.hall, r.seat
        taken = [x for x in db.scalars(select(dm.VsbAllocRecord.seat).where(
            dm.VsbAllocRecord.batch_id == ref, dm.VsbAllocRecord.hall == hall_code, vis.seat_public_filter())).all() if x]
        head = {"exam": b.exam_name, "date": b.exam_date.isoformat(), "session": b.session}

    hall = db.scalar(select(dm.Hall).where(func.upper(func.trim(dm.Hall.code)) == hall_code.upper()))
    inventory: list[str] = []
    capacity = None
    if hall is not None and hall.verified:
        capacity = hall.capacity
        inventory = [x.seat_label for x in db.scalars(select(models.HallSeat).where(
            models.HallSeat.hall_id == hall.id, models.HallSeat.active == True)).all()]  # noqa: E712
    taken_set = {t.strip().upper() for t in taken}
    mine_key = mine.strip().upper()
    if inventory:
        labels, layout = sorted(set(inventory) | {mine}, key=_natural), "hall_inventory"
    else:
        labels, layout = sorted(set(taken) | {mine}, key=_natural), "allotted_seats_only"
    shown = labels[:MAX_MAP_SEATS]
    if mine not in shown:
        shown = shown[:MAX_MAP_SEATS - 1] + [mine]
    seats = [{"l": lab, "s": "yours" if lab.strip().upper() == mine_key else
              ("taken" if lab.strip().upper() in taken_set else "vacant")} for lab in shown]
    out = {"kind": kind, "ref": ref, "hall": hall_code, "your_seat": mine, "layout_source": layout, "seats": seats,
           "truncated": len(labels) > len(shown), "taken_count": len(taken_set), "capacity": capacity,
           "vacant_count": sum(1 for x in seats if x["s"] == "vacant") if inventory else None, **head}
    loc = verified_location(db, hall_code)
    if loc:
        out["location"] = loc
    out["note"] = ("Seats are listed in seat-number order. The physical row/column layout of the room is not stored, "
                   "so none is drawn." + ("" if inventory else " Only allotted seats are listed because this hall has no seat inventory."))
    return out


# ----------------------------------------------------------------------------- official PDF page preview
@router.get("/pdf-page/{register_number}")
def pdf_page(register_number: str, request: Request, ref: int = Query(..., ge=1), source: Literal["hall", "seat"] = Query(...),
             db: Session = Depends(get_db)):
    """PNG of the ORIGINAL, UNMASKED page of the official hall/seat PDF that lists THIS student (see vsb_live/render.py; the
    searched number is highlighted by a separate overlay, nothing is covered). Same visibility rules as the lookup: published + approved + verified; the seat sheet only when
    FULLY_VERIFIED. Any failure is a plain 404 so the endpoint reveals nothing about unpublished allocations."""
    import json
    from fastapi.responses import Response
    from ..vsb_live import render
    from . import docproc
    ip = public_guard(request)
    reg = parse_register(register_number, ip)
    s = find_student(db, reg)
    if not s:
        note_miss(ip)
        raise HTTPException(404, "No matching student record")
    cond = vis.seat_public_filter() if source == "seat" else vis.public_filter()
    row = db.execute(select(dm.VsbAllocRecord, dm.VsbAllocBatch).join(dm.VsbAllocBatch, dm.VsbAllocBatch.id == dm.VsbAllocRecord.batch_id).where(
        dm.VsbAllocRecord.student_id == s.id, dm.VsbAllocRecord.batch_id == ref, cond, dm.VsbAllocBatch.status == "published")).first()
    if not row or row[0].register_number != reg:
        raise HTTPException(404, "No published page found")
    r, b = row
    try:
        page = (json.loads(r.detail) if r.detail else {}).get("hall_page" if source == "hall" else "seat_page")
    except ValueError:
        page = None
    vid = b.hall_version_id if source == "hall" else b.seat_version_id
    v = db.get(dm.DocumentVersion, vid) if vid else None
    if v is None or not isinstance(page, int) or page < 0:
        raise HTTPException(404, "No published page found")
    try:
        png = render.render_original_page(docproc.stored_path(v), page, reg, highlight=True, cache_key=v.sha256).png
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 - unreadable PDF, page out of range, ...
        raise HTTPException(404, "No published page found")
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
                                                          "X-Original-Page": "unmasked"})
