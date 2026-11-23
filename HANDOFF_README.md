# Exam Monitor Ultimate - VSB Karur V7 - Claude handoff

Package: `EXAM_MONITOR_ULTIMATE_VSB_KARUR_V7_LATEST_CLAUDE_HANDOFF.zip`
Base: the uploaded V7 "UNMASKED_LIVE_REFRESH" project plus the changes below. Nothing was reverted or removed.

## Setup (Linux/macOS, Python 3.12)
    cd backend
    python3 -m venv .venv && . .venv/bin/activate
    pip install -r requirements.txt -r requirements-dev.txt
    python -m app.cli init-env && python -m app.cli migrate    # database revision 0016
    python -m uvicorn app.main:app --port 8000
Student search: http://127.0.0.1:8000/portal/  | Admin: http://127.0.0.1:8000/ | Health: /api/health
Windows: `install.bat`, `start.bat`, `stop.bat`, `health_check.bat`, `test.bat` (never executed in this audit).
Tesseract binary is optional (OCR fallback). Frontend tests need `npm ci` in `backend/tests/e2e_jsdom` (not shipped: node_modules excluded).

## Changes made in this session (only file modified: `backend/app/static/js/pages-live.js`)
1. Admin "Live monitoring" tab switcher: each tab render now gets its own container, so a slow earlier tab can no longer overwrite the tab the user switched to.
2. Records tab: latest-request-wins guard, so an older unfiltered response can no longer overwrite a newer search result.
Both were found because `tests/e2e_jsdom/run_e2e.py` was intermittently failing (2 of the first 3 runs).
No other source files were changed. No new tests were added. Documentation not updated except this file.

## Test results (this environment, Python 3.12.3, Node 22, Linux)
| Check | Result |
|---|---|
| Backend pytest (run in two halves) | 788 passed, 38 skipped, 0 failed (skips: PostgreSQL-only tests, operator/real-notice data not distributed) |
| Portal jsdom (`tests/portal_dom/run_portal_dom.py`) | 39 passed, 0 failed |
| Admin jsdom E2E, before fixes | 1 of 3 runs passed (aborted at "tab notify") |
| Admin jsdom E2E, after fix 1 | 4 of 5 passed (one aborted at "records table") |
| Admin jsdom E2E, after both fixes | 5 of 5 runs passed, 247 checks each (one further run was killed by the environment and is not counted) |
| Python compileall (app, tests, migrations, scripts) | OK |
| JavaScript `node --check` (15 app/portal files + test scripts) | OK |
| Fresh DB migration | revision 0016 |
| Independent unmasked-page check (real server, fixture PDF) | 78 other register numbers pixel-identical; plain image identical to raw 130-DPI render |

## NOT verified / outstanding
- Live monitoring against vsbec.edu.in: the site was unreachable here; everything used fixtures generated from the real 20-Nov-2026 page text (not VSB's binary PDFs).
- Not executed: Windows scripts, Docker, GitHub Actions (read only), Supabase, real SMTP, real-browser suite (`browser_e2e`), PostgreSQL tests, printing, mobile layout, per-button admin audit, full security audit, the 22-step end-to-end acceptance test.
- Known findings left unfixed: (a) students get an "Official PDF" link only when an official URL exists; locally imported PDFs get none and no endpoint serves the stored PDF (PARTIAL); (b) README says API version 0.8.0 but the server reports 0.9.0; (c) an 11-digit register number returns HTTP 200 rather than a validation error (intent not investigated).
- `FILE_MANIFEST.txt` and `RELEASE_MANIFEST_SHA256.txt` are the ORIGINAL manifests and are stale for `pages-live.js`; use `HANDOFF_SHA256_MANIFEST.txt`.
- Release label: not assigned (audit incomplete). Do not treat as READY FOR RELEASE.

## Update 2 - student portal shows only current exams
Problem: the student page listed every stored exam (e.g. May 2026) with its page images. The reference portal shows only current ones.
Fix: `GET /api/public/lookup/...`, the print slip and `/published` now return only exams dated (today - PORTAL_PAST_DAYS) or later,
in APP_TIMEZONE. Default is now `PORTAL_PAST_DAYS=-1` (keep every stored exam); the student page shows upcoming exams, or only the latest previous exam day when none is upcoming. Old records are NOT deleted (still in admin).
Files: `backend/app/config.py`, `backend/app/routers/public_live.py`, `backend/tests/conftest.py` (sets -1 for old fixtures),
`backend/tests/test_v7_live.py` (+1 test), `backend/.env.example`.
Tests: backend 789 passed, 38 skipped, 0 failed. Portal jsdom and admin E2E were NOT rerun after this change (no JS changed).
Windows note: if a "Application Control policy" error blocks DLLs, run the project from a short path such as C:\ExamMonitor (this worked on Python 3.14.10).

## Update 3 - faster refresh, tests fixed
- Portal checks `/api/public/version/{register}` (tiny token) every 5 s while the tab is visible and runs the full lookup only when it changes; 60 s full refresh kept as fallback (`backend/app/static/portal/portal.js`, `routers/public_live.py`). Lookup JSON now includes `version`.
- `VSB_POLL_SECONDS` (default 60, clamped 15-300, 0 = legacy VSB_POLL_MINUTES) controls the scan interval (`config.py`, `vsb_sources.py`). Conditional requests (ETag/Last-Modified) already existed.
- README API version corrected to 0.9.0. 11-digit register numbers are intentionally accepted (6-20 chars; non-standard ids kept verbatim).
- Tests: backend 791 passed, 38 skipped, 0 failed (run in three groups); portal jsdom 39/39; admin E2E 10/10 runs x 247 checks; compileall and node --check OK.
- Measured (empty DB, in-process): lookup/version median ~3.4 ms, p95 4-6 ms. No real-data or 50-concurrent load test was run. "0.01 s" is not literal: updates appear within ~5 s.
- STILL NOT DONE: serving stored original PDFs, investigating "Needs verification"/"documents disagree" records, Windows/Docker/CI/real SMTP/Supabase/PostgreSQL/real-browser/OCR/security/mobile/22-step workflow, live vsbec.edu.in check.
