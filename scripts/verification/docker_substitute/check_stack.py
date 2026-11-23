"""End-to-end check of the running compose stack, through the nginx TLS proxy. Never prints tokens or passwords."""
import http.client, json, os, ssl, sys
HOST = os.environ.get("EM_TEST_HOST", "exam.test.local"); CERT = os.environ["EM_TEST_CERT"]
PW = os.environ["EM_ADMIN_PASSWORD"]; USER = "docker_admin"
ctx = ssl.create_default_context(); ctx.load_verify_locations(CERT); ctx.check_hostname = False   # pinned throwaway cert, no SAN
results = []
def rec(name, ok, detail=""):
    results.append((name, bool(ok), detail)); print(("PASS  " if ok else "FAIL  ") + name + (f"   [{detail}]" if detail else ""))
def req(method, path, body=None, token=None, https=True, headers=None):
    c = http.client.HTTPSConnection(HOST, 443, context=ctx, timeout=30) if https else http.client.HTTPConnection(HOST, 80, timeout=30)
    h = {"Accept": "application/json"}; h.update(headers or {})
    data = None
    if body is not None: data = json.dumps(body); h["Content-Type"] = "application/json"
    if token: h["Authorization"] = "Bearer " + token
    c.request(method, path, body=data, headers=h); r = c.getresponse(); raw = r.read(); hd = {k.lower(): v for k, v in r.getheaders()}; c.close()
    try: js = json.loads(raw)
    except Exception: js = None
    return r.status, hd, js, raw
def stage(title): print(f"\n== {title}")

stage("proxy / transport")
s, h, _, _ = req("GET", "/", https=False); rec("HTTP :80 redirects to HTTPS", s in (301, 308) and h.get("location", "").startswith("https://"), f"{s} -> {h.get('location','')[:40]}")
s, h, js, _ = req("GET", "/api/health"); rec("GET /api/health via TLS proxy", s == 200 and js and js.get("status") == "ok", f"{s} {js}")
s, h, js, _ = req("GET", "/api/ready"); rec("GET /api/ready (database reachable)", s == 200, f"{s} {js}")
rec("HSTS header present", "strict-transport-security" in h, h.get("strict-transport-security", "")[:50])
rec("X-Content-Type-Options present", h.get("x-content-type-options", "").lower() == "nosniff")
s, h2, _, raw = req("GET", "/"); rec("Frontend served at / (HTML)", s == 200 and "text/html" in h2.get("content-type", "") and b"<html" in raw.lower(), f"{s} {h2.get('content-type','')[:20]} {len(raw)} bytes")
s, _, _, _ = req("GET", "/docs"); rec("API docs disabled in production (/docs not served)", s in (404, 401, 403), str(s))

stage("authentication")
s, _, js, _ = req("POST", "/api/auth/login", {"username": USER, "password": "WrongPassword123x"}); rec("wrong password refused", s == 401 and not (js and "access_token" in js), str(s))
s, _, _, _ = req("GET", "/api/students"); rec("unauthenticated /api/students refused", s in (401, 403), str(s))
s, _, js, _ = req("POST", "/api/auth/login", {"username": USER, "password": PW}); tok = js.get("access_token") if js else None
rec("admin login", s == 200 and bool(tok), f"{s} role={js.get('role') if js else None}")
if not tok: print("cannot continue without a token"); sys.exit(2)
s, _, js, _ = req("GET", "/api/auth/me", token=tok); rec("GET /api/auth/me returns the logged-in user", s == 200 and js and js.get("username") == USER, str(s))

