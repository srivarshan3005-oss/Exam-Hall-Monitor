"""Show which official PDFs were found and how many students each exam date has.   Usage (from the backend folder):
    python scripts/what_found.py
Read-only: it never changes the database."""
from __future__ import annotations

import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select  # noqa: E402

from app import doc_models as dm  # noqa: E402
from app.database import SessionLocal  # noqa: E402


def main() -> int:
    db = SessionLocal()
    try:
        since = date.today() - timedelta(days=4)
        links = db.scalars(select(dm.VsbSourceLink).where(dm.VsbSourceLink.doc_kind.in_(("hall_allotment", "seating_allotment")))
                           .order_by(dm.VsbSourceLink.exam_date.desc(), dm.VsbSourceLink.session)).all()
        print(f"Official hall / seat PDF links found: {len(links)}")
        print("date        session kind               download   still on site  file")
        for l in links:
            if l.exam_date is None or l.exam_date >= since:
                print(f"{l.exam_date or '(no date)'}  {l.session or '-':<7} {l.doc_kind:<18} {l.download_status:<10} {str(l.still_listed):<14} {l.url.rsplit('/', 1)[-1]}"
                      + (f"   ERROR: {l.last_error}" if l.last_error else ""))
        print()
        rows = db.execute(select(dm.LiveAllotment.exam_date, dm.LiveAllotment.session, dm.LiveAllotment.status)
                          .where(dm.LiveAllotment.is_current == True)).all()  # noqa: E712
        per = Counter((d, s, st) for d, s, st in rows)
        print("Students per exam date / session / status (what the website is built from):")
        for (d, s, st), n in sorted(per.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2]), reverse=True):
            if d >= since:
                print(f"{d} {s}  {st:<14} {n}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
