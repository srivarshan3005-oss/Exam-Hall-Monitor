"""Automatic ingestion: current hall/seat PDF versions -> parsed -> reconciled -> searchable LiveAllotment rows.

Nothing here asks an administrator to approve anything. Instead every row is *classified* from the parser's own evidence and
said so honestly to the student:

  CONFIRMED      hall list and seat sheet both name this register number and agree (hall + seat shown)
  HALL_ONLY      only the hall list names it (seat sheet not published, or does not list the number) -> hall shown, seat NOT
  SEAT_ONLY      only the seat sheet names it (hall list not published / does not list it)
  CONFLICT       sources disagree (hall, seat, subject, or two documents for one session) -> nothing is picked silently
  MANUAL_REVIEW  the parser itself raised an error/uncertainty flag (OCR damage, count mismatch, text-order seat, ...) ->
                 values are kept apart as "unverified" and the original page image is the evidence

Failure policy: a document that fails to download, validate or parse never removes existing rows. Rows of a (date, session)
change only when that session was successfully re-parsed.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import doc_models as dm
from ..config import settings
from ..vsb_alloc.common import PageInput
from ..vsb_alloc.hall_parser import HallDocument, parse_hall_pdf
from ..vsb_alloc.reconcile import ERROR_FLAGS, AllocRecord, reconcile
from ..vsb_alloc.seat_parser import SeatDocument, parse_seat_pdf

log = logging.getLogger("exam_monitor.live")

HALL, SEAT = "hall_allotment", "seating_allotment"
CONFLICT_FLAGS = frozenset({"conflicting_halls", "hall_mismatch", "subject_mismatch", "conflicting_seats", "multiple_subjects",
                            "duplicate_seat", "source_documents_disagree"})
# flags that make a record "needs a human", beyond the hard conflicts
REVIEW_FLAGS = (ERROR_FLAGS - CONFLICT_FLAGS - {"missing_in_seating_pdf", "missing_in_hall_pdf"}) | {
    "seat_from_text_order", "ocr_text", "ocr_ambiguous"}

# Flags that cast doubt on the HALL itself. Without any of them, a hall named identically by the hall list and the seat sheet is shown
# even when the seat still needs a human check (the seat stays hidden).
HALL_DOUBT_FLAGS = frozenset({"conflicting_halls", "hall_mismatch", "hall_check_failed", "hall_missing", "hall_label_variant",
                              "hall_capacity_exceeded", "source_documents_disagree", "source_not_official", "provenance_mismatch"})

_lock = threading.RLock()
_parse_cache: "OrderedDict[tuple, tuple]" = OrderedDict()
_CACHE_MAX = 12


def now() -> datetime:
    return datetime.now(timezone.utc)


# ----------------------------------------------------------------------------- small pure helpers
_PROG = re.compile(r"^\s*(B\.?\s?E\.?|B\.?\s?TECH\.?|M\.?\s?E\.?|M\.?\s?TECH\.?|MBA|MCA)(?=[\s.\-–:]|$)[\s.\-–:]*(.*)$", re.I)


def split_programme(label: str | None) -> tuple[str | None, str | None]:
    """'BE-CIVIL' -> ('BE', 'CIVIL'); 'B.TECH - IT' -> ('BTECH', 'IT'); anything else -> (None, label)."""
    if not label or not label.strip():
        return None, None
    m = _PROG.match(label)
    if not m:
        return None, label.strip()
    prog = re.sub(r"[\s.]+", "", m.group(1)).upper()      # B.E. / BE / B E -> BE
    rest = m.group(2).strip(" -–:.") or None
    return prog, rest


def weekday_name(d: date) -> str:
    return ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")[d.weekday()]


def _agreed_hall(r, flags) -> str | None:
    """The hall when BOTH official documents name the same hall and nothing doubts it; otherwise None."""
    a, b = (r.hall_pdf_hall or "").strip().upper(), (r.seat_pdf_hall or "").strip().upper()
    if a and a == b and not (set(flags) & HALL_DOUBT_FLAGS):
        return r.hall_pdf_hall
    return None


def classify(flags: list[str], *, hall_doc_present: bool, seat_doc_present: bool, has_hall: bool, has_seat: bool) -> str:
    """Map the reconciler's flags to the public status. Pure function (unit-tested)."""
    fs = set(flags)
    if fs & CONFLICT_FLAGS:
        return "CONFLICT"
    if fs & REVIEW_FLAGS:
        return "MANUAL_REVIEW"
    if "missing_in_seating_pdf" in fs or (has_hall and not has_seat):
        return "HALL_ONLY"
    if "missing_in_hall_pdf" in fs or (has_seat and not has_hall):
        return "SEAT_ONLY"
    if has_hall and has_seat:
        return "CONFIRMED"
    return "MANUAL_REVIEW"


