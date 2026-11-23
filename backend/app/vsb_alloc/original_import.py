"""Stage the ORIGINAL sabareesh2008 EXAM_MONITOR portal data (`allotments.json`) into the VSB review workflow.

The original repository is an external public mirror, so its records are never trusted as they stand. This module:

* validates every row (12-digit register number, date, FN/AN session, hall, seat, subject, https source URL);
* detects duplicate rows (identical duplicates are merged, conflicting ones are NOT staged);
* detects seats that two different register numbers share in one hall and session;
* flags hall labels that appear in two spellings within the same session (e.g. ``MB III 203`` and ``MB III A203``);
* stages one DRAFT batch per (exam date, session) in the existing review -> approve -> publish pipeline, with the
  source file hash, source URL, mirror page number and import time kept as provenance.

What it never does: publish, approve, create students or halls, invent capacities, seats or register numbers, or
overwrite a draft that already holds reviewed decisions. Students see nothing from an import until an administrator
approves the records and publishes the batch through the normal endpoints.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import audit, doc_models as dm
from ..regno import id_kind
from .common import norm_hall
from .reconcile import ERROR_FLAGS
from .service import known_register_numbers

ADAPTER = "original-portal-json"
PARSER_VERSION = "original-import-1.0"
OFFICIAL_HOST = "vsbec.edu.in"

# ---------------------------------------------------------------------------
# Official VSB verification status rules (derived from provenance evidence).
# 2026-11-17 AN: both hall-list and seat-sheet PDFs confirmed -> FULLY_VERIFIED (627 records).
# 2026-11-17 FN + 2026-11-18: hall-list confirmed, seat not independently verified -> HALL_LIST_CONFIRMED (1,159 records).
# 2026-11-16 (all sessions): no official PDF confirmation -> UNRESOLVED (1,520 records).
# Any future date without explicit verification defaults to UNRESOLVED.
_FULLY_VERIFIED_SESSIONS: frozenset[tuple] = frozenset({
    (date(2026, 11, 17), "AN"),
})
_HALL_LIST_CONFIRMED_DATES: frozenset = frozenset({
    date(2026, 11, 17),   # FN session
    date(2026, 11, 18),   # FN session (only date present in source)
})


def _verif_status(exam_date: date, session: str) -> str:
    """Return the VSB Official Verification Status for this exam date/session."""
    if (exam_date, session) in _FULLY_VERIFIED_SESSIONS:
        return "FULLY_VERIFIED"
    if exam_date in _HALL_LIST_CONFIRMED_DATES:
        return "HALL_LIST_CONFIRMED"
    return "UNRESOLVED"
MAX_BYTES = 8 * 1024 * 1024
MAX_LISTED = 100
DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "original_portal"
CHART_DIR = DATA_DIR / "seating_charts"
PROVENANCE_FILE = DATA_DIR / "allocation_provenance.json"

_REG = re.compile(r"[0-9]{12}")
_SEAT = re.compile(r"[A-Za-z0-9\-]{1,30}")
_SUBJ = re.compile(r"[A-Za-z0-9]{5,12}")
CHART_NAME = re.compile(r"[0-9a-f]{12}_[0-9A-Za-z.\-]{1,40}_page_[0-9]{1,3}\.png")
_IMAGE_REF = re.compile(r"evidence/(" + CHART_NAME.pattern + r")")
_SEAT_PAGE = re.compile(r"_page_([0-9]{1,3})\.png$")
_HALL_FORMS = re.compile(r"MB III (A?)([0-9]+)")


class ImportRefused(Exception):
    """The whole file is unusable (not a register-keyed JSON object, too large, not UTF-8 JSON)."""


class _Reject(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class Row:
    register: str
    exam_date: date
    session: str
    hall: str
    raw_hall: str
    seat: str
    subject_code: str | None
    subject_name: str | None
    source_url: str
    json_page: int | None
    chart: str | None


def load_provenance(path: Path = PROVENANCE_FILE) -> dict | None:
    """Per-record provenance built from the mirror's own database (scripts/build_original_provenance.py).
    Returns None when the file is absent; a malformed file is refused rather than ignored."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise ImportRefused(f"The provenance file is not valid JSON: {e}")
    if not isinstance(data, dict) or not isinstance(data.get("records"), dict) or not isinstance(data.get("documents"), dict):
        raise ImportRefused("The provenance file does not have the expected structure.")
    # Optional, append-only record of corrections made with official evidence. The original provenance above is never rewritten.
    corr_file = path.parent / "provenance_corrections.json"
    if corr_file.is_file():
        try:
            corr = json.loads(corr_file.read_text(encoding="utf-8"))
        except ValueError as e:
            raise ImportRefused(f"The provenance corrections file is not valid JSON: {e}")
        if not isinstance(corr, dict) or not isinstance(corr.get("corrections"), dict):
            raise ImportRefused("The provenance corrections file does not have the expected structure.")
        data["corrections"] = corr["corrections"]
    return data


