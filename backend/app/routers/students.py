from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .. import models, schemas, audit, doc_models
from ..config import settings
from ..database import get_db
from ..deps import department_scope, require_roles, optional_user
from ..deps_ip import client_ip
from ..ratelimit import limiter
from ..regno import normalize_register_number

router = APIRouter(prefix="/api", tags=["Students"])
_MISS_WINDOW = 15 * 60


def public_guard(request: Request) -> str:
    """Rate-limit public register-number lookups and cap repeated misses (anti-enumeration)."""
    ip = client_ip(request)
    ok, retry = limiter.check_and_record(f"pub:{ip}", settings.public_lookup_per_minute, 60)
    if ok:
        blocked, retry = limiter.is_blocked(f"miss:{ip}", settings.public_lookup_miss_limit, _MISS_WINDOW)
        ok = not blocked
    if not ok:
        raise HTTPException(status_code=429, detail="Too many searches. Please wait and try again.",
                            headers={"Retry-After": str(retry)})
    return ip


def note_miss(ip: str) -> None:
    limiter.record(f"miss:{ip}")


def parse_register(raw: str, ip: str) -> str:
    try:
        return normalize_register_number(raw)
    except ValueError:
        note_miss(ip)
        raise HTTPException(status_code=422, detail="Enter a valid register number (letters and digits only)")


def find_student(db: Session, reg: str) -> models.Student | None:
    return db.scalar(select(models.Student).where(models.Student.register_number == reg,
                                                  models.Student.active == True))  # noqa: E712


def public_student(s: models.Student) -> dict:
    out = {"register_number": s.register_number, "department": s.department, "year": s.year}
    if settings.public_show_names:
        out["full_name"] = s.full_name
    return out


def verified_location(db: Session, hall_code: str) -> dict:
    """Public location metadata for a hall - ONLY when an administrator verified the hall record.
    Empty dict otherwise. Shared by the legacy lookup and the portal endpoints so both obey one privacy rule."""
    hall = db.scalar(select(doc_models.Hall).where(func.upper(func.trim(doc_models.Hall.code)) == (hall_code or "").upper()))
    if not (hall and hall.verified):
        return {}
    building = db.get(models.Building, hall.building_id) if hall.building_id else None
    block = db.get(models.Block, hall.block_id) if hall.block_id else None
    floor = db.get(models.Floor, hall.floor_id) if hall.floor_id else None
    # A verified hall may still have no hierarchy metadata: never serialize empty/null location values.
    return {key: value for key, value in {
        "building": building.name if building else hall.building,
        "block": block.name if block else hall.block,
        "floor": floor.name if floor else hall.floor,
        "room": hall.room,
    }.items() if value is not None and str(value).strip()}


def public_allotments(db: Session, s: models.Student) -> list[dict]:
    """Only allotments of PUBLISHED examinations are ever returned publicly."""
    rows = db.scalars(select(models.Allotment).join(models.Exam)
                      .where(models.Allotment.student_id == s.id, models.Exam.status == "published")
                      .order_by(models.Exam.exam_date, models.Exam.start_time)).all()
    output=[]
    for a in rows:
        location=verified_location(db, a.hall)
        item={"exam":a.exam.title,"subject_code":a.exam.subject_code,"date":a.exam.exam_date,
              "time":a.exam.start_time,"hall":a.hall,"seat":a.seat}
        # Preserve the legacy public response shape when no verified directory
        # location exists. Only expose location metadata after hall verification.
        if location:
            item["location"] = location
        output.append(item)
    return output


