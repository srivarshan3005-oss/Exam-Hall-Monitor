"""Examination management: CRUD, filters, publish/unpublish, audience (eligibility) mapping."""
from datetime import date
from .. import notifications as notify
from fastapi import APIRouter, Depends, HTTPException, Request, Query, Response
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from pydantic import ValidationError
from .. import models, schemas, audit
from ..database import get_db
from ..deps import require_roles
from ..services_allocation import (duration_minutes, session_of, overlapping_exams, audience_conflict,
                                   load_audience, student_eligible)

router = APIRouter(prefix="/api", tags=["Examinations"])
STAFF = ("admin", "staff")


def exam_dict(e: models.Exam) -> dict:
    return {"id": e.id, "title": e.title, "subject_code": e.subject_code, "exam_date": e.exam_date,
            "start_time": e.start_time, "end_time": e.end_time, "venue": e.venue, "status": e.status,
            "subject_id": e.subject_id, "term_id": e.term_id,
            "duration_minutes": duration_minutes(e.start_time, e.end_time), "session": session_of(e.start_time)}


def _venue_conflict(db: Session, payload: dict, exclude_id: int | None = None):
    """Return an existing exam that overlaps in the same venue and date."""
    venue = str(payload.get("venue") or "").strip().casefold()
    if not venue:
        return None
    query = select(models.Exam).where(models.Exam.exam_date == payload["exam_date"])
    if exclude_id is not None:
        query = query.where(models.Exam.id != exclude_id)
    for other in db.scalars(query).all():
        if str(other.venue or "").strip().casefold() != venue:
            continue
        # Half-open intervals: an exam ending at 11:00 does not conflict with one
        # beginning at 11:00. Inputs are already validated as 24-hour HH:MM.
        if payload["start_time"] < other.end_time and other.start_time < payload["end_time"]:
            return other
    return None


def _conflict_409(other: models.Exam, message: str):
    return HTTPException(status_code=409, detail={"message": message, "conflicting_exam_id": other.id,
                                                  "conflicting_exam_title": other.title})


def _resolve_links(db: Session, payload: dict) -> None:
    """Validate subject/term references; the catalogue subject wins over a typed code."""
    if payload.get("subject_id"):
        subj = db.get(models.Subject, payload["subject_id"])
        if not subj:
            raise HTTPException(status_code=422, detail="Unknown subject")
        if not subj.active:
            raise HTTPException(status_code=422, detail="Subject is inactive")
        payload["subject_code"] = subj.code
    if payload.get("term_id"):
        term = db.get(models.ExamTerm, payload["term_id"])
        if not term:
            raise HTTPException(status_code=422, detail="Unknown examination term")
        d = date.fromisoformat(payload["exam_date"])
        if not term.start_date <= d <= term.end_date:
            raise HTTPException(status_code=422, detail=f"Exam date must fall within the term "
                                                        f"({term.start_date} to {term.end_date})")


def _check_schedule(db: Session, payload: dict, exclude_id: int | None, exam: models.Exam | None = None):
    other = _venue_conflict(db, payload, exclude_id)
    if other:
        raise _conflict_409(other, "Examination time conflicts with another examination in the same venue")
    if exam is not None:
        other = audience_conflict(db, exam, times=(payload["exam_date"], payload["start_time"], payload["end_time"]))
        if other:
            raise _conflict_409(other, "Overlaps another examination for an intersecting department/year audience")
        # Existing seat allocations must not collide with exams now running at the same time.
        probe = models.Exam(id=exam.id, exam_date=payload["exam_date"], start_time=payload["start_time"],
                            end_time=payload["end_time"])
        sims = [o.id for o in overlapping_exams(db, probe)]
        if sims:
            mine = db.execute(select(models.Allotment.student_id, models.Allotment.hall, models.Allotment.seat)
                              .where(models.Allotment.exam_id == exam.id)).all()
            theirs = db.execute(select(models.Allotment.student_id, models.Allotment.hall, models.Allotment.seat)
                                .where(models.Allotment.exam_id.in_(sims))).all()
            students = {t[0] for t in theirs}
            seats = {(t[1].strip().upper(), t[2].strip().upper()) for t in theirs}
            if any(m[0] in students or (m[1].strip().upper(), m[2].strip().upper()) in seats for m in mine):
                raise HTTPException(status_code=409, detail="New schedule would give students or seats two "
                                                            "simultaneous examinations; correct the allotments first")


