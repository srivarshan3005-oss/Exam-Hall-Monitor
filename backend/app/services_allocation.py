"""Database-facing helpers shared by the exam, allotment and report routers.

Everything here is read-only except `log_history`, which only *adds* a row so the caller's
single commit stores the change, its audit line and its history row together (atomic).
"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from . import models, doc_models
from .allocation_engine import (Config, HallRec, StudentRec, Result, allocate, natural_key,
                                REASON_CAPACITY, REASON_RULES)


# ----------------------------------------------------------------------------- time helpers
def duration_minutes(start: str, end: str) -> int:
    sh, sm = map(int, start.split(":"))
    eh, em = map(int, end.split(":"))
    return (eh * 60 + em) - (sh * 60 + sm)


def session_of(start: str) -> str:
    """FN (forenoon) before 12:00, otherwise AN (afternoon)."""
    return "FN" if start < "12:00" else "AN"


def overlapping_exams(db: Session, exam: models.Exam) -> list[models.Exam]:
    """Other exams on the same date whose time window overlaps (half-open intervals)."""
    rows = db.scalars(select(models.Exam).where(models.Exam.exam_date == exam.exam_date,
                                                models.Exam.id != exam.id)).all()
    return [o for o in rows if exam.start_time < o.end_time and o.start_time < exam.end_time]


# ----------------------------------------------------------------------------- eligibility
def _n(v) -> str:
    return str(v or "").strip().casefold()


def load_audience(db: Session, exam_id: int):
    rules = db.scalars(select(models.ExamEligibilityRule).where(models.ExamEligibilityRule.exam_id == exam_id)).all()
    ov = db.scalars(select(models.ExamStudentOverride).where(models.ExamStudentOverride.exam_id == exam_id)).all()
    return (rules, {o.student_id for o in ov if o.kind == "include"}, {o.student_id for o in ov if o.kind == "exclude"})


def rule_matches(rule, student: models.Student) -> bool:
    return ((rule.department is None or _n(rule.department) == _n(student.department))
            and (rule.course is None or _n(rule.course) == _n(student.course))
            and (rule.year is None or rule.year == student.year))


def student_eligible(audience, student: models.Student) -> bool:
    rules, include, exclude = audience
    if student.id in exclude:
        return False
    if not rules and not include:
        return True                      # no audience defined => every active student (Phase 1 behaviour)
    return student.id in include or any(rule_matches(r, student) for r in rules)


def eligible_students(db: Session, exam: models.Exam) -> list[models.Student]:
    audience = load_audience(db, exam.id)
    students = db.scalars(select(models.Student).where(models.Student.active == True)  # noqa: E712
                          .order_by(models.Student.register_number)).all()
    return [s for s in students if student_eligible(audience, s)]


def _field_overlap(a, b) -> bool:
    return a is None or b is None or _n(a) == _n(b)


def audiences_may_intersect(rules_a, rules_b) -> bool:
    """True when some student could match a rule of both exams (rules only; both must be non-empty)."""
    for ra in rules_a:
        for rb in rules_b:
            if (_field_overlap(ra.department, rb.department) and _field_overlap(ra.course, rb.course)
                    and (ra.year is None or rb.year is None or ra.year == rb.year)):
                return True
    return False


def audience_conflict(db: Session, exam: models.Exam, rules=None, times=None):
    """Another exam at an overlapping time whose explicit audience overlaps this one's."""
    rules = rules if rules is not None else load_audience(db, exam.id)[0]
    if not rules:
        return None
    probe = exam
    if times:  # (date, start, end) candidate values not yet saved
        probe = models.Exam(id=exam.id, exam_date=times[0], start_time=times[1], end_time=times[2])
    for other in overlapping_exams(db, probe):
        other_rules = load_audience(db, other.id)[0]
        if other_rules and audiences_may_intersect(rules, other_rules):
            return other
    return None


# ----------------------------------------------------------------------------- occupancy
def occupancy(db: Session, exam: models.Exam):
    """Seats taken for this exam (with department) and by simultaneous exams (department None).
    Returns {HALL_UPPER: {SEAT_UPPER: dept-or-None}}."""
    out: dict[str, dict[str, str | None]] = {}
    ids = [exam.id] + [o.id for o in overlapping_exams(db, exam)]
    rows = db.execute(select(models.Allotment.exam_id, models.Allotment.hall, models.Allotment.seat,
                             models.Student.department)
                      .join(models.Student, models.Student.id == models.Allotment.student_id)
                      .where(models.Allotment.exam_id.in_(ids))).all()
    for exam_id, hall, seat, dept in rows:
        out.setdefault(hall.strip().upper(), {})[seat.strip().upper()] = dept if exam_id == exam.id else None
    return out