def public_source_records(db: Session, reg: str) -> list[dict]:
    """Administrator-approved PDF extraction rows for one register number (already public in /api/lookup)."""
    approved = db.scalars(select(doc_models.RegisterEntry).join(doc_models.DocumentVersion,
        doc_models.RegisterEntry.version_id == doc_models.DocumentVersion.id).join(doc_models.OfficialDocument,
        doc_models.DocumentVersion.document_id == doc_models.OfficialDocument.id).join(doc_models.PdfPage,
        doc_models.RegisterEntry.page_id == doc_models.PdfPage.id).where(
        doc_models.RegisterEntry.register_number == reg,
        doc_models.RegisterEntry.review_status == "approved",
        doc_models.DocumentVersion.review_status == "approved",
        doc_models.OfficialDocument.status == "active").order_by(doc_models.DocumentVersion.downloaded_at.desc()).limit(20)).all()
    source_records = [{"register_number": e.register_number,
        "page_number": db.get(doc_models.PdfPage, e.page_id).page_index + 1,
        "seat_number": e.seat_number, "subject_code": e.subject_code,
        "hall": (db.get(doc_models.SeatingSheet, e.sheet_id).hall_code_raw if e.sheet_id and db.get(doc_models.SeatingSheet, e.sheet_id) else None),
        "source": "administrator-approved PDF extraction"} for e in approved]
    return source_records


@router.get("/students")
def list_students(q: str = Query("", max_length=60), limit: int = Query(200, ge=1, le=200),
                  offset: int = Query(0, ge=0), db: Session = Depends(get_db),
                  user: models.User = Depends(require_roles("admin", "staff"))):
    stmt = select(models.Student).order_by(models.Student.register_number).limit(limit).offset(offset)
    if q:
        stmt = stmt.where(models.Student.register_number.icontains(q, autoescape=True)
                          | models.Student.full_name.icontains(q, autoescape=True))
    scope = department_scope(user)           # department staff only see their own department
    if scope:
        stmt = stmt.where(func.lower(models.Student.department) == scope.lower())
    return [{"id": s.id, "register_number": s.register_number, "full_name": s.full_name,
             "department": s.department, "course": s.course, "year": s.year, "active": s.active}
            for s in db.scalars(stmt).all()]


@router.get("/students/{register_number}")
def student_lookup(register_number: str, request: Request, db: Session = Depends(get_db)):
    ip = public_guard(request)
    reg = parse_register(register_number, ip)
    s = find_student(db, reg)
    if not s:
        note_miss(ip)
        raise HTTPException(status_code=404, detail="No matching student record")
    return public_student(s)


@router.get("/lookup/{register_number}")
def combined_lookup(register_number: str, request: Request, db: Session = Depends(get_db),
                    user: models.User | None = Depends(optional_user)):
    """One request for the student page: identity card + published seat allotments."""
    ip = public_guard(request)
    reg = parse_register(register_number, ip)
    s = find_student(db, reg)
    if not s:
        note_miss(ip)
        raise HTTPException(status_code=404, detail="No matching student record")
    source_records = public_source_records(db, reg)
    from .vsb_alloc import published_for_student
    return {"student": public_student(s), "allotments": public_allotments(db, s),
            "vsb_allocations": published_for_student(db, s) if settings.vsb_public_lookup else [],
            "source_documents": source_records,
            "results_available_without_signin": settings.public_results_enabled}


@router.post("/students", status_code=201)
def create_student(data: schemas.StudentCreate, request: Request, db: Session = Depends(get_db),
                   user: models.User = Depends(require_roles("admin"))):
    if db.scalar(select(models.Student).where(models.Student.register_number == data.register_number)):
        raise HTTPException(status_code=409, detail="Register number already exists")
    s = models.Student(**data.model_dump())
    db.add(s)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Register number already exists")
    audit.record(db, user.username, "student.created", data.register_number, request=request, role=user.role)
    db.commit()
    return {"id": s.id, "register_number": s.register_number}


@router.patch("/students/{register_number}")
def update_student(register_number: str, data: schemas.StudentUpdate, request: Request,
                   db: Session = Depends(get_db), user: models.User = Depends(require_roles("admin"))):
    try:
        reg = normalize_register_number(register_number)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid register number")
    s = db.scalar(select(models.Student).where(models.Student.register_number == reg))
    if not s:
        raise HTTPException(status_code=404, detail="No matching student record")
    changes = data.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(s, k, v)
    # Field names only: never write personal values into the audit log.
    audit.record(db, user.username, "student.updated", reg, {"fields": sorted(changes)}, request, user.role)
    db.commit()
    return {"id": s.id, "register_number": s.register_number, "updated": sorted(changes)}
