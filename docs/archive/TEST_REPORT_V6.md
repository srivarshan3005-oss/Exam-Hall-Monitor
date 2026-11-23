# UPDATED_CANDIDATE_v2 test status (newest section)

> **Historical record.** This document describes an earlier build. Its test counts and status statements are not the current verification status. For the current commands, results and limitations see `docs/VALIDATION_REPORT_v6.md` (or `VALIDATION_REPORT_v6.md` from the top-level folder).

**No tests were executed for this version.** The environment used to prepare it had no network and none of the required Python packages (FastAPI, SQLAlchemy, Alembic, pytest), no Android SDK/Gradle and no Windows.
Checks that were actually performed: `python -m py_compile` on every modified or added Python file (Python 3.12.3) and a byte-level check of Windows script line endings; manifest verification is recorded in `RELEASE_MANIFEST_SHA256.txt` (regenerated).
Added but unexecuted: `backend/tests/test_vsb_verification_enforcement.py` (15 tests). Totals passed/failed/skipped for the full suite: **NOT AVAILABLE**. Run `docs/WINDOWS_TEST_RUNBOOK.md`.
The sections below describe earlier versions and are kept for history.

---

# PRODUCTION-READINESS IMPLEMENTATION SESSION (16 Nov 2026) - newest section

## Changes made
* **Deployment is environment-driven:** *deploy/nginx.conf* replaced by `deploy/nginx.conf.template` (host from `DOMAIN_NAME`; TLS 1.2/1.3, HSTS and headers unchanged); `docker-compose.yml` derives `PUBLIC_BASE_URL`/`CORS_ORIGINS` from `DOMAIN_NAME` and refuses to start without it; `backend/.env.production.example` now carries `DOMAIN_NAME` and the `SMTP_*` settings; `app.cli check-config` (production) fails on example placeholders in `PUBLIC_BASE_URL`, `CORS_ORIGINS`, `DATABASE_URL` and warns when `SMTP_HOST` is empty (`app/config.py`, `app/cli.py`).
* **Android:** release tasks now fail unless an HTTPS `API_BASE_URL` is supplied (Gradle property or environment variable); the compiled-in `exams.example.edu` default was removed. Signing stays environment-driven (all-or-nothing keystore inputs).
* **Docs added/updated:** `WINDOWS_INSTALLATION.md`, `ANDROID_RELEASE.md`, `VSB_VERIFICATION_LIMITATIONS.md`, `DOCKER.md`, `PRODUCTION_DEPLOYMENT.md`, `RELEASE_PACKAGE.md`, `INSTALLATION.md`, `VSB_INTEGRATION.md`, `android/README.md`, this report and `FINAL_RELEASE_NOTES.md`.
* New tests: `backend/tests/test_release_config.py` (5 tests: preflight accepts real values, rejects 3 placeholders, SMTP warning only, Compose/Nginx/env consistency, Android release URL guard).
* VSB publication gating was reviewed and left unchanged: bulk approval covers only unflagged records; flagged records (incl. `seat_from_text_order`) need an individual administrator note; records without hall/seat cannot be published; students see approved + published records only.

## Tests executed in this session (scratch copy of the final tree)
| Check | Result |
|---|---|
| Full backend suite, SQLite: `python -m pytest -p no:cacheprovider -q -rs` | **590 passed, 0 failed, 24 skipped** (614 collected). Skips: 21 need PostgreSQL (`TEST_POSTGRES_URL` unset), 3 are the real-notice tests that skip because the private fixtures are not shipped. |
| Targeted before the full run | `tests/test_release_config.py tests/test_cli_and_seed.py tests/test_phase7_android_contract.py`: 26 passed |
| jsdom workflow (214) and JS syntax (13 files) | Passed in the previous session after the last JavaScript/CSS change; **not re-run now** because no JavaScript or CSS changed since. |
| PostgreSQL 601 passed, migrations 0001-0013 | Retained from the earlier session; **not re-run**. |
| `docker-compose.yml` | YAML parsed; template rendering simulated in Python (2 host substitutions, `$host` etc. untouched). **No `docker compose config/build/up`, no `nginx -t`.** |
| Package | ZIP extracted and every file checked against `RELEASE_MANIFEST_SHA256.txt` (see end of this section / release notes for the result). |