def fingerprint_of(parts: dict) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


# ----------------------------------------------------------------------------- reading PDFs (text layer + OCR fallback)
def read_pages_with_ocr(path: str, lang: str | None = None) -> tuple[list[PageInput], int]:
    """Word boxes from the text layer; image-only pages are OCR'd (text only, no boxes -> never used for seat geometry)."""
    from .. import doc_extract as dx
    from ..vsb_alloc import pdfwords
    pages = pdfwords.read_pages(path)
    ocr_pages = 0
    empty = [p for p in pages if not p.text.strip()]
    if empty and settings.vsb_auto_process_ocr and dx.ocr_available():
        import fitz
        doc = fitz.open(path)
        try:
            for p in empty:
                try:
                    text, conf = dx.ocr_page(doc[p.index], lang or settings.ocr_default_language)
                except Exception:  # noqa: BLE001 - one unreadable page must not stop the document
                    continue
                if text.strip():
                    p.text, p.method, p.ocr_confidence, p.words = text, "ocr", conf, []
                    ocr_pages += 1
        finally:
            doc.close()
    if not any(p.text.strip() for p in pages):
        raise ValueError("The PDF has no readable text (and OCR is unavailable or found nothing)")
    return pages, ocr_pages


def _parse_version(version: dm.DocumentVersion, kind: str):
    """Parse one stored version (cached in memory by version id). Returns (document, ocr_pages)."""
    key = (version.id, version.sha256)           # sha256 too: a reused id can never return another file's parse
    with _lock:
        hit = _parse_cache.get(key)
        if hit is not None:
            _parse_cache.move_to_end(key)
            return hit
    from ..routers import docproc
    pages, ocr_pages = read_pages_with_ocr(str(docproc.stored_path(version)))
    doc = parse_hall_pdf(pages) if kind == HALL else parse_seat_pdf(pages)
    with _lock:
        _parse_cache[key] = (doc, ocr_pages, len(pages))
        while len(_parse_cache) > _CACHE_MAX:
            _parse_cache.popitem(last=False)
    return doc, ocr_pages, len(pages)


def forget(version_id: int | None = None) -> None:
    with _lock:
        if version_id is None:
            _parse_cache.clear()
        else:
            for k in [k for k in _parse_cache if k[0] == version_id]:
                _parse_cache.pop(k, None)


# ----------------------------------------------------------------------------- ingest queue
def current_allotment_versions(db: Session) -> list[tuple[dm.OfficialDocument, dm.DocumentVersion]]:
    out = []
    for doc in db.scalars(select(dm.OfficialDocument).where(dm.OfficialDocument.doc_kind.in_((HALL, SEAT)),
                                                            dm.OfficialDocument.status == "active")).all():
        v = db.scalar(select(dm.DocumentVersion).where(dm.DocumentVersion.document_id == doc.id,
                                                       dm.DocumentVersion.is_current == True)  # noqa: E712
                      .order_by(dm.DocumentVersion.version_no.desc()).limit(1))
        if v is not None:
            out.append((doc, v))
    return out


