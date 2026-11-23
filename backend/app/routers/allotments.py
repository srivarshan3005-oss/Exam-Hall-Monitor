import json
from .. import notifications as notify
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .. import models, schemas, audit
from ..database import get_db
from ..dbutil import lock_allocation
from ..deps import require_roles, department_scope
from ..services_allocation import (build_run, run_summary, check_placement, log_history)
from .students import public_guard, parse_register, find_student, public_allotments

router = APIRouter(prefix="/api/allotments", tags=["Seat allotments"])
STAFF = ("admin", "staff")
READ = ("admin", "staff", "invigilator")


def _own_department_only(user: models.User, student: models.Student) -> None:
    scope = department_scope(user)
    if scope and (student.department or "").strip().lower() != scope.lower():
        raise HTTPException(status_code=403, detail="This student belongs to another department")


def _allotment_dict(a: models.Allotment, s: models.Student | None = None) -> dict:
    s = s or a.student
    return {"id": a.id, "exam_id": a.exam_id, "register_number": s.register_number, "student_name": s.full_name,
            "department": s.department, "hall": a.hall, "seat": a.seat, "source": a.source or "legacy"}


@router.post("", status_code=201)
def create_allotment(data: schemas.AllotmentCreate, request: Request, db: Session = Depends(get_db),
                     user: models.User = Depends(require_roles(*STAFF))):
    """Manual allocation. Same rules as automatic allocation: verified hall, active seat, capacity,
    eligibility, no duplicate student/seat and no clash with a simultaneous examination."""
    lock_allocation(db)   # serialise "check then write" decisions (clash / capacity) across concurrent requests
    s = db.scalar(select(models.Student).where(models.Student.register_number == data.register_number))
    e = db.get(models.Exam, data.exam_id)
    if not s or not e:
        raise HTTPException(status_code=404, detail="Student or examination not found")
    _own_department_only(user, s)
    check_placement(db, e, s, data.hall, data.seat)
    a = models.Allotment(student_id=s.id, exam_id=e.id, hall=data.hall.strip().upper(),
                         seat=data.seat.strip(), source="manual")
    db.add(a)
    try:
        db.flush()
    except IntegrityError:  # concurrent request won the race; DB unique constraints are the backstop
        db.rollback()
        raise HTTPException(status_code=409, detail="Student or seat already allotted for this examination")
    audit.record(db, user.username, "allotment.created", str(a.id),
                 {"exam_id": e.id, "student_id": s.id}, request, user.role)
    log_history(db, exam_id=e.id, student_id=s.id, action="created", actor=user.username, allotment_id=a.id,
                new=(a.hall, a.seat), reason="manual allocation")
    db.commit()
    notify.notify_seat_events(db, e, [{"student_id": s.id, "kind": "allocated", "hall": a.hall, "seat": a.seat}], user.username)
    return {"id": a.id, "hall": a.hall, "seat": a.seat}


@router.patch("/{allotment_id}")
def move_allotment(allotment_id: int, data: schemas.AllotmentMove, request: Request, db: Session = Depends(get_db),
                   user: models.User = Depends(require_roles(*STAFF))):
    """Correct an existing allocation (change hall/seat). A reason is mandatory and recorded."""
    lock_allocation(db)
    a = db.get(models.Allotment, allotment_id)
    if not a:
        raise HTTPException(status_code=404, detail="Allotment not found")
    _own_department_only(user, a.student)
    check_placement(db, a.exam, a.student, data.hall, data.seat, exclude_allotment_id=a.id)
    old = (a.hall, a.seat)
    a.hall, a.seat, a.source = data.hall, data.seat, "manual"
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Seat already allotted for this examination")
    audit.record(db, user.username, "allotment.moved", str(a.id),
                 {"exam_id": a.exam_id, "from": f"{old[0]}/{old[1]}", "to": f"{a.hall}/{a.seat}"}, request, user.role)
    log_history(db, exam_id=a.exam_id, student_id=a.student_id, action="moved", actor=user.username,
                allotment_id=a.id, old=old, new=(a.hall, a.seat), reason=data.reason)
    db.commit()
    if old != (a.hall, a.seat):
        notify.notify_seat_events(db, a.exam, [{"student_id": a.student_id, "kind": "corrected", "hall": a.hall, "seat": a.seat,
                                                "old_hall": old[0], "old_seat": old[1]}], user.username)
    return {"id": a.id, "hall": a.hall, "seat": a.seat}