stage("CRUD: students (create / read / update; the API has no student delete)")
REG = "990000770001"
s, _, js, _ = req("POST", "/api/students", {"register_number": REG, "full_name": "Docker Test Student", "department": "CSE", "year": 2, "email": None}, tok); rec("create student", s == 201, str(s))
s, _, js, raw = req("GET", f"/api/students/{REG}"); rec("public student lookup works but hides the full name (PUBLIC_SHOW_NAMES=false)", s == 200 and js and js.get("register_number") == REG and "full_name" not in js and b"Docker Test Student" not in raw, f"{s} keys={sorted(js.keys()) if js else None}")
s, _, js, _ = req("GET", "/api/students", token=tok); row = next((r for r in (js or []) if r.get("register_number") == REG), None); rec("admin list returns the full student record", s == 200 and row and row.get("full_name") == "Docker Test Student", str(s))
s, _, js, _ = req("PATCH", f"/api/students/{REG}", {"year": 3, "department": "ECE"}, tok); rec("update student", s == 200, f"{s} {str(js)[:60]}")
s, _, js, _ = req("GET", "/api/students", token=tok); row = next((r for r in (js or []) if r.get("register_number") == REG), None); rec("admin list after update shows new values", s == 200 and row and row.get("year") == 3 and row.get("department") == "ECE", f"year={row.get('year') if row else None}")
s, _, _, _ = req("POST", "/api/students", {"register_number": REG, "full_name": "Docker Test Student", "department": "CSE", "year": 2}, tok); rec("duplicate student refused", s in (409, 422), str(s))

stage("CRUD: announcements (create / read / update / delete) and public visibility")
s, _, js, _ = req("POST", "/api/admin/announcements", {"title": "Docker stack check", "body": "created by the compose verification", "published": False}, tok); aid = js.get("id") if js else None
rec("create announcement (unpublished)", s == 201 and aid, f"{s} id={aid}")
s, _, js, _ = req("GET", "/api/announcements"); titles = [a.get("title") for a in (js if isinstance(js, list) else (js or {}).get("items", []))]
rec("unpublished announcement NOT visible publicly", s == 200 and "Docker stack check" not in titles, f"{s} public_titles={len(titles)}")
s, _, js, _ = req("GET", "/api/admin/announcements", token=tok); lst = js if isinstance(js, list) else (js or {}).get("items", [])
rec("admin list contains the announcement", s == 200 and any(a.get("id") == aid for a in lst), str(s))
s, _, js, _ = req("PATCH", f"/api/admin/announcements/{aid}", {"title": "Docker stack check (edited)", "body": "edited", "published": True}, tok); rec("update + publish announcement", s == 200, str(s))
s, _, js, _ = req("GET", "/api/announcements"); titles = [a.get("title") for a in (js if isinstance(js, list) else (js or {}).get("items", []))]
rec("published announcement visible publicly", s == 200 and "Docker stack check (edited)" in titles, f"{s}")
s, _, js, _ = req("DELETE", f"/api/admin/announcements/{aid}", token=tok); rec("delete announcement", s == 200, str(s))
s, _, js, _ = req("GET", "/api/announcements"); titles = [a.get("title") for a in (js if isinstance(js, list) else (js or {}).get("items", []))]
rec("deleted announcement gone", "Docker stack check (edited)" not in titles, str(s))
s, _, _, _ = req("DELETE", f"/api/admin/announcements/{aid}", token=tok); rec("second delete answers 404", s == 404, str(s))

stage("public lookup does not expose an unallocated student")
s, _, js, raw = req("GET", f"/api/lookup/{REG}"); rec("public lookup leaks no full name", b"Docker Test Student" not in raw, f"{s}")

stage("session end")
s, _, _, _ = req("POST", "/api/auth/logout", token=tok); rec("logout", s in (200, 204), str(s))
s, _, _, _ = req("GET", "/api/auth/me", token=tok); rec("token rejected after logout", s in (401, 403), str(s))
json.dump([{"check": n, "ok": ok, "detail": d} for n, ok, d in results], open(os.environ.get("EM_RESULT_JSON", "docker_check_results.json"), "w"), indent=1)
bad = [r for r in results if not r[1]]; print(f"\nTOTAL {len(results)}  PASS {len(results)-len(bad)}  FAIL {len(bad)}"); sys.exit(1 if bad else 0)
