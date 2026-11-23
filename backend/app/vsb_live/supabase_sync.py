"""Optional Supabase mirror of the live allotment index (backend only).

* Enabled only when SUPABASE_URL (https) and SUPABASE_SERVICE_KEY are set. Local SQLite works without it.
* The service-role key stays on the server; students never talk to Supabase. The provided SQL enables Row Level Security with NO
  policy for anon/authenticated users, so the public key can neither read nor write: the mirror is a backup, not a public API.
* Rows are upserted on their natural key, so repeating a sync never duplicates anything. Failures are logged to live_sync_log and
  retried on the next cycle; they never affect lookups.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import doc_models as dm
from ..config import settings

log = logging.getLogger("exam_monitor.supabase")
BATCH = 400
ON_CONFLICT = "register_number,exam_date,session,subject_code,fingerprint"


def now() -> datetime:
    return datetime.now(timezone.utc)


def row_payload(a: dm.LiveAllotment) -> dict:
    return {"register_number": a.register_number, "exam_date": a.exam_date.isoformat(), "session": a.session,
            "subject_code": a.subject_code or "", "subject_name": a.subject_name, "programme": a.programme,
            "department": a.department, "hall": a.hall, "seat": a.seat, "status": a.status, "flags": a.flags,
            "hall_page": a.hall_page, "seat_page": a.seat_page, "hall_source_url": a.hall_source_url,
            "seat_source_url": a.seat_source_url, "fingerprint": a.fingerprint, "revision": a.revision,
            "is_current": a.is_current, "first_seen_at": a.first_seen_at.isoformat() if a.first_seen_at else None,
            "last_verified_at": a.last_verified_at.isoformat() if a.last_verified_at else None}


def _post(rows: list[dict]) -> None:
    url = f"{settings.supabase_url.rstrip('/')}/rest/v1/{settings.supabase_table}?on_conflict={ON_CONFLICT}"
    req = urllib.request.Request(url, data=json.dumps(rows).encode(), method="POST", headers={
        "apikey": settings.supabase_service_key, "Authorization": f"Bearer {settings.supabase_service_key}",
        "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates,return=minimal"})
    with urllib.request.urlopen(req, timeout=30) as r:
        if r.status >= 300:
            raise RuntimeError(f"HTTP {r.status}")


def sync(db: Session, force_all: bool = False) -> dict:
    """Push rows created/superseded since the last successful sync. Returns {'status': ok|failed|skipped, 'records': n}."""
    if not settings.supabase_enabled:
        return {"status": "skipped", "records": 0, "message": "Supabase is not configured (optional)."}
    log_row = dm.LiveSyncLog(target="supabase", status="running")
    db.add(log_row)
    db.commit()
    since = None
    if not force_all:
        last = db.scalar(select(dm.LiveSyncLog.started_at).where(dm.LiveSyncLog.target == "supabase", dm.LiveSyncLog.status == "ok")
                         .order_by(dm.LiveSyncLog.id.desc()).limit(1))
        since = last
    stmt = select(dm.LiveAllotment)
    if since is not None:
        since = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
        stmt = stmt.where(or_(dm.LiveAllotment.first_seen_at >= since, dm.LiveAllotment.superseded_at >= since))
    rows = db.scalars(stmt.order_by(dm.LiveAllotment.id)).all()
    sent = 0
    try:
        for i in range(0, len(rows), BATCH):
            _post([row_payload(a) for a in rows[i:i + BATCH]])
            sent += len(rows[i:i + BATCH])
        log_row.status, log_row.records = "ok", sent
    except urllib.error.HTTPError as e:
        log_row.status, log_row.records, log_row.error = "failed", sent, f"Supabase returned HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        log_row.status, log_row.records, log_row.error = "failed", sent, f"{type(e).__name__}: sync failed"[:200]
        log.warning("supabase sync failed: %s", type(e).__name__)
    log_row.finished_at = now()
    db.commit()
    return {"status": log_row.status, "records": log_row.records, "message": log_row.error}
