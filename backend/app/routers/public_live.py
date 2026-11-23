"""Public student API of the live system - register number ONLY, no login.

  GET /api/public/lookup/{register_number}                      every matching examination record
  GET /api/public/page/{register_number}/{record_id}/{source}   the ORIGINAL, UNMASKED PDF page image (source = hall | seat)
  GET /api/public/slip/{register_number}                        printable slip (HTML)
  GET /api/public/status                                        last scan / last successful scan / source health summary

Privacy and honesty rules
* The student types nothing but a register number. Nothing is invented: absent fields are absent.
* The page image is the official page, complete and unmasked (see vsb_live/render.py). It is the same document the college
  publishes on its own website. The searched number is highlighted by a separate overlay when it can be located reliably.
* No endpoint lists, exports or searches by anything other than ONE register number. Requests are rate limited per client and
  repeated misses are throttled (anti-enumeration).
"""
from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import doc_models as dm
from ..config import settings
from ..database import get_db
from ..deps_ip import client_ip
from ..ratelimit import limiter
from ..vsb_live import cycle, locations, render
from ..vsb_live.pipeline import weekday_name
from .students import note_miss, parse_register, public_guard

router = APIRouter(prefix="/api/public", tags=["Public live lookup (register number only)"])

STATUS_LABELS = {
    "CONFIRMED": "Hall and seat confirmed in both official documents",
    "HALL_ONLY": "Hall confirmed. Seat not published / not verified yet",
    "SEAT_ONLY": "Seat sheet found. Hall list not matched yet",
    "CONFLICT": "Official documents disagree - check the original pages",
    "MANUAL_REVIEW": "Manual verification required - check the original page",
}
iso = lambda d: d.isoformat() if d else None  # noqa: E731


def _unverified(notes: str | None) -> dict | None:
    for part in (notes or "").split(" | "):
        if part.startswith("unverified:"):
            try:
                return json.loads(part[len("unverified:"):])
            except ValueError:
                return None
    return None


def _human_notes(notes: str | None) -> list[str]:
    return [p for p in (notes or "").split(" | ") if p and not p.startswith(("unverified:", "page totals did not add up"))]


def _src(db: Session, a: dm.LiveAllotment, which: str) -> dict | None:
    vid, page, fn, url = ((a.hall_version_id, a.hall_page, a.hall_filename, a.hall_source_url) if which == "hall"
                          else (a.seat_version_id, a.seat_page, a.seat_filename, a.seat_source_url))
    if not vid or page is None:
        return None
    v = db.get(dm.DocumentVersion, vid)
    if v is None:
        return None
    from ..vsb_sources import is_allowed_url
    url = url if url and is_allowed_url(url) else None          # local imports have no official link to show
    cv = f"{settings.preview_cache_version}-{v.sha256[:10]}"
    return {"kind": which, "label": "Hall allotment" if which == "hall" else "Seating allotment", "filename": fn, "page": page + 1,
            "page_count": v.page_count, "official_url": url, "pdf_sha256": v.sha256[:16],
            "image_url": f"/api/public/page/{a.register_number}/{a.id}/{which}?v={cv}",
            "plain_image_url": f"/api/public/page/{a.register_number}/{a.id}/{which}?hl=0&v={cv}",
            "downloaded_at": iso(v.downloaded_at)}


REASON_TEXT = {
    "seat_from_text_order": "The seat number was guessed from the order of text on the page, not from the seat box, so it may be wrong.",
    "ocr_text": "This page is a scanned image, so the numbers were read by OCR and may contain mistakes.",
    "ocr_ambiguous": "The scanned text was unclear, so the number could not be read with certainty.",
    "seat_label_missing": "The seat number label could not be found next to this register number.",
    "seat_label_ambiguous": "More than one seat number was found near this register number.",
    "seat_cell_ambiguous": "The seat box for this register number could not be told apart from its neighbours.",
    "seat_missing": "No seat number was found for this register number.",
    "hall_missing": "The hall name could not be read on the page.",
    "hall_check_failed": "The hall check did not match the page totals.",
    "group_check_failed": "The student count on the page did not match the list.",
    "department_total_mismatch": "The department total on the page did not match the list.",
    "hall_capacity_exceeded": "More students than seats were found for this hall.",
    "hall_label_variant": "The hall name is spelt differently in two places.",
    "subject_missing": "The subject code could not be read.",
    "session_unknown": "The exam session (FN/AN) could not be read.",
    "source_not_official": "The file did not come from an official college address.",
    "provenance_mismatch": "The file does not match the official source record.",
}


