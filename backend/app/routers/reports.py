"""Seating charts, allocation lists and summaries (admin/staff only; never public).

Every list endpoint takes ?format=json|csv|xlsx|pdf. Student names appear here because these are
internal administrative reports; the public lookup endpoints are unchanged and name-free by default.
"""
from collections import Counter
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .. import models, doc_models
from ..allocation_engine import natural_key
from ..database import get_db
from ..deps import require_roles, department_scope
from ..exports import tabular, seating_pdf
from ..services_allocation import (eligible_students, overlapping_exams, usable_seats, session_of)

router = APIRouter(prefix="/api/admin/reports", tags=["Seating plans and reports"])
STAFF = ("admin", "staff")
Fmt = Query("json", pattern="^(json|csv|xlsx|pdf)$")


def _exam(db: Session, exam_id: int) -> models.Exam:
    e = db.get(models.Exam, exam_id)
    if not e:
        raise HTTPException(status_code=404, detail="Examination not found")
    return e


def _meta(e: models.Exam) -> list[str]:
    return [f"Examination: {e.title} ({e.subject_code})", f"Date: {e.exam_date}  {e.start_time}-{e.end_time} ({session_of(e.start_time)})"]


def _respond(fmt, name, title, columns, rows, meta, payload):
    if fmt == "json":
        return payload
    return tabular(fmt, name, title, columns, rows, meta)


def _rows(db: Session, exam: models.Exam):
    return db.execute(select(models.Allotment, models.Student).join(models.Student, models.Student.id == models.Allotment.student_id)
                      .where(models.Allotment.exam_id == exam.id)).all()


# ----------------------------------------------------------------------------- overview and summary
def _counts(db: Session, e: models.Exam) -> dict:
    eligible = eligible_students(db, e)
    allotted = db.scalar(select(func.count()).select_from(models.Allotment).where(models.Allotment.exam_id == e.id)) or 0
    halls = db.scalar(select(func.count(func.distinct(models.Allotment.hall))).where(models.Allotment.exam_id == e.id)) or 0
    ids = {s.id for s in eligible}
    seated = set(db.scalars(select(models.Allotment.student_id).where(models.Allotment.exam_id == e.id)).all())
    return {"exam_id": e.id, "title": e.title, "subject_code": e.subject_code, "exam_date": e.exam_date,
            "start_time": e.start_time, "end_time": e.end_time, "status": e.status,
            "eligible_students": len(eligible), "allotted": allotted, "halls_used": halls,
            "unallocated": len(ids - seated)}