def ingest_pending(db: Session) -> dict:
    """Parse every current hall/seat version that has no successful LiveIngest row. Returns counts. Never raises."""
    done = failed = 0
    for doc, v in current_allotment_versions(db):
        row = db.scalar(select(dm.LiveIngest).where(dm.LiveIngest.version_id == v.id))
        if row is not None and row.status in ("ok",):
            continue
        if row is not None and row.status == "failed" and row.attempts >= 3:
            continue                                  # stop hammering a document that is simply broken; admin can retry
        if row is None:
            row = dm.LiveIngest(version_id=v.id, status="pending", attempts=0)
            db.add(row)
            db.flush()
        row.status, row.attempts = "processing", (row.attempts or 0) + 1
        db.commit()
        try:
            parsed, ocr_pages, n_pages = _parse_version(v, doc.doc_kind)
            if not parsed.sessions:
                raise ValueError("No examination date/session was found in the PDF")
            if any(s is None for _, s in parsed.sessions):
                raise ValueError("The FN/AN session could not be read from the PDF header")
            regs = {r for g in getattr(parsed, "groups", []) for r in g.register_numbers} | \
                   {a.register_number for s in getattr(parsed, "sheets", []) for a in s.assignments}
            row.status, row.error, row.records, row.pages, row.ocr_pages = "ok", None, len(regs), n_pages, ocr_pages
            v.processing_status = "processed" if _has_status(v, "processed") else v.processing_status
            done += 1
        except Exception as e:  # noqa: BLE001 - recorded; nothing is deleted
            db.rollback()
            row = db.scalar(select(dm.LiveIngest).where(dm.LiveIngest.version_id == v.id))
            row.status, row.error = "failed", f"{type(e).__name__}: {str(e)[:380]}"
            failed += 1
            log.warning("live ingest failed for version %s: %s", v.id, type(e).__name__)
        row.processed_at = now()
        db.commit()
    return {"parsed": done, "failed": failed}


def _has_status(v: dm.DocumentVersion, name: str) -> bool:
    return False          # the existing processing_status vocabulary is owned by the manual workflow; leave it untouched


# ----------------------------------------------------------------------------- rebuild
@dataclass
class Event:
    allotment_id: int
    kind: str                # new | revised
    register_number: str


@dataclass
class _Src:
    doc: dm.OfficialDocument
    version: dm.DocumentVersion
    parsed: object


def _newest(items: list[_Src]) -> _Src | None:
    if not items:
        return None
    return sorted(items, key=lambda s: (s.version.downloaded_at or datetime.min.replace(tzinfo=timezone.utc), s.version.id))[-1]


def _filename(doc: dm.OfficialDocument) -> str:
    return (doc.original_filename or urlparse(doc.source_url or "").path.rsplit("/", 1)[-1] or "document.pdf")[:200]


def _placements(src: _Src, d: date, s: str, hall: bool) -> dict[str, set]:
    out: dict[str, set] = {}
    if hall:
        for g in src.parsed.groups:
            if g.exam_date == d and g.session == s:
                for r in g.register_numbers:
                    out.setdefault(r, set()).add((g.hall, g.subject_code))
    else:
        for sh in src.parsed.sheets:
            if sh.exam_date == d and sh.session == s:
                for a in sh.assignments:
                    out.setdefault(a.register_number, set()).add((sh.hall, a.seat))
    return out


