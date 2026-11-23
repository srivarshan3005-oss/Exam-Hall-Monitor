"""Starts a throw-away server (temp SQLite DB, synthetic data incl. published VSB rows in each verification state), then runs
browser_e2e.mjs in real headless Chromium (default) or Firefox (BROWSER=firefox FIREFOX_PATH=/path/to/firefox). Needs Node 18+ and `npm ci` in this folder (downloads a bundled Chromium via npm).
Usage (from backend/):  python tests/browser_e2e/run_browser_e2e.py"""
import os, subprocess, sys, tempfile, time, shutil, urllib.request
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
TMP = tempfile.mkdtemp(prefix="em_br_")
PORT = os.environ.get("E2E_PORT", "8766")
PW = "Sturdy-Pass-2026-xyz"
env = dict(os.environ, DATABASE_URL="sqlite:///" + Path(TMP, "e2e.db").as_posix(), SECRET_KEY="e2e-secret-key-0123456789-abcdefghijklmnopqrstuvwxyz",
           ENVIRONMENT="test", PBKDF2_ROUNDS="1000", SEED_DEMO="false", DOCUMENT_STORAGE_DIR=Path(TMP, "docs").as_posix(),
           PUBLIC_BASE_URL=f"http://127.0.0.1:{PORT}", CORS_ORIGINS=f"http://127.0.0.1:{PORT}")
os.environ.update(env)
sys.path[:0] = [str(BACKEND), str(BACKEND / "tests")]
from app import models, doc_models as dm  # noqa
from app.database import SessionLocal
from app.dbcheck import migrate
from app.security import hash_password
migrate()
with SessionLocal() as db:
    studs = []
    for i, (reg, nm, dept, yr) in enumerate([("990025106001", "Asha Rao", "Electronics and Communication", 2), ("990025106002", "Ravi Kumar", "Electronics and Communication", 2), ("990025205001", "Meena Iyer", "Computer Science", 2)]):
        s = models.Student(register_number=reg, full_name=nm, department=dept, year=yr, email=f"s{i}@example.test"); db.add(s); studs.append(s)
    db.commit()
    for name, role, stu in [("e2e-admin", "admin", None), ("e2e-staff", "staff", None), ("e2e-invig", "invigilator", None),
                            ("e2e-student", "student", studs[0]), ("e2e-legacy", "student", studs[2])]:
        db.add(models.User(username=name, password_hash=hash_password(PW), role=role, student_id=stu.id if stu else None, active=True))
    b = dm.VsbAllocBatch(exam_date=date(2099, 1, 15), session="AN", created_by="seed", status="published")
    db.add(b); db.commit()
    for stu, st, seat in zip(studs, ("FULLY_VERIFIED", "HALL_LIST_CONFIRMED", "UNRESOLVED"), ("11", "12", "13")):
        db.add(dm.VsbAllocRecord(batch_id=b.id, register_number=stu.register_number, student_id=stu.id, subject_code="23ECT307",
                                 subject_title="DIGITAL ELECTRONICS", hall="MB III A103", seat=seat, review_status="approved",
                                 published=True, verification_status=st))
    db.commit()
srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", PORT], cwd=BACKEND, env=env,
                       stdout=open(Path(TMP, "server.log"), "w"), stderr=subprocess.STDOUT)
code = 1
try:
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=1); break
        except Exception:
            time.sleep(0.5)
    else:
        raise SystemExit("server did not start; see " + str(Path(TMP, "server.log")))
    code = subprocess.call(["node", str(HERE / "browser_e2e.mjs")], env=dict(env, BASE=f"http://127.0.0.1:{PORT}", E2E_PW=PW), cwd=HERE)
finally:
    srv.terminate()
    try: srv.wait(10)
    except Exception: srv.kill()
    if code: print(Path(TMP, "server.log").read_text()[-2500:])
    shutil.rmtree(TMP, ignore_errors=True)
sys.exit(code)