@router.delete("/{allotment_id}")
def delete_allotment(allotment_id: int, request: Request, reason: str = Query("", max_length=300),
                     db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    a = db.get(models.Allotment, allotment_id)
    if not a:
        raise HTTPException(status_code=404, detail="Allotment not found")
    _own_department_only(user, a.student)
    exam_ref, sid, old_pos = a.exam, a.student_id, (a.hall, a.seat)
    audit.record(db, user.username, "allotment.deleted", str(a.id),
                 {"exam_id": a.exam_id, "student_id": a.student_id}, request, user.role)
    log_history(db, exam_id=a.exam_id, student_id=a.student_id, action="deleted", actor=user.username,
                allotment_id=a.id, old=(a.hall, a.seat), reason=reason.strip() or None)
    db.delete(a)
    db.commit()
    notify.notify_seat_events(db, exam_ref, [{"student_id": sid, "kind": "removed", "old_hall": old_pos[0], "old_seat": old_pos[1]}], user.username)
    return {"deleted": allotment_id}


@router.get("/exam/{exam_id}")
def exam_allotments(exam_id: int, q: str = Query("", max_length=60), hall: str = Query("", max_length=100),
                    limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0),
                    db: Session = Depends(get_db), user: models.User = Depends(require_roles(*READ))):
    """Administrative list of an examination's allotments (for correction)."""
    if not db.get(models.Exam, exam_id):
        raise HTTPException(status_code=404, detail="Examination not found")
    stmt = (select(models.Allotment, models.Student).join(models.Student, models.Student.id == models.Allotment.student_id)
            .where(models.Allotment.exam_id == exam_id).order_by(models.Student.register_number).limit(limit).offset(offset))
    if q:
        stmt = stmt.where(models.Student.register_number.icontains(q, autoescape=True)
                          | models.Student.full_name.icontains(q, autoescape=True))
    if hall:
        stmt = stmt.where(func.upper(models.Allotment.hall) == hall.strip().upper())
    scope = department_scope(user)
    if scope:
        stmt = stmt.where(func.lower(models.Student.department) == scope.lower())
    return [_allotment_dict(a, s) for a, s in db.execute(stmt).all()]


@router.get("/history")
def allotment_history(exam_id: int | None = Query(None, ge=1), register_number: str = Query("", max_length=30),
                      limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db),
                      user: models.User = Depends(require_roles(*STAFF))):
    stmt = select(models.AllotmentHistory, models.Student.register_number).outerjoin(
        models.Student, models.Student.id == models.AllotmentHistory.student_id).order_by(
        models.AllotmentHistory.id.desc()).limit(limit)
    if exam_id:
        stmt = stmt.where(models.AllotmentHistory.exam_id == exam_id)
    if register_number:
        stmt = stmt.where(models.Student.register_number == register_number.strip().upper())
    return [{"id": h.id, "exam_id": h.exam_id, "register_number": reg, "action": h.action,
             "from": f"{h.old_hall}/{h.old_seat}" if h.old_hall else None,
             "to": f"{h.new_hall}/{h.new_seat}" if h.new_hall else None, "reason": h.reason,
             "actor": h.actor, "plan_id": h.plan_id, "created_at": h.created_at.isoformat()}
            for h, reg in db.execute(stmt).all()]


# ----------------------------------------------------------------------------- plans: preview -> approve -> commit
def _plan_view(p: models.AllocationPlan, full: bool = True, limit: int = 500) -> dict:
    assignments = json.loads(p.assignments)
    out = {"id": p.id, "exam_id": p.exam_id, "status": p.status, "created_by": p.created_by,
           "created_at": p.created_at.isoformat(), "committed_by": p.committed_by,
           "committed_at": p.committed_at.isoformat() if p.committed_at else None,
           "config": json.loads(p.config), "summary": json.loads(p.summary),
           "assignment_count": len(assignments)}
    if full:
        out["assignments"] = assignments[:limit]
        out["assignments_truncated"] = len(assignments) > limit
        out["unallocated"] = json.loads(p.unallocated)[:limit]
    return out