def rebuild_index(db: Session) -> dict:
    """Recompute LiveAllotment rows for every (date, session) that has a successfully parsed current hall and/or seat PDF."""
    from ..vsb_alloc.reconcile import reconcile as _reconcile  # noqa: F401 (import check)
    halls: dict[tuple, list[_Src]] = {}
    seats: dict[tuple, list[_Src]] = {}
    for doc, v in current_allotment_versions(db):
        ing = db.scalar(select(dm.LiveIngest).where(dm.LiveIngest.version_id == v.id))
        if ing is None or ing.status != "ok":
            continue
        try:
            parsed, _, _ = _parse_version(v, doc.doc_kind)
        except Exception:  # noqa: BLE001
            log.warning("rebuild: version %s could not be re-read", v.id)
            continue
        for key in parsed.sessions:
            (halls if doc.doc_kind == HALL else seats).setdefault(key, []).append(_Src(doc, v, parsed))
    events: list[Event] = []
    stats = {"sessions": 0, "records": 0, "new": 0, "revised": 0, "unchanged": 0, "removed": 0}
    for key in sorted(set(halls) | set(seats)):
        d, s = key
        if s is None:
            continue
        h_src, s_src = _newest(halls.get(key, [])), _newest(seats.get(key, []))
        rec = reconcile(h_src.parsed if h_src else None, s_src.parsed if s_src else None, d, s, None)
        extra_notes: dict[str, list[str]] = {}
        disagree: set[str] = set()
        for group, primary, is_hall in ((halls.get(key, []), h_src, True), (seats.get(key, []), s_src, False)):
            if primary is None or len(group) < 2:
                continue
            base = _placements(primary, d, s, is_hall)
            for other in group:
                if other is primary:
                    continue
                alt = _placements(other, d, s, is_hall)
                for reg in set(base) | set(alt):
                    if base.get(reg) != alt.get(reg):
                        disagree.add(reg)
                        extra_notes.setdefault(reg, []).append(
                            f"{_filename(primary.doc)} says {sorted(map(str, base.get(reg, [])))}; "
                            f"{_filename(other.doc)} says {sorted(map(str, alt.get(reg, [])))}")
        rows = []
        for r in rec.records:
            flags = list(r.flags)
            if r.register_number in disagree:
                flags.append("source_documents_disagree")
            status = classify(flags, hall_doc_present=h_src is not None, seat_doc_present=s_src is not None,
                              has_hall=bool(r.hall_pdf_hall), has_seat=bool(r.seat_pdf_hall or r.seat is not None))
            prog, dept = split_programme(r.department)
            hall_value = r.hall
            seat_value = None if r.seat is None else str(r.seat)
            unverified = None
            if status == "MANUAL_REVIEW":
                unverified = {"hall": r.hall or r.hall_pdf_hall or r.seat_pdf_hall, "seat": seat_value}
                hall_value, seat_value = None, None
                hall_value = _agreed_hall(r, flags)
            elif status == "HALL_ONLY":
                seat_value = None
            elif status == "CONFLICT":
                unverified = {"hall_pdf_hall": r.hall_pdf_hall, "seat_pdf_hall": r.seat_pdf_hall, "seat": seat_value}
                hall_value, seat_value = _agreed_hall(r, flags), None
            notes = list(r.notes) + extra_notes.get(r.register_number, [])
            if unverified is not None:
                notes.append("unverified:" + json.dumps(unverified, sort_keys=True))
            hver = h_src.version if (h_src and r.hall_pdf_hall is not None or (h_src and r.hall_page is not None)) else None
            sver = s_src.version if (s_src and (r.seat_page is not None)) else None
            parts = {"reg": r.register_number, "d": d.isoformat(), "s": s, "sub": r.subject_code or "", "title": r.subject_title,
                     "hall": hall_value, "seat": seat_value, "status": status, "dept": r.department,
                     "hv": hver.sha256 if hver else None, "sv": sver.sha256 if sver else None,
                     "hp": r.hall_page, "sp": r.seat_page, "notes": notes}
            rows.append(dict(
                register_number=r.register_number, exam_date=d, session=s, subject_code=(r.subject_code or "")[:30],
                subject_name=(r.subject_title or None) and r.subject_title[:300], programme=prog, department=(dept or None) and dept[:150],
                hall=hall_value, seat=seat_value, status=status, flags=json.dumps(sorted(set(flags))),
                notes=" | ".join(notes)[:4000] or None, confidence=float(r.confidence or 0.0),
                hall_version_id=hver.id if hver else None, seat_version_id=sver.id if sver else None,
                hall_page=r.hall_page if hver else None, seat_page=r.seat_page if sver else None,
                hall_source_url=(h_src.doc.source_url if hver else None), seat_source_url=(s_src.doc.source_url if sver else None),
                hall_filename=_filename(h_src.doc) if hver else None, seat_filename=_filename(s_src.doc) if sver else None,
                fingerprint=fingerprint_of(parts)))
        e = _apply_session(db, d, s, rows)
        events += e["events"]
        stats["sessions"] += 1
        stats["records"] += len(rows)
        for k in ("new", "revised", "unchanged", "removed"):
            stats[k] += e[k]
    db.commit()
    stats["events"] = len(events)
    return {"stats": stats, "events": events}