def chart_path(name: str) -> Path | None:
    """Absolute path of a seating-chart image, or None if the name is malformed or the file is absent."""
    if not isinstance(name, str) or not CHART_NAME.fullmatch(name):
        return None
    p = CHART_DIR / name
    return p if p.is_file() else None


def _hall_alternative(label: str) -> str | None:
    """'MB III 203' <-> 'MB III A203'. Returns the other spelling of the same hall label, if the label has one."""
    m = _HALL_FORMS.fullmatch(label or "")
    if not m:
        return None
    return f"MB III {'' if m.group(1) else 'A'}{m.group(2)}"


def _row(key: str, raw) -> Row:
    if not isinstance(raw, dict):
        raise _Reject("not_an_object")
    if not _REG.fullmatch(key):
        raise _Reject("register_not_12_digits")
    if raw.get("register_number") != key:
        raise _Reject("register_key_mismatch")
    try:
        exam_date = date.fromisoformat(str(raw.get("exam_date")))
    except ValueError:
        raise _Reject("date_invalid")
    session = str(raw.get("session") or "").strip().upper()
    if session not in ("FN", "AN"):
        raise _Reject("session_invalid")
    raw_hall = str(raw.get("hall_number") or "").strip()
    hall = norm_hall(raw_hall)
    if not hall or len(hall) > 100:
        raise _Reject("hall_missing")
    seat = str(raw.get("seat_number") if raw.get("seat_number") is not None else "").strip().upper()
    if not _SEAT.fullmatch(seat):
        raise _Reject("seat_invalid")
    code = raw.get("subject_code")
    code = str(code).strip().upper() if code not in (None, "") else None
    if code is not None and not _SUBJ.fullmatch(code):
        raise _Reject("subject_code_invalid")
    name = raw.get("subject_name")
    name = str(name).strip()[:300] or None if name not in (None, "") else None
    url = raw.get("source_url")
    parts = urlsplit(url) if isinstance(url, str) else None
    if parts is None or parts.scheme != "https" or not parts.netloc:
        raise _Reject("source_url_invalid")
    page = raw.get("page")
    page = page if isinstance(page, int) and not isinstance(page, bool) and page >= 1 else None
    image = raw.get("seating_image")
    m = _IMAGE_REF.fullmatch(image) if isinstance(image, str) else None
    return Row(key, exam_date, session, hall, raw_hall, seat, code, name, url, page, m.group(1) if m else None)


def parse_payload(payload) -> tuple[list[Row], list[dict]]:
    """Validate every row. Returns (valid rows, rejected rows with a reason code). Never raises for a bad row."""
    if not isinstance(payload, dict) or not payload:
        raise ImportRefused("The file must be a JSON object keyed by 12-digit register number.")
    rows: list[Row] = []
    rejected: list[dict] = []
    for key, items in payload.items():
        key = str(key)
        if not isinstance(items, list):
            rejected.append({"register_number": key, "reason": "not_a_list"})
            continue
        for raw in items:
            try:
                rows.append(_row(key, raw))
            except _Reject as e:
                rejected.append({"register_number": key, "reason": e.reason})
    return rows, rejected


def _group_identical(rows: list[Row]) -> tuple[list[Row], list[dict], int]:
    """One row per (register, date, session). Identical repeats are merged; conflicting ones are not staged at all."""
    by_key: dict[tuple, list[Row]] = defaultdict(list)
    for r in rows:
        by_key[(r.register, r.exam_date, r.session)].append(r)
    keep, conflicts, merged = [], [], 0
    for (reg, d, s), items in by_key.items():
        if len({(i.hall, i.seat, i.subject_code) for i in items}) == 1:
            keep.append(items[0])
            merged += len(items) - 1
        else:
            conflicts.append({"register_number": reg, "exam_date": d.isoformat(), "session": s, "variants": [
                {"hall": i.raw_hall, "seat": i.seat, "subject_code": i.subject_code, "source_url": i.source_url,
                 "json_page": i.json_page} for i in items]})
    return keep, conflicts, merged


def _seat_key(r: Row) -> tuple:
    return (r.exam_date, r.session, r.hall, r.seat)


