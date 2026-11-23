"""Run the public-portal DOM test: temp SQLite DB + synthetic data + real uvicorn + jsdom.
Requires Node 18+ and `npm install` once in tests/e2e_jsdom (shared jsdom). Usage:  python tests/portal_dom/run_portal_dom.py
"""
import os, shutil, subprocess, sys, tempfile, time, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__)); BACKEND = os.path.abspath(os.path.join(HERE, "..", ".."))
PORT = os.environ.get("PORTAL_DOM_PORT", "8767")
tmp = tempfile.mkdtemp(prefix="portal_dom_")
env = dict(os.environ, DATABASE_URL="sqlite:///" + os.path.join(tmp, "t.db").replace("\\", "/"), SECRET_KEY="portal-dom-test-" + "x" * 40,
           ENVIRONMENT="development", SCHEDULER_ENABLED="false", BACKUP_DIR=os.path.join(tmp, "b"), LOG_DIR=os.path.join(tmp, "l"))
node_path = os.path.join(BACKEND, "tests", "e2e_jsdom", "node_modules")
if not os.path.isdir(node_path):
    sys.exit("Run `npm install` in backend/tests/e2e_jsdom first (provides jsdom).")
server = None
try:
    subprocess.run([sys.executable, os.path.join(HERE, "seed_portal_dom.py")], cwd=BACKEND, env=env, check=True)
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", PORT, "--host", "127.0.0.1"], cwd=BACKEND, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/ready", timeout=2); break
        except Exception:
            time.sleep(0.5)
    else:
        sys.exit("server did not start")
    r = subprocess.run(["node", os.path.join(HERE, "portal_dom_test.js")], env=dict(env, BASE=f"http://127.0.0.1:{PORT}", NODE_PATH=node_path))
    sys.exit(r.returncode)
finally:
    if server: server.terminate()
    shutil.rmtree(tmp, ignore_errors=True)
