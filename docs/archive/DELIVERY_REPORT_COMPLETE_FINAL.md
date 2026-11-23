# Delivery report — EXAM_MONITOR_ULTIMATE_COMPLETE_FINAL (v0.8.0)

> **Historical record.** This document describes an earlier build. Its test counts and status statements are not the current verification status. For the current commands, results and limitations see `docs/VALIDATION_REPORT_v6.md` (or `VALIDATION_REPORT_v6.md` from the top-level folder).

## 1. Audit summary (input: EXAM_MONITOR_ULTIMATE_VSB_KARUR_FINAL_RELEASE.zip)
* FastAPI + SQLAlchemy + Alembic (13 migrations), vanilla-JS admin SPA at `/`, separate static portal at `/portal/`.
* Baseline on the untouched upload: **590 passed, 24 skipped, 0 failed**.
* Defects found and fixed: (a) the old `/portal/` used inline `<script>`/`onclick`, which the app's CSP (`default-src 'self'`) blocks, so it could not work in a real browser; (b) example register number `922525106` appeared as a placeholder in the portal and the admin landing, was auto-focused, and was hardcoded in `test_portal.py`; (c) the jsdom e2e asserted a landing page that no longer existed and aborted on its first check.
* Packaging problems in the upload: it shipped `backend/.env` (a real `SECRET_KEY`), a 200 MB `.venv`, `.run.pid`, a migration lock and caches. None are in this package. **Rotate the old SECRET_KEY if that upload was shared.**
* Removed a stray developer script, *backend/app/static/portal/.patch_main.py* (historical; not in the release).

## 2. Implemented
Reference-style portal (empty default, `?reg=` only), live notices banner, enriched lookup, seat-number chart, print slip, loading/error/empty/unpublished states; operations overview (readiness, completeness, hall utilisation, anomalies, publication history) with dashboard card; test suites listed below.
## 3. Improved
Admin landing (no example number/autofocus); `test_portal.py`; e2e suite repaired and extended; shared helpers extracted from `students.py` (behaviour unchanged).
## 4. Files
Created: `routers/portal.py`, `routers/operations.py`, `static/portal/portal.css`, `static/portal/portal.js`, `tests/test_phase13_portal.py`, `tests/portal_dom/*`, `docs/PORTAL_AND_OPERATIONS.md`, this report.
Modified: `app/main.py` (router registration, version 0.8.0), `routers/students.py` (extracted `verified_location`, `public_source_records`), `static/portal/index.html` (rewritten), `static/js/main.js` (placeholder/autofocus), `static/js/pages-dash.js` (operations card), `tests/e2e_jsdom/e2e.js`, `test_portal.py`, `docs/API_CHANGES.md`, `docs/WINDOWS_INSTALLATION.md`, `README.md`, `RELEASE_MANIFEST_SHA256.txt`.
## 5. Database
No schema change and no migration: existing tables only (students, exams, allotments, halls/hall seats, subjects/terms, VSB batches/records, announcements, audit log). Existing migrations preserved.
## 6. API changes
See `docs/API_CHANGES.md` (0.8.0). `/api/lookup/{reg}` unchanged.
## 7. Security
Public endpoints are read-only, validated (6–20 letters/digits), rate limited, return published data only, hide names unless `PUBLIC_SHOW_NAMES=true`, expose hall location only for verified halls, and the seat map never contains another student's identity (verified by mutation-checked tests). Portal JS builds DOM with `textContent` (no `innerHTML`). SQL-injection and script payloads in the register number return 422/404. CSP, `X-Frame-Options`, `nosniff`, `Referrer-Policy` present; no CORS for foreign origins; API docs are off in production. Operations endpoint requires staff/admin; staff are department-scoped; audit data is admin-only. No secrets in the package (scan of the tree; only `REPLACE_WITH…` placeholders).
## 8–9. Tests actually executed (on an extracted copy of the package)
| Suite | Result |
|---|---|
| Full pytest (`python -m pytest`) | **617 passed, 24 skipped, 0 failed** (baseline 590 + 27 new) |
| jsdom e2e (`tests/e2e_jsdom/run_e2e.py`) | **225 checks passed, 0 failed** |
| Portal DOM (`tests/portal_dom/run_portal_dom.py`) | **26 passed, 0 failed** |
| Live smoke (`test_portal.py` against a started server) | **15/15 passed** |
| Clean start-up: `init-env` → `check-config` → `migrate` → uvicorn; `/api/ready`, `/`, `/portal/` | all OK (HTTP 200) |
The 24 skipped tests are pre-existing skips.
## 10. Known limitations
* No real browser was available: no pixel/visual or true mobile-device verification (responsiveness reviewed from CSS and exercised in jsdom only).
* Windows `.bat` scripts were reviewed, not run on Windows; the same CLI steps were run on Linux.
* The seat chart is a seat-number grid; the room's physical layout is not stored, so none is drawn.
* Students have a *year*, not a *semester*; semester appears only from exam term/subject.
* Hall management, subjects, terms, allocation, publication workflow and eligibility already existed and were not rebuilt; they were not individually re-audited beyond the existing test suite.
* Default `COLLEGE_NAME` is "Your College Name" until set in `backend\.env` (the Windows configuration wizard asks).
## 12. Windows installation and start-up
1. Install Python 3.12+ (real python.org build, "Add to PATH").
2. Extract the ZIP, e.g. to `C:\ExamMonitor\`.
3. Double-click `install.bat` (creates `backend\.venv`, installs dependencies, generates `backend\.env` with a new random secret, runs the configuration wizard, migrates).
4. Double-click `start.bat`. Admin: http://127.0.0.1:8000/ — Student portal: http://127.0.0.1:8000/portal/ (`?reg=REGISTER_NUMBER` searches directly).
5. `stop.bat` stops it; `backup.bat` makes a verified backup; `test.bat` runs the tests. Details: `docs/WINDOWS_INSTALLATION.md`.