@router.get("/exams")
def exams_overview(format: str = Fmt, status: str = Query("", max_length=20), q: str = Query("", max_length=80),
                   db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    """Examination-wise report: one line per examination with allocation totals."""
    stmt = select(models.Exam).order_by(models.Exam.exam_date.desc(), models.Exam.start_time).limit(300)
    if status:
        stmt = stmt.where(models.Exam.status == status)
    if q:
        stmt = stmt.where(models.Exam.title.icontains(q, autoescape=True) | models.Exam.subject_code.icontains(q.upper(), autoescape=True))
    data = [_counts(db, e) for e in db.scalars(stmt).all()]
    cols = ["Exam", "Subject", "Date", "Start", "End", "Status", "Eligible", "Allotted", "Unallocated", "Halls"]
    rows = [[d["title"], d["subject_code"], d["exam_date"], d["start_time"], d["end_time"], d["status"],
             d["eligible_students"], d["allotted"], d["unallocated"], d["halls_used"]] for d in data]
    return _respond(format, "examination_allocation_summary", "Examination-wise allocation summary", cols, rows, [], data)


@router.get("/exams/{exam_id}/summary")
def exam_summary(exam_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    e = _exam(db, exam_id)
    out = _counts(db, e)
    out["by_department"] = dict(Counter(s.department for _, s in _rows(db, e)))
    return out


# ----------------------------------------------------------------------------- allocation lists
@router.get("/exams/{exam_id}/allocations")
def allocation_list(exam_id: int, format: str = Fmt, order: str = Query("register", pattern="^(register|hall|name)$"),
                    hall: str = Query("", max_length=100), department: str = Query("", max_length=100),
                    q: str = Query("", max_length=60), db: Session = Depends(get_db),
                    user: models.User = Depends(require_roles(*STAFF))):
    """order=register gives the register-number-wise list; order=hall the hall/seat-wise list."""
    e = _exam(db, exam_id)
    items = []
    scope = department_scope(user)
    if scope:
        department = scope
    for a, s in _rows(db, e):
        if hall and a.hall.strip().upper() != hall.strip().upper():
            continue
        if department and s.department.strip().casefold() != department.strip().casefold():
            continue
        if q and q.casefold() not in s.register_number.casefold() and q.casefold() not in s.full_name.casefold():
            continue
        items.append({"register_number": s.register_number, "student_name": s.full_name, "department": s.department,
                      "year": s.year, "hall": a.hall, "seat": a.seat})
    keys = {"register": lambda x: x["register_number"], "name": lambda x: x["student_name"].casefold(),
            "hall": lambda x: (x["hall"], natural_key(x["seat"]))}
    items.sort(key=keys[order])
    cols = ["Register number", "Name", "Department", "Year", "Hall", "Seat"]
    rows = [[i["register_number"], i["student_name"], i["department"], i["year"], i["hall"], i["seat"]] for i in items]
    return _respond(format, f"allocation_{e.subject_code}_{e.exam_date}_{order}", f"Allocation list ({order}-wise)",
                    cols, rows, _meta(e), items)


@router.get("/exams/{exam_id}/unallocated")
def unallocated_report(exam_id: int, format: str = Fmt, db: Session = Depends(get_db),
                       user: models.User = Depends(require_roles(*STAFF))):
    e = _exam(db, exam_id)
    seated = set(db.scalars(select(models.Allotment.student_id).where(models.Allotment.exam_id == e.id)).all())
    sims = [o.id for o in overlapping_exams(db, e)]
    busy = set(db.scalars(select(models.Allotment.student_id).where(models.Allotment.exam_id.in_(sims))).all()) if sims else set()
    items = [{"register_number": s.register_number, "student_name": s.full_name, "department": s.department,
              "year": s.year, "reason": "Seated in a simultaneous examination" if s.id in busy else "No seat allotted"}
             for s in eligible_students(db, e) if s.id not in seated]
    cols = ["Register number", "Name", "Department", "Year", "Reason"]
    rows = [[i["register_number"], i["student_name"], i["department"], i["year"], i["reason"]] for i in items]
    return _respond(format, f"unallocated_{e.subject_code}_{e.exam_date}", "Unallocated students", cols, rows, _meta(e), items)


# ----------------------------------------------------------------------------- hall occupancy and seating charts
def _hall_record(db: Session, code: str):
    return db.scalar(select(doc_models.Hall).where(func.upper(func.trim(doc_models.Hall.code)) == code.strip().upper()))


@router.get("/exams/{exam_id}/halls")
def hall_occupancy(exam_id: int, format: str = Fmt, include_unused: bool = False, db: Session = Depends(get_db),
                   user: models.User = Depends(require_roles("admin", "staff", "invigilator"))):
    """Capacity and occupancy per hall for this examination's time slot."""
    e = _exam(db, exam_id)
    mine: dict[str, list] = {}
    for a, s in _rows(db, e):
        mine.setdefault(a.hall.strip().upper(), []).append(s)
    sims = [o.id for o in overlapping_exams(db, e)]
    other = Counter(h.strip().upper() for h in db.scalars(select(models.Allotment.hall).where(
        models.Allotment.exam_id.in_(sims))).all()) if sims else Counter()
    codes = set(mine)
    if include_unused:
        codes |= {h.code.strip().upper() for h in db.scalars(select(doc_models.Hall).where(doc_models.Hall.verified == True)).all()}  # noqa: E712
    items = []
    for code in sorted(codes):
        h = _hall_record(db, code)
        seats = usable_seats(db, h) if h else ()
        capacity = len(seats) if seats else (h.capacity if h and h.capacity else None)
        used = len(mine.get(code, []))
        free = None if capacity is None else max(capacity - used - other.get(code, 0), 0)
        depts = Counter(s.department for s in mine.get(code, []))
        items.append({"hall": code, "verified": bool(h and h.verified), "capacity": capacity, "allocated": used,
                      "used_by_simultaneous_exams": other.get(code, 0), "free": free,
                      "occupancy_percent": round(100 * used / capacity, 1) if capacity else None,
                      "departments": dict(depts)})
    cols = ["Hall", "Capacity", "Allocated", "Other exams", "Free", "Occupancy %", "Departments"]
    rows = [[i["hall"], i["capacity"] if i["capacity"] is not None else "n/a", i["allocated"], i["used_by_simultaneous_exams"],
             i["free"] if i["free"] is not None else "n/a", i["occupancy_percent"] if i["occupancy_percent"] is not None else "n/a",
             ", ".join(f"{k}: {v}" for k, v in i["departments"].items())] for i in items]
    return _respond(format, f"hall_occupancy_{e.subject_code}_{e.exam_date}", "Hall occupancy and capacity", cols, rows, _meta(e), items)


def _chart(db: Session, e: models.Exam, code: str, mine: list, other: set[str]) -> dict:
    h = _hall_record(db, code)
    taken = {a.seat.strip().upper(): (a, s) for a, s in mine if a.hall.strip().upper() == code}
    labels: list[tuple[str, bool]] = []     # (label, usable)
    if h:
        all_seats = db.scalars(select(models.HallSeat).where(models.HallSeat.hall_id == h.id)).all()
        usable = {x.upper() for x in usable_seats(db, h)}
        labels = [(x.seat_label, x.seat_label.upper() in usable) for x in sorted(all_seats, key=lambda z: natural_key(z.seat_label))]
    known = {x[0].upper() for x in labels}
    labels += [(a.seat, True) for k, (a, _) in sorted(taken.items(), key=lambda z: natural_key(z[0])) if k not in known]
    seats = []
    for label, ok in labels:
        k = label.upper()
        if k in taken:
            a, s = taken[k]
            seats.append({"seat": label, "state": "allocated", "register_number": s.register_number,
                          "student_name": s.full_name, "department": s.department})
        elif k in other:
            seats.append({"seat": label, "state": "other_exam", "register_number": None, "student_name": None, "department": None})
        elif not ok:
            seats.append({"seat": label, "state": "unavailable", "register_number": None, "student_name": None, "department": None})
        else:
            seats.append({"seat": label, "state": "free", "register_number": None, "student_name": None, "department": None})
    free = sum(1 for s in seats if s["state"] == "free")
    return {"hall": code, "capacity": len([s for s in seats if s["state"] != "unavailable"]),
            "allocated": len(taken), "free": free, "seats": seats}


@router.get("/exams/{exam_id}/seating")
def seating_chart(exam_id: int, format: str = Fmt, hall: str = Query("", max_length=100),
                  columns: int = Query(5, ge=1, le=12), db: Session = Depends(get_db),
                  user: models.User = Depends(require_roles("admin", "staff", "invigilator"))):
    """Hall-wise seating chart(s). Without ?hall= every hall with allocations is included (one PDF page each)."""
    if department_scope(user):
        raise HTTPException(status_code=403, detail="Hall seating charts list students of every department; "
                                                    "ask an examination administrator, or use the department allocation list")
    e = _exam(db, exam_id)
    mine = _rows(db, e)
    codes = sorted({a.hall.strip().upper() for a, _ in mine})
    if hall:
        code = hall.strip().upper()
        if code not in codes and not _hall_record(db, code):
            raise HTTPException(status_code=404, detail="Hall not found")
        codes = [code]
    if not codes:
        raise HTTPException(status_code=404, detail="No allocations exist for this examination")
    sims = [o.id for o in overlapping_exams(db, e)]
    other = {(h.strip().upper(), s.strip().upper()) for h, s in db.execute(select(models.Allotment.hall, models.Allotment.seat).where(
        models.Allotment.exam_id.in_(sims))).all()} if sims else set()
    charts = [_chart(db, e, c, mine, {s for h, s in other if h == c}) for c in codes]
    if format == "json":
        return charts
    if format == "pdf":
        return seating_pdf(f"seating_{e.subject_code}_{e.exam_date}", f"Seating plan - {e.title}", _meta(e)[1:], charts, columns)
    rows = [[c["hall"], s["seat"], s["register_number"] or "", s["student_name"] or "", s["department"] or "", s["state"]]
            for c in charts for s in c["seats"]]
    return tabular(format, f"seating_{e.subject_code}_{e.exam_date}", "Seating plan",
                   ["Hall", "Seat", "Register number", "Name", "Department", "State"], rows, _meta(e))


# ----------------------------------------------------------------------------- student-wise seat lookup (staff view)
@router.get("/students/seats")
def student_seat_lookup(q: str = Query(..., min_length=2, max_length=60), db: Session = Depends(get_db),
                        user: models.User = Depends(require_roles(*STAFF))):
    """Staff lookup by register number or name, across ALL examinations (including unpublished).
    The public student lookup is separate and still shows published examinations only."""
    students = db.scalars(select(models.Student).where(
        models.Student.register_number.icontains(q.strip().upper(), autoescape=True)
        | models.Student.full_name.icontains(q.strip(), autoescape=True),
        *([func.lower(models.Student.department) == department_scope(user).lower()] if department_scope(user) else [])
        ).order_by(models.Student.register_number).limit(25)).all()
    out = []
    for s in students:
        rows = db.execute(select(models.Allotment, models.Exam).join(models.Exam, models.Exam.id == models.Allotment.exam_id)
                          .where(models.Allotment.student_id == s.id).order_by(models.Exam.exam_date, models.Exam.start_time)).all()
        out.append({"register_number": s.register_number, "student_name": s.full_name, "department": s.department,
                    "year": s.year, "active": s.active,
                    "allotments": [{"exam_id": e.id, "exam": e.title, "subject_code": e.subject_code, "date": e.exam_date,
                                    "start_time": e.start_time, "status": e.status, "hall": a.hall, "seat": a.seat}
                                   for a, e in rows]})
    return out