def usable_seats(db: Session, hall: doc_models.Hall) -> tuple[str, ...]:
    seats = db.scalars(select(models.HallSeat.seat_label).where(models.HallSeat.hall_id == hall.id,
                                                                 models.HallSeat.active == True)).all()  # noqa: E712
    seats = sorted(seats, key=natural_key)
    if hall.capacity is not None and len(seats) > hall.capacity:
        seats = seats[:hall.capacity]
    return tuple(seats)


# ----------------------------------------------------------------------------- existing allotment health
def invalid_existing(db: Session, exam: models.Exam, audience) -> list[dict]:
    """Existing allotments that no longer satisfy the rules. Reported, never auto-changed."""
    problems = []
    rows = db.execute(select(models.Allotment, models.Student).join(models.Student, models.Student.id == models.Allotment.student_id)
                      .where(models.Allotment.exam_id == exam.id)).all()
    halls = {h.code.strip().upper(): h for h in db.scalars(select(doc_models.Hall)).all()}
    inventory: dict[int, set[str]] = {}
    has_inv: set[int] = set()
    for hid, label, active in db.execute(select(models.HallSeat.hall_id, models.HallSeat.seat_label, models.HallSeat.active)).all():
        has_inv.add(hid)
        if active:
            inventory.setdefault(hid, set()).add(label.upper())
    for a, s in rows:
        issue = None
        h = halls.get(a.hall.strip().upper())
        if not s.active:
            issue = "student inactive"
        elif not student_eligible(audience, s):
            issue = "student no longer eligible"
        elif h is not None and not h.verified:
            issue = "hall not verified"
        elif h is not None and h.id in has_inv and a.seat.strip().upper() not in inventory.get(h.id, set()):
            issue = "seat inactive or removed"
        if issue:
            problems.append({"allotment_id": a.id, "register_number": s.register_number, "hall": a.hall,
                             "seat": a.seat, "problem": issue})
    return problems


# ----------------------------------------------------------------------------- allocation run
def build_run(db: Session, exam: models.Exam, data) -> dict:
    """Compute (but never save) an allocation for `exam` from an AutoAllocationInput-like object."""
    audience = load_audience(db, exam.id)
    if data.register_numbers is None:
        selected = eligible_students(db, exam)
        not_eligible: list[models.Student] = []
    else:
        explicit = db.scalars(select(models.Student).where(
            models.Student.register_number.in_(data.register_numbers), models.Student.active == True  # noqa: E712
        ).order_by(models.Student.register_number)).all()
        missing = sorted(set(data.register_numbers) - {s.register_number for s in explicit})
        if missing:
            raise HTTPException(status_code=422, detail={"message": "Unknown or inactive students",
                                                         "register_numbers": missing})
        selected = [s for s in explicit if student_eligible(audience, s)]
        not_eligible = [s for s in explicit if not student_eligible(audience, s)]

    existing = db.scalars(select(models.Allotment).where(models.Allotment.exam_id == exam.id)).all()
    existing_ids = {a.student_id for a in existing}
    already = [s for s in selected if s.id in existing_ids]
    pending = [s for s in selected if s.id not in existing_ids]

    # Students already seated in a simultaneous exam cannot be given a second seat at the same time.
    sim_ids = [o.id for o in overlapping_exams(db, exam)]
    busy = set()
    if sim_ids and pending:
        busy = set(db.scalars(select(models.Allotment.student_id).where(models.Allotment.exam_id.in_(sim_ids))).all())
    conflicted = [s for s in pending if s.id in busy]
    pending = [s for s in pending if s.id not in busy]

    q = select(doc_models.Hall).where(doc_models.Hall.verified == True)  # noqa: E712
    if data.hall_ids is not None:
        q = q.where(doc_models.Hall.id.in_(data.hall_ids))
    halls = db.scalars(q.order_by(doc_models.Hall.code)).all()
    if data.hall_ids is not None and len(halls) != len(data.hall_ids):
        raise HTTPException(status_code=422, detail="One or more selected halls are missing or not verified")
    if not halls:
        raise HTTPException(status_code=409, detail="No verified halls are available")

    occ = occupancy(db, exam)
    hall_recs, occupied = [], {}
    for h in halls:
        seats = usable_seats(db, h)
        if seats:
            hall_recs.append(HallRec(h.id, h.code, seats))
            occupied[h.code] = occ.get(h.code.strip().upper(), {})

    cfg = Config(data.strategy, data.seat_gap, data.department_separation)
    result: Result = allocate([StudentRec(s.id, s.register_number, s.full_name, s.department) for s in pending],
                              hall_recs, occupied, cfg)
    extra = ([{"student_id": s.id, "register_number": s.register_number, "student_name": s.full_name,
               "department": s.department, "reason": "not_eligible"} for s in not_eligible]
             + [{"student_id": s.id, "register_number": s.register_number, "student_name": s.full_name,
                 "department": s.department, "reason": "simultaneous_exam"} for s in conflicted])
    unallocated = [asdict(u) for u in result.unallocated] + extra
    return {"exam": exam, "config": cfg, "result": result, "unallocated": unallocated,
            "selected": len(selected) + len(not_eligible), "already": len(already), "pending": len(pending),
            "assignments": [asdict(a) for a in result.assignments],
            "invalid_existing": invalid_existing(db, exam, audience),
            "capacity_short": [u for u in result.unallocated if u.reason in (REASON_CAPACITY, REASON_RULES)]}