## Still NOT verified (unchanged unless stated)
Windows execution of `install.bat`/`start.bat`/`stop.bat`/`managed_server.ps1` (static review only); Android build, unit tests and APK (no SDK/Gradle; none exists); Docker build/run, TLS and nginx syntax; OCR, AN sessions, 14 Nov PDFs and all unlisted 16 Nov pages; manual browser testing. **Not declared production-ready.**

---


# FINAL BALANCE VERIFICATION SESSION (16 Nov 2026) - read this section first

It supersedes the "unchanged" / "not reachable" statements further down where they differ.

## Commands run and exact results

| Check | Command (from `backend/` unless noted) | Result |
|---|---|---|
| Full backend suite, SQLite | `python -m pytest -p no:cacheprovider -q` (scratch copy, after all changes) | **588 passed, 0 failed, 21 skipped** (609 collected; previously 585 passed; +3 = new real-notice tests, which are skipped when the fixtures are absent, as in this package). Skip reasons were not individually re-inspected. |
| VSB tests only | `python -m pytest tests/vsb -q` | 33 passed before the fixtures were removed (30 existing + 3 real-notice). In the shipped package the 3 real-notice tests skip. |
| jsdom workflow | `python tests/e2e_jsdom/run_e2e.py` after `npm install` | **214 checks passed, 0 failed** (re-run after the JS/CSS changes) |
| JavaScript syntax | `node --check` on each of the 12 `app/static/js/*.js` plus `tests/e2e_jsdom/e2e.js` | 13 files OK |
| Install sequence (Linux equivalent of `install.bat`/`start.bat` steps) | `python -m app.cli init-env`, `check-config`, `migrate`, `db-audit`, `create-admin` | all succeeded, revision 0013 |
| docker-compose.yml | `yaml.safe_load` + `depends_on` target check | parses; services `db`, `app`, `proxy`; volumes `postgres_data`, `app_uploads`, `app_backups` |
| PostgreSQL 601 passed, migrations 0001-0013 | **Retained from the earlier session. NOT re-run in this session.** | n/a |

No Phase 1-12 feature, migration (0001-0013) or database record was removed or altered.

## Defects found and fixed in this session

| Area | Defect | Fix |
|---|---|---|
| Web UI (admin Database page) | A healthy database showed a red "Attention required" badge: the page read `integrity.ok`, the API returns `healthy`. | `pages-admin.js` now uses `healthy` (falls back to `ok`). |
| Web UI / CSS | The integrity `<pre>` and wide tables could make the page scroll sideways at 375 px and 1280 px. | `.pre` wraps and is width-limited; `.tablewrap` is `position:relative; max-width:100%`. Measured after the fix: `scrollWidth == clientWidth` at 375 and 1280 px on Database and Notification-preferences. |
| `start.bat` / `stop.bat` | The PID check used `find "%%P"`, a substring match: false "already running" results, and `stop.bat` could kill an unrelated process that reused a stale PID. | New `scripts/managed_server.ps1`: exact numeric PID, must be a live `python(w).exe` whose command line contains `uvicorn` and `app.main:app`; otherwise the PID file is treated as stale and nothing is killed. |
| `install.bat` | Only the `py` launcher was tried. | Tries `py -3`, then `python`, each verified as 3.12+; clear error otherwise. The Microsoft Store stub is rejected by the version check. |
| `scripts/configure_windows.ps1` | LF line endings although `.gitattributes` requires CRLF. | Converted to CRLF (new `managed_server.ps1` is also CRLF). |

## Website runtime (automated browser, NOT manual testing)

