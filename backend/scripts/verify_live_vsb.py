"""LIVE end-to-end check against the real vsbec.edu.in. Run it on a machine with internet access:

    cd backend && python scripts/verify_live_vsb.py [--hall URL --seat URL]

It uses a THROWAWAY database and storage folder (nothing of yours is touched), then: reads the configured COE page, discovers the
hall/seat PDFs, downloads them, hashes them, parses them, pairs them by date+session, stages a DRAFT batch, and compares the
parser's figures with the totals printed inside the PDFs. It never approves or publishes anything and prints PASS/FAIL/NOT TESTED
per stage; a network failure is reported as FAIL for the stage that hit it and NOT TESTED for the stages after it.
"""
import argparse, hashlib, json, os, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ap = argparse.ArgumentParser()
ap.add_argument("--hall", default="https://vsbec.edu.in/wp-content/uploads/2026/11/20.11.26-AN-HALL.pdf")
ap.add_argument("--seat", default="https://vsbec.edu.in/wp-content/uploads/2026/11/20.11.26-AN-SEAT.pdf")
args = ap.parse_args()
tmp = tempfile.mkdtemp(prefix="vsb_live_")
os.environ.update(DATABASE_URL="sqlite:///" + (Path(tmp) / "t.db").as_posix(), DOCUMENT_STORAGE_DIR=str(Path(tmp) / "up"),
                  SECRET_KEY="live-verify-" + "k" * 48, ENVIRONMENT="development", SCHEDULER_ENABLED="false",
                  BACKUP_DIR=str(Path(tmp) / "b"), LOG_DIR=str(Path(tmp) / "l"), VSB_REQUEST_DELAY_SECONDS="1")
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
subprocess.run([sys.executable, "-m", "app.cli", "migrate"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

from sqlalchemy import select
from app import doc_models as dm, vsb_sources as vs
from app.database import SessionLocal
from app.vsb_alloc import service as svc
from app.vsb_alloc.hall_parser import parse_hall_pdf
from app.vsb_alloc.seat_parser import parse_seat_pdf
from app.routers import docproc

V = {k: "NOT TESTED" for k in "ABCDEFG"}
rep = {"verdicts": V, "workdir": tmp}
with SessionLocal() as db:
    run = vs.run_discovery(db, actor="live-verify", trigger="manual", download=True, auto_process=None)
    rep["discovery_run"] = {k: run.get(k) for k in ("status", "links_found", "new_links", "downloaded", "duplicates", "unavailable", "failed", "message")}
    V["A"] = "PASS" if run["status"] != "failed" else "FAIL"
    if V["A"] == "PASS":
        links = {l.url: l for l in db.scalars(select(dm.VsbSourceLink)).all()}
        found = {"hall": links.get(args.hall), "seat": links.get(args.seat)}
        V["B"] = "PASS" if all(found.values()) else "FAIL"
        rep["discovered"] = {k: (v.url if v else None) for k, v in found.items()}
        if V["B"] == "PASS":
            vers = {}
            for k, l in found.items():
                doc = db.get(dm.OfficialDocument, l.document_id) if l.document_id else None
                ver = vs._latest_version(db, doc.id) if doc else None
                if ver:
                    data = Path(docproc.stored_path(ver)).read_bytes()
                    ok = data[:5] == b"%PDF-" and hashlib.sha256(data).hexdigest() == ver.sha256
                    rep.setdefault("downloads", {})[k] = {"bytes": len(data), "sha256": ver.sha256, "hash_matches_file": ok,
                                                           "date": str(doc.exam_date), "session": doc.session, "title": doc.title}
                    if ok:
                        vers[k] = ver
            V["C"] = "PASS" if len(vers) == 2 else "FAIL"
            if V["C"] == "PASS":
                hall = parse_hall_pdf(svc.load_pages(db, vers["hall"]))
                seat = parse_seat_pdf(svc.load_pages(db, vers["seat"]))
                bad_tot = [(t.department, t.declared, t.extracted) for t in hall.dept_totals if t.ok is not True]
                errs = [i.kind for i in hall.all_issues() + seat.all_issues() if i.severity == "error"]
                rep["parse"] = {"hall_students": hall.total_students(), "dept_totals": {t.department: [t.declared, t.extracted] for t in hall.dept_totals},
                                "seat_sheets": len(seat.sheets), "seat_students": sum(s.grid_count for s in seat.sheets),
                                "dept_total_mismatches": bad_tot, "error_issues": sorted(set(errs))}
                V["E"] = "PASS" if not bad_tot and not errs and hall.total_students() == sum(s.grid_count for s in seat.sheets) else "FAIL"
                notes = svc.auto_stage(db, "live-verify")
                rep["staging_notes"] = notes
                b = db.scalar(select(dm.VsbAllocBatch).order_by(dm.VsbAllocBatch.id.desc()))
                if b:
                    recs = db.scalars(select(dm.VsbAllocRecord).where(dm.VsbAllocRecord.batch_id == b.id)).all()
                    rep["batch"] = {"status": b.status, "date": str(b.exam_date), "session": b.session, "records": len(recs),
                                    "with_hall_and_seat": sum(1 for r in recs if r.hall and r.seat), "published": sum(r.published for r in recs),
                                    "roster_matched": sum(1 for r in recs if r.student_id), "roster_unmatched": sum(1 for r in recs if not r.student_id)}
                    V["G"] = "PASS" if rep["batch"]["records"] == hall.total_students() and rep["batch"]["published"] == 0 else "FAIL"
                    V["F"] = "PASS" if rep["batch"]["roster_matched"] > 0 else "NOT TESTED (empty roster in the throwaway DB; import your authorised roster to test)"
print(json.dumps(rep, indent=1, default=str))
print("\nVERDICTS (A site, B discovery, C download+hash, E parsing, F roster, G hall/seat staged):", V)