def _reasons(flags_json: str | None) -> list[str]:
    try:
        flags = json.loads(flags_json or "[]")
    except ValueError:
        return []
    return [REASON_TEXT[f] for f in flags if f in REASON_TEXT]


def serialize(db: Session, a: dm.LiveAllotment) -> dict:
    loc = locations.public_location(db, a.hall) if a.hall else {}
    t = settings.session_time_map.get(a.session)
    unv = _unverified(a.notes) if a.status in ("MANUAL_REVIEW", "CONFLICT") else None
    return {"id": a.id, "register_number": a.register_number, "date": a.exam_date.isoformat(), "weekday": weekday_name(a.exam_date),
            "session": a.session, "session_time": t, "session_time_note": "Configured time; the PDFs do not print it." if t else None,
            "subject_code": a.subject_code or None, "subject_name": a.subject_name, "programme": a.programme, "department": a.department,
            "hall": a.hall, "seat": a.seat, "status": a.status, "status_label": STATUS_LABELS[a.status],
            "seat_note": ("Seat not published or not verified yet." if a.status == "HALL_ONLY" else None),
            "unverified": unv, "review_reasons": _reasons(a.flags) if a.status == "MANUAL_REVIEW" else [], "notes": _human_notes(a.notes), "revision": a.revision, "revised": "revised_allotment" in json.loads(a.flags or "[]"),
            "first_seen_at": iso(a.first_seen_at), "last_verified_at": iso(a.last_verified_at),
            "sources": [s for s in (_src(db, a, "hall"), _src(db, a, "seat")) if s],
            "location": loc or None, "location_message": None if loc else locations.NOT_VERIFIED_TEXT if a.hall else None}


def portal_cutoff():
    """Earliest exam date the student portal shows (None = no limit). Older exams are hidden, not deleted."""
    n = settings.portal_past_days
    if n is None or n < 0:
        return None
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo(settings.app_timezone)).date() - timedelta(days=n)


def data_version(db: Session, reg: str) -> str:
    """Cheap change token for one register number (no serialisation): changes when any shown record is added/revised/re-verified."""
    import hashlib
    q = select(func.count(), func.max(dm.LiveAllotment.id), func.max(dm.LiveAllotment.revision), func.max(dm.LiveAllotment.last_verified_at)) \
        .where(dm.LiveAllotment.register_number == reg, dm.LiveAllotment.is_current == True)  # noqa: E712
    cutoff = portal_cutoff()
    if cutoff is not None:
        q = q.where(dm.LiveAllotment.exam_date >= cutoff)
    n, mid, rev, lv = db.execute(q).one()
    scan = cycle.status_summary(db)["last_scan_status"]
    return hashlib.sha1(f"{n}|{mid}|{rev}|{lv}|{scan}".encode()).hexdigest()[:16]


def lookup(db: Session, reg: str) -> dict:
    q = select(dm.LiveAllotment).where(dm.LiveAllotment.register_number == reg, dm.LiveAllotment.is_current == True)  # noqa: E712
    cutoff = portal_cutoff()
    if cutoff is not None:
        q = q.where(dm.LiveAllotment.exam_date >= cutoff)
    rows = db.scalars(q.order_by(dm.LiveAllotment.exam_date, dm.LiveAllotment.session, dm.LiveAllotment.subject_code)).all()
    st = cycle.status_summary(db)
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo(settings.app_timezone)).date().isoformat()      # the server's idea of "today" (exam-day logic)
    out: dict = {"version": data_version(db, reg), "register_number": reg, "college_name": settings.college_name, "today": today, "records": [serialize(db, a) for a in rows],
                 "last_synchronised_at": st["last_success_at"], "last_scan_status": st["last_scan_status"], "warnings": []}
    scan_failed = st["last_scan_status"] == "failed"
    if rows:
        statuses = {a.status for a in rows}
        out["status"] = "conflict" if "CONFLICT" in statuses else "manual_verification" if "MANUAL_REVIEW" in statuses else "found"
        if scan_failed:
            out["warnings"].append("The official website could not be checked in the latest scan. The records below were verified "
                                   f"earlier (last successful check: {st['last_success_at'] or 'unknown'}).")
        out["message"] = {"found": f"{len(rows)} examination record(s) found.",
                          "conflict": "A record has conflicting information in the official documents. Check the original pages.",
                          "manual_verification": "A record needs manual verification. Use the original page shown below."}[out["status"]]
        return out
    busy = db.scalar(select(func.count()).select_from(dm.LiveIngest).where(dm.LiveIngest.status.in_(("pending", "processing")))) or 0
    parsed = db.scalar(select(func.count()).select_from(dm.LiveIngest).where(dm.LiveIngest.status == "ok")) or 0
    if busy:
        out["status"], out["message"] = "processing", "A newly published document is being processed. Please try again in a few minutes."
    elif scan_failed:
        out["status"] = "source_unavailable"
        out["message"] = ("No record was found in the documents stored so far, and the official website could not be reached in the "
                          "latest check. Please try again later or check the official notice.")
    elif parsed == 0:
        out["status"], out["message"] = "not_yet_published", "No hall or seating allotment has been published/processed yet."
    else:
        out["status"] = "no_match"
        out["message"] = ("No allotment was found for this register number in the documents published so far. "
                          "It may not have been published yet; check again later or ask the Controller of Examinations.")
    return out