# ----------------------------------------------------------------------------- listing
@router.get("/exams")
def list_exams(db: Session = Depends(get_db)):
    rows = db.scalars(select(models.Exam).where(models.Exam.status == "published")
                      .order_by(models.Exam.exam_date, models.Exam.start_time)).all()
    return [exam_dict(e) for e in rows]


@router.get("/admin/exams")
def admin_exams(response: Response, q: str = Query("", max_length=80), status: str = Query("", max_length=20),
                term_id: int | None = Query(None, ge=1), subject_id: int | None = Query(None, ge=1),
                department: str = Query("", max_length=100), session: str = Query("", pattern="^(FN|AN)?$"),
                date_from: str = Query("", pattern=r"^(\d{4}-\d{2}-\d{2})?$"),
                date_to: str = Query("", pattern=r"^(\d{4}-\d{2}-\d{2})?$"),
                limit: int = Query(200, ge=1, le=500), offset: int = Query(0, ge=0),
                db: Session = Depends(get_db), user: models.User = Depends(require_roles("admin", "staff", "invigilator"))):
    """Filterable examination list. Total matches are returned in the X-Total-Count header."""
    if status and status not in ("draft", "published", "completed"):
        raise HTTPException(status_code=422, detail="Unknown status")
    cond = []
    if q:
        cond.append(models.Exam.title.icontains(q, autoescape=True) | models.Exam.subject_code.icontains(q.upper(), autoescape=True))
    if status:
        cond.append(models.Exam.status == status)
    if term_id:
        cond.append(models.Exam.term_id == term_id)
    if subject_id:
        cond.append(models.Exam.subject_id == subject_id)
    if date_from:
        cond.append(models.Exam.exam_date >= date_from)
    if date_to:
        cond.append(models.Exam.exam_date <= date_to)
    if session == "FN":
        cond.append(models.Exam.start_time < "12:00")
    elif session == "AN":
        cond.append(models.Exam.start_time >= "12:00")
    if department:
        cond.append(models.Exam.id.in_(select(models.ExamEligibilityRule.exam_id).where(
            func.lower(models.ExamEligibilityRule.department) == department.strip().lower())))
    total = db.scalar(select(func.count()).select_from(models.Exam).where(*cond)) or 0
    rows = db.scalars(select(models.Exam).where(*cond).order_by(models.Exam.exam_date.desc(), models.Exam.id.desc())
                      .limit(limit).offset(offset)).all()
    response.headers["X-Total-Count"] = str(total)
    ids = [e.id for e in rows]
    allotted = dict(db.execute(select(models.Allotment.exam_id, func.count()).where(models.Allotment.exam_id.in_(ids))
                               .group_by(models.Allotment.exam_id)).all()) if ids else {}
    rules = dict(db.execute(select(models.ExamEligibilityRule.exam_id, func.count()).where(
        models.ExamEligibilityRule.exam_id.in_(ids)).group_by(models.ExamEligibilityRule.exam_id)).all()) if ids else {}
    subjects = {s.id: s.name for s in db.scalars(select(models.Subject)).all()}
    terms = {t.id: t.name for t in db.scalars(select(models.ExamTerm)).all()}
    return [{**exam_dict(e), "subject_name": subjects.get(e.subject_id), "term_name": terms.get(e.term_id),
             "allotment_count": allotted.get(e.id, 0), "eligibility_rule_count": rules.get(e.id, 0)} for e in rows]


