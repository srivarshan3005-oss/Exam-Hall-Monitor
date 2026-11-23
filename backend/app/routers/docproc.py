"""Phase 3 document-processing workspace: secure PDF intake, text extraction/OCR, timetable extraction,
human review with an audit trail, and an administrator-confirmed import into the examination tables.

Roles: admin + staff may upload, process, view, preview, download and read previews;
only admin may edit, approve/reject and import. Students and anonymous users have no access.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from .. import notifications as notify
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, doc_extract as dx, doc_models as dm, models
from ..config import settings
from ..database import get_db
from ..deps import require_roles
from ..services_allocation import audiences_may_intersect, duration_minutes, load_audience
from .exams import _check_schedule

router = APIRouter(prefix="/api/admin/doc-processing", tags=["Document processing (Phase 3)"])
STAFF = ("admin", "staff")
ADMIN = ("admin",)
DEFAULT_VENUE = "To be announced"
FIELDS_EDITABLE = ("exam_date", "start_time", "end_time", "session", "subject_code", "subject_name",
                   "department", "year", "semester", "subject_id")
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_ACTIVE_CONTENT = re.compile(rb"/(JavaScript|JS|Launch)\b")


def now():
    return datetime.now(timezone.utc)


def storage_dir() -> Path:
    base = Path(settings.document_storage_dir) if settings.document_storage_dir else Path(__file__).resolve().parents[2] / "uploads"
    base.mkdir(parents=True, exist_ok=True)
    return base.resolve()


def stored_path(v: dm.DocumentVersion) -> Path:
    """Resolve the stored file and make sure it is inside the storage directory (path-traversal guard)."""
    root = storage_dir()
    p = Path(v.storage_path)
    p = (root / p.name) if not p.is_absolute() else p
    try:
        rp = p.resolve(strict=True)
    except (FileNotFoundError, OSError):
        raise HTTPException(404, "The stored PDF file is missing")
    if root not in rp.parents:
        raise HTTPException(404, "The stored PDF file is unavailable")
    return rp


def safe_display_name(name: str | None) -> str:
    base = os.path.basename((name or "document.pdf").replace("\\", "/"))
    base = re.sub(r"[^A-Za-z0-9._ \-()]", "_", base)[:120].strip(" .") or "document.pdf"
    return base if base.lower().endswith(".pdf") else base + ".pdf"


def event(db: Session, version_id: int, ev: str, actor: str, detail: str | dict | None = None) -> None:
    if detail is not None and not isinstance(detail, str):
        detail = json.dumps(detail, default=str, sort_keys=True)
    db.add(dm.DocumentEvent(version_id=version_id, event=ev, actor=actor[:80], detail=(detail or None) and detail[:1000]))


def _j(v) -> list:
    try:
        return json.loads(v) if v else []
    except ValueError:
        return []


def get_version(db: Session, vid: int) -> dm.DocumentVersion:
    v = db.get(dm.DocumentVersion, vid)
    if not v:
        raise HTTPException(404, "Document version not found")
    return v


def version_dict(db: Session, v: dm.DocumentVersion) -> dict:
    d = v.document
    counts = dict(db.execute(select(dm.TimetableEntry.review_status, func.count()).where(
        dm.TimetableEntry.version_id == v.id).group_by(dm.TimetableEntry.review_status)).all())
    ex = db.scalar(select(dm.DocumentExtraction).where(dm.DocumentExtraction.version_id == v.id))
    return {"document_id": d.id, "version_id": v.id, "title": d.title, "kind": d.doc_kind, "origin": d.origin,
            "source": d.source_label, "exam_name": d.exam_name, "term_id": d.term_id,
            "original_filename": d.original_filename, "uploaded_by": d.uploaded_by,
            "uploaded_at": (d.discovered_at or v.downloaded_at).isoformat() if (d.discovered_at or v.downloaded_at) else None,
            "size_bytes": v.size_bytes, "sha256": v.sha256, "pages": v.page_count,
            "processing_status": v.processing_status, "processing_error": v.processing_error,
            "review_status": v.review_status, "reviewed_by": v.reviewed_by,
            "reviewed_at": v.reviewed_at.isoformat() if v.reviewed_at else None,
            "ocr_used": v.ocr_used, "processed_at": v.processed_at.isoformat() if v.processed_at else None,
            "entry_counts": counts, "imported_at": ex.imported_at.isoformat() if ex and ex.imported_at else None}


def entry_dict(e: dm.TimetableEntry) -> dict:
    return {"id": e.id, "row_no": e.row_no, "page_number": (e.page_index or 0) + 1,
            "exam_date": e.exam_date.isoformat() if e.exam_date else None, "start_time": e.start_time,
            "end_time": e.end_time, "session": e.session, "subject_code": e.subject_code,
            "subject_name": e.subject_name, "department": e.department, "year": e.year, "semester": e.semester,
            "subject_id": e.subject_id, "raw_text": e.raw_text, "source": e.source, "confidence": e.confidence,
            "flags": _j(e.flags), "uncertain_fields": _j(e.uncertain_fields), "edited": e.edited,
            "review_status": e.review_status, "reviewed_by": e.reviewed_by, "imported_exam_id": e.imported_exam_id,
            "low_confidence": (e.confidence is not None and e.confidence < dx.LOW_CONF)}


def header_dict(x: dm.DocumentExtraction | None, with_registers: bool = False) -> dict | None:
    if not x:
        return None
    regs = _j(x.register_numbers)
    out = {"exam_name": x.exam_name, "session_label": x.session_label, "academic_year": x.academic_year,
           "department": x.department, "semester": x.semester, "instructions": _j(x.instructions),
           "flags": _j(x.flags), "issues": _j(x.issues), "ocr_language": x.ocr_language,
           "register_numbers_found": len(regs), "extracted_at": x.extracted_at.isoformat(),
           "imported_at": x.imported_at.isoformat() if x.imported_at else None}
    if with_registers:
        out["register_numbers"] = regs
    return out


# ----------------------------------------------------------------------------- capabilities / list
@router.get("/capabilities")
def capabilities(user: models.User = Depends(require_roles(*STAFF))):
    langs = dx.available_ocr_languages()
    return {"ocr_available": dx.ocr_available(), "ocr_languages": langs,
            "default_language": settings.ocr_default_language, "max_upload_mb": settings.max_upload_mb,
            "max_pages": dx.MAX_PAGES, "kinds": list(dm.DOC_KINDS), "extractor_version": dx.EXTRACTOR_VERSION,
            "can_review": user.role in ("admin", "super_admin")}


@router.get("")
def list_documents(q: str = Query("", max_length=80), status: str = Query("", max_length=20),
                   kind: str = Query("", max_length=30), limit: int = Query(100, ge=1, le=300),
                   offset: int = Query(0, ge=0), db: Session = Depends(get_db),
                   user: models.User = Depends(require_roles(*STAFF))):
    stmt = (select(dm.DocumentVersion).join(dm.OfficialDocument)
            .order_by(dm.DocumentVersion.id.desc()).limit(limit).offset(offset))
    if q:
        stmt = stmt.where(dm.OfficialDocument.title.icontains(q, autoescape=True)
                          | dm.OfficialDocument.exam_name.icontains(q, autoescape=True)
                          | dm.OfficialDocument.source_label.icontains(q, autoescape=True))
    if status:
        stmt = stmt.where(dm.DocumentVersion.processing_status == status)
    if kind:
        stmt = stmt.where(dm.OfficialDocument.doc_kind == kind)
    return [version_dict(db, v) for v in db.scalars(stmt).all()]


# ----------------------------------------------------------------------------- upload
@router.post("/upload", status_code=201)
async def upload(request: Request, file: UploadFile = File(...), title: str = Form(...), doc_kind: str = Form("timetable"),
                 source_label: str = Form(""), exam_name: str = Form(""), term_id: int | None = Form(None),
                 db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    title = title.strip()
    if not 1 <= len(title) <= 300:
        raise HTTPException(422, "A document title of 1–300 characters is required")
    if doc_kind not in dm.DOC_KINDS:
        raise HTTPException(422, "Invalid document type")
    if len(source_label) > 200 or len(exam_name) > 200:
        raise HTTPException(422, "Source and examination name must be 200 characters or fewer")
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(415, "Only .pdf files are accepted")
    if file.content_type not in (None, "", "application/pdf", "application/x-pdf", "application/octet-stream"):
        raise HTTPException(415, "Only PDF documents are accepted")
    limit = settings.max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"PDF exceeds the {settings.max_upload_mb} MB upload limit")
    if not data.startswith(b"%PDF-"):
        raise HTTPException(415, "The uploaded file is not a valid PDF")
    if _ACTIVE_CONTENT.search(data):
        raise HTTPException(422, "PDFs containing JavaScript or launch actions are rejected for safety")
    if term_id is not None and not db.get(models.ExamTerm, term_id):
        raise HTTPException(422, "Unknown examination term")
    digest = hashlib.sha256(data).hexdigest()
    dup = db.scalar(select(dm.DocumentVersion).where(dm.DocumentVersion.sha256 == digest))
    if dup:
        raise HTTPException(409, {"message": "This exact PDF has already been uploaded", "duplicate": True,
                                  "document_id": dup.document_id, "version_id": dup.id,
                                  "title": dup.document.title})
    try:  # validate structure without executing anything
        import fitz
        probe = fitz.open(stream=data, filetype="pdf")
        pages = len(probe)
        locked = probe.needs_pass or probe.is_encrypted
        probe.close()
    except Exception:
        raise HTTPException(422, "The PDF is damaged or unreadable")
    if locked:
        raise HTTPException(422, "Encrypted or password-protected PDFs are not supported")
    if not 1 <= pages <= dx.MAX_PAGES:
        raise HTTPException(422, f"PDF must have 1–{dx.MAX_PAGES} pages")
    path = storage_dir() / (uuid.uuid4().hex + ".pdf")
    path.write_bytes(data)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    doc = dm.OfficialDocument(source_url="upload://" + digest, title=title, doc_kind=doc_kind, origin="upload",
                              source_label=source_label.strip() or None, exam_name=exam_name.strip() or None,
                              term_id=term_id, uploaded_by=user.username,
                              original_filename=safe_display_name(file.filename))
    db.add(doc)
    db.flush()
    v = dm.DocumentVersion(document_id=doc.id, version_no=1, sha256=digest, size_bytes=len(data), page_count=pages,
                           storage_path=str(path), processing_status="pending")
    db.add(v)
    db.flush()
    event(db, v.id, "uploaded", user.username, {"bytes": len(data), "pages": pages, "kind": doc_kind})
    audit.record(db, user.username, "document.uploaded", str(doc.id), {"version": v.id, "kind": doc_kind, "bytes": len(data)},
                 request, user.role)
    db.commit()
    return version_dict(db, v)


# ----------------------------------------------------------------------------- processing
@router.post("/{version_id}/process")
def process(version_id: int, request: Request, force_ocr: bool = Query(False), lang: str = Query("", max_length=40),
            db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    v = get_version(db, version_id)
    path = stored_path(v)
    lang = lang or settings.ocr_default_language
    if not dx.LANG_RE.match(lang):
        raise HTTPException(422, "OCR language must be a Tesseract code such as eng or tam+eng")
    if force_ocr and not dx.ocr_available():
        raise HTTPException(503, "OCR is not available on this server (install PyMuPDF, pytesseract and Tesseract; see docs/OCR.md)")
    if db.scalar(select(dm.TimetableEntry.id).where(dm.TimetableEntry.version_id == v.id,
                                                    dm.TimetableEntry.review_status == "imported").limit(1)):
        raise HTTPException(409, "Entries from this document were already imported; re-processing is blocked")
    if v.processing_status == "processing":
        raise HTTPException(409, "This document is already being processed")
    v.processing_status = "processing"
    db.commit()
    try:
        pages = dx.read_pdf(str(path), lang=lang, force_ocr=force_ocr)
        doc_kind = db.scalar(select(dm.OfficialDocument.doc_kind).where(dm.OfficialDocument.id == v.document_id))
        if doc_kind in ("hall_allotment", "seating_allotment"):
            # allotment PDFs are read by the dedicated VSB parsers (app/vsb_alloc); the timetable heuristics would only produce junk rows
            parsed = dx.Parsed(dx.Header(), [], [])
        else:
            parsed = dx.parse_timetable(pages)
    except Exception as exc:
        db.rollback()
        v = get_version(db, version_id)
        v.processing_status = "failed"
        v.processing_error = str(exc)[:500]
        event(db, v.id, "processing_failed", user.username, str(exc)[:300])
        db.commit()
        raise HTTPException(422, f"PDF processing failed: {str(exc)[:200]}")
    # replace previous *unreviewed machine output* for this version; human edit history is kept
    for old in db.scalars(select(dm.TimetableEntry).where(dm.TimetableEntry.version_id == v.id)).all():
        db.delete(old)
    old_x = db.scalar(select(dm.DocumentExtraction).where(dm.DocumentExtraction.version_id == v.id))
    if old_x:
        db.delete(old_x)
    db.flush()
    existing_pages = {p.page_index: p for p in db.scalars(select(dm.PdfPage).where(dm.PdfPage.version_id == v.id)).all()}
    for p in pages:
        row = existing_pages.get(p.index) or dm.PdfPage(version_id=v.id, page_index=p.index)
        row.width_pt, row.height_pt = p.width, p.height
        row.text_content = p.text[:200_000]
        row.text_chars = len(p.text)
        row.text_sha256 = hashlib.sha256(p.text.encode("utf-8")).hexdigest()
        row.ocr_used = p.method == "ocr"
        row.ocr_confidence = p.ocr_confidence
        row.extraction_method = p.method
        row.page_warning = (p.warning or None) and p.warning[:300]
        db.add(row)
    fp = hashlib.sha256(dx.normalise_title("\n".join(p.text for p in pages)).encode()).hexdigest()
    h = parsed.header
    issues = list(parsed.issues)
    twin = db.scalar(select(dm.DocumentExtraction).where(dm.DocumentExtraction.text_fingerprint == fp,
                                                         dm.DocumentExtraction.version_id != v.id))
    if twin:
        issues.append(f"Possible duplicate: identical text to document version #{twin.version_id}")
        h.flags.append("possible_duplicate_document")
    db.add(dm.DocumentExtraction(
        version_id=v.id, exam_name=h.exam_name, session_label=h.session_label, academic_year=h.academic_year,
        department=h.department, semester=h.semester, instructions=json.dumps(h.instructions),
        register_numbers=json.dumps(h.register_numbers), flags=json.dumps(sorted(set(h.flags))),
        issues=json.dumps(issues), ocr_language=lang if any(p.method == "ocr" for p in pages) else None,
        text_fingerprint=fp))
    for e in parsed.entries:
        db.add(dm.TimetableEntry(
            version_id=v.id, row_no=e.row_no, page_index=e.page_index, exam_date=e.exam_date, start_time=e.start_time,
            end_time=e.end_time, session=e.session, subject_code=e.subject_code, subject_name=e.subject_name,
            department=e.department or h.department, year=e.year, semester=e.semester or h.semester,
            raw_text=e.raw_text, source=e.source, confidence=e.confidence, flags=json.dumps(e.flags),
            uncertain_fields=json.dumps(e.uncertain_fields), review_status="pending"))
    ocr_pages = sum(1 for p in pages if p.method == "ocr")
    needs = (doc_kind not in ("hall_allotment", "seating_allotment")) and (not parsed.entries or issues or any(e.confidence < dx.LOW_CONF or e.uncertain_fields for e in parsed.entries))
    v.page_count = len(pages)
    v.ocr_used = ocr_pages > 0
    v.extractor_version = dx.EXTRACTOR_VERSION
    v.processed_at = now()
    v.processing_error = None
    v.processing_status = "needs_review" if needs else "processed"
    v.review_status = "pending"
    event(db, v.id, "processed", user.username, {"pages": len(pages), "ocr_pages": ocr_pages, "entries": len(parsed.entries),
                                                "language": lang, "forced_ocr": force_ocr})
    audit.record(db, user.username, "document.processed", str(v.id),
                 {"pages": len(pages), "ocr_pages": ocr_pages, "entries": len(parsed.entries)}, request, user.role)
    db.commit()
    return {**version_dict(db, v), "issues": issues, "ocr_pages": ocr_pages, "entries": len(parsed.entries)}


# ----------------------------------------------------------------------------- detail / files
@router.get("/{version_id}")
def detail(version_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    v = get_version(db, version_id)
    ex = db.scalar(select(dm.DocumentExtraction).where(dm.DocumentExtraction.version_id == v.id))
    pages = db.scalars(select(dm.PdfPage).where(dm.PdfPage.version_id == v.id).order_by(dm.PdfPage.page_index)).all()
    return {**version_dict(db, v), "header": header_dict(ex),
            "page_info": [{"page_number": p.page_index + 1, "method": p.extraction_method, "chars": p.text_chars,
                           "ocr_confidence": p.ocr_confidence, "warning": p.page_warning} for p in pages]}


@router.get("/{version_id}/pages/{page_number}/text")
def page_text(version_id: int, page_number: int, db: Session = Depends(get_db),
              user: models.User = Depends(require_roles(*STAFF))):
    get_version(db, version_id)
    p = db.scalar(select(dm.PdfPage).where(dm.PdfPage.version_id == version_id, dm.PdfPage.page_index == page_number - 1))
    if not p:
        raise HTTPException(404, "Page has not been processed")
    return {"page_number": page_number, "method": p.extraction_method, "ocr_confidence": p.ocr_confidence,
            "warning": p.page_warning, "text": p.text_content or ""}


@router.get("/{version_id}/pages/{page_number}/preview")
def preview(version_id: int, page_number: int, db: Session = Depends(get_db),
            user: models.User = Depends(require_roles(*STAFF))):
    v = get_version(db, version_id)
    if page_number < 1 or (v.page_count and page_number > v.page_count):
        raise HTTPException(404, "Page not found")
    try:
        png = dx.render_page_png(str(stored_path(v)), page_number - 1)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, "The page could not be rendered")
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, no-store"})


@router.get("/{version_id}/download")
def download(version_id: int, request: Request, db: Session = Depends(get_db),
             user: models.User = Depends(require_roles(*STAFF))):
    v = get_version(db, version_id)
    path = stored_path(v)
    event(db, v.id, "downloaded", user.username)
    audit.record(db, user.username, "document.downloaded", str(v.id), None, request, user.role)
    db.commit()
    name = safe_display_name(v.document.original_filename or v.document.title)

    def stream():
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                yield chunk
    return StreamingResponse(stream(), media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff", "Content-Length": str(path.stat().st_size)})


@router.get("/{version_id}/history")
def history(version_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    get_version(db, version_id)
    ev = db.scalars(select(dm.DocumentEvent).where(dm.DocumentEvent.version_id == version_id)
                    .order_by(dm.DocumentEvent.id.desc()).limit(300)).all()
    ed = db.scalars(select(dm.ExtractionEdit).where(dm.ExtractionEdit.version_id == version_id)
                    .order_by(dm.ExtractionEdit.id.desc()).limit(500)).all()
    return {"events": [{"event": e.event, "actor": e.actor, "detail": e.detail, "at": e.created_at.isoformat()} for e in ev],
            "edits": [{"entry_id": e.entry_id, "field": e.field, "old": e.old_value, "new": e.new_value,
                       "by": e.edited_by, "at": e.edited_at.isoformat(), "reason": e.reason} for e in ed]}


# ----------------------------------------------------------------------------- entries (review workspace)
@router.get("/{version_id}/review")
def review(version_id: int, status: str = Query("", max_length=15), only_uncertain: bool = False,
           db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    v = get_version(db, version_id)
    ex = db.scalar(select(dm.DocumentExtraction).where(dm.DocumentExtraction.version_id == v.id))
    stmt = select(dm.TimetableEntry).where(dm.TimetableEntry.version_id == v.id).order_by(dm.TimetableEntry.row_no)
    if status:
        stmt = stmt.where(dm.TimetableEntry.review_status == status)
    rows = [entry_dict(e) for e in db.scalars(stmt).all()]
    if only_uncertain:
        rows = [r for r in rows if r["uncertain_fields"] or r["low_confidence"]]
    subjects = {s.code.upper(): s for s in db.scalars(select(models.Subject)).all()}
    for r in rows:
        s = subjects.get(re.sub(r"\s+", "", (r["subject_code"] or "").upper()))
        r["catalogue_match"] = {"id": s.id, "name": s.name, "active": s.active} if s else None
    return {"version": version_dict(db, v), "header": header_dict(ex), "entries": rows}


class HeaderEdit(BaseModel):
    exam_name: str | None = Field(default=None, max_length=200)
    session_label: str | None = Field(default=None, pattern=r"^(FN|AN)$")
    academic_year: str | None = Field(default=None, max_length=20)
    department: str | None = Field(default=None, max_length=150)
    semester: int | None = Field(default=None, ge=1, le=12)
    reason: str | None = Field(default=None, max_length=300)


@router.patch("/{version_id}/header")
def edit_header(version_id: int, data: HeaderEdit, request: Request, db: Session = Depends(get_db),
                user: models.User = Depends(require_roles(*ADMIN))):
    v = get_version(db, version_id)
    ex = db.scalar(select(dm.DocumentExtraction).where(dm.DocumentExtraction.version_id == v.id))
    if not ex:
        raise HTTPException(409, "Process the document first")
    changes = data.model_dump(exclude_unset=True)
    reason = changes.pop("reason", None)
    for k, new in changes.items():
        new = (new.strip() if isinstance(new, str) else new) or None
        old = getattr(ex, k)
        if old != new:
            db.add(dm.ExtractionEdit(version_id=v.id, entry_id=None, field=k, old_value=None if old is None else str(old),
                                     new_value=None if new is None else str(new), edited_by=user.username, reason=reason))
            setattr(ex, k, new)
    event(db, v.id, "header_edited", user.username, sorted(changes))
    audit.record(db, user.username, "document.header_edited", str(v.id), {"fields": sorted(changes)}, request, user.role)
    db.commit()
    return header_dict(ex)


class EntryEdit(BaseModel):
    exam_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    start_time: str | None = None
    end_time: str | None = None
    session: str | None = Field(default=None, pattern=r"^(FN|AN)$")
    subject_code: str | None = Field(default=None, max_length=30)
    subject_name: str | None = Field(default=None, max_length=200)
    department: str | None = Field(default=None, max_length=150)
    year: int | None = Field(default=None, ge=1, le=6)
    semester: int | None = Field(default=None, ge=1, le=12)
    subject_id: int | None = Field(default=None, ge=1)
    reason: str | None = Field(default=None, max_length=300)


def _norm_code(c: str | None) -> str | None:
    c = re.sub(r"\s+", "", (c or "").upper())
    return c or None


def _validate_entry_values(vals: dict) -> None:
    for k in ("start_time", "end_time"):
        if vals.get(k) and not _TIME.match(vals[k]):
            raise HTTPException(422, f"{k} must be HH:MM (24-hour)")
    if vals.get("start_time") and vals.get("end_time") and vals["end_time"] <= vals["start_time"]:
        raise HTTPException(422, "end_time must be later than start_time")
    if vals.get("exam_date"):
        try:
            d = date.fromisoformat(vals["exam_date"])
        except ValueError:
            raise HTTPException(422, "exam_date is not a valid calendar date")
        if not 2000 <= d.year <= 2100:
            raise HTTPException(422, "exam_date year is implausible")
    if vals.get("subject_code") and not re.fullmatch(r"[A-Z0-9][A-Z0-9\-_/]{1,29}", vals["subject_code"]):
        raise HTTPException(422, "Subject code may contain letters, digits, '-', '_' or '/' only")


def _editable_entry(db: Session, entry_id: int) -> dm.TimetableEntry:
    e = db.get(dm.TimetableEntry, entry_id)
    if not e:
        raise HTTPException(404, "Timetable entry not found")
    if e.review_status == "imported":
        raise HTTPException(409, "This entry was already imported and can no longer be edited here")
    return e


@router.patch("/entries/{entry_id}")
def edit_entry(entry_id: int, data: EntryEdit, request: Request, db: Session = Depends(get_db),
               user: models.User = Depends(require_roles(*ADMIN))):
    e = _editable_entry(db, entry_id)
    changes = data.model_dump(exclude_unset=True)
    reason = changes.pop("reason", None)
    if "subject_code" in changes:
        changes["subject_code"] = _norm_code(changes["subject_code"])
    for k in list(changes):
        if isinstance(changes[k], str):
            changes[k] = changes[k].strip() or None
    if "exam_date" in changes and changes["exam_date"]:
        pass
    merged = {k: (getattr(e, k).isoformat() if k == "exam_date" and getattr(e, k) else getattr(e, k)) for k in FIELDS_EDITABLE}
    merged.update(changes)
    _validate_entry_values(merged)
    if changes.get("subject_id") and not db.get(models.Subject, changes["subject_id"]):
        raise HTTPException(422, "Unknown subject")
    changed = []
    for k, new in changes.items():
        old = getattr(e, k)
        oldv = old.isoformat() if isinstance(old, date) else old
        if oldv == new:
            continue
        db.add(dm.ExtractionEdit(version_id=e.version_id, entry_id=e.id, field=k, old_value=None if oldv is None else str(oldv),
                                 new_value=None if new is None else str(new), edited_by=user.username, reason=reason))
        setattr(e, k, date.fromisoformat(new) if k == "exam_date" and new else new)
        changed.append(k)
    if changed:
        e.edited = True
        e.uncertain_fields = json.dumps([f for f in _j(e.uncertain_fields) if f not in changed])
        e.review_status = "pending"          # a corrected row must be approved again
        e.reviewed_by = e.reviewed_at = None
        v = get_version(db, e.version_id)
        v.review_status = "pending"
        event(db, v.id, "entry_edited", user.username, {"entry": e.id, "fields": changed})
        audit.record(db, user.username, "document.entry_edited", str(e.id), {"fields": changed, "version": v.id}, request, user.role)
    db.commit()
    return entry_dict(e)


@router.post("/{version_id}/entries", status_code=201)
def add_entry(version_id: int, data: EntryEdit, request: Request, db: Session = Depends(get_db),
              user: models.User = Depends(require_roles(*ADMIN))):
    v = get_version(db, version_id)
    vals = data.model_dump(exclude_unset=True)
    reason = vals.pop("reason", None)
    if "subject_code" in vals:
        vals["subject_code"] = _norm_code(vals["subject_code"])
    _validate_entry_values(vals)
    nxt = (db.scalar(select(func.max(dm.TimetableEntry.row_no)).where(dm.TimetableEntry.version_id == v.id)) or 0) + 1
    e = dm.TimetableEntry(version_id=v.id, row_no=nxt, page_index=0, source="manual", confidence=1.0, flags="[]",
                          uncertain_fields="[]", edited=True, review_status="pending",
                          raw_text="Added manually by " + user.username)
    for k, val in vals.items():
        setattr(e, k, date.fromisoformat(val) if k == "exam_date" and val else val)
    db.add(e)
    db.flush()
    db.add(dm.ExtractionEdit(version_id=v.id, entry_id=e.id, field="(row added)", old_value=None,
                             new_value=json.dumps(vals, default=str)[:500], edited_by=user.username, reason=reason))
    v.review_status = "pending"
    event(db, v.id, "entry_added", user.username, {"entry": e.id})
    audit.record(db, user.username, "document.entry_added", str(e.id), {"version": v.id}, request, user.role)
    db.commit()
    return entry_dict(e)


def completeness_problems(e: dm.TimetableEntry) -> list[str]:
    p = []
    if not e.exam_date:
        p.append("exam date is missing")
    if not (e.start_time and e.end_time):
        p.append("start/end time is missing")
    elif e.end_time <= e.start_time:
        p.append("end time is not after start time")
    if not (e.subject_code or e.subject_id):
        p.append("subject code is missing")
    return p


class Decision(BaseModel):
    decision: str = Field(pattern=r"^(approved|rejected|pending)$")


@router.post("/entries/{entry_id}/decision")
def entry_decision(entry_id: int, data: Decision, request: Request, db: Session = Depends(get_db),
                   user: models.User = Depends(require_roles(*ADMIN))):
    e = _editable_entry(db, entry_id)
    if data.decision == "approved":
        problems = completeness_problems(e)
        if problems:
            raise HTTPException(422, "Cannot approve: " + "; ".join(problems) + ". Edit the row first.")
    e.review_status = data.decision
    e.reviewed_by, e.reviewed_at = user.username, now()
    v = get_version(db, e.version_id)
    v.review_status = "pending"
    event(db, v.id, "entry_" + data.decision, user.username, {"entry": e.id})
    audit.record(db, user.username, "document.entry_" + data.decision, str(e.id), {"version": v.id}, request, user.role)
    db.commit()
    return entry_dict(e)


class BulkDecision(BaseModel):
    decision: str = Field(pattern=r"^(approved|rejected)$")
    ids: list[int] | None = None
    only_confident: bool = True      # approve only complete, certain rows (no flagged fields, confidence >= threshold)


@router.post("/{version_id}/entries/bulk-decision")
def bulk_decision(version_id: int, data: BulkDecision, request: Request, db: Session = Depends(get_db),
                  user: models.User = Depends(require_roles(*ADMIN))):
    v = get_version(db, version_id)
    rows = db.scalars(select(dm.TimetableEntry).where(dm.TimetableEntry.version_id == v.id,
                                                      dm.TimetableEntry.review_status.in_(("pending", "approved", "rejected")))).all()
    if data.ids is not None:
        rows = [r for r in rows if r.id in set(data.ids)]
    changed, skipped = 0, []
    for e in rows:
        if data.decision == "approved":
            if completeness_problems(e) or (data.only_confident and (_j(e.uncertain_fields) or (e.confidence or 0) < dx.LOW_CONF)):
                skipped.append(e.id)
                continue
        if e.review_status != data.decision:
            e.review_status, e.reviewed_by, e.reviewed_at = data.decision, user.username, now()
            changed += 1
    v.review_status = "pending"
    event(db, v.id, "bulk_" + data.decision, user.username, {"changed": changed, "skipped": len(skipped)})
    audit.record(db, user.username, "document.bulk_" + data.decision, str(v.id), {"changed": changed, "skipped": len(skipped)},
                 request, user.role)
    db.commit()
    return {"changed": changed, "skipped_ids": skipped}


class DocDecision(BaseModel):
    decision: str = Field(pattern=r"^(approved|rejected)$")
    note: str | None = Field(default=None, max_length=300)


@router.post("/{version_id}/decision")
def document_decision(version_id: int, data: DocDecision, request: Request, db: Session = Depends(get_db),
                      user: models.User = Depends(require_roles(*ADMIN))):
    v = get_version(db, version_id)
    if v.processing_status not in ("processed", "needs_review"):
        raise HTTPException(409, "Process the document before reviewing it")
    if data.decision == "approved":
        counts = dict(db.execute(select(dm.TimetableEntry.review_status, func.count()).where(
            dm.TimetableEntry.version_id == v.id).group_by(dm.TimetableEntry.review_status)).all())
        if counts.get("pending"):
            raise HTTPException(409, f"{counts['pending']} extracted row(s) still need an approve or reject decision")
        if not counts.get("approved") and not counts.get("imported"):
            raise HTTPException(409, "Approve at least one timetable row before approving the document")
    v.review_status, v.reviewed_by, v.reviewed_at = data.decision, user.username, now()
    event(db, v.id, "document_" + data.decision, user.username, data.note)
    audit.record(db, user.username, "document." + data.decision, str(v.id), {"note": data.note}, request, user.role)
    db.commit()
    return version_dict(db, v)


# ----------------------------------------------------------------------------- import planning
class ImportOptions(BaseModel):
    create_missing_subjects: bool = False
    term_id: int | None = Field(default=None, ge=1)
    update_existing_entry_ids: list[int] = Field(default_factory=list)
    skip_blocked: bool = False
    signature: str | None = None
    confirm: bool = False


def _times_overlap(a, b) -> bool:
    return a.start_time < b.end_time and b.start_time < a.end_time


def _audience(dept, year):
    return (dept or None, year or None)


def _compat(a, b) -> bool:
    return a is None or b is None or str(a).casefold() == str(b).casefold()


def build_plan(db: Session, v: dm.DocumentVersion, opts: ImportOptions) -> dict:
    entries = db.scalars(select(dm.TimetableEntry).where(dm.TimetableEntry.version_id == v.id,
                                                         dm.TimetableEntry.review_status == "approved")
                         .order_by(dm.TimetableEntry.row_no)).all()
    subjects = {s.code.upper(): s for s in db.scalars(select(models.Subject)).all()}
    by_id = {s.id: s for s in subjects.values()}
    all_codes = list(subjects)
    student_depts = {str(d).casefold(): d for d in db.scalars(select(models.Student.department).distinct()).all() if d}
    term = db.get(models.ExamTerm, opts.term_id or v.document.term_id) if (opts.term_id or v.document.term_id) else None
    existing = db.scalars(select(models.Exam)).all()
    by_date: dict[str, list[models.Exam]] = {}
    for x in existing:
        by_date.setdefault(x.exam_date, []).append(x)
    items, seen, accepted = [], {}, []
    today = date.today()
    for e in entries:
        it = {"entry_id": e.id, "row_no": e.row_no, "subject_code": e.subject_code,
              "subject_name": e.subject_name, "exam_date": e.exam_date.isoformat() if e.exam_date else None,
              "start_time": e.start_time, "end_time": e.end_time, "department": e.department, "year": e.year,
              "action": "create", "errors": [], "warnings": [], "subject": None, "existing_exam_id": None,
              "suggestions": [], "audience_rule": None}
        items.append(it)
        problems = completeness_problems(e)
        if problems:
            it["errors"] += problems
        # ---- subject mapping
        subj = by_id.get(e.subject_id) if e.subject_id else subjects.get(_norm_code(e.subject_code) or "")
        if subj:
            it["subject"] = {"id": subj.id, "code": subj.code, "name": subj.name}
            if not subj.active:
                it["errors"].append("catalogue subject is inactive")
            if e.subject_name and subj.name:
                r = difflib.SequenceMatcher(None, dx.normalise_title(e.subject_name), dx.normalise_title(subj.name)).ratio()
                if r < 0.6:
                    it["warnings"].append(f"extracted name differs from catalogue name “{subj.name}”")
        elif e.subject_code:
            norm = e.subject_code.upper().translate(str.maketrans("OISB", "0158"))
            it["suggestions"] = [c for c in difflib.get_close_matches(e.subject_code.upper(), all_codes, 3, 0.75)]
            it["suggestions"] += [c for c in all_codes if c.translate(str.maketrans("OISB", "0158")) == norm
                                  and c not in it["suggestions"]][:3]
            if opts.create_missing_subjects and e.subject_name:
                it["action"] = "create_with_new_subject"
                it["warnings"].append("subject is not in the catalogue and will be created")
            else:
                it["errors"].append("subject code is not in the catalogue (map it, or allow creating subjects)"
                                    + ("" if e.subject_name else "; no subject name to create it with"))
        code = (subj.code if subj else _norm_code(e.subject_code)) or ""
        # ---- term / date sanity
        if e.exam_date:
            if term and not term.start_date <= e.exam_date <= term.end_date:
                it["errors"].append(f"date is outside the term ({term.start_date} to {term.end_date})")
            if e.exam_date < today:
                it["warnings"].append("date is in the past")
        # ---- audience rule
        if e.department or e.year:
            dept = student_depts.get(str(e.department).casefold()) if e.department else None
            if e.department and not dept:
                it["warnings"].append("department does not match any student record; no audience rule will be created")
                it["audience_rule"] = {"department": None, "year": None, "created": False} if not e.year else {"department": None, "year": e.year, "created": True}
            else:
                it["audience_rule"] = {"department": dept, "year": e.year, "created": True}
        if it["errors"]:
            it["action"] = "blocked"
            continue
        key = (code, it["exam_date"], e.start_time, e.end_time, str(e.department or "").casefold(), e.year)
        if key in seen:
            it["action"] = "skip_duplicate_in_document"
            it["warnings"].append(f"duplicate of row {seen[key]} in this document")
            continue
        seen[key] = e.row_no
        # ---- existing examinations
        same_day = by_date.get(it["exam_date"], [])
        exact = [x for x in same_day if x.subject_code.upper() == code and x.start_time == e.start_time and x.end_time == e.end_time]
        diff_time = [x for x in same_day if x.subject_code.upper() == code and x not in exact]
        if exact:
            it["action"], it["existing_exam_id"] = "skip_existing", exact[0].id
            it["warnings"].append(f"identical examination already exists (#{exact[0].id}); left unchanged")
            continue
        if diff_time:
            x = diff_time[0]
            it["existing_exam_id"] = x.id
            if e.id in opts.update_existing_entry_ids:
                it["action"] = "update_existing"
                it["warnings"].append(f"will reschedule existing examination #{x.id} from {x.start_time}-{x.end_time}")
            else:
                it["action"] = "conflict_existing"
                it["errors"].append(f"examination #{x.id} for this subject exists that day at {x.start_time}-{x.end_time}; "
                                    "tick 'update existing' for this row to reschedule it")
                continue
        other_dates = [x.id for x in existing if x.subject_code.upper() == code and x.exam_date != it["exam_date"]]
        if other_dates and it["action"] != "update_existing":
            it["warnings"].append(f"subject also scheduled on another date (exam #{other_dates[0]}); a new examination will be added")
        # ---- time conflicts: inside this document
        probe = models.Exam(start_time=e.start_time, end_time=e.end_time)
        for prev_it, prev in accepted:
            if prev.exam_date == e.exam_date and _times_overlap(prev, e) and prev_it["subject_code"] != it["subject_code"]:
                known = (e.department or e.year) and (prev.department or prev.year)
                if _compat(prev.department, e.department) and _compat(prev.year, e.year):
                    msg = f"time overlaps row {prev.row_no} ({prev.subject_code}) for an intersecting audience"
                    if known or (e.department or e.year or prev.department or prev.year):
                        it["errors"].append(msg)
                    else:
                        it["warnings"].append(msg + " (no department/year printed; audience unknown)")
        # ---- time conflicts: existing exams
        for x in same_day:
            if x.id == it["existing_exam_id"] or not (probe.start_time < x.end_time and x.start_time < probe.end_time):
                continue
            rules = [models.ExamEligibilityRule(department=(it["audience_rule"] or {}).get("department"), year=(it["audience_rule"] or {}).get("year"))] \
                if it["audience_rule"] and it["audience_rule"]["created"] else []
            orules = load_audience(db, x.id)[0]
            if rules and orules and audiences_may_intersect(rules, orules):
                it["errors"].append(f"overlaps examination #{x.id} ({x.subject_code}) for an intersecting audience")
            else:
                it["warnings"].append(f"time overlaps examination #{x.id} ({x.subject_code}); audiences are not known to intersect")
        if it["errors"]:
            it["action"] = "blocked"
            continue
        if it["action"] == "update_existing":
            x = next(z for z in existing if z.id == it["existing_exam_id"])
            merged = {"exam_date": it["exam_date"], "start_time": e.start_time, "end_time": e.end_time, "venue": x.venue}
            try:
                _check_schedule(db, merged, x.id, x)
            except HTTPException as exc:
                d = exc.detail
                it["errors"].append("cannot reschedule: " + (d.get("message") if isinstance(d, dict) else str(d)))
                it["action"] = "blocked"
                continue
        accepted.append((it, e))
    counts: dict[str, int] = {}
    for it in items:
        counts[it["action"]] = counts.get(it["action"], 0) + 1
    sig_src = json.dumps({"v": v.id, "items": [(i["entry_id"], i["action"], i["existing_exam_id"], i["exam_date"],
                                                i["start_time"], i["end_time"], (i["subject"] or {}).get("id"))
                                               for i in items],
                          "exams": sorted((x.id, str(x.updated_at), x.exam_date, x.start_time) for x in existing),
                          "opts": [opts.create_missing_subjects, opts.term_id, sorted(opts.update_existing_entry_ids)]},
                         default=str)
    return {"items": items, "counts": counts, "signature": hashlib.sha256(sig_src.encode()).hexdigest(),
            "term": {"id": term.id, "name": term.name} if term else None,
            "will_create": counts.get("create", 0) + counts.get("create_with_new_subject", 0),
            "will_update": counts.get("update_existing", 0), "blocked": counts.get("blocked", 0)
            + counts.get("conflict_existing", 0), "default_status": "draft"}


@router.post("/{version_id}/import/preview")
def import_preview(version_id: int, data: ImportOptions, db: Session = Depends(get_db),
                   user: models.User = Depends(require_roles(*STAFF))):
    v = get_version(db, version_id)
    if v.processing_status not in ("processed", "needs_review"):
        raise HTTPException(409, "Process the document first")
    plan = build_plan(db, v, data)
    plan["document_approved"] = v.review_status == "approved"
    return plan


@router.post("/{version_id}/import")
def import_timetable(version_id: int, data: ImportOptions, request: Request, db: Session = Depends(get_db),
                     user: models.User = Depends(require_roles(*ADMIN))):
    v = get_version(db, version_id)
    if not data.confirm:
        raise HTTPException(422, "Administrator confirmation is required (confirm=true)")
    if v.review_status != "approved":
        raise HTTPException(409, "The document must be approved before its timetable can be imported")
    plan = build_plan(db, v, data)
    if not data.signature or data.signature != plan["signature"]:
        raise HTTPException(409, "The examination data or the preview changed; request a new import preview and confirm again")
    if plan["blocked"] and not data.skip_blocked:
        raise HTTPException(409, {"message": f"{plan['blocked']} row(s) are blocked. Fix them, or confirm with skip_blocked to import the rest.",
                                  "blocked": [i for i in plan["items"] if i["action"] in ("blocked", "conflict_existing")]})
    ex = db.scalar(select(dm.DocumentExtraction).where(dm.DocumentExtraction.version_id == v.id))
    title_base = (ex.exam_name if ex and ex.exam_name else v.document.exam_name or v.document.title)
    term_id = data.term_id or v.document.term_id
    created, updated, skipped = [], [], 0
    snaps: dict[int, dict] = {}
    subj_cache = {s.code.upper(): s for s in db.scalars(select(models.Subject)).all()}
    try:
        for it in plan["items"]:
            e = db.get(dm.TimetableEntry, it["entry_id"])
            act = it["action"]
            if act in ("blocked", "conflict_existing", "skip_existing", "skip_duplicate_in_document"):
                skipped += 1
                continue
            subj = db.get(models.Subject, it["subject"]["id"]) if it["subject"] else None
            if act == "create_with_new_subject":
                code = _norm_code(e.subject_code)
                subj = subj_cache.get(code)
                if not subj:
                    subj = models.Subject(code=code, name=e.subject_name[:200], department=e.department, semester=e.semester, active=True)
                    db.add(subj)
                    db.flush()
                    subj_cache[code] = subj
                    audit.record(db, user.username, "subject.created_from_document", subj.code, {"version": v.id}, request, user.role)
                e.subject_id = subj.id
            if act == "update_existing":
                x = db.get(models.Exam, it["existing_exam_id"])
                old = f"{x.exam_date} {x.start_time}-{x.end_time}"
                snaps[x.id] = notify.exam_snapshot(x)
                x.exam_date, x.start_time, x.end_time = it["exam_date"], e.start_time, e.end_time
                x.duration_minutes = duration_minutes(e.start_time, e.end_time)
                audit.record(db, user.username, "exam.updated_from_document", str(x.id),
                             {"from": old, "to": f"{x.exam_date} {x.start_time}-{x.end_time}", "version": v.id, "entry": e.id},
                             request, user.role)
                e.imported_exam_id = x.id
                updated.append(x.id)
            else:
                title = f"{title_base} – {subj.name}"[:180]
                x = models.Exam(title=title, subject_code=subj.code, subject_id=subj.id, exam_date=it["exam_date"],
                                start_time=e.start_time, end_time=e.end_time, venue=DEFAULT_VENUE, status="draft",
                                term_id=term_id if term_id and db.get(models.ExamTerm, term_id) else None,
                                duration_minutes=duration_minutes(e.start_time, e.end_time))
                db.add(x)
                db.flush()
                rule = it["audience_rule"]
                if rule and rule["created"] and (rule["department"] or rule["year"]):
                    db.add(models.ExamEligibilityRule(exam_id=x.id, department=rule["department"], year=rule["year"]))
                audit.record(db, user.username, "exam.imported_from_document", str(x.id),
                             {"version": v.id, "entry": e.id, "subject": subj.code}, request, user.role)
                e.imported_exam_id = x.id
                created.append(x.id)
            e.subject_id = subj.id if subj else e.subject_id
            e.review_status = "imported"
        if ex:
            ex.imported_at, ex.imported_by = now(), user.username
        event(db, v.id, "imported", user.username, {"created": len(created), "updated": len(updated), "skipped": skipped})
        audit.record(db, user.username, "document.imported", str(v.id),
                     {"created": created[:50], "updated": updated[:50], "skipped": skipped}, request, user.role)
        db.commit()
    except Exception:
        db.rollback()
        raise
    for xid, old_snap in snaps.items():       # a published examination whose date/time the import changed -> timetable-change notice
        notify.notify_exam_transition(db, db.get(models.Exam, xid), old_snap, user.username)
    return {"created_exam_ids": created, "updated_exam_ids": updated, "skipped": skipped, "status": "draft",
            "note": "Imported examinations are drafts; publish them from the Examinations tab after checking."}