@router.get("/lookup/{register_number}")
def public_lookup(register_number: str, request: Request, db: Session = Depends(get_db)):
    ip = public_guard(request)
    reg = parse_register(register_number, ip)
    res = lookup(db, reg)
    if not res["records"]:
        note_miss(ip)
    return res


@router.get("/version/{register_number}")
def public_version(register_number: str, request: Request, response: Response, db: Session = Depends(get_db)):
    """Tiny change check used by the portal every few seconds; the full lookup runs only when this token changes."""
    ip = public_guard(request)
    reg = parse_register(register_number, ip)
    response.headers["Cache-Control"] = "no-store"
    return {"version": data_version(db, reg)}


def _row_for(db: Session, reg: str, record_id: int) -> dm.LiveAllotment:
    a = db.get(dm.LiveAllotment, record_id)
    if a is None or a.register_number != reg or not a.is_current:
        raise HTTPException(404, "No page found")
    return a


@router.get("/page/{register_number}/{record_id}/{source}")
def original_page(register_number: str, record_id: int, source: Literal["hall", "seat"], request: Request,
                  hl: int = Query(1, ge=0, le=1), dpi: int = Query(0, ge=0, le=220), db: Session = Depends(get_db)):
    """PNG of the whole original PDF page. NOTHING is masked. hl=0 returns the pristine page without the highlight overlay."""
    ip = client_ip(request)
    ok, retry = limiter.check_and_record(f"pubimg:{ip}", 240, 60)
    if not ok:
        raise HTTPException(429, "Too many requests. Please wait and try again.", headers={"Retry-After": str(retry)})
    reg = parse_register(register_number, ip)
    a = _row_for(db, reg, record_id)
    vid, page = (a.hall_version_id, a.hall_page) if source == "hall" else (a.seat_version_id, a.seat_page)
    v = db.get(dm.DocumentVersion, vid) if vid else None
    if v is None or page is None:
        raise HTTPException(404, "No page found")
    from . import docproc
    try:
        r = render.render_original_page(docproc.stored_path(v), page, reg, highlight=bool(hl), dpi=dpi or None, cache_key=v.sha256)
    except render.PageUnavailable:
        raise HTTPException(404, "No page found")
    except Exception:  # noqa: BLE001
        raise HTTPException(404, "No page found")
    return Response(r.png, media_type="image/png", headers={
        "Cache-Control": "private, max-age=120", "X-Content-Type-Options": "nosniff", "X-Original-Page": "unmasked",
        "X-Highlight-Count": str(max(r.highlights, 0)), "X-Preview-Cache-Version": settings.preview_cache_version,
        "Content-Disposition": f'inline; filename="original-page-{record_id}-{source}.png"'})


@router.get("/status")
def public_status(db: Session = Depends(get_db)):
    st = cycle.status_summary(db)
    health = db.scalars(select(dm.VsbSourceHealth)).all()
    docs = db.scalar(select(func.count()).select_from(dm.LiveIngest).where(dm.LiveIngest.status == "ok")) or 0
    return {**st, "poll_minutes": settings.poll_minutes, "poll_seconds": settings.poll_seconds, "documents_processed": docs,
            "sources": [{"method": h.method, "status": h.last_status, "last_success_at": iso(h.last_success_at)} for h in health
                        if h.method in ("html", "wp_media", "sitemap")],
            "official_pages": ["https://vsbec.edu.in/controller-of-examination/", "https://coe.vsbec.edu.in/"],
            "college_name": settings.college_name}


