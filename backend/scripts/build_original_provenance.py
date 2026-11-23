"""Build the per-record provenance file for the original hall-allocation mirror.

Reads the ORIGINAL sabareesh2008/EXAM_MONITOR files (read-only):
  * allotments.json                          (the records the public mirror shows)
  * data/state/vsb_exam_watch.sqlite3        (the mirror's own per-PDF rows and document table)

For every record it takes the hall-allocation PDF row and the seating-chart PDF row from the SQLite database, so the
two PDFs keep their own page numbers, labels and document hashes. The build FAILS if any record does not have exactly
one hall row and exactly one seat row, or if the mirror's seat number or subject disagrees with its own database.

    python scripts/build_original_provenance.py \
        --json /path/to/EXAM_MONITOR-main/allotments.json \
        --sqlite /path/to/EXAM_MONITOR-main/data/state/vsb_exam_watch.sqlite3 \
        --out data/original_portal/allocation_provenance.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(json_path: Path, sqlite_path: Path) -> dict:
    data = json.loads(json_path.read_bytes())
    con = sqlite3.connect(f"file:{sqlite_path.as_posix()}?mode=ro", uri=True)
    rows = con.execute("SELECT register_number, exam_date, session, hall_number, seat_number, page, subject_code, source_url "
                       "FROM allotments").fetchall()
    docs = {}
    for url, sha, extraction in con.execute("SELECT url, sha256, extraction_json FROM documents"):
        try:
            meta = json.loads(extraction or "{}")
        except ValueError:
            meta = {}
        docs[url] = {"filename": url.rsplit("/", 1)[-1], "sha256": sha, "page_count": meta.get("page_count"),
                     "document_type": meta.get("document_type")}
    con.close()

    index = defaultdict(list)
    for r in rows:
        index[(r[0], r[1], r[2])].append(r)

    records, problems = {}, []
    for reg, items in data.items():
        for it in items:
            key = (reg, it["exam_date"], it["session"])
            cands = index.get(key, [])
            halls = [x for x in cands if "hall" in (x[7] or "").lower()]
            seats = [x for x in cands if "seat" in (x[7] or "").lower()]
            if len(halls) != 1 or len(seats) != 1:
                problems.append(f"{reg} {it['exam_date']} {it['session']}: {len(halls)} hall row(s), {len(seats)} seat row(s)")
                continue
            h, s = halls[0], seats[0]
            # the seat sheet carries the seat; the hall list carries the subject
            if str(s[4]) != str(it["seat_number"]) or (h[6] or "") != (it.get("subject_code") or ""):
                problems.append(f"{reg} {it['exam_date']} {it['session']}: JSON seat/subject differ from the mirror database")
                continue
            records[f"{reg}|{it['exam_date']}|{it['session']}"] = {
                "hall_pdf_url": h[7], "hall_pdf_page": h[5], "hall_pdf_label": h[3],
                "seat_pdf_url": s[7], "seat_pdf_page": s[5], "seat_pdf_label": s[3],
                "seat_number": str(s[4]), "subject_code": h[6]}
    if problems:
        raise SystemExit("Build refused. Records that cannot be traced to exactly one hall row and one seat row:\n  "
                         + "\n  ".join(problems[:50]) + (f"\n  ... {len(problems) - 50} more" if len(problems) > 50 else ""))
    used = {v["hall_pdf_url"] for v in records.values()} | {v["seat_pdf_url"] for v in records.values()}
    return {"generated_from": {"allotments_json_sha256": _sha256(json_path), "sqlite_sha256": _sha256(sqlite_path)},
            "records": dict(sorted(records.items())),
            "documents": {u: docs[u] for u in sorted(used) if u in docs}}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--json", required=True, type=Path)
    p.add_argument("--sqlite", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    a = p.parse_args(argv)
    out = build(a.json, a.sqlite)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {len(out['records'])} records and {len(out['documents'])} source documents to {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