# ----------------------------------------------------------------------------- create / update
@router.post("/exams", status_code=201)
def create_exam(data: schemas.ExamCreate, request: Request, db: Session = Depends(get_db),
                user: models.User = Depends(require_roles(*STAFF))):
    payload = data.model_dump()
    _resolve_links(db, payload)
    _check_schedule(db, payload, None)
    payload["duration_minutes"] = duration_minutes(payload["start_time"], payload["end_time"])
    e = models.Exam(**payload)
    db.add(e)
    db.flush()
    audit.record(db, user.username, "exam.created", str(e.id), {"title": e.title, "status": e.status},
                 request, user.role)
    db.commit()
    notify.notify_exam_transition(db, e, {**notify.exam_snapshot(e), "status": "draft"}, user.username)
    return {"id": e.id, "title": e.title}


@router.patch("/exams/{exam_id}")
def update_exam(exam_id: int, data: schemas.ExamUpdate, request: Request, db: Session = Depends(get_db),
                user: models.User = Depends(require_roles(*STAFF))):
    e = db.get(models.Exam, exam_id)
    if not e:
        raise HTTPException(status_code=404, detail="Examination not found")
    changes = data.model_dump(exclude_unset=True)
    merged = {**exam_dict(e), **changes}
    merged.pop("id")
    try:  # re-validate the combined record (e.g. end time after start time)
        schemas.ExamCreate(**merged)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_url=False, include_context=False))
    _resolve_links(db, merged)
    if "subject_id" in changes or "subject_code" in changes:
        changes["subject_code"] = merged["subject_code"]
    timing = {"exam_date", "start_time", "end_time"} & set(changes)
    _check_schedule(db, merged, e.id, e if timing else None)
    old_status = e.status
    old_snap = notify.exam_snapshot(e)
    for k, v in changes.items():
        setattr(e, k, v)
    e.duration_minutes = duration_minutes(e.start_time, e.end_time)
    details = {"fields": sorted(changes)}
    if "status" in changes and changes["status"] != old_status:
        details["status"] = f"{old_status}->{changes['status']}"
    audit.record(db, user.username, "exam.updated", str(e.id), details, request, user.role)
    db.commit()
    notify.notify_exam_transition(db, e, old_snap, user.username)
    return exam_dict(e)


@router.post("/exams/{exam_id}/publish")
def publish_exam(exam_id: int, request: Request, db: Session = Depends(get_db),
                 user: models.User = Depends(require_roles(*STAFF))):
    e = db.get(models.Exam, exam_id)
    if not e:
        raise HTTPException(status_code=404, detail="Examination not found")
    if e.status == "published":
        raise HTTPException(status_code=409, detail="Examination is already published")
    if e.status == "completed":
        raise HTTPException(status_code=409, detail="A completed examination cannot be published")
    if date.fromisoformat(e.exam_date) < date.today():
        raise HTTPException(status_code=422, detail="Cannot publish an examination dated in the past")
    payload = exam_dict(e)
    other = _venue_conflict(db, payload, e.id)
    if other:
        raise _conflict_409(other, "Examination time conflicts with another examination in the same venue")
    old_snap = notify.exam_snapshot(e)
    e.status = "published"
    audit.record(db, user.username, "exam.published", str(e.id), {"status": "draft->published"}, request, user.role)
    db.commit()
    notify.notify_exam_transition(db, e, old_snap, user.username)
    return exam_dict(e)


@router.post("/exams/{exam_id}/unpublish")
def unpublish_exam(exam_id: int, request: Request, db: Session = Depends(get_db),
                   user: models.User = Depends(require_roles(*STAFF))):
    e = db.get(models.Exam, exam_id)
    if not e:
        raise HTTPException(status_code=404, detail="Examination not found")
    if e.status != "published":
        raise HTTPException(status_code=409, detail="Only a published examination can be unpublished")
    old_snap = notify.exam_snapshot(e)
    e.status = "draft"
    audit.record(db, user.username, "exam.unpublished", str(e.id), {"status": "published->draft"}, request, user.role)
    db.commit()
    notify.notify_exam_transition(db, e, old_snap, user.username)
    return exam_dict(e)