def _same_visible_content(old: dm.LiveAllotment, row: dict) -> bool:
    """True when everything a student can read (subject, programme, department, hall, seat, status) is identical."""
    return all(getattr(old, k) == row[k] for k in ("subject_code", "subject_name", "programme", "department", "hall", "seat", "status")) \
        and (old.exam_date, old.session) == (row["exam_date"], row["session"])


def is_material_change(old: dm.LiveAllotment, row: dict) -> bool:
    """A REVISION is a change of what the student must do: date/session/subject, a different hall, or a different seat.
    Adding the seat to a hall-only record (or resolving a flag) is new detail, not a revised allotment."""
    if old.subject_code != row["subject_code"]:
        return True
    if old.hall and row["hall"] and old.hall != row["hall"]:
        return True
    if old.seat and row["seat"] and old.seat != row["seat"]:
        return True
    if (old.hall and not row["hall"] and row["status"] not in ("MANUAL_REVIEW", "CONFLICT")) or (old.seat and not row["seat"] and row["status"] == "HALL_ONLY"):
        return True                      # a published hall/seat disappeared without the record being flagged: treat as a change
    return False


def _apply_session(db: Session, d: date, s: str, rows: list[dict]) -> dict:
    stamp = now()
    cur = {(a.register_number, a.subject_code): a for a in db.scalars(select(dm.LiveAllotment).where(
        dm.LiveAllotment.exam_date == d, dm.LiveAllotment.session == s, dm.LiveAllotment.is_current == True)).all()}  # noqa: E712
    seen = set()
    out = {"events": [], "new": 0, "revised": 0, "unchanged": 0, "removed": 0}
    for row in rows:
        key = (row["register_number"], row["subject_code"])
        seen.add(key)
        old = cur.get(key)
        if old is None:
            # the same register may already have a current row for this session under another subject code (subject appeared/vanished)
            alt = [a for (r, _), a in cur.items() if r == row["register_number"] and (r, _) not in seen]
            old = alt[0] if alt else None
        if old is not None and old.fingerprint == row["fingerprint"]:
            old.last_verified_at = stamp
            out["unchanged"] += 1
            continue
        if old is not None and _same_visible_content(old, row):
            # The PDF was re-published but THIS student's allotment did not change: keep the row (and its history), only
            # repoint it at the new source version/page. No revision, no notification.
            for k in ("hall_version_id", "seat_version_id", "hall_page", "seat_page", "hall_source_url", "seat_source_url",
                      "hall_filename", "seat_filename", "flags", "notes", "confidence"):
                setattr(old, k, row[k])
            clash = db.scalar(select(dm.LiveAllotment.id).where(
                dm.LiveAllotment.register_number == row["register_number"], dm.LiveAllotment.exam_date == d,
                dm.LiveAllotment.session == s, dm.LiveAllotment.subject_code == row["subject_code"],
                dm.LiveAllotment.fingerprint == row["fingerprint"], dm.LiveAllotment.id != old.id))
            if clash is None:
                old.fingerprint = row["fingerprint"]
            old.last_verified_at = stamp
            out["unchanged"] += 1
            continue
        existing_same = db.scalar(select(dm.LiveAllotment).where(
            dm.LiveAllotment.register_number == row["register_number"], dm.LiveAllotment.exam_date == d,
            dm.LiveAllotment.session == s, dm.LiveAllotment.subject_code == row["subject_code"],
            dm.LiveAllotment.fingerprint == row["fingerprint"]))
        if existing_same is not None:      # content returned to an earlier state: revive that row, keep history
            if old is not None and old.id != existing_same.id:
                old.is_current, old.superseded_at = False, stamp
            existing_same.is_current, existing_same.superseded_at, existing_same.last_verified_at = True, None, stamp
            out["unchanged"] += 1
            continue
        rev, material = 1, False
        if old is not None:
            material = is_material_change(old, row)
            old.is_current, old.superseded_at = False, stamp
            rev = (old.revision or 1) + 1
            if material or "revised_allotment" in json.loads(old.flags or "[]"):
                row = {**row, "flags": json.dumps(sorted(set(json.loads(row["flags"])) | {"revised_allotment"}))}
            db.flush()
        a = dm.LiveAllotment(**row, revision=rev, revised_from_id=old.id if old else None, is_current=True,
                             first_seen_at=stamp, last_verified_at=stamp)
        db.add(a)
        db.flush()
        out["events"].append(Event(a.id, "revised" if material else "new", row["register_number"]))
        out["revised" if material else "new"] += 1
    for key, a in cur.items():
        if key not in seen and a.is_current:
            a.is_current, a.superseded_at = False, stamp       # the number left the document: history kept, no longer searchable
            out["removed"] += 1
    return out


