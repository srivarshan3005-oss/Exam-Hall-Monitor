from datetime import datetime, timezone
from .. import notifications as notify
from fastapi import APIRouter, Depends, HTTPException, Request, Query, Response
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .. import models, schemas, audit
from ..config import settings
from ..database import get_db
from ..deps import require_roles, optional_user
from .students import public_guard, parse_register, note_miss

router = APIRouter(prefix="/api/results", tags=["Results"])


@router.post("", status_code=201)
def create_result(data: schemas.ResultCreate, request: Request, db: Session = Depends(get_db),
                  user: models.User = Depends(require_roles("admin"))):
    s = db.scalar(select(models.Student).where(models.Student.register_number == data.register_number))
    e = db.get(models.Exam, data.exam_id)
    if not s or not e:
        raise HTTPException(status_code=404, detail="Student or examination not found")
    if db.scalar(select(models.Result).where(models.Result.student_id == s.id, models.Result.exam_id == e.id)):
        raise HTTPException(status_code=409, detail="A result already exists for this student and examination")
    fields = data.model_dump(exclude={"register_number", "exam_id"})
    r = models.Result(student_id=s.id, exam_id=e.id, **fields)
    if r.published:
        r.published_at = datetime.now(timezone.utc)
    db.add(r)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A result already exists for this student and examination")
    # Marks are deliberately NOT written to the audit log.
    audit.record(db, user.username, "result.created", str(r.id),
                 {"exam_id": e.id, "student_id": s.id, "published": r.published}, request, user.role)
    db.commit()
    return {"id": r.id, "published": r.published}


def _set_published(result_id: int, value: bool, request: Request, db: Session, user: models.User):
    r = db.get(models.Result, result_id)
    if not r:
        raise HTTPException(status_code=404, detail="Result not found")
    if r.published != value:
        r.published = value
        r.published_at = datetime.now(timezone.utc) if value else None
        audit.record(db, user.username, "result.published" if value else "result.unpublished",
                     str(r.id), {"exam_id": r.exam_id, "student_id": r.student_id}, request, user.role)
        db.commit()
        if value:
            notify.notify_result_published(db, r, user.username)
    return {"id": r.id, "published": r.published}


@router.post("/{result_id}/publish")
def publish_result(result_id: int, request: Request, db: Session = Depends(get_db),
                   user: models.User = Depends(require_roles("admin"))):
    return _set_published(result_id, True, request, db, user)


@router.post("/{result_id}/unpublish")
def unpublish_result(result_id: int, request: Request, db: Session = Depends(get_db),
                     user: models.User = Depends(require_roles("admin"))):
    return _set_published(result_id, False, request, db, user)


@router.get("/admin/list")
def list_results(response: Response, q: str = Query("", max_length=60), exam_id: int | None = Query(None, ge=1),
                 published: bool | None = None, limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0),
                 db: Session = Depends(get_db), user: models.User = Depends(require_roles("admin"))):
    """Administrator view of ALL results (published or not) so they can be published/unpublished by id."""
    cond = []
    if exam_id:
        cond.append(models.Result.exam_id == exam_id)
    if published is not None:
        cond.append(models.Result.published == published)
    if q:
        cond.append(models.Student.register_number.icontains(q, autoescape=True) | models.Student.full_name.icontains(q, autoescape=True))
    base = select(models.Result).join(models.Student, models.Result.student_id == models.Student.id).where(*cond)
    response.headers["X-Total-Count"] = str(db.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rows = db.scalars(base.order_by(models.Result.id.desc()).limit(limit).offset(offset)).all()
    return [{"id": r.id, "register_number": r.student.register_number, "student_name": r.student.full_name,
             "exam_id": r.exam_id, "exam": r.exam.title if r.exam else None, "subject_code": r.exam.subject_code if r.exam else None,
             "marks": r.marks, "max_marks": r.max_marks, "grade": r.grade, "published": r.published} for r in rows]


@router.get("/{register_number}")
def get_results(register_number: str, request: Request, db: Session = Depends(get_db),
                user: models.User | None = Depends(optional_user)):
    """Published results.

    BREAKING CHANGE vs 0.1.0: requires sign-in (staff/admin, or the student the account is linked to)
    unless PUBLIC_RESULTS_ENABLED=true. Marks keyed only by a guessable register number are private data.
    """
    ip = public_guard(request)
    reg = parse_register(register_number, ip)
    if not settings.public_results_enabled:
        if user is None:
            raise HTTPException(status_code=401, detail="Sign in to view results")
        if user.role not in ("super_admin", "admin", "staff"):
            own = db.get(models.Student, user.student_id) if user.student_id else None
            if not own or own.register_number != reg:
                raise HTTPException(status_code=403, detail="You can only view your own results")
    s = db.scalar(select(models.Student).where(models.Student.register_number == reg))
    if not s:
        note_miss(ip)
        raise HTTPException(status_code=404, detail="No matching student record")
    rows = db.scalars(select(models.Result).where(models.Result.student_id == s.id,
                                                  models.Result.published == True)).all()  # noqa: E712
    return [{"exam": r.exam.title, "subject_code": r.exam.subject_code, "marks": r.marks,
             "max_marks": r.max_marks, "grade": r.grade} for r in rows if r.exam]
