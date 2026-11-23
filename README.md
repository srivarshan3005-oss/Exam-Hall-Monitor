# Exam Monitor Ultimate - VSB Engineering College, Karur (V7)

Automatic examination hall & seat finder. **A student enters only a register number**; the system, which watches the official
Controller of Examinations notices every 5 minutes, shows every matching examination (date, weekday, session, subject, programme,
department, **hall, seat**) together with the **original, complete, unmasked page** of the official PDF.

```
open /portal/  ->  enter register number  ->  all matching exams  ->  hall + seat  ->  original PDF page (zoom)  ->  verified building/floor  ->  print
```

## Quick start (Windows)
1. Extract the ZIP (a short path such as `C:\ExamMonitor` is best).
2. Double-click **`install.bat`** (needs Python 3.12; answer `N` to the administrator question if you only want the student site).
3. Double-click **`start.bat`**.
4. Open **http://127.0.0.1:8000/portal/** and search a register number.
   Administrators: **http://127.0.0.1:8000/** -> sign in -> *Live monitoring*.
`stop.bat` stops the server, `health_check.bat` checks it, `test.bat` runs the automated tests.

## Quick start (Linux / Docker)
`docs/DEPLOYMENT.md` - `docker compose -f docker-compose.local.yml up --build -d`, or a plain Python 3.12 venv.

## What is automatic
Discovery (HTML, embedded PDFs, WordPress media/search, sitemaps on `vsbec.edu.in` and `coe.vsbec.edu.in`) -> download with
validation and SHA-256 -> hall/seat extraction (text, tables, OCR fallback) -> matching and conflict detection -> searchable index
-> optional e-mail and Supabase mirror. A failed scan never erases data and is never reported as a success.
Details: `docs/LIVE_MONITORING.md`.

## Honesty notes (read these)
* The build environment could not reach the live college website: **live verification is pending**; everything was tested with
  fixtures generated from the real 20-Nov-2026 page text. `docs/V7_KNOWN_LIMITATIONS.md`.
