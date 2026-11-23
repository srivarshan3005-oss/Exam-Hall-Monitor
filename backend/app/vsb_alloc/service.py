"""Database workflow for VSB allocations: parse -> reconcile -> stage a DRAFT batch. Nothing here publishes anything."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import doc_models as dm, models
from .common import PARSER_VERSION, Issue, PageInput, norm_hall
from .hall_parser import HallDocument, parse_hall_pdf
from .reconcile import reconcile
from .seat_parser import SeatDocument, parse_seat_pdf

log = logging.getLogger("exam_monitor.vsb_alloc")


def now() -> datetime:
    return datetime.now(timezone.utc)


class BuildError(Exception):
    pass


def load_pages(db: Session, version: dm.DocumentVersion) -> list[PageInput]:
    """Word boxes from the stored PDF (needed for seat mapping); OCR pages keep their stored OCR text and have no boxes."""
    from . import pdfwords
    from ..routers import docproc
    rows = {p.page_index: p for p in db.scalars(select(dm.PdfPage).where(dm.PdfPage.version_id == version.id)).all()}
    pages: list[PageInput] = []
    try:
        pages = pdfwords.read_pages(str(docproc.stored_path(version)))
    except Exception as exc:  # noqa: BLE001 - fall back to stored text; seats will then be flagged as unconfirmed
        log.warning("VSB: could not read words from version %s (%s); using stored text", version.id, type(exc).__name__)
    if not pages:
        pages = [PageInput(i, p.text_content or "", [], p.extraction_method or "text_layer", p.ocr_confidence)
                 for i, p in sorted(rows.items())]
    for pg in pages:
        row = rows.get(pg.index)
        if row is not None and (row.extraction_method == "ocr" or not pg.text.strip()):
            pg.text, pg.words, pg.method, pg.ocr_confidence = row.text_content or "", [], row.extraction_method or "ocr", row.ocr_confidence
    if not any(p.text.strip() for p in pages):
        raise BuildError("The PDF has no readable text yet. Process it (with OCR if scanned) first.")
    return pages


def check_capacity(db: Session, rec) -> None:
    """Compare the students placed in each hall with the capacity recorded in the hall directory (when one is recorded).
    A hall over capacity is a blocking error on every record in it; a hall missing from the directory is only an info note
    (nothing is invented: capacity stays unknown)."""
    by_hall: dict[str, list] = {}
    for r in rec.records:
        key = norm_hall(r.hall)
        if key:
            by_hall.setdefault(key, []).append(r)
    if not by_hall:
        return
    directory = {norm_hall(h.code): h for h in db.scalars(select(dm.Hall)).all()}
    for hall, rs in sorted(by_hall.items()):
        h = directory.get(hall)
        if h is None:
            rec.issues.append(Issue("hall_not_in_directory", "info", f"{hall} is not in the hall directory, so its capacity could not be checked.", hall=hall))
        elif h.capacity and len(rs) > h.capacity:
            rec.issues.append(Issue("hall_capacity_exceeded", "error",
                                    f"{hall}: {len(rs)} students are placed but the hall directory records a capacity of {h.capacity}.", hall=hall,
                                    detail={"placed": len(rs), "capacity": h.capacity}))
            for r in rs:
                if "hall_capacity_exceeded" not in r.flags:
                    r.flags.append("hall_capacity_exceeded")


def known_register_numbers(db: Session) -> dict[str, int]:
    return {r: i for i, r in db.execute(select(models.Student.id, models.Student.register_number)).all()}


def current_version(db: Session, document_id: int) -> dm.DocumentVersion | None:
    return db.scalar(select(dm.DocumentVersion).where(dm.DocumentVersion.document_id == document_id)
                     .order_by(dm.DocumentVersion.version_no.desc()).limit(1))


def build_batches(db: Session, hall_version_id: int | None, seat_version_id: int | None, actor: str) -> list[dm.VsbAllocBatch]:
    """Parse the given PDF versions and stage one DRAFT batch per (date, session). Existing drafts of the same session are
    replaced; published batches are never touched (a published batch is superseded only when its replacement is published)."""
    if not hall_version_id and not seat_version_id:
        raise BuildError("Choose a hall-allotment PDF, a seating-allotment PDF, or both.")
    hall_doc: HallDocument | None = None
    seat_doc: SeatDocument | None = None
    hv = db.get(dm.DocumentVersion, hall_version_id) if hall_version_id else None
    sv = db.get(dm.DocumentVersion, seat_version_id) if seat_version_id else None
    if hall_version_id and hv is None or seat_version_id and sv is None:
        raise BuildError("Document version not found.")
    if hv is not None:
        hall_doc = parse_hall_pdf(load_pages(db, hv))
    if sv is not None:
        seat_doc = parse_seat_pdf(load_pages(db, sv))
    sessions: list[tuple[date, str | None]] = []
    for doc in (hall_doc, seat_doc):
        for s in (doc.sessions if doc else []):
            if s not in sessions:
                sessions.append(s)
    if not sessions:
        raise BuildError("No examination date was found in the PDF(s); nothing was staged.")
    if any(s is None for _, s in sessions):
        raise BuildError("The FN/AN session could not be read from the PDF header; nothing was staged. "
                         "Check the header line 'DATE OF EXAMINATION ... SESSION'.")
    known = known_register_numbers(db)
    out: list[dm.VsbAllocBatch] = []
    for d, sess in sessions:
        rec = reconcile(hall_doc, seat_doc, d, sess, set(known))
        check_capacity(db, rec)
        for old in db.scalars(select(dm.VsbAllocBatch).where(dm.VsbAllocBatch.exam_date == d, dm.VsbAllocBatch.session == sess,
                                                              dm.VsbAllocBatch.status == "draft")).all():
            db.delete(old)
        db.flush()
        b = dm.VsbAllocBatch(exam_date=d, session=sess, exam_name=rec.exam_name, hall_version_id=hv.id if hv else None,
                             seat_version_id=sv.id if sv else None, status="draft", parser_version=PARSER_VERSION,
                             summary=json.dumps(rec.stats), created_by=actor[:80])
        db.add(b)
        db.flush()
        for r in rec.records:
            db.add(dm.VsbAllocRecord(
                batch_id=b.id, register_number=r.register_number, id_kind=r.id_kind, student_id=known.get(r.register_number),
                department=r.department, department_source=r.department_source, subject_code=r.subject_code,
                subject_title=(r.subject_title or None) and r.subject_title[:300], hall=r.hall,
                seat=None if r.seat is None else str(r.seat), sources=r.sources, flags=json.dumps(r.flags),
                detail=json.dumps({"hall_pdf_hall": r.hall_pdf_hall, "seat_pdf_hall": r.seat_pdf_hall, "hall_page": r.hall_page,
                                   "seat_page": r.seat_page, "notes": r.notes}), confidence=r.confidence,
                review_status="pending", published=False))
        for i in rec.issues:
            db.add(dm.VsbAllocIssue(batch_id=b.id, kind=i.kind[:40], severity=i.severity, message=i.message[:2000],
                                    register_number=i.register_number, hall=i.hall, subject_code=i.subject_code,
                                    page=i.page, status="open"))
        out.append(b)
    db.flush()
    return out


# ----------------------------------------------------------------------------- automatic staging after discovery
def _docs_for_session(db: Session, d: date, sess: str, kind: str) -> list[dm.OfficialDocument]:
    return db.scalars(select(dm.OfficialDocument).where(
        dm.OfficialDocument.doc_kind == kind, dm.OfficialDocument.exam_date == d, dm.OfficialDocument.session == sess,
        dm.OfficialDocument.status == "active")).all()


def auto_stage(db: Session, actor: str) -> list[str]:
    """For every (date, session) that has exactly one processed hall PDF and one processed seat PDF whose versions are not
    yet staged, stage a DRAFT batch. Ambiguous cases (several PDFs for one session) are reported, never guessed.
    Returns human-readable notes."""
    notes: list[str] = []
    keys = {(x.exam_date, x.session) for x in db.scalars(select(dm.OfficialDocument).where(
        dm.OfficialDocument.doc_kind.in_(("hall_allotment", "seating_allotment")), dm.OfficialDocument.exam_date.is_not(None),
        dm.OfficialDocument.session.is_not(None), dm.OfficialDocument.status == "active")).all()}
    for d, sess in sorted(keys):
        halls, seats = _docs_for_session(db, d, sess, "hall_allotment"), _docs_for_session(db, d, sess, "seating_allotment")
        label = f"{d.isoformat()} {sess}"
        if len(halls) > 1 or len(seats) > 1:
            notes.append(f"{label}: several PDFs of the same type are stored; choose the right ones manually (VSB allocation page).")
            continue
        hv = current_version(db, halls[0].id) if halls else None
        sv = current_version(db, seats[0].id) if seats else None
        if not hv or not sv:
            notes.append(f"{label}: waiting for the {'seating' if hv else 'hall'} allotment PDF before a batch can be staged.")
            continue
        if db.scalar(select(dm.VsbAllocBatch.id).where(dm.VsbAllocBatch.hall_version_id == hv.id, dm.VsbAllocBatch.seat_version_id == sv.id,
                                                       dm.VsbAllocBatch.exam_date == d, dm.VsbAllocBatch.session == sess).limit(1)):
            continue
        if db.scalar(select(dm.VsbAllocBatch.id).where(dm.VsbAllocBatch.exam_date == d, dm.VsbAllocBatch.session == sess,
                                                       dm.VsbAllocBatch.status == "published").limit(1)):
            notes.append(f"{label}: a published batch exists and the source PDFs changed; rebuild it manually to review the differences.")
            continue
        try:
            build_batches(db, hv.id, sv.id, actor)
            db.commit()
            notes.append(f"{label}: draft batch staged for administrator review (nothing is published).")
        except BuildError as e:
            db.rollback()
            notes.append(f"{label}: not staged - {e}")
        except Exception:  # noqa: BLE001
            db.rollback()
            log.exception("VSB auto-stage failed for %s", label)
            notes.append(f"{label}: staging failed; see the server log.")
    return notes


def source_changed(db: Session, b: dm.VsbAllocBatch) -> bool:
    """True when the PDF behind this batch has since been replaced by a newer version of the same official document."""
    for vid in (b.hall_version_id, b.seat_version_id):
        v = db.get(dm.DocumentVersion, vid) if vid else None
        if v is not None:
            cur = current_version(db, v.document_id)
            if cur is not None and cur.id != v.id:
                return True
    return False
