"""Starts a throw-away server (temp database, synthetic data), seeds users and runs e2e.js (jsdom) against it.
Usage (from backend/):  python tests/e2e_jsdom/run_e2e.py     — needs Node 18+ and `npm install` in this folder."""
import os, subprocess, sys, tempfile, time, shutil, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
TMP = tempfile.mkdtemp(prefix="em_e2e_")
PORT = os.environ.get("E2E_PORT", "8765")
PW = "Sturdy-Pass-2026-xyz"
env = dict(os.environ, DATABASE_URL="sqlite:///" + Path(TMP, "e2e.db").as_posix(), SECRET_KEY="e2e-secret-key-0123456789-abcdefghijklmnopqrstuvwxyz",
           ENVIRONMENT="test", PBKDF2_ROUNDS="1000", SEED_DEMO="false", DOCUMENT_STORAGE_DIR=Path(TMP, "docs").as_posix(),
           PUBLIC_BASE_URL=f"http://127.0.0.1:{PORT}", CORS_ORIGINS=f"http://127.0.0.1:{PORT}",
           SCHEDULER_ENABLED="false", VSB_AUTO_DISCOVER_ENABLED="false")   # the UI test must never depend on the live college site
os.environ.update(env)
sys.path[:0] = [str(BACKEND), str(BACKEND / "tests")]
from app import models, doc_models  # noqa
from app.database import SessionLocal
from app.dbcheck import migrate
from app.security import hash_password
migrate()
with SessionLocal() as db:
    studs = []
    for i, (reg, nm, dept, yr) in enumerate([("990025106001", "Asha Rao", "Electronics and Communication", 2), ("990025106002", "Ravi Kumar", "Electronics and Communication", 2), ("990025205001", "Meena Iyer", "Computer Science", 2)]):
        s = models.Student(register_number=reg, full_name=nm, department=dept, year=yr, email=f"s{i}@example.test"); db.add(s); studs.append(s)
    db.commit()
    for name, role, stu in [("e2e-super", "super_admin", None), ("e2e-admin", "admin", None), ("e2e-staff", "staff", None), ("e2e-invig", "invigilator", None), ("e2e-student", "student", studs[0])]:
        db.add(models.User(username=name, password_hash=hash_password(PW), role=role, student_id=stu.id if stu else None, active=True))
    db.commit()
srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", PORT], cwd=BACKEND, env=env, stdout=open(Path(TMP, "server.log"), "w"), stderr=subprocess.STDOUT)
# live-monitoring fixtures: the generated 20-Nov PDFs are ingested exactly like downloads (E2E_NO_LIVE=1 skips them)
if not os.environ.get('E2E_NO_LIVE'):
    from v7_pdfs import write_hall_pdf, write_seat_pdf
    from app.vsb_live import pipeline
    _t = Path(TMP)
    with SessionLocal() as db:
        pipeline.import_local_pdf(db, write_hall_pdf(_t / "20.11.26-AN-HALL.pdf"), "hall", source_url="https://vsbec.edu.in/wp-content/uploads/2026/11/20.11.26-AN-HALL.pdf")
        pipeline.import_local_pdf(db, write_seat_pdf(_t / "20.11.26-AN-SEAT.pdf"), "seat", source_url="https://vsbec.edu.in/wp-content/uploads/2026/11/20.11.26-AN-SEAT.pdf")
        pipeline.ingest_pending(db); pipeline.rebuild_index(db)
code = 1
try:
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=1); break
        except Exception:
            time.sleep(0.5)
    else:
        raise SystemExit("server did not start; see " + str(Path(TMP, "server.log")))
    import pdf_factory as pf
    Path(TMP, "tt.pdf").write_bytes(pf.table_pdf())
    env2 = dict(env, BASE=f"http://127.0.0.1:{PORT}", E2E_PW=PW, E2E_PDF=str(Path(TMP, "tt.pdf")))
    code = subprocess.call(["node", str(HERE / "e2e.js")], env=env2, cwd=HERE)
finally:
    srv.terminate()
    try: srv.wait(10)
    except Exception: srv.kill()
    if code: print(Path(TMP, "server.log").read_text()[-2500:])
    shutil.rmtree(TMP, ignore_errors=True)
sys.exit(code)