def run_summary(run: dict) -> dict:
    r: Result = run["result"]
    return {"selected_students": run["selected"], "already_allocated": run["already"],
            "pending_students": run["pending"], "new_allocations": len(run["assignments"]),
            "unallocated_count": len(run["unallocated"]), "free_seats_before": r.free_seats_before,
            "capacity_sufficient": r.sufficient, "warnings": r.warnings, "hall_stats": r.hall_stats,
            "invalid_existing_count": len(run["invalid_existing"])}


# ----------------------------------------------------------------------------- manual placement validation
def check_placement(db: Session, exam: models.Exam, student: models.Student, hall_code: str, seat: str,
                    exclude_allotment_id: int | None = None) -> None:
    """Raise HTTPException unless (student, hall, seat) is a valid seat for `exam`."""
    hall_code, seat = hall_code.strip().upper(), seat.strip().upper()
    if not student.active:
        raise HTTPException(status_code=409, detail="Student record is inactive")
    if not student_eligible(load_audience(db, exam.id), student):
        raise HTTPException(status_code=409, detail="Student is not eligible for this examination")
    ids = [exam.id] + [o.id for o in overlapping_exams(db, exam)]
    hall = db.scalar(select(doc_models.Hall).where(func.upper(func.trim(doc_models.Hall.code)) == hall_code))
    if hall:
        if not hall.verified:
            raise HTTPException(status_code=409, detail="Hall directory record must be verified before allocation")
        inv = db.scalar(select(func.count()).select_from(models.HallSeat).where(models.HallSeat.hall_id == hall.id)) or 0
        if inv:
            ok = db.scalar(select(models.HallSeat.id).where(
                models.HallSeat.hall_id == hall.id, func.upper(models.HallSeat.seat_label) == seat,
                models.HallSeat.active == True))  # noqa: E712
            if not ok:
                raise HTTPException(status_code=422, detail="Seat is not in this hall's active seat inventory")
        if hall.capacity:
            q = select(func.count()).select_from(models.Allotment).where(
                models.Allotment.exam_id.in_(ids), func.upper(func.trim(models.Allotment.hall)) == hall_code)
            if exclude_allotment_id:
                q = q.where(models.Allotment.id != exclude_allotment_id)
            if (db.scalar(q) or 0) >= hall.capacity:
                raise HTTPException(status_code=409, detail="Hall capacity would be exceeded")
    base = select(models.Allotment).where(models.Allotment.exam_id == exam.id)
    own = base.where((models.Allotment.student_id == student.id) |
                     ((func.upper(func.trim(models.Allotment.hall)) == hall_code) &
                      (func.upper(func.trim(models.Allotment.seat)) == seat)))
    if exclude_allotment_id:
        own = own.where(models.Allotment.id != exclude_allotment_id)
    if db.scalar(own.limit(1)):
        raise HTTPException(status_code=409, detail="Student or seat already allotted for this examination")
    others = ids[1:]
    if others:
        sim = select(models.Allotment).where(models.Allotment.exam_id.in_(others)).where(
            (models.Allotment.student_id == student.id) |
            ((func.upper(func.trim(models.Allotment.hall)) == hall_code) &
             (func.upper(func.trim(models.Allotment.seat)) == seat)))
        hit = db.scalar(sim.limit(1))
        if hit:
            what = "Student already has a simultaneous examination" if hit.student_id == student.id \
                else "Seat is already used by a simultaneous examination"
            raise HTTPException(status_code=409, detail=what)


def log_history(db: Session, *, exam_id: int, student_id: int, action: str, actor: str,
                allotment_id: int | None = None, old: tuple | None = None, new: tuple | None = None,
                reason: str | None = None, plan_id: int | None = None) -> None:
    db.add(models.AllotmentHistory(exam_id=exam_id, student_id=student_id, allotment_id=allotment_id,
                                   action=action, actor=actor[:80], reason=reason, plan_id=plan_id,
                                   old_hall=old[0] if old else None, old_seat=old[1] if old else None,
                                   new_hall=new[0] if new else None, new_seat=new[1] if new else None))