def _build(rows: list[Row], known: dict[str, int], file_sha256: str, imported_at: str, provenance: dict | None = None) -> dict:
    """Pure computation: flags, per-record provenance and issues for the kept rows, grouped by (date, session)."""
    prov_records = (provenance or {}).get("records", {})
    prov_docs = (provenance or {}).get("documents", {})
    halls_in_session: dict[tuple, set] = defaultdict(set)
    for r in rows:
        halls_in_session[(r.exam_date, r.session)].add(r.hall)
    seat_users: dict[tuple, set] = defaultdict(set)
    for r in rows:
        seat_users[_seat_key(r)].add(r.register)
    groups: dict[tuple, list[dict]] = defaultdict(list)
    issues_by_group: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        flags: list[str] = []
        if not r.subject_code:
            flags.append("subject_missing")
        if (urlsplit(r.source_url).hostname or "").lower() != OFFICIAL_HOST:
            flags.append("source_not_official")
        if r.chart is None:
            flags.append("seating_chart_missing")
        alt = _hall_alternative(r.hall)
        if alt and alt in halls_in_session[(r.exam_date, r.session)]:
            flags.append("hall_label_variant")
        if len(seat_users[_seat_key(r)]) > 1:
            flags.append("duplicate_seat")
        student_id = known.get(r.register)
        if student_id is None:
            flags.append("student_not_in_database")
        filename = urlsplit(r.source_url).path.rsplit("/", 1)[-1]
        kind = "seat" if "seat" in filename.lower() else ("hall" if "hall" in filename.lower() else "unknown")
        notes: list[str] = []
        prov = prov_records.get(f"{r.register}|{r.exam_date.isoformat()}|{r.session}")
        if prov is not None:
            detail, flags = _provenance_detail(r, prov, prov_docs, flags, notes, file_sha256, imported_at)
            corr = ((provenance or {}).get("corrections") or {}).get(f"{r.register}|{r.exam_date.isoformat()}|{r.session}")
            if isinstance(corr, dict):
                detail["provenance_correction"] = corr
                notes.append("Official evidence corrects the mirror's value for this record "
                             f"({corr.get('mirror_value')} -> {corr.get('corrected_value')}, seat {corr.get('corrected_seat')}); "
                             "the original mirror value is kept as provenance. See provenance_correction.")
        else:
            seat_page = None
            if kind == "seat" and r.chart:
                pm = _SEAT_PAGE.search(r.chart)
                seat_page = int(pm.group(1)) - 1 if pm else None
            notes.append("No per-PDF provenance exists for this record. The seat page comes from the chart file name and the "
                         "hall-list page is unknown.")
            detail = {"adapter": ADAPTER, "source_url": r.source_url, "source_filename": filename, "source_kind": kind,
                      "json_page": r.json_page, "seat_page": seat_page, "seating_chart": r.chart,
                      "hall_pdf_hall": r.raw_hall if kind == "hall" else None,
                      "seat_pdf_hall": r.raw_hall if kind == "seat" else None, "raw_hall": r.raw_hall, "raw_seat": r.seat,
                      "file_sha256": file_sha256, "imported_at": imported_at, "notes": notes}
        groups[(r.exam_date, r.session)].append({
            "register_number": r.register, "id_kind": id_kind(r.register), "student_id": student_id,
            "subject_code": r.subject_code, "subject_title": r.subject_name, "hall": r.hall, "seat": r.seat,
            "sources": "original", "flags": flags, "detail": detail, "source_url": r.source_url,
            "verification_status": _verif_status(r.exam_date, r.session)})
    for (d, s), items in groups.items():
        n_variant = sum(1 for i in items if "hall_label_variant" in i["flags"])
        if n_variant:
            issues_by_group[(d, s)].append({"kind": "hall_label_variant", "severity": "warning", "register_number": None,
                                             "hall": None, "message": f"{n_variant} record(s) use a hall label that also appears "
                                             "in the other spelling (with or without the letter A) in this session. Check each "
                                             "hall against the official PDF before approving."})
    for (d, s), items in groups.items():
        n_hall = sum(1 for i in items if "hall_mismatch" in i["flags"])
        n_prov = sum(1 for i in items if "provenance_mismatch" in i["flags"])
        if n_hall:
            issues_by_group[(d, s)].append({"kind": "hall_mismatch", "severity": "error", "register_number": None, "hall": None,
                                            "message": f"{n_hall} record(s) show a different hall in the hall list and the seat "
                                            "sheet. They cannot be approved until both PDFs are checked."})
        if n_prov:
            issues_by_group[(d, s)].append({"kind": "provenance_mismatch", "severity": "error", "register_number": None, "hall": None,
                                            "message": f"{n_prov} uploaded row(s) differ from the mirror's own database. Check the file version."})
    duplicate_seats = 0
    for key, regs in seat_users.items():
        if len(regs) > 1:
            d, s, hall, seat = key
            duplicate_seats += 1
            issues_by_group[(d, s)].append({"kind": "duplicate_seat", "severity": "error", "register_number": None,
                                             "hall": hall, "message": f"Seat {seat} in {hall} is listed for {len(regs)} different "
                                             "register numbers. Neither record can be approved until the seat is corrected."})
    return {"groups": groups, "issues": issues_by_group, "duplicate_seats": duplicate_seats}