Method: the real application on a temporary SQLite database with **synthetic** demo data (not VSB data), driven by headless Chromium through Playwright, desktop 1280 px and mobile 375 px, accounts admin, staff, invigilator and student. Navigation entries per role: admin 24, staff 18, invigilator 8, student 8. Every page was opened; **0 browser console errors, 0 HTTP >= 400 responses** except HTTP 429 from the application's own login rate limiter, triggered by repeated test logins (it works as designed). The student dashboard showed the (synthetic) hall/seat; the public register lookup endpoint returned 200.
Not tested: PDF upload and import through the browser, report generation/export, the VSB allocation workflow screens, link-by-link crawling, print layout, accessibility tooling, and any manual human browser session.

## Real VSB PDF validation - PARTIAL, text layer only

* Source: `https://vsbec.edu.in/controller-of-examination/`. It resolved only through the build tool's fetch function, **not from the sandbox shell**, so raw PDF bytes could not be downloaded. The text extracted by that tool from `16.11.26-FN-HALL.pdf` and `16.11.26-FN-SEAT.pdf` (date 16-11-2026, session FN) was used.
* Only **selected pages** were transcribed and compared: 10 programme pages of the hall list (CIVIL, CSE, EEE, MECH, BME, AIML, CHEM, IT, BIOTECH, CSBS) and 7 hall seating sheets (A101, A202, A203, A204, A303, A304, 02). The large ECE and AI&DS blocks, and all other hall sheets, were **not** compared.
* Hall parser: all 10 printed programme totals reconciled; **282 hall-list students**, no issues, date 2026-11-16, session FN.
* Seat parser: **170 seat assignments** matched an independent regex reading of the same text with 0 mismatches and 0 duplicates; for halls A202, A203, A204, A303 and A304 the seat register set equals the hall-list set exactly. A101 and 02 differ from the partial hall subset only because the omitted ECE/AI&DS pages were not transcribed (an artefact of the subset, not a parser finding).
* Every sheet is flagged `seat_map_from_text_order` (seat-to-register pairing derived from text order, not word coordinates). **Such mappings stay unconfirmed and must not be published** until a human compares them with the source PDF. Nothing from this check was imported or published.
* **Unverified:** the OCR path, the coordinate-based seat mapping on the real file, the AN session, the 14 November 2026 PDFs, and every page not listed above.
* Privacy: the transcribed fixtures contain real register numbers printed on a public notice. They were used for the run above and then **deleted from this package**; `tests/vsb/test_vsb_real_20261116.py` contains no register numbers and skips when the fixtures are absent.
* Manual validation procedure: see `docs/VSB_INTEGRATION.md`; in short, upload the official PDFs, review every proposed record and flagged issue against the PDF, correct, approve, and only then import.

## Android - NOT built, no APK

Configuration reviewed statically: AGP/Gradle wrapper 8.10.2, Kotlin JVM target 17, `compileSdk`/`targetSdk` 35, `minSdk` 26, 26 Kotlin sources, 2 unit-test files, debug default API URL `http://10.0.2.2:8000/` (cleartext for debug only), release requires an HTTPS `API_BASE_URL`. The sandbox has only a JRE 21 (no `javac`), no Android SDK/platform 35/build-tools, no Gradle distribution, and `dl.google.com` / `services.gradle.org` are unreachable, so `assembleDebug` and unit tests were **not run** and login, API integration, role dashboards, notifications and seat display on Android are **unverified**. Requirements to build: JDK 17+, Android SDK platform 35 and build-tools, network access to Google Maven and Gradle, then `cd android && ./gradlew testDebugUnitTest assembleDebug` (Windows: `android\build_debug.bat`).

## Docker / Windows execution environments

Docker is not installed and no Windows/PowerShell exists here: `docker build`, `docker compose up`, nginx config test, TLS, `install.bat`, `start.bat`, `stop.bat` and the new `managed_server.ps1` were **never executed**; the Windows edits are static-only and untested on Windows.

## Required production inputs (never shipped in this package)

* A real DNS name, set once as `DOMAIN_NAME` in `backend/.env.production` (Compose derives Nginx `server_name`, `PUBLIC_BASE_URL`, `CORS_ORIGINS`; no file edit needed).
* A TLS certificate and key (`fullchain.pem`, `privkey.pem`) placed in `deploy/certs/`.
* In `backend/.env.production` (created from the example, mode 600): `SECRET_KEY` (long random), `POSTGRES_PASSWORD`, `DATABASE_URL`, SMTP host/user/password, and the first administrator password set via `python -m app.cli create-admin`.
* For Android release: the HTTPS `API_BASE_URL` and an app-signing keystore.

