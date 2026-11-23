"""Explain why records need manual verification.   Usage (from the backend folder):
    .venv\\Scripts\\python.exe scripts\\why_review.py 922525106326     one register number
    .venv\\Scripts\\python.exe scripts\\why_review.py                  summary of the most common causes
Read-only: it never changes the database."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select  # noqa: E402

from app import doc_models as dm  # noqa: E402
from app.database import SessionLocal  # noqa: E402


def main() -> int:
    reg = sys.argv[1].strip().upper() if len(sys.argv) > 1 else None
    db = SessionLocal()
    try:
        q = select(dm.LiveAllotment).where(dm.LiveAllotment.is_current == True)  # noqa: E712
        if reg:
            q = q.where(dm.LiveAllotment.register_number == reg)
        rows = db.scalars(q.order_by(dm.LiveAllotment.exam_date)).all()
        if reg:
            for a in rows:
                print(f"{a.exam_date} {a.session} {a.subject_code} status={a.status} hall={a.hall} seat={a.seat} "
                      f"hall_page={a.hall_page} seat_page={a.seat_page}")
                print("   flags:", a.flags)
                print("   notes:", a.notes)
            return 0
        total = Counter(a.status for a in rows)
        print("Records by status:", dict(total))
        causes = Counter()
        for a in rows:
            if a.status == "MANUAL_REVIEW":
                causes.update(json.loads(a.flags or "[]"))
        print("Flags on MANUAL_REVIEW records (most common first):")
        for f, n in causes.most_common():
            print(f"  {n:6d}  {f}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