def _provenance_detail(r: Row, prov: dict, docs: dict, flags: list[str], notes: list[str], file_sha256: str,
                       imported_at: str) -> tuple[dict, list[str]]:
    """Provenance from the mirror's database. Cross-checks the uploaded row against it and flags any disagreement."""
    hall_label = norm_hall(prov.get("hall_pdf_label"))
    seat_label = norm_hall(prov.get("seat_pdf_label"))
    if prov.get("seat_number") != r.seat or (r.subject_code and prov.get("subject_code") != r.subject_code):
        flags.append("provenance_mismatch")
        notes.append("The uploaded seat or subject differs from the mirror's own database row. Do not approve until checked.")
    if hall_label != r.hall or seat_label != r.hall:
        flags.append("hall_mismatch")
        notes.append(f"The hall list shows {hall_label or '—'} and the seat sheet shows {seat_label or '—'}. "
                     "Check both PDFs before approving.")
    hall_page = prov.get("hall_pdf_page")
    seat_page = prov.get("seat_pdf_page")
    if r.json_page is not None and seat_page is not None and r.json_page != seat_page:
        which = "the hall-list page" if hall_page == r.json_page else "a page that is neither PDF's"
        notes.append(f"The mirror's page field ({r.json_page}) is {which}. The seat-sheet page is {seat_page}; both are recorded.")
    url_doc = docs.get(prov.get("seat_pdf_url"), {})
    hall_doc = docs.get(prov.get("hall_pdf_url"), {})
    detail = {"adapter": ADAPTER, "provenance": "allocation_provenance.json",
              "source_url": prov["seat_pdf_url"], "source_filename": prov["seat_pdf_url"].rsplit("/", 1)[-1],
              "source_kind": "seat", "json_page": r.json_page,
              "hall_pdf_url": prov["hall_pdf_url"], "hall_pdf_page": hall_page, "hall_pdf_sha256": hall_doc.get("sha256"),
              "seat_pdf_url": prov["seat_pdf_url"], "seat_pdf_page": seat_page, "seat_pdf_sha256": url_doc.get("sha256"),
              # the pipeline stores 0-based pages (the UI adds 1)
              "hall_page": None if hall_page is None else hall_page - 1,
              "seat_page": None if seat_page is None else seat_page - 1,
              "hall_pdf_hall": prov.get("hall_pdf_label"), "seat_pdf_hall": prov.get("seat_pdf_label"),
              "seating_chart": r.chart, "raw_hall": r.raw_hall, "raw_seat": r.seat, "file_sha256": file_sha256,
              "imported_at": imported_at, "notes": notes}
    return detail, flags


def _session_blocker(db: Session, d: date, s: str) -> str | None:
    """Why a session must not be re-staged right now, or None when it is safe to replace its import draft."""
    for b in db.scalars(select(dm.VsbAllocBatch).where(dm.VsbAllocBatch.exam_date == d, dm.VsbAllocBatch.session == s,
                                                       dm.VsbAllocBatch.status == "draft")).all():
        if b.parser_version != PARSER_VERSION:
            return "a draft from another source already exists for this session; resolve or discard it first"
        reviewed = db.scalar(select(func.count()).select_from(dm.VsbAllocRecord).where(
            dm.VsbAllocRecord.batch_id == b.id, (dm.VsbAllocRecord.review_status != "pending") | (dm.VsbAllocRecord.edited == True))) or 0  # noqa: E712
        if reviewed:
            return f"the existing import draft has {reviewed} reviewed or corrected record(s); reset them or withdraw the draft first"
    return None


def _discard_import_draft(db: Session, d: date, s: str) -> None:
    for b in db.scalars(select(dm.VsbAllocBatch).where(dm.VsbAllocBatch.exam_date == d, dm.VsbAllocBatch.session == s,
                                                       dm.VsbAllocBatch.status == "draft",
                                                       dm.VsbAllocBatch.parser_version == PARSER_VERSION)).all():
        db.execute(delete(dm.VsbAllocIssue).where(dm.VsbAllocIssue.batch_id == b.id))
        db.execute(delete(dm.VsbAllocRecord).where(dm.VsbAllocRecord.batch_id == b.id))
        db.delete(b)
    db.flush()