## Verdict

Not declared production-ready: Android build, Docker deployment, Windows execution, OCR, AN-session and full real-PDF validation, and a manual browser pass remain unverified.

---

# Final test and verification report — VSB Karur release

Date: 16 Nov 2026. Environment: Linux sandbox, Python 3.12.3, Node 22, Java 21. Every number below comes from a command that was actually run; the raw logs are in `docs/test_results_final/`. The earlier per-phase report is preserved as `docs/TEST_REPORT_PHASE_HISTORY.md`.

## Summary

| Area | Result |
|---|---|
| Backend suite, SQLite, **first run on the received code** | 606 tests: **19 failed**, 21 skipped (log 01) |
| Backend suite, SQLite, after fixes | **585 passed, 21 skipped, 0 failed**, 65 s (log 02) |
| Backend suite with real PostgreSQL 16.2 enabled | **601 passed, 5 skipped, 0 failed**, 73 s (log 03) |
| Migration chain 0001 to 0013 on PostgreSQL (`migrate`, `db-audit`, downgrade to 0011, re-upgrade) | passed (log 04) |
| JavaScript syntax (`node --check`, 13 files) | 13 OK (log 05) |
| jsdom website workflow test | first run 188 passed / 5 failed (log 06); after fixing stale expectations **214 passed, 0 failed** (log 07) |
| Android build | **NOT performed** |
| Docker build / compose | **NOT performed** (static inspection only) |
| Windows scripts | **NOT executed** (static inspection only) |
| Real official VSB PDFs | **NOT validated** (not accessible) |

## Commands

```
cd backend
python3 -m venv venv && . venv/bin/activate
pip install -r requirements-dev.txt          # includes aiosmtpd and, after this release, pdfplumber
pip install pgserver "psycopg[binary]"       # test tooling only: bundled PostgreSQL 16.2 binaries

# SQLite, whole suite
python -m pytest -o addopts="" -p no:cacheprovider -ra --junitxml=results.xml

# PostgreSQL, whole suite (server: pgserver 0.1.4 = PostgreSQL 16.2 over a Unix socket)
export PATH=$PATH:<pgserver>/pginstall/bin   # makes pg_dump / pg_restore 16.2 available
export TEST_POSTGRES_URL='postgresql+psycopg://postgres:@/postgres?host=<pgdata dir>'
python -m pytest -o addopts="" -p no:cacheprovider -ra --junitxml=results_pg.xml

# PostgreSQL migration chain
DATABASE_URL='postgresql+psycopg://postgres:@/em_final?host=<pgdata dir>' python -m app.cli migrate
... python -m app.cli db-audit
... alembic downgrade to 0011 (via app.dbcheck.alembic_config), then python -m app.cli migrate

# JavaScript
node --check app/static/js/*.js tests/e2e_jsdom/e2e.js
cd tests/e2e_jsdom && npm install && cd ../.. && python tests/e2e_jsdom/run_e2e.py
```

The 5 remaining skips in the PostgreSQL run are the SQLite-parametrised variants of PostgreSQL-only tests; their PostgreSQL variants ran and passed. Migration 0013 and the VSB allocation/capacity tests (`test_vsb_alloc_workflow.py`, `tests/vsb/`, `test_vsb_crawler.py`) pass on both databases.

## Failures found in the first run, and what was changed

All 19 were genuine product defects or stale tests. No feature was removed.

