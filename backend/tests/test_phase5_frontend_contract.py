"""Static front-end ↔ API contract checks (no browser): every /api path the JavaScript calls must exist in the
OpenAPI schema, every script referenced by index.html must exist, and security-sensitive coding rules hold."""
import re
from pathlib import Path
import pytest

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
JS = sorted((STATIC / "js").glob("*.js"))


def _segments(u):
    return [s for s in re.sub(r"\$\{[^}]*\}", "X", u).split("/") if s != ""]


def _matches(url, ends_slash, template):
    u, t = _segments(url), _segments(template)
    if ends_slash:                      # "/api/exams/" + id  -> prefix followed by one dynamic segment
        u = u + ["X"]
    if len(u) != len(t):
        return False
    return all(a == b or a == "X" or (b.startswith("{") and b.endswith("}")) for a, b in zip(u, t))


def test_every_api_path_used_by_the_frontend_exists(client):
    paths = list(client.app.openapi()["paths"])
    missing = []
    for f in JS:
        text = f.read_text()
        # A page may declare `const API = "/api/xyz"` and call `${API}/a/${id}` or `API + "/a"`. Expand those calls to full
        # paths so they are checked too, and do not report the bare base itself (it is a prefix, not a route).
        bases = re.findall(r'const API = "(/api/[^"]*)"', text)
        expanded = []
        for base in bases:
            expanded += [base + m.group(1) for m in re.finditer(r"\$\{API\}([^`\"'?]*)", text)]
            expanded += [base + m.group(1) for m in re.finditer(r'API \+ "([^"?]*)"', text)]
        found = [m.group(1) for m in re.finditer(r"[`\"'](/api/[^`\"'?]*)", text) if m.group(1) not in bases] + expanded
        for raw in found:
            if not any(_matches(raw, raw.endswith("/"), p) for p in paths) and not any(_matches(raw.rstrip("/"), False, p) for p in paths):
                missing.append((f.name, raw))
    assert missing == []


def test_index_html_references_existing_assets():
    html = (STATIC / "index.html").read_text()
    refs = re.findall(r'(?:src|href)="(/[^"#]+)"', html)
    assert refs and all((STATIC / r.lstrip("/")).is_file() for r in refs)


def test_removed_legacy_scripts_are_not_referenced():
    html = (STATIC / "index.html").read_text()
    for old in ("phase2.js", "phase3.js", "phase4.js", "style.css", "/app.js"):
        assert old not in html
        assert not (STATIC / old.lstrip("/")).exists()


def test_no_inline_scripts_or_handlers():
    html = (STATIC / "index.html").read_text()
    assert not re.search(r"<script(?![^>]*\bsrc=)", html) and not re.search(r"\son\w+=", html)
    for f in JS:
        assert not re.search(r"\son(click|focus|change|submit|load|error|input)=", f.read_text()), f.name


def test_token_is_session_storage_only_and_no_eval():
    for f in JS:
        s = f.read_text()
        assert "eval(" not in s and "new Function(" not in s and "document.write" not in s, f.name
        assert not re.search(r"localStorage\.(set|get)Item\(\s*[\"']em_token", s), f.name
    assert "sessionStorage" in (STATIC / "js" / "main.js").read_text()


def test_untrusted_output_goes_through_escape_helper():
    # innerHTML assignments in templates must never interpolate raw API fields: spot-check that the escape helper exists
    core = (STATIC / "js" / "core.js").read_text()
    assert "EM.esc" in core and "&#39;" in core


def test_every_page_has_a_route_name_and_unique():
    names = []
    for f in JS:
        names += re.findall(r"EM\.page\(\{ name: \"([a-z-]*)\"", f.read_text())
    assert len(names) == len(set(names)) and {"", "login", "dashboard", "exams", "allocation", "documents", "accounts", "security", "audit"} <= set(names)


@pytest.mark.parametrize("path", ["/", "/css/app.css", "/js/core.js", "/js/main.js"])
def test_static_assets_served_with_security_headers(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert "default-src 'self'" in r.headers["content-security-policy"] and r.headers["x-content-type-options"] == "nosniff"
