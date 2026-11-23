"""After restart and after down/up (volumes kept): data and login must survive. Never prints tokens or passwords."""
import http.client, json, os, ssl, sys
ctx = ssl.create_default_context(); ctx.load_verify_locations(os.environ["EM_TEST_CERT"]); ctx.check_hostname = False
def req(m, p, b=None, t=None):
    c = http.client.HTTPSConnection(os.environ.get("EM_TEST_HOST", "exam.test.local"), 443, context=ctx, timeout=30); h = {"Accept": "application/json"}; d = None
    if b is not None: d = json.dumps(b); h["Content-Type"] = "application/json"
    if t: h["Authorization"] = "Bearer " + t
    c.request(m, p, body=d, headers=h); r = c.getresponse(); raw = r.read(); c.close()
    try: return r.status, json.loads(raw)
    except Exception: return r.status, None
label = sys.argv[1]; ok_all = True
s, j = req("POST", "/api/auth/login", {"username": "docker_admin", "password": os.environ["EM_ADMIN_PASSWORD"]}); tok = (j or {}).get("access_token")
print(("PASS  " if s == 200 and tok else "FAIL  ") + f"[{label}] admin can log in", s); ok_all &= bool(s == 200 and tok)
s, j = req("GET", "/api/students", t=tok); row = next((r for r in (j or []) if r.get("register_number") == "990000770001"), None)
good = bool(s == 200 and row and row.get("year") == 3 and row.get("department") == "ECE"); print(("PASS  " if good else "FAIL  ") + f"[{label}] student record and its update survived", s); ok_all &= good
s, j = req("GET", "/api/ready"); good = s == 200; print(("PASS  " if good else "FAIL  ") + f"[{label}] /api/ready", s); ok_all &= good
sys.exit(0 if ok_all else 1)