| Failure | Cause | Fix |
|---|---|---|
| `test_downgrade_to_base_and_back`, `test_0007_upgrade_keeps_existing_accounts`, `test_migration_0009_keeps_existing_announcements_and_downgrades` and the downgrade-based tests in `test_phase8_database.py` (no test code edited for the first three; they pass with the fix) | **Product defect:** migration 0012 had no `downgrade()` | Added `downgrade()` to `migrations/versions/0012_vsb_official_sources.py` (drops both tables and their indexes). Upgrade path untouched. |
| `test_upgrade_head_matches_models_exactly`, `test_fresh_database_reaches_head_and_matches_models` | **Product defect:** migration 0011 creates 7 indexes the ORM models did not declare (schema drift) | Declared the same 7 indexes in `app/models.py` (students, exams, allotments, results, audit_logs, security_events, auth_sessions). |
| Tests hard-coding head `0010` (several in `test_phase8_database.py`) | Stale tests | Head constant, chain-order check, expected migration filenames, safety-copy filename and the failure-injection revision updated to 0013. |
| `test_upgrade_of_a_real_phase71_database_file` | Stale assertion: compared all tables, but 0012/0013 add new tables | Now asserts every pre-existing table is row-for-row unchanged and the newly added tables are empty. |
| `test_vsb_seat_parser::test_pdf_round_trip_with_real_coordinates` | **Packaging defect:** test imports `pdfplumber`, which was not in `requirements-dev.txt` | Added `pdfplumber>=0.11,<1` to `requirements-dev.txt` (test-only). |
| `test_missing_seat_cannot_be_approved_until_corrected` | Test assumed a new batch id; SQLite reused the freed rowid (observed `1 -> 1`), so the draft replacement had actually worked | Assertion now checks that exactly one draft remains and the old rows did not survive. Not a product change. |
| `test_every_api_path_used_by_the_frontend_exists` | Contract test could not handle the VSB page's `const API = "/api/vsb-allocation"` base | Test now expands `${API}/...` and `API + "..."` calls into full paths and validates each against OpenAPI (verified by temporarily breaking one endpoint: the test failed, then the file was restored). |
| jsdom: 5 role-sidebar checks | Stale expectations: lists lacked `workflow`, `database`, `vsb`, `vsb-allocation` and `my-vsb-seat` | Updated in `tests/e2e_jsdom/e2e.js` to match each page's declared `roles` in the JS (admin/super admin: all; staff: workflow, vsb, vsb-allocation added; invigilator: workflow; student: my-vsb-seat). Application code was not changed. The count rose from 193 to 214 because more pages are now exercised. |

Files changed: `backend/app/models.py`, `backend/migrations/versions/0012_vsb_official_sources.py`, `backend/requirements-dev.txt`, and four test files (`test_phase8_database.py`, `test_vsb_alloc_workflow.py`, `test_phase5_frontend_contract.py`, `tests/e2e_jsdom/e2e.js`).

## Inspections that could be done (static only)

* **Docker:** `docker-compose.yml` parses as valid YAML: services `db` (postgres:16-alpine with a `pg_isready` healthcheck), `app` (built from `backend/Dockerfile`, waits for a healthy `db`, no published ports) and `proxy` (nginx 1.27, ports 80/443). The Dockerfile is `python:3.12-slim`, installs tesseract-ocr and `requirements.txt` + `requirements-postgres.txt`, runs as a non-root user and has a healthcheck on `/api/ready`. `deploy/certs/` contains only `.gitkeep`, and *deploy/nginx.conf* (historical) uses the placeholder `exam.example.edu`, so the proxy needs a real certificate and host name before it can serve HTTPS.
* **Windows scripts:** all `.bat` and `.ps1` files use CRLF line endings, as `.gitattributes` requires. The scripts are unchanged from the received package.
* **Android:** `gradlew` and `build_debug.sh` pass `bash -n`; the wrapper jar is present and pins Gradle 8.10.2.

## NOT verified (do not rely on these)