@router.delete("/exams/{exam_id}")
def delete_exam(exam_id: int, request: Request, db: Session = Depends(get_db),
                user: models.User = Depends(require_roles("admin"))):
    e = db.get(models.Exam, exam_id)
    if not e:
        raise HTTPException(status_code=404, detail="Examination not found")
    if e.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft examinations can be deleted; unpublish it first")
    used = (db.scalar(select(func.count()).select_from(models.Allotment).where(models.Allotment.exam_id == e.id)) or 0) + \
           (db.scalar(select(func.count()).select_from(models.Result).where(models.Result.exam_id == e.id)) or 0)
    if used:
        raise HTTPException(status_code=409, detail="Examination has allotments or results and cannot be deleted")
    audit.record(db, user.username, "exam.deleted", str(e.id), {"title": e.title}, request, user.role)
    db.delete(e)
    db.commit()
    return {"deleted": exam_id}


# ----------------------------------------------------------------------------- eligibility (audience) mapping
def _eligibility_view(db: Session, e: models.Exam) -> dict:
    rules, inc, exc = load_audience(db, e.id)
    regs = {s.id: s.register_number for s in db.scalars(select(models.Student).where(
        models.Student.id.in_(inc | exc))).all()} if (inc or exc) else {}
    audience = (rules, inc, exc)
    active = db.scalars(select(models.Student).where(models.Student.active == True)).all()  # noqa: E712
    return {"exam_id": e.id,
            "rules": [{"department": r.department, "course": r.course, "year": r.year} for r in rules],
            "include": sorted(regs[i] for i in inc if i in regs), "exclude": sorted(regs[i] for i in exc if i in regs),
            "eligible_count": sum(1 for s in active if student_eligible(audience, s)), "active_students": len(active),
            "all_students_eligible": not rules and not inc}


@router.get("/exams/{exam_id}/eligibility")
def get_eligibility(exam_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    e = db.get(models.Exam, exam_id)
    if not e:
        raise HTTPException(status_code=404, detail="Examination not found")
    return _eligibility_view(db, e)


@router.put("/exams/{exam_id}/eligibility")
def set_eligibility(exam_id: int, data: schemas.EligibilityInput, request: Request, db: Session = Depends(get_db),
                    user: models.User = Depends(require_roles(*STAFF))):
    """Replace the exam's audience: department/course/year rules plus individual include/exclude lists."""
    e = db.get(models.Exam, exam_id)
    if not e:
        raise HTTPException(status_code=404, detail="Examination not found")
    wanted = set(data.include) | set(data.exclude)
    found = {s.register_number: s for s in db.scalars(select(models.Student).where(
        models.Student.register_number.in_(wanted))).all()} if wanted else {}
    missing = sorted(wanted - set(found))
    if missing:
        raise HTTPException(status_code=422, detail={"message": "Unknown students", "register_numbers": missing})
    new_rules = [models.ExamEligibilityRule(exam_id=e.id, **r.model_dump()) for r in data.rules]
    other = audience_conflict(db, e, rules=new_rules)
    if other:
        raise _conflict_409(other, "This audience overlaps another examination scheduled at the same time")
    db.query(models.ExamEligibilityRule).filter(models.ExamEligibilityRule.exam_id == e.id).delete()
    db.query(models.ExamStudentOverride).filter(models.ExamStudentOverride.exam_id == e.id).delete()
    db.add_all(new_rules)
    db.add_all([models.ExamStudentOverride(exam_id=e.id, student_id=found[r].id, kind="include") for r in data.include]
               + [models.ExamStudentOverride(exam_id=e.id, student_id=found[r].id, kind="exclude") for r in data.exclude])
    audit.record(db, user.username, "exam.eligibility_set", str(e.id),
                 {"rules": len(data.rules), "include": len(data.include), "exclude": len(data.exclude)}, request, user.role)
    db.commit()
    return _eligibility_view(db, e)
