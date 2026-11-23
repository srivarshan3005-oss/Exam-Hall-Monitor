"""One complete monitoring cycle: discover -> download -> validate -> parse -> reconcile -> index -> notify -> (optional) sync.

Used by the scheduler (every VSB_POLL_MINUTES and once at start-up), the dashboard "Run scan now" button, the CLI and the
GitHub Actions workflow, so there is exactly one implementation. Each stage is isolated: a failure in one stage is reported
and never erases data or stops the later stages that can still run.
"""
from __future__ import annotations

import logging
import threading

from sqlalchemy import select

from .. import doc_models as dm, vsb_sources as vs
from ..database import SessionLocal
from . import notify, pipeline, supabase_sync

log = logging.getLogger("exam_monitor.cycle")
_lock = threading.Lock()
_holder: dict = {}


def run_cycle(*, trigger: str = "scheduler", actor: str = "scheduler", download: bool = True, rebuild: bool = False) -> dict:
    """Raises RuntimeError('busy') if another cycle is running."""
    if not _lock.acquire(blocking=False):
        raise RuntimeError(f"busy (held by {_holder.get('thread')} trigger={_holder.get('trigger')} since {_holder.get('since')})")
    _holder.update(thread=threading.current_thread().name, trigger=trigger, since=__import__("time").strftime("%H:%M:%S"))
    out: dict = {"trigger": trigger}
    try:
        try:
            with SessionLocal() as db:
                run = vs.run_discovery(db, actor=actor, trigger=trigger, download=download, auto_process=None)
            out["discovery"] = {k: run[k] for k in ("id", "status", "links_found", "new_links", "downloaded", "duplicates",
                                                    "unavailable", "failed", "message")}
        except RuntimeError:
            out["discovery"] = {"status": "busy"}
        except Exception:  # noqa: BLE001
            log.exception("discovery stage failed")
            out["discovery"] = {"status": "failed", "message": "discovery crashed; see server log"}
        events = []
        try:
            with SessionLocal() as db:
                out["ingest"] = pipeline.ingest_pending(db)
                if out["ingest"]["parsed"] or rebuild:
                    r = pipeline.rebuild_index(db)
                    out["index"], events = r["stats"], r["events"]
        except Exception:  # noqa: BLE001
            log.exception("ingest/rebuild stage failed")
            out["ingest_error"] = "ingestion crashed; existing data was kept (see server log)"
        try:
            with SessionLocal() as db:
                out["notifications_queued"] = notify.enqueue_events(db, events)
                out["notifications"] = notify.process_due(db)
        except Exception:  # noqa: BLE001
            log.exception("notification stage failed")
            out["notification_error"] = "notification stage failed (lookups are unaffected)"
        try:
            with SessionLocal() as db:
                out["supabase"] = supabase_sync.sync(db)
        except Exception:  # noqa: BLE001
            log.exception("sync stage failed")
        d = out.get("discovery", {})
        out["status"] = "failed" if d.get("status") == "failed" else "ok" if d.get("status") in ("ok",) else d.get("status", "ok")
        return out
    finally:
        _holder.clear()
        _lock.release()


def status_summary(db) -> dict:
    """Facts for the public footer and the dashboard. `last_success_at` only moves when a scan really read a source."""
    iso = lambda d: d.isoformat() if d else None  # noqa: E731
    last = db.scalar(select(dm.VsbCrawlRun).order_by(dm.VsbCrawlRun.id.desc()).limit(1))
    ok = db.scalar(select(dm.VsbCrawlRun).where(dm.VsbCrawlRun.status.in_(("ok", "partial")))
                   .order_by(dm.VsbCrawlRun.id.desc()).limit(1))
    return {"last_scan_at": iso(last.finished_at or last.started_at) if last else None,
            "last_scan_status": last.status if last else None,
            "last_success_at": iso(ok.finished_at or ok.started_at) if ok else None}