* **Android:** no Android SDK or Gradle distribution is installed, and attempts to reach `services.gradle.org` and `dl.google.com` returned no response from this sandbox. `gradlew assembleDebug` and the Android unit tests were **not run**. The earlier Android core test logs in `docs/` are from previous phases, not this run.
* **Docker:** Docker is not installed. `docker build`, `docker compose up`, nginx configuration validation and TLS were **not run**. PostgreSQL was tested with a bundled 16.2 binary, not the `postgres:16-alpine` image.
* **Windows:** no Windows or PowerShell is available. `install.bat`, `start.bat`, `run_windows.bat`, `backup.bat`, `restore_backup.bat`, `test.bat` and `configure_windows.ps1` were **not executed**, and PowerShell syntax was not checked.
* **Real official VSB PDFs:** `vsbec.edu.in` does not resolve from the sandbox and the package contains no PDFs, so the hall and seating parsers have **only been tested on generated PDFs** (reportlab fixtures) and synthetic text. Parsing accuracy on real VSB Karur documents, layout variations and scanned/OCR pages is **pending**. Run the parser on real PDFs and review every flagged record before publishing any allocation.
* **Real browser:** the jsdom test is not a rendering engine. Layout, CSS, print output, file pickers/downloads and accessibility are untested.
* Python 3.13/3.14, load/performance, real SMTP/SMS, OCR accuracy, PostgreSQL `pg_dump`/`pg_restore` through the Windows scripts: not tested here. Warnings seen in the runs: a Starlette `httpx` deprecation notice, PyMuPDF `fitz` import deprecation, and an aiosmtpd test-server AUTH-without-TLS notice (test tooling only).

## Original-portal integration (this release)

Environment: Linux container, Python 3.12.3, SQLite. Windows, Android and Docker were **not** run (see limitations).

| Check | Command | Result |
|---|---|---|
| Baseline suite, unmodified upload | `pytest` | 617 passed, 24 skipped, 0 failed |
| Importer and admin endpoint tests | `pytest tests/test_original_import.py` | 11 passed |
| Real-data import, full `allotments.json` | `ORIGINAL_ALLOTMENTS_JSON=… pytest tests/test_original_import_real_data.py` | 1 passed |
| Full backend suite after changes | `pytest` | see the final line of this section |
| Front-end DOM smoke (jsdom, 225 checks) | `python tests/e2e_jsdom/run_e2e.py` | 225 passed, 0 failed |
| Live server, real HTTP, port 8000 | curl sequence in `ORIGINAL_PORTAL_IMPORT.md` | all expected codes (below) |
| Lint of changed Python modules | `pyflakes` | clean (one pre-existing warning in `reconcile.py` left unchanged) |

Real-data import results (`allotments.json`, SHA-256 `feb63d6b…4950`): 3,306 rows, 2,934 register numbers, 0 rejected,
0 conflicting, 0 duplicate seats, 6 draft batches. In that test database no student master was loaded, so every record
carries `student_not_in_database`. 2,099 records carry the blocking `hall_label_variant` flag.

Live HTTP results: readiness 200; `/portal/` 200; `/portal` 302 to `/portal/`; dry run 200; apply without confirm 422;
lookup before publication returns no VSB entries; approval without a note 422; approval with note 200; publish 200; public
lookup returns the seat (AN, 2026-11-17, MB III A103, seat 23); invalid register 422; unknown register 404; admin chart
200 image/png (1179×834); chart without credentials 401.

Final full-suite result (after all changes): **628 passed, 25 skipped, 0 failed** (baseline 617 passed, 24 skipped). The 11 new importer tests account for the increase; the one additional skip is the real-data test, which runs only when `ORIGINAL_ALLOTMENTS_JSON` is set.

## Final verification (comparison and audit round)

This section supersedes the counts above, which were recorded earlier in the same release cycle. Full findings: `AUDIT_ORIGINAL_INTEGRATION.md`.

| Suite | Python 3.12.3 | Python 3.14.10 |
|---|---|---|
| Backend, full (`python -m pytest`) | 636 passed, 24 skipped, 0 failed | 636 passed, 24 skipped, 0 failed |
| Importer unit tests (`test_original_import.py`) | 17 passed | 17 passed |
| Real-data tests (`test_original_import_real_data.py`, full file, field-by-field) | 2 passed | 2 passed |
| jsdom general smoke (`tests/e2e_jsdom/run_e2e.py`, live server) | 225 passed, 0 failed | 225 passed, 0 failed |
| jsdom original-data workflow (`tests/e2e_jsdom/run_original_e2e.py`, live server) | 29 passed, 0 failed | 29 passed, 0 failed |

