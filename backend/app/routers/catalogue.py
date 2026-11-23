"""Subject catalogue, academic years and examination terms."""
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .. import models, schemas, audit
from ..database import get_db
from ..deps import require_roles

router = APIRouter(prefix="/api/admin", tags=["Subjects, academic years and terms"])
STAFF = ("admin", "staff")


def _subject(s: models.Subject) -> dict:
    return {"id": s.id, "code": s.code, "name": s.name, "department": s.department, "semester": s.semester,
            "credits": s.credits, "active": s.active}


# ----------------------------------------------------------------------------- subjects
@router.get("/subjects")
def list_subjects(q: str = Query("", max_length=80), department: str = Query("", max_length=100),
                  active: bool | None = None, limit: int = Query(200, ge=1, le=500), offset: int = Query(0, ge=0),
                  db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    stmt = select(models.Subject).order_by(models.Subject.code).limit(limit).offset(offset)
    if q:
        stmt = stmt.where(models.Subject.code.icontains(q.upper(), autoescape=True)
                          | models.Subject.name.icontains(q, autoescape=True))
    if department:
        stmt = stmt.where(func.lower(models.Subject.department) == department.strip().lower())
    if active is not None:
        stmt = stmt.where(models.Subject.active == active)
    return [_subject(s) for s in db.scalars(stmt).all()]


@router.post("/subjects", status_code=201)
def create_subject(data: schemas.SubjectInput, request: Request, db: Session = Depends(get_db),
                   user: models.User = Depends(require_roles(*STAFF))):
    if db.scalar(select(models.Subject.id).where(models.Subject.code == data.code)):
        raise HTTPException(status_code=409, detail="Subject code already exists")
    s = models.Subject(**data.model_dump())
    db.add(s)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Subject code already exists")
    audit.record(db, user.username, "subject.created", s.code, {"id": s.id}, request, user.role)
    db.commit()
    return _subject(s)


@router.patch("/subjects/{subject_id}")
def update_subject(subject_id: int, data: schemas.SubjectUpdate, request: Request, db: Session = Depends(get_db),
                   user: models.User = Depends(require_roles(*STAFF))):
    s = db.get(models.Subject, subject_id)
    if not s:
        raise HTTPException(status_code=404, detail="Subject not found")
    changes = data.model_dump(exclude_unset=True)
    if "code" in changes and changes["code"] != s.code:
        if db.scalar(select(models.Subject.id).where(models.Subject.code == changes["code"])):
            raise HTTPException(status_code=409, detail="Subject code already exists")
    for k, v in changes.items():
        setattr(s, k, v)
    if "code" in changes:  # keep denormalised exam.subject_code in step with the catalogue
        for e in db.scalars(select(models.Exam).where(models.Exam.subject_id == s.id)).all():
            e.subject_code = s.code
    audit.record(db, user.username, "subject.updated", s.code, {"fields": sorted(changes)}, request, user.role)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Subject code already exists")
    return _subject(s)


@router.delete("/subjects/{subject_id}")
def delete_subject(subject_id: int, request: Request, db: Session = Depends(get_db),
                   user: models.User = Depends(require_roles("admin"))):
    s = db.get(models.Subject, subject_id)
    if not s:
        raise HTTPException(status_code=404, detail="Subject not found")
    if db.scalar(select(func.count()).select_from(models.Exam).where(models.Exam.subject_id == s.id)):
        raise HTTPException(status_code=409, detail="Subject is used by examinations; deactivate it instead")
    audit.record(db, user.username, "subject.deleted", s.code, request=request, role=user.role)
    db.delete(s)
    db.commit()
    return {"deleted": subject_id}


# ----------------------------------------------------------------------------- academic years
def _year(y: models.AcademicYear) -> dict:
    return {"id": y.id, "label": y.label, "start_date": y.start_date.isoformat(), "end_date": y.end_date.isoformat(),
            "is_current": y.is_current}


@router.get("/academic-years")
def list_years(db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    return [_year(y) for y in db.scalars(select(models.AcademicYear).order_by(models.AcademicYear.start_date.desc())).all()]


def _single_current(db: Session, keep_id: int) -> None:
    for y in db.scalars(select(models.AcademicYear).where(models.AcademicYear.is_current == True,  # noqa: E712
                                                          models.AcademicYear.id != keep_id)).all():
        y.is_current = False


@router.post("/academic-years", status_code=201)
def create_year(data: schemas.AcademicYearInput, request: Request, db: Session = Depends(get_db),
                user: models.User = Depends(require_roles("admin"))):
    if db.scalar(select(models.AcademicYear.id).where(models.AcademicYear.label == data.label)):
        raise HTTPException(status_code=409, detail="Academic year already exists")
    y = models.AcademicYear(**data.model_dump())
    db.add(y)
    db.flush()
    if y.is_current:
        _single_current(db, y.id)
    audit.record(db, user.username, "academic_year.created", y.label, request=request, role=user.role)
    db.commit()
    return _year(y)


@router.patch("/academic-years/{year_id}")
def update_year(year_id: int, data: schemas.AcademicYearInput, request: Request, db: Session = Depends(get_db),
                user: models.User = Depends(require_roles("admin"))):
    y = db.get(models.AcademicYear, year_id)
    if not y:
        raise HTTPException(status_code=404, detail="Academic year not found")
    if data.label != y.label and db.scalar(select(models.AcademicYear.id).where(models.AcademicYear.label == data.label)):
        raise HTTPException(status_code=409, detail="Academic year already exists")
    for k, v in data.model_dump().items():
        setattr(y, k, v)
    if y.is_current:
        _single_current(db, y.id)
    audit.record(db, user.username, "academic_year.updated", y.label, request=request, role=user.role)
    db.commit()
    return _year(y)


# ----------------------------------------------------------------------------- examination terms
def _term(t: models.ExamTerm) -> dict:
    return {"id": t.id, "academic_year_id": t.academic_year_id, "name": t.name, "semester_no": t.semester_no,
            "start_date": t.start_date.isoformat(), "end_date": t.end_date.isoformat(), "active": t.active}


@router.get("/terms")
def list_terms(academic_year_id: int | None = Query(None, ge=1), active: bool | None = None,
               db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    stmt = select(models.ExamTerm).order_by(models.ExamTerm.start_date.desc())
    if academic_year_id:
        stmt = stmt.where(models.ExamTerm.academic_year_id == academic_year_id)
    if active is not None:
        stmt = stmt.where(models.ExamTerm.active == active)
    return [_term(t) for t in db.scalars(stmt).all()]


def _check_term(db: Session, data: schemas.ExamTermInput, exclude_id: int | None = None) -> None:
    year = db.get(models.AcademicYear, data.academic_year_id)
    if not year:
        raise HTTPException(status_code=422, detail="Unknown academic year")
    if data.start_date < year.start_date or data.end_date > year.end_date:
        raise HTTPException(status_code=422, detail="Term dates must lie inside the academic year")
    q = select(models.ExamTerm.id).where(models.ExamTerm.academic_year_id == data.academic_year_id,
                                         func.lower(models.ExamTerm.name) == data.name.lower())
    if exclude_id:
        q = q.where(models.ExamTerm.id != exclude_id)
    if db.scalar(q):
        raise HTTPException(status_code=409, detail="A term with this name already exists in the academic year")


@router.post("/terms", status_code=201)
def create_term(data: schemas.ExamTermInput, request: Request, db: Session = Depends(get_db),
                user: models.User = Depends(require_roles("admin"))):
    _check_term(db, data)
    t = models.ExamTerm(**data.model_dump())
    db.add(t)
    db.flush()
    audit.record(db, user.username, "term.created", t.name, {"id": t.id}, request, user.role)
    db.commit()
    return _term(t)


@router.patch("/terms/{term_id}")
def update_term(term_id: int, data: schemas.ExamTermInput, request: Request, db: Session = Depends(get_db),
                user: models.User = Depends(require_roles("admin"))):
    t = db.get(models.ExamTerm, term_id)
    if not t:
        raise HTTPException(status_code=404, detail="Term not found")
    _check_term(db, data, exclude_id=t.id)
    # Exams already scheduled in this term must still fall inside the new window.
    for e in db.scalars(select(models.Exam).where(models.Exam.term_id == t.id)).all():
        if not data.start_date.isoformat() <= e.exam_date <= data.end_date.isoformat():
            raise HTTPException(status_code=409, detail=f"Examination '{e.title}' ({e.exam_date}) would fall outside the term")
    for k, v in data.model_dump().items():
        setattr(t, k, v)
    audit.record(db, user.username, "term.updated", t.name, {"id": t.id}, request, user.role)
    db.commit()
    return _term(t)