# ----------------------------------------------------------------------------- local import (CLI / tests)
def import_local_pdf(db: Session, path: str | Path, kind: str, *, source_url: str | None = None, actor: str = "cli") -> dm.DocumentVersion:
    """Store a PDF from disk exactly like a downloaded one (same validation, hashing and versioning). `kind` = hall|seat.
    `source_url` should be the official address when known; otherwise a local-import:// marker is used and no official
    link is shown to students for it."""
    import os
    import uuid
    from .. import vsb_sources as vs
    from ..routers import docproc
    doc_kind = {"hall": HALL, "seat": SEAT, "seating": SEAT}.get(kind)
    if doc_kind is None:
        raise ValueError("kind must be 'hall' or 'seat'")
    data = Path(path).read_bytes()
    pages = vs.validate_pdf(data)
    digest = hashlib.sha256(data).hexdigest()
    existing = db.scalar(select(dm.DocumentVersion).where(dm.DocumentVersion.sha256 == digest).limit(1))
    if existing is not None:
        return existing
    url = source_url or f"local-import://{digest[:16]}/{Path(path).name}"
    doc = db.scalar(select(dm.OfficialDocument).where(dm.OfficialDocument.source_url == url))
    if doc is None:
        doc = dm.OfficialDocument(source_url=url, title=Path(path).stem[:300], doc_kind=doc_kind, origin="upload", status="active",
                                  uploaded_by=actor[:80], original_filename=docproc.safe_display_name(Path(path).name))
        db.add(doc)
        db.flush()
    nxt = (db.scalar(select(dm.DocumentVersion.version_no).where(dm.DocumentVersion.document_id == doc.id)
                     .order_by(dm.DocumentVersion.version_no.desc()).limit(1)) or 0) + 1
    for old in db.scalars(select(dm.DocumentVersion).where(dm.DocumentVersion.document_id == doc.id)).all():
        old.is_current = False
    dest = docproc.storage_dir() / (uuid.uuid4().hex + ".pdf")
    dest.write_bytes(data)
    try:
        os.chmod(dest, 0o600)
    except OSError:
        pass
    v = dm.DocumentVersion(document_id=doc.id, version_no=nxt, sha256=digest, size_bytes=len(data), page_count=pages,
                           storage_path=str(dest), is_current=True, processing_status="pending")
    db.add(v)
    db.commit()
    return v