Notes on how these were produced:

- The full backend suite ran before a final cosmetic cleanup of unused imports and one unused variable in two test
  files. Those two files were then re-run on both interpreters (19 passed each). No application code changed after the
  full-suite run.
- The 24 skipped tests are the same as in the unmodified upload. Their reasons were checked (`pytest -rs`): 21 are
  PostgreSQL tests that need `TEST_POSTGRES_URL`, and 3 need real VSB notice fixtures that are deliberately not distributed.
  None is a Windows-only check. (An earlier draft of this report described them incorrectly.)
- Python 3.14 was tested on Linux with `requirements.txt`. Windows was not available.

Static checks: `pyflakes` reports one pre-existing unused variable in `app/vsb_alloc/reconcile.py` (`kind_ok`), which
this work did not touch. `node --check` passes for the changed front-end and test scripts.

Verification of the delivered ZIP (extracted into a clean directory) is reported with the release, not embedded in it, because a file written after packaging cannot be inside the package.

## Release verification round (working tree before packaging)

Run on the working tree after all changes in this round. Counts are from pytest and the scripts' own summaries.

| Check | Python 3.12.3 | Python 3.14.10 |
|---|---|---|
| Full backend suite (`python -m pytest`) | 656 passed, 24 skipped, 0 failed | 656 passed, 24 skipped, 0 failed |
| jsdom general smoke (`tests/e2e_jsdom/run_e2e.py`) | 225 checks passed, 0 failed | not re-run in this round |
| jsdom original-data workflow (`tests/e2e_jsdom/run_original_e2e.py`) | 29 checks passed, 0 failed | not re-run in this round |

Affected test files, run individually: mail outbox configuration 12 passed; mail (Phase 6) 22 passed; portal disclosure 7
passed; portal (Phase 13) 27 passed; importer 18 passed; real-data comparison 2 passed; VSB workflow 12 passed; allocation
engine 16 passed; allocation phase 2 13 passed; `tests/vsb` 30 passed, 3 skipped.

Live HTTP verification (`final_live.py`, server started from the working tree, temporary databases outside the release):
28 checks passed, 0 failed. It covers the outbox folder (valid and invalid), the absence of `pending_unpublished` in lookup
responses, unpublished records staying hidden, approval of hall-label variants staying manual, refusal of an edit that
creates a live seat clash, the sample register and the known conflict register.

Database check of the live run: 3,306 records; 2,099 carry `hall_label_variant`; 2,098 of them are pending. The one
approved variant record is the sample, which was approved manually with a note in the verification run to test visibility.
Nothing was approved automatically.

Note on the sample: this verification approved it manually and does not verify it against the official PDF.

## Phase 13 verification-status safeguards (this package revision)

Focused tests run after the verification-status enforcement changes:

- `pytest -q tests/test_original_import.py tests/test_vsb_alloc_workflow.py`: **30 passed, 0 failed**.
- `python -m compileall -q backend/app backend/migrations`: passed.
- Hall-label variant CSV: **2,099 rows**; 377 FULLY_VERIFIED, 772 HALL_LIST_CONFIRMED, 950 UNRESOLVED.

The complete backend suite was **not completed** in this environment. Initial collection stopped because the optional test dependency `aiosmtpd` is not installed (`tests/test_phase6_mail.py`). A second attempt excluding that test file exceeded the 120-second execution limit before completion. These results must not be represented as a full-suite pass. The focused tests use the isolated SQLite test harness; Windows installation, Android build, Docker build, PostgreSQL tests, and production deployment were not run in this revision.

The new administrator endpoint `POST /api/vsb-allocation/records/{record_id}/verification` records explicit verification status, official PDF references, an explanatory note, and an audit event. FULLY_VERIFIED requires both official hall-list and seat-sheet PDF references; HALL_LIST_CONFIRMED requires the hall-list reference. Editing hall, seat, or subject code resets status to UNRESOLVED.