@router.post("/plans", status_code=201)
def create_plan(data: schemas.PlanInput, request: Request, db: Session = Depends(get_db),
                user: models.User = Depends(require_roles(*STAFF))):
    """Build an allocation preview and store it as a plan. Nothing is allotted until an
    administrator commits the plan. Insufficient capacity is reported, not hidden."""
    exam = db.get(models.Exam, data.exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Examination not found")
    run = build_run(db, exam, data)
    summary = run_summary(run)
    plan = models.AllocationPlan(exam_id=exam.id, status="preview", created_by=user.username,
                                 config=json.dumps(data.model_dump(), default=str),
                                 assignments=json.dumps(run["assignments"]),
                                 unallocated=json.dumps(run["unallocated"]), summary=json.dumps(summary))
    db.add(plan)
    db.flush()
    audit.record(db, user.username, "allocation.plan_created", str(plan.id),
                 {"exam_id": exam.id, "new": summary["new_allocations"], "unallocated": summary["unallocated_count"]},
                 request, user.role)
    db.commit()
    view = _plan_view(plan)
    view["invalid_existing"] = run["invalid_existing"]
    view["can_commit"] = bool(run["assignments"]) and not run["capacity_short"]
    view["exam_title"] = exam.title
    return view


@router.get("/plans")
def list_plans(exam_id: int | None = Query(None, ge=1), db: Session = Depends(get_db),
               user: models.User = Depends(require_roles(*STAFF))):
    stmt = select(models.AllocationPlan).order_by(models.AllocationPlan.id.desc()).limit(50)
    if exam_id:
        stmt = stmt.where(models.AllocationPlan.exam_id == exam_id)
    return [_plan_view(p, full=False) for p in db.scalars(stmt).all()]


@router.get("/plans/{plan_id}")
def get_plan(plan_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    p = db.get(models.AllocationPlan, plan_id)
    if not p:
        raise HTTPException(status_code=404, detail="Plan not found")
    return _plan_view(p)


@router.post("/plans/{plan_id}/discard")
def discard_plan(plan_id: int, request: Request, db: Session = Depends(get_db),
                 user: models.User = Depends(require_roles(*STAFF))):
    p = db.get(models.AllocationPlan, plan_id)
    if not p:
        raise HTTPException(status_code=404, detail="Plan not found")
    if p.status != "preview":
        raise HTTPException(status_code=409, detail=f"Plan is already {p.status}")
    p.status = "discarded"
    audit.record(db, user.username, "allocation.plan_discarded", str(p.id), {"exam_id": p.exam_id}, request, user.role)
    db.commit()
    return {"id": p.id, "status": p.status}


def _notify_created(db: Session, exam: models.Exam, created: list[dict], user) -> None:
    """One 'seat allocated' notice per affected student (only those who were just given a seat)."""
    ids = {r["register_number"]: r for r in created}
    studs = db.scalars(select(models.Student).where(models.Student.register_number.in_(list(ids)))).all() if ids else []
    notify.notify_seat_events(db, exam, [{"student_id": s.id, "kind": "allocated", "hall": ids[s.register_number]["hall"],
                                          "seat": ids[s.register_number]["seat"]} for s in studs], user.username)


def _write_assignments(db: Session, exam: models.Exam, assignments: list[dict], user, plan_id: int | None) -> list[dict]:
    created = []
    for item in assignments:
        row = models.Allotment(student_id=item["student_id"], exam_id=exam.id, hall=item["hall"], seat=item["seat"],
                               source="auto", plan_id=plan_id)
        db.add(row)
        db.flush()
        log_history(db, exam_id=exam.id, student_id=item["student_id"], action="auto_created", actor=user.username,
                    allotment_id=row.id, new=(item["hall"], item["seat"]), plan_id=plan_id)
        created.append({"id": row.id, "register_number": item["register_number"], "hall": item["hall"], "seat": item["seat"]})
    return created


@router.post("/plans/{plan_id}/commit", status_code=201)
def commit_plan(plan_id: int, request: Request, body: schemas.PlanCommitInput | None = None,
                db: Session = Depends(get_db), user: models.User = Depends(require_roles("admin"))):
    """Administrator approval. The plan is re-computed from the CURRENT data; it is saved only if it is
    identical to the approved preview, otherwise the plan is marked stale. One transaction: all or nothing."""
    lock_allocation(db)   # the plan is re-computed from current data: nobody may change seats meanwhile
    p = db.get(models.AllocationPlan, plan_id)
    if not p:
        raise HTTPException(status_code=404, detail="Plan not found")
    if p.status != "preview":
        raise HTTPException(status_code=409, detail=f"Plan is already {p.status}")
    exam = db.get(models.Exam, p.exam_id)
    run = build_run(db, exam, schemas.AutoAllocationInput(**json.loads(p.config)))
    key = lambda rows: [(r["student_id"], r["hall"], r["seat"]) for r in rows]  # noqa: E731
    if key(run["assignments"]) != key(json.loads(p.assignments)):
        p.status = "stale"
        db.commit()
        raise HTTPException(status_code=409, detail="Students, halls, seats or schedules changed since this preview "
                                                    "was built. Create a new preview and approve it.")
    if not run["assignments"]:
        raise HTTPException(status_code=409, detail="Nothing to allocate")
    if run["capacity_short"] and not (body and body.allow_partial):
        raise HTTPException(status_code=409, detail={
            "message": "Insufficient capacity: some students would remain unallocated. Add halls/seats or approve a "
                       "partial allocation explicitly.", "unallocated": len(run["capacity_short"]),
            "available_seats": run["result"].free_seats_before})
    try:
        created = _write_assignments(db, exam, run["assignments"], user, p.id)
        p.status, p.committed_by = "committed", user.username
        p.committed_at = models.utcnow()
        audit.record(db, user.username, "allocation.plan_committed", str(p.id),
                     {"exam_id": exam.id, "created": len(created), "partial": bool(run["capacity_short"])},
                     request, user.role)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Allocation conflict detected; nothing was saved. Create a new preview.")
    _notify_created(db, exam, created, user)
    return {"plan_id": p.id, "exam_id": exam.id, "created": len(created), "unallocated": len(run["unallocated"])}


@router.get("/{register_number}")
def get_allotments(register_number: str, request: Request, db: Session = Depends(get_db)):
    ip = public_guard(request)
    reg = parse_register(register_number, ip)
    s = find_student(db, reg)
    # Unknown student -> empty list (same shape as "known, nothing published"): no existence oracle here.
    return public_allotments(db, s) if s else []


# ----------------------------------------------------------------------------- Phase 1 endpoints (kept; now use the Phase 2 engine)
def _legacy_run(db: Session, data: schemas.AutoAllocationInput):
    exam = db.get(models.Exam, data.exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Examination not found")
    run = build_run(db, exam, data)
    if run["capacity_short"]:
        raise HTTPException(status_code=409, detail={
            "message": "Insufficient verified seat inventory",
            "students_waiting": run["pending"], "available_seats": run["result"].free_seats_before})
    return exam, run


@router.post("/auto-preview")
def preview_auto_allocation(data: schemas.AutoAllocationInput, db: Session = Depends(get_db),
                            user: models.User = Depends(require_roles(*STAFF))):
    exam, run = _legacy_run(db, data)
    return {"exam_id": exam.id, "exam_title": exam.title, "selected_students": run["selected"],
            "already_allocated": run["already"], "new_allocations": len(run["assignments"]),
            "assignments": run["assignments"], "unallocated": run["unallocated"],
            "requires_confirmation": True}


@router.post("/auto-allocate", status_code=201)
def commit_auto_allocation(data: schemas.AutoAllocationInput, request: Request, db: Session = Depends(get_db),
                           user: models.User = Depends(require_roles("admin"))):
    lock_allocation(db)
    exam, run = _legacy_run(db, data)
    if not run["assignments"]:
        return {"exam_id": exam.id, "created": 0, "already_allocated": run["already"], "allocations": []}
    try:
        created = _write_assignments(db, exam, run["assignments"], user, None)
        audit.record(db, user.username, "allotment.auto_created", str(exam.id),
                     {"created": len(created), "already_allocated": run["already"]}, request, user.role)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Allocation conflict detected; no new allocations were saved. Refresh the preview.")
    _notify_created(db, exam, created, user)
    return {"exam_id": exam.id, "created": len(created), "already_allocated": run["already"], "allocations": created}