def run(db: Session, payload, *, file_sha256: str, actor: str, role: str | None = None, request=None,
        dry_run: bool = True, documents: dict | None = None, provenance: dict | None = None) -> dict:
    """Validate, cross-check and (unless dry_run) stage the original allotments. Returns a report.

    ``documents`` optionally maps a source URL to provenance metadata (sha256, page_count, document_type,
    first_seen_at) taken from the original mirror's own document table.
    """
    rows, rejected = parse_payload(payload)
    keep, conflicts, merged = _group_identical(rows)
    imported_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    built = _build(keep, known_register_numbers(db), file_sha256, imported_at, provenance)
    documents = documents or (provenance or {}).get("documents") or {}

    sessions = []
    for (d, s), items in sorted(built["groups"].items()):
        blocker = _session_blocker(db, d, s)
        flagged = sum(1 for i in items if i["flags"])
        blocking = sum(1 for i in items if set(i["flags"]) & ERROR_FLAGS)
        sessions.append({"exam_date": d.isoformat(), "session": s, "records": len(items), "flagged": flagged,
                         "blocking": blocking, "student_linked": sum(1 for i in items if i["student_id"]),
                         "skipped_reason": blocker})

    report = {"adapter": ADAPTER, "parser_version": PARSER_VERSION, "file_sha256": file_sha256, "imported_at": imported_at,
              "dry_run": dry_run, "registers": len({r.register for r in rows}), "rows_read": len(rows) + len(rejected), "rows_valid": len(rows), "rows_rejected": len(rejected),
              "rejected": rejected[:MAX_LISTED], "identical_duplicates_merged": merged, "conflicts": conflicts[:MAX_LISTED],
              "conflicts_total": len(conflicts), "duplicate_seats": built["duplicate_seats"], "sessions": sessions,
              "records_to_stage": sum(x["records"] for x in sessions if not x["skipped_reason"]),
              "batches": [], "note": "Staged as draft batches only. Nothing is visible to students until approval and publication."}
    if dry_run:
        return report

    for (d, s), items in sorted(built["groups"].items()):
        if _session_blocker(db, d, s):
            continue
        _discard_import_draft(db, d, s)
        sources = defaultdict(int)
        for i in items:
            sources[i["source_url"]] += 1
        primary = max(sources, key=lambda u: (sources[u], u))
        batch = dm.VsbAllocBatch(
            exam_date=d, session=s, exam_name=None, hall_version_id=None, seat_version_id=None, status="draft",
            parser_version=PARSER_VERSION, created_by=actor[:80],
            summary=json.dumps({"adapter": ADAPTER, "file_sha256": file_sha256, "imported_at": imported_at, "imported_by": actor,
                                "primary_source": {"title": urlsplit(primary).path.rsplit("/", 1)[-1], "url": primary},
                                "source_urls": sorted(sources), "source_documents": {u: documents[u] for u in sources if u in documents},
                                "records": len(items), "flagged": sum(1 for i in items if i["flags"]),
                                "blocking": sum(1 for i in items if set(i["flags"]) & ERROR_FLAGS),
                                "note": "Imported from an external mirror. Review every flagged record against the official PDF."},
                               sort_keys=True))
        db.add(batch)
        db.flush()
        for i in items:
            db.add(dm.VsbAllocRecord(batch_id=batch.id, register_number=i["register_number"], id_kind=i["id_kind"],
                                     student_id=i["student_id"], subject_code=i["subject_code"],
                                     subject_title=i["subject_title"], hall=i["hall"], seat=i["seat"], sources=i["sources"],
                                     flags=json.dumps(sorted(i["flags"])), detail=json.dumps(i["detail"], sort_keys=True),
                                     confidence=None, review_status="pending",
                                     verification_status=i.get("verification_status", "UNRESOLVED"),
                                     published=False))
        for issue in built["issues"].get((d, s), []):
            db.add(dm.VsbAllocIssue(batch_id=batch.id, kind=issue["kind"][:40], severity=issue["severity"],
                                    message=issue["message"][:2000], register_number=issue["register_number"],
                                    hall=issue["hall"], status="open"))
        report["batches"].append({"id": batch.id, "exam_date": d.isoformat(), "session": s, "records": len(items)})
    audit.record(db, actor, "vsb_alloc.original_imported", "original-portal", {
        "file_sha256": file_sha256, "batches": len(report["batches"]), "records": report["records_to_stage"],
        "rejected": len(rejected), "conflicts": len(conflicts)}, request, role)
    db.commit()
    return report
