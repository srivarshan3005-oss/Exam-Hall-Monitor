#!/usr/bin/env python3
"""Static cross-reference check (no server, no database needed).

1. every '#/page' link and EM.go('/page') in the frontend names a registered EM.page;
2. every '/api/...' path called from the frontend matches a route declared by a router;
3. every `models.X` / `dm.X` / `doc_models.X` attribute used in backend code exists in the model modules;
4. every router module is included in app/main.py.
Exit status 1 when something is missing."""
import ast, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "backend" / "app"
JS = sorted((ROOT / "static" / "js").glob("*.js")) + [ROOT / "static" / "index.html"]
js_text = {p: p.read_text(encoding="utf-8") for p in JS}
problems: list[str] = []

# 1 -- pages
pages = set(re.findall(r'EM\.page\(\{\s*name:\s*"([^"]+)"', "\n".join(js_text.values())))
pages |= {"", "login", "change-password", "lookup", "forgot-password"}      # shells handled in main.js
core = (ROOT / "static" / "js" / "main.js").read_text(encoding="utf-8")
for p, t in js_text.items():
    for m in re.finditer(r'href="#/([a-z0-9\-]*)', t):
        if m.group(1) not in pages:
            problems.append(f"{p.name}: link #/{m.group(1)} has no EM.page")
    for m in re.finditer(r'EM\.go\("/([a-z0-9\-]*)', t):
        if m.group(1) not in pages:
            problems.append(f"{p.name}: EM.go(/{m.group(1)}) has no EM.page")

# 2 -- api routes
routes: list[re.Pattern] = []
raw_routes: list[str] = []
for f in (ROOT / "routers").glob("*.py"):
    src = f.read_text(encoding="utf-8")
    pm = re.search(r'APIRouter\(\s*prefix="([^"]*)"', src)
    prefix = pm.group(1) if pm else ""
    for m in re.finditer(r'@router\.(?:get|post|patch|put|delete)\(\s*"([^"]*)"', src):
        pat = re.sub(r"\{[^}]+\}", "[^/]+", prefix + m.group(1))
        routes.append(re.compile("^" + pat + "/?$"))
        raw_routes.append(prefix + m.group(1))
main_src = (ROOT / "main.py").read_text(encoding="utf-8")
for m in re.finditer(r'@app\.(?:get|post)\(\s*"([^"]*)"', main_src):
    routes.append(re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", m.group(1)) + "$"))
consts = {}
for p, t in js_text.items():
    for m in re.finditer(r'const\s+([A-Z_]+)\s*=\s*"(/api[^"]*)"', t):
        consts[m.group(1)] = m.group(2)
for p, t in js_text.items():
    for m in re.finditer(r'(?:api|apiList|fetch)\(\s*([`"])(/api/[^`"?]*)([`"])\s*(\+)?', t):
        path = re.sub(r"\$\{[^}]*\}", "1", m.group(2)) + ("1" if m.group(4) and m.group(2).endswith("/") else "")
        concat = bool(m.group(4)) and m.group(2).endswith("/")
        if concat and any(r.startswith(m.group(2)) for r in raw_routes):
            continue
        if not any(r.match(path) for r in routes):
            problems.append(f"{p.name}: API path {m.group(2)} has no route")
    for m in re.finditer(r'(?:api|apiList)\(\s*(\w+)\s*\+\s*([`"])([^`"?]*)', t):
        base = consts.get(m.group(1))
        if base:
            path = re.sub(r"\$\{[^}]*\}", "1", base + m.group(3))
            if not any(r.match(path) for r in routes):
                problems.append(f"{p.name}: API path {base + m.group(3)} has no route")
    for m in re.finditer(r'(?:api|apiList)\(\s*`\$\{(\w+)\}([^`?]*)`', t):
        base = consts.get(m.group(1))
        if base:
            path = re.sub(r"\$\{[^}]*\}", "1", base + m.group(2))
            if not any(r.match(path) for r in routes):
                problems.append(f"{p.name}: API path {base + m.group(2)} has no route")

# 3 -- model attributes
def class_names(mod: str) -> set[str]:
    tree = ast.parse((ROOT / mod).read_text(encoding="utf-8"))
    imported = {a.asname or a.name for n in tree.body if isinstance(n, ast.ImportFrom) for a in n.names}
    funcs = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    return imported | funcs | {n.name for n in tree.body if isinstance(n, ast.ClassDef)} | {t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
M, D = class_names("models.py"), class_names("doc_models.py")
for f in ROOT.rglob("*.py"):
    tree = ast.parse(f.read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
            if n.value.id == "models" and n.attr not in M and f.name != "models.py":
                problems.append(f"{f.relative_to(ROOT)}:{n.lineno}: models.{n.attr} does not exist")
            if n.value.id in ("dm", "doc_models") and n.attr not in D and n.attr not in M:
                problems.append(f"{f.relative_to(ROOT)}:{n.lineno}: {n.value.id}.{n.attr} does not exist")

# 4 -- routers included
for f in (ROOT / "routers").glob("*.py"):
    if f.stem != "__init__" and f"{f.stem}.router" not in main_src:
        problems.append(f"routers/{f.name} is not included in main.py")

print("\n".join(problems) if problems else "references OK")
sys.exit(1 if problems else 0)