* Page images are **unmasked on purpose** (they equal the college's public PDF pages). `docs/SECURITY.md`.
* Session times are shown only if you set `SESSION_TIMES`; building/floor/map only after an administrator verifies them with a source.

## Documentation
`docs/LIVE_MONITORING.md` - `docs/DEPLOYMENT.md` - `docs/ENVIRONMENT.md` - `docs/V7_RELEASE_REPORT.md` (+ commands) -
`docs/V7_REFERENCE_COMPARISON.md` - `docs/V7_TEST_REPORT.md` - `docs/V7_KNOWN_LIMITATIONS.md` - `docs/BACKUP_RECOVERY.md` -
`docs/SECURITY.md` - older material in `docs/archive/` (history only). The sections below are the V6 README, still valid for the legacy parts.

---

# Exam Monitor Ultimate — VSB Karur final release (Phases 1–12)

> **Release status: v6 public release candidate. NOT a production release.** The public package excludes the operator's real
> VSB allocation data (see *Public and private data* below). Evidence, commands and exact counts are in
> [docs/archive/VALIDATION_REPORT_v6.md](docs/archive/VALIDATION_REPORT_v6.md).
> **Verified:** backend suites on SQLite and PostgreSQL 16; jsdom front-end suites; the real-browser suite in headless
> Chromium 141 and in Firefox 160; migration 0015 (fail-closed, both databases); the operator-data tests against an authorised
> private copy; 25 pure-Kotlin core unit tests on the JVM.
> **Partially verified:** Docker (the real `docker-compose.yml` and `backend/Dockerfile` were run end to end, but on **local
> substitute base images**, not the pinned official ones, see `scripts/verification/docker_substitute/README.md`); Android
> (core logic only: no Gradle build, no APK, data layer untested); Windows (scripts parsed and linted, never executed).
> **Blocked / untested:** execution on Windows, Docker with the official images, the Android build and APK, real SMTP
> delivery, and Safari.

> Version identifiers in the code: the API reports `0.9.0` (`VERSION` in `backend/app/main.py`) and the Android app `versionName 0.8.1`.
> Database head revision: `0015`. Always run `python -m app.cli migrate`.


An independent examination-management platform (FastAPI + SQLAlchemy + Alembic, SQLite by default) with a responsive single-page web interface. It is **not** an official institutional portal. Use synthetic or institution-authorised data only.

## What it does
Role-based web application for examinations and subjects, academic years and terms, students, seat allocation (preview → administrator approval → commit, corrections, history), seating plans and reports (CSV/XLSX/PDF/print), official timetable PDF upload with OCR review and confirmed import, seating-allotment PDF import, user accounts and permissions, security dashboard, audit history, announcements, and student/invigilator portals.

| Role | Sees |
|---|---|
| Super administrator / Examination administrator | Everything, including accounts, results publication, security dashboard, audit history, approval and import steps |
| Department staff | Examinations, subjects, students (their department), allocation preview/manual seats, reports, halls (read), document upload/extraction, announcements |
| Invigilator | Read-only hall rosters and seating charts, announcements |
| Student | Own seats, published timetable, own published results, announcements |
| Public (not signed in) | Register-number lookup, published timetable, announcements, sign-in / registration |

**Hiding a menu item is never the security boundary.** Every action calls an API endpoint that enforces the role on the server (see `docs/archive/PHASE4_SECURITY.md`); the UI shows server errors verbatim.

## Install and start
Requirements: Python 3.12+ (tested with 3.12). Optional: Tesseract for OCR of scanned PDFs (`docs/OCR.md`).

**Windows:** run `install.bat` (checks Python, creates `backend/.venv`, installs dependencies, generates a local secret, runs the configuration wizard, migrates and prompts for the first administrator), then `start.bat` and open <http://127.0.0.1:8000>. The launcher checks `/api/ready`; logs are in `backend/logs/`. Use `stop.bat` to stop the managed server. See [Windows installation](docs/WINDOWS_INSTALLATION.md) and [Windows user guide](docs/WINDOWS_USER_GUIDE.md).

**Production Docker:** configure `backend/.env.production` from its example, install a valid TLS certificate in `deploy/certs/`, update the Nginx hostname, run the `check-config` and `migrate` steps (start-up does not migrate), then follow [production deployment](docs/PRODUCTION_DEPLOYMENT.md) and [Docker guide](docs/DOCKER.md). PostgreSQL, uploads and backups use persistent named volumes. No production deployment is claimed by this source package.

**Linux / macOS:**
```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt            # add -r requirements-dev.txt for tests, -r requirements-ocr.txt for OCR
cp .env.example .env                       # then set SECRET_KEY (python -c "import secrets;print(secrets.token_urlsafe(48))")
python -m app.cli migrate                  # the app refuses to start on an unmigrated database
python -m app.cli create-admin --username <name>   # first administrator (prompts for a password)
uvicorn app.main:app --host 127.0.0.1 --port 8000
```
Open <http://127.0.0.1:8000>. API docs: `/docs` (when `ENABLE_DOCS=true`).

## Public and private data
This public package contains **synthetic data only** for every test. The operator's real VSB allocation records,
provenance and correction files, seating-chart evidence, and the hall-label review CSV contain real student register
numbers and are **not** included. Tests that need them are explicitly skipped, with the reason shown in the test
summary, and their assertions are unchanged. They run in an authorised deployment that places its copy under
`backend/data/original_portal/` as described in `backend/data/original_portal/README.md`. Never publish that data.

## Tests
```bash
cd backend && python -m pytest                      # backend + front-end contract tests (requires requirements-dev.txt; test.bat installs it on demand)
# DOM-level UI tests (Node 18+ and jsdom, not a real browser):
cd tests/e2e_jsdom && npm ci && cd ../.. && python tests/e2e_jsdom/run_e2e.py
# real-browser suite: headless Chromium (downloads its own Chromium via npm), or Firefox 129+ via WebDriver BiDi:
cd tests/browser_e2e && npm ci && cd ../.. && python tests/browser_e2e/run_browser_e2e.py
BROWSER=firefox FIREFOX_PATH=/path/to/firefox python tests/browser_e2e/run_browser_e2e.py
```
Results and what was *not* verified: `docs/V7_TEST_REPORT.md` and `docs/V7_KNOWN_LIMITATIONS.md`. Front-end design and routes: `docs/FRONTEND.md`. History of earlier phases (V1-V6): `docs/archive/`.

## Other documentation
[installation](docs/INSTALLATION.md) · [Windows installation](docs/WINDOWS_INSTALLATION.md) · [Windows user guide](docs/WINDOWS_USER_GUIDE.md) · [production deployment](docs/PRODUCTION_DEPLOYMENT.md) · [Docker](docs/DOCKER.md) · [deployment troubleshooting](docs/TROUBLESHOOTING_DEPLOYMENT.md) · [configuration](docs/CONFIGURATION.md) · [database](docs/DATABASE.md) · [administrator guide](docs/ADMIN_GUIDE.md) · [student guide](docs/STUDENT_GUIDE.md) · [backup/recovery](docs/BACKUP_RECOVERY.md) · [troubleshooting](docs/TROUBLESHOOTING.md) · [security](docs/SECURITY.md) · [Phase 4 security](docs/archive/PHASE4_SECURITY.md) · [architecture](docs/ARCHITECTURE.md) · [upgrading](docs/UPGRADING.md) · [OCR](docs/OCR.md)

## Upgrading from Phase 4 (historical note)
No database migration was required for Phase 5 (head was `0008` at that time; the current head is `0015`, so always run `python -m app.cli migrate`). Two additive API endpoints were added; the old multi-script UI (`app.js`, `phase2-4.js`, `style.css`) was replaced by `static/js/*` and `static/css/app.css`. Existing records, APIs and migrations are unchanged.

## Android build (summary — full steps in docs/WINDOWS_TEST_RUNBOOK.md and android/README.md)
Requirements: JDK 17+, Android SDK platform 35, internet on first run. From `android\`: `gradlew.bat tasks`, `gradlew.bat testDebugUnitTest`, `gradlew.bat assembleDebug` (or `build_debug.bat`). Declared: Gradle 8.10.2, Android Gradle Plugin 8.7.3, Kotlin 2.0.21, compileSdk/targetSdk 35, minSdk 26, application ID `com.example.exammonitor`. Release builds need `-PAPI_BASE_URL=https://…` and either all four `RELEASE_*` signing inputs or none (unsigned). No APK has been produced from this package yet.

## Official VSB verification counts (do not confuse the two datasets)
Records (3,306): **627** fully verified · **1,159** hall-list confirmed, seats not independently verified · **1,520** unresolved. Hall-label variant review (a separate 2,099-record dataset): **377** · **772** · **950**. Only fully verified records can be approved or published; acknowledgement never bypasses this.

## Remaining limitations (honest list)
* **Validation:** see `docs/archive/VALIDATION_REPORT_v6.md` for exactly what was run, with the commands and results, and what is still outstanding (Windows install, Android build, Docker build, operator-data tests in an authorised deployment).
* The browser suite was run in headless Chromium 141 and in Firefox 160. It is **not** a Safari/WebKit check, **not** a visual or responsive check on real devices, and **not** an accessibility audit (axe/Lighthouse or a screen reader).
* File-picker upload and the PDF page-image preview were not driven through the UI test (jsdom has no file chooser / image decoding); the API behind them is covered by backend tests.
* The Android app (`android/`, Phase 7) is fully implemented in source but **has never been compiled or run with the Android toolchain** (no SDK/Maven access here); see `android/README.md` for exactly what was verified. Windows `.bat` scripts were not executed on Windows. PostgreSQL, load testing, MFA, SMS and real SMTP delivery are untested/not implemented.
* OCR/parsers are tuned on synthetic PDFs only; real college PDFs need human review (which the workflow enforces).
* Rate limiting is in-process; use a shared limiter for multi-worker deployments. Department scope applies to the endpoints listed in `docs/archive/PHASE4_SECURITY.md`.
* Results can be created/published but not edited or deleted through the API (unchanged backend behaviour); the UI therefore offers publish/unpublish only.


## Phase 6 - Notifications & e-mail
In-app notification centre, preferences, SMTP delivery with retries, reminders and an administrator Communications page. See `docs/archive/PHASE6_NOTIFICATIONS.md`. Set SMTP_* in `backend/.env`; run `python -m app.cli migrate` after upgrading.


## Phase 8.3 database administration

The Phase 8.3 database console and migration/index updates are documented in `docs/archive/PHASE83_DATABASE_ADMIN.md`. Apply migrations from `backend` with `python -m app.cli migrate`. Restore remains an offline CLI maintenance operation. Phase 8.3 tests were intentionally not rerun for this delivery.


## Phase 11 — integrated workflows

The signed-in **Workflow centre** composes live data from the existing examination, eligibility, campus, seat-allocation, results, PDF/OCR and notification modules. It provides a permission-scoped system overview and an examination readiness checklist with links into the existing approval workflows. The Android Retrofit client exposes the same workflow summary/readiness endpoints and the student's own analytics endpoint through its repository container. No database migration is required. See [Phase 11 Integration](docs/archive/PHASE11_INTEGRATION.md).

Phase 11 is covered by the v5 backend, jsdom and browser runs listed in `docs/archive/VALIDATION_REPORT_v6.md`. Older reports in `docs/` describe earlier builds.

## Phase 10 — Analytics & intelligence

The administrator/staff dashboard now includes a live examination intelligence panel. Open **Reports & plans** for filters, academic-year/semester comparisons, trend insights, at-risk screening, hall utilization and CSV/Excel/PDF performance exports.

Key API endpoints:
- `GET /api/analytics/dashboard`
- `GET /api/analytics/comparisons`
- `GET /api/analytics/insights`
- `GET /api/analytics/allocation`
- `GET /api/analytics/students/{register_number}`
- `GET /api/analytics/students/at-risk`
- `GET /api/analytics/me` (student's own published results)
- `GET /api/analytics/reports/performance?format=csv|xlsx|pdf|json`

See [Phase 10 Analytics Guide](docs/archive/PHASE10_ANALYTICS.md) for filters, permissions, formulas, screening rules and report instructions. All performance calculations use published result records. Attendance is explicitly unavailable because this project schema does not yet contain attendance records. Unverified or missing hall capacity is not estimated.


## Phase 12 release package

See [release package and operator checklist](docs/archive/RELEASE_PACKAGE.md) for production configuration, Windows deployment, Docker/PostgreSQL setup, Android release signing inputs, and migration instructions. Browse the [documentation index](docs/README.md) for the complete guide catalogue. This archive is a source release: Android APK/AAB artifacts and production secrets are intentionally not included.


## Release corrections

This archive supersedes `Exam_Monitor_Ultimate_FINAL_RELEASE.zip`. Packaging and configuration fixes are listed in [docs/archive/RELEASE_FIXES.md](docs/archive/RELEASE_FIXES.md). The SHA-256 inventory is `RELEASE_MANIFEST_SHA256.txt`; it records file hashes only and is not a build, test or audit report.

## Official VSB integration
The app links to and can fetch PDFs from the college's official Controller of Examinations page (https://vsbec.edu.in/controller-of-examination/):
staff page **VSB official notices**, public home-page card, `/api/vsb/*`, migration 0012. Downloaded PDFs flow into the existing
Timetable PDFs review and Seating PDF import. See `docs/VSB_INTEGRATION.md`.

**VSB hall and seat allocation** (migration 0013, `/api/vsb-allocation/*`, staff page *VSB allocation*, student page *My VSB seat*): hall-allotment and
seating-allotment PDFs are parsed into **draft** batches linked to student records; an administrator corrects, approves, previews and publishes them.
Nothing is published automatically, and students see only approved, published seats. See `docs/VSB_ALLOCATION.md`.

### Quick start for V.S.B. Engineering College, Karur
1. Windows: `install.bat` → `start.bat` → <http://127.0.0.1:8000>; sign in with the administrator you created.
2. Set `COLLEGE_NAME=V.S.B. Engineering College, Karur` in `backend/.env` (stop first with `stop.bat`).
3. Staff → **VSB official notices** → *Check official page now* to list the PDFs; download and *Process* the hall and seating PDFs.
4. Staff → **VSB allocation** → build a batch, resolve flagged issues, approve, preview, publish.
5. Use only institution-authorised data. Scheduled discovery stays off unless you set `VSB_AUTO_DISCOVER_ENABLED=true`.

## v0.8.0 — student portal and operations overview
Public portal: `http://127.0.0.1:8000/portal/` (opens empty; `?reg=REGISTER_NUMBER` searches). Admin app: `http://127.0.0.1:8000/`.
Windows: run `install.bat` once, then `start.bat` (stop with `stop.bat`). Details: `docs/WINDOWS_INSTALLATION.md`,
`docs/PORTAL_AND_OPERATIONS.md`.
