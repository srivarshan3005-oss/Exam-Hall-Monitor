"""Starts a throw-away server (temporary database), creates the accounts the original-data workflow needs and runs
e2e_original.js (jsdom, NOT a real browser). Usage from backend/:  python tests/e2e_jsdom/run_original_e2e.py
Needs Node 18+ and `npm ci` in this folder. Reads the operator-supplied allotments.json; when it is absent the run is reported as SKIPPED (exit 0), never as passed."""
import os, subprocess, sys, tempfile, time, shutil, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
SRC = Path(os.environ.get("ORIGINAL_ALLOTMENTS_JSON") or BACKEND / "data" / "original_portal" / "source" / "allotments.json")
if not SRC.is_file():
    print(f"SKIPPED: operator-supplied allotments.json not present ({SRC}); see backend/data/original_portal/README.md")
    sys.exit(0)
TMP = tempfile.mkdtemp(prefix="em_orig_e2e_")
PORT = os.environ.get("E2E_PORT", "8766")
PW = "Sturdy-Pass-2026-xyz"
SAMPLE = "992696352326"
env = dict(os.environ, DATABASE_URL="sqlite:///" + Path(TMP, "e2e.db").as_posix(),
           SECRET_KEY="orig-e2e-secret-0123456789-abcdefghijklmnopqrstuvwxyz", ENVIRONMENT="test", PBKDF2_ROUNDS="1000",
           SEED_DEMO="false", SCHEDULER_ENABLED="false", DOCUMENT_STORAGE_DIR=Path(TMP, "docs").as_posix(),
           PUBLIC_BASE_URL=f"http://127.0.0.1:{PORT}", CORS_ORIGINS=f"http://127.0.0.1:{PORT}")
os.environ.update(env)
sys.path[:0] = [str(BACKEND), str(BACKEND / "tests")]
from app import models, doc_models  # noqa: F401  (registers the ORM tables)
from app.database import SessionLocal
from app.dbcheck import migrate
from app.security import hash_password
migrate()
with SessionLocal() as db:
    stu = models.Student(register_number=SAMPLE, full_name="Sample Student", department="Electronics and Communication", year=2)
    db.add(stu); db.commit()
    db.add(models.User(username="e2e-admin", password_hash=hash_password(PW), role="admin", active=True))
    db.add(models.User(username="e2e-staff", password_hash=hash_password(PW), role="staff", active=True))
    db.add(models.User(username="e2e-sample", password_hash=hash_password(PW), role="student", student_id=stu.id, active=True))
    db.commit()
srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", PORT], cwd=BACKEND,
                       env=env, stdout=open(Path(TMP, "server.log"), "w"), stderr=subprocess.STDOUT)
code = 1
try:
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=1); break
        except Exception:
            time.sleep(0.5)
    else:
        raise SystemExit("server did not start; see " + str(Path(TMP, "server.log")))
    env2 = dict(env, BASE=f"http://127.0.0.1:{PORT}", E2E_PW=PW, ORIG_JSON=str(SRC))
    code = subprocess.call(["node", str(HERE / "e2e_original.js")], env=env2, cwd=HERE)
finally:
    srv.terminate()
    try: srv.wait(10)
    except Exception: srv.kill()
    if code: print(Path(TMP, "server.log").read_text()[-3000:])
    shutil.rmtree(TMP, ignore_errors=True)
sys.exit(code)