@router.get("/published")
def published(db: Session = Depends(get_db)):
    """Which examination sessions have published allotments (counts and official links only - never student data)."""
    rows = db.execute(select(dm.LiveAllotment.exam_date, dm.LiveAllotment.session, func.count(), func.max(dm.LiveAllotment.last_verified_at),
                             func.max(dm.LiveAllotment.hall_source_url), func.max(dm.LiveAllotment.seat_source_url))
                      .where(dm.LiveAllotment.is_current == True,  # noqa: E712
                             *([dm.LiveAllotment.exam_date >= portal_cutoff()] if portal_cutoff() is not None else []))
                      .group_by(dm.LiveAllotment.exam_date, dm.LiveAllotment.session)
                      .order_by(dm.LiveAllotment.exam_date.desc(), dm.LiveAllotment.session)).all()
    from ..vsb_sources import is_allowed_url
    ok = lambda u: u if u and is_allowed_url(u) else None  # noqa: E731
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo(settings.app_timezone)).date().isoformat()
    return {"today": today,
            "sessions": [{"date": d.isoformat(), "weekday": weekday_name(d), "session": s, "session_time": settings.session_time_map.get(s), "students": n,
                          "last_verified_at": iso(lv), "hall_pdf": ok(h), "seat_pdf": ok(st)} for d, s, n, lv, h, st in rows][:40]}


# ----------------------------------------------------------------------------- printable slip
_E = html.escape


@router.get("/slip/{register_number}", response_class=HTMLResponse)
def slip(register_number: str, request: Request, db: Session = Depends(get_db)):
    ip = public_guard(request)
    reg = parse_register(register_number, ip)
    res = lookup(db, reg)
    rows = []
    for r in res["records"]:
        hall = r["hall"] or (f"unverified: {_E(str((r['unverified'] or {}).get('hall') or '-'))}" if r["unverified"] else "-")
        seat = r["seat"] or ("not published / not verified" if r["status"] == "HALL_ONLY" else "-")
        src = "; ".join(f"{_E(s['filename'] or '')} p.{s['page']}" for s in r["sources"])
        loc = r.get("location") or {}
        locs = ", ".join(f"{k}: {_E(str(loc[k]))}" for k in ("building", "block", "floor", "room") if loc.get(k)) or _E(r["location_message"] or "")
        rows.append(f"<tr><td>{_E(r['date'])}<br>{_E(r['weekday'])}</td><td>{_E(r['session'])}</td>"
                    f"<td>{_E(r['subject_code'] or '')}<br>{_E(r['subject_name'] or '')}</td><td>{_E(hall)}</td><td>{_E(seat)}</td>"
                    f"<td>{_E(r['status_label'])}{' (revised)' if r['revised'] else ''}</td><td>{locs}</td><td>{src}</td></tr>")
    body = "".join(rows) or f"<tr><td colspan='8'>{_E(res['message'])}</td></tr>"
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Examination slip {_E(reg)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="/portal/slip.css"></head>
<body><main><h1>{_E(settings.college_name)}</h1><h2>Examination allotment slip</h2>
<p><strong>Register number:</strong> {_E(reg)} &nbsp; <strong>Generated:</strong> {_E(datetime.now(timezone.utc).strftime('%d-%m-%Y %H:%M UTC'))}
 &nbsp; <strong>Last synchronised:</strong> {_E(res['last_synchronised_at'] or 'unknown')}</p>
<table><thead><tr><th>Date</th><th>Session</th><th>Subject</th><th>Hall</th><th>Seat</th><th>Status</th><th>Location</th><th>Source (PDF page)</th></tr></thead>
<tbody>{body}</tbody></table>
<p class="note">This slip is generated from the college's published hall and seating allotment PDFs. It is not an official hall ticket.
Always verify with the official notice of the Controller of Examinations (vsbec.edu.in/controller-of-examination).</p>
<p class="noprint"><button id="print-btn" type="button">Print</button> <a href="/portal/">Back to search</a></p></main>
<script src="/portal/slip.js"></script></body></html>"""
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})
