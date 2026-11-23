# Phase 11 — cross-module integration (2026-11-15)

> **Historical record.** This document describes an earlier build. Its test counts and status statements are not the current verification status. For the current commands, results and limitations see `docs/VALIDATION_REPORT_v6.md` (or `VALIDATION_REPORT_v6.md` from the top-level folder).

**State: implementation package prepared; Phase 11 tests, audits, builds and verification were not run, as explicitly requested.**

## Implemented
- Added a dedicated integration router that composes the existing Phase 1–10 data models and service logic without replacing domain APIs.
- Added a role-protected, department-scoped system overview for active students, exams, published timetables, seat allotments, published results, verified halls, processed PDF versions and the caller's unread notifications.
- Added an examination readiness endpoint joining eligibility, verified hall capacity, committed allocations and result publication state, with actionable next-step links.
- Added a responsive staff Workflow centre page with live module summary, examination selector, readiness checklist and links to existing workflows.
- Added Android Retrofit endpoints and an `IntegrationRepository` for workflow overview, exam readiness and the authenticated student's own analytics; exposed it through the existing app service container.
- Updated README, phase status and dedicated Phase 11 integration documentation.

## Boundaries and limitations
- Integration summaries are read-only; publishing, OCR approvals, allocation commits and result publication remain in their established protected domain APIs.
- No database migration or destructive data operation was added.
- Attendance remains explicitly unavailable because no attendance source is implemented. SMTP, OCR and PostgreSQL maintenance still depend on external configuration/tooling.
- Android source changes are included; no APK/build is claimed.

## Verification status
No Phase 11 tests, audits, static checks, Android builds, browser checks or other verification were run. Historical reports refer only to earlier phases.

---

# Phase 9 progress — deployment, Windows installation and production configuration

**State: implementation packaged; no production deployment claimed. Previous test suites were not rerun, as requested.**

## Delivered
- `install.bat` checks Python 3.12+, creates `backend/.venv`, installs runtime dependencies, creates a non-overwriting `.env` with generated secret, invokes a PowerShell configuration wizard, validates config, migrates and audits schema, and prompts for the first administrator.
- `start.bat` validates configuration, applies migrations, starts the backend as a managed process, captures logs, polls `/api/ready`, and cleans up on failed startup. `stop.bat` stops the managed process.
- `backend/Dockerfile`: Python 3.12, PostgreSQL driver, non-root user, read-only root filesystem compatible layout, healthcheck.
- `docker-compose.yml`: PostgreSQL 16, private app service, Nginx TLS proxy, named persistent volumes and bounded JSON logs.
- `deploy/nginx.conf.template` (rendered from `DOMAIN_NAME`; earlier builds used a fixed *deploy/nginx.conf*): HTTP redirect, TLS 1.2/1.3, HSTS and security headers.
- Production environment template and documentation for Windows installation/use, Docker, production deployment and troubleshooting.

## Verification / limitations
- Existing Phase 1–8 test suites were not rerun.
- Static review of generated scripts/configuration and package contents only; no Windows execution, Docker build, PostgreSQL deployment, TLS certificate validation or production rollout was performed.
- Replace sample hostname and install real TLS certificates. Create protected production secret values before launch.
- PostgreSQL dump/restore requires client binaries in the maintenance environment; these are not included in the app image.
- Windows scripts bind to loopback only.
- No Phase 10 work started.

## Preservation
Phase 1–8 code, migrations, Android source and existing scripts are retained. The package excludes real secrets, databases, backups, logs, caches and virtual environments.

---

# Phase 8.3 progress — database performance and administration

**State: implementation checkpoint packaged; tests intentionally not rerun as requested.**

## Implemented
- Added additive migration `0011_phase83_query_indexes.py` with guarded composite indexes for common student, exam, allotment, result, audit, security-event and session query paths. Existing rows are untouched.
- Extended the existing Phase 8.2 database router with read-only migration history, verified backup download, and explicit archive verification endpoints. Filename validation and checksum/ZIP verification are applied before download.
- Added the administrator **Database administration** UI page with engine/revision status, integrity report, migration ledger, backup create/list/verify/download, CSV/XLSX/JSON/PDF export, and student import preview/confirmed commit.
- Reused existing Phase 8.1 connection/session/migration controls and Phase 8.2 backup/import/export/integrity services. Restore remains offline CLI-only to avoid replacing a live database underneath active workers.
- Added `docs/PHASE83_DATABASE_ADMIN.md`.

## Not done / not claimed
- Per request, no previous tests were rerun. New Phase 8.3 changes have not been test-verified.
- No online restore endpoint was added; use the documented offline restore workflow.
- Performance improvements are schema/index-level; no benchmark numbers are claimed.
- No Phase 9 work started.

## Preserved
All existing Phase 1–8.2 source, Android source, Windows scripts, data-management services, migrations and documentation are retained. No existing database or user data was opened or modified during packaging.

---
# Phase 8.1 progress - database architecture and schema audit (checkpoint package, NOT fully verified)

**State: code and documentation complete; final verification incomplete. Package built on request before the last checks finished.**

## Delivered
* Connection layer (`app/database.py`, `dbtypes.py`, `dbutil.py`): SQLite WAL/busy-timeout/FK pragmas, PostgreSQL pool/UTC session, URL normalisation, `session_scope()`, `UTCDateTime` (aware UTC on both engines), `lock_allocation()` on every seat-deciding endpoint.
* Migration 0010 (indexes on 8 FK columns, unique account per student, 5 CHECK constraints; skips - never forces - a constraint that existing data violates). Released migrations 0001-0009 are byte-identical to the Phase 7.1 archive (SHA-256 pinned by a test).
* Runner (`app/dbcheck.py`, `migrations/env.py`): per-revision atomic migrations on both engines, cross-process lock, SQLite pre-upgrade safety copy, PostgreSQL empty-database bootstrap at head, refusal of raw alembic / history-less PostgreSQL databases, `python -m app.cli db-audit`.
* Fixes: case-insensitive search on PostgreSQL (`icontains`), canonical allotment hall/seat, 409 for a second account per student, admin create-user check, connection leak after migrate, `requirements-postgres.txt`.
* Docs: `docs/DATABASE.md` (rewritten), `docs/MIGRATIONS.md` (failure/recovery runbook), `docs/CONFIGURATION.md`, `.env.example`, result files `docs/PHASE81_*`.
* Tests: `tests/test_phase8_database.py` (61 tests incl. parametrised PostgreSQL cases), fixture `tests/fixtures/phase71_release.sqlite3` (a real database written by the untouched Phase 7.1 build).

## Verification that WAS run (actual results, see docs/PHASE81_* files)
* Whole backend suite on SQLite: 538 tests, 0 failures, 0 errors, 5 skipped (engine-specific). PostgreSQL 16.15: 538 tests, 0 failures, 0 errors, 4 skipped (engine-specific). **These two runs happened BEFORE the final edit to one test** (below).
* Real Phase 7.1 database file upgraded as a copy (SQLite): 40 tables, 0 differing tables, integrity ok, safety copy intact. PostgreSQL at simulated 0009 upgraded by CLI: rows identical.
* Concurrency: 10/10 repeated runs per engine with the lock; with the lock disabled the capacity/clash rules broke (PostgreSQL 12/12). Details: `docs/PHASE81_CONCURRENCY_RESULTS.txt`.
* Mutation check: re-introducing the naming-convention bug makes the two real-release tests fail.

## NOT finished / NOT verified (be aware)
1. **Full suites were not re-run after the last test edit.** `test_database_unique_constraint_is_the_backstop_without_the_lock` was changed (worker threads used the main session's ORM object - a test bug). Afterwards only the Phase 8.1 module was run: 12 of 12 SQLite runs clean. The run WITHOUT PostgreSQL configured (`docs/PHASE81_BACKEND_NO_POSTGRES_RESULTS.xml`) shows **1 failure - that same test, before the fix**.
2. The fix was not verified on PostgreSQL suites or in a second repeat series; no final no-PostgreSQL full run exists.
3. `docs/TEST_REPORT.md`, `docs/PHASE_STATUS.md` and `docs/UPGRADING.md` were NOT updated for Phase 8.1 (they still describe Phase 7.1). This file and `docs/DATABASE.md` / `docs/MIGRATIONS.md` are the Phase 8.1 documentation.
4. Not tested: PostgreSQL versions other than 16.15, load/performance, Windows (all testing ran on Linux; the Windows lock path `msvcrt.locking` in `dbcheck.py` is untested), the node `e2e_jsdom` suite, Android build (unchanged, still unbuilt - see Phase 7.1 notes).
5. Downgrading below 0009 on PostgreSQL is unsupported/untested.

## Process notes
* The full backend suite was run in this phase although earlier notes ask to wait for "AUTHORIZE FINAL TESTING AND VERIFICATION"; all runs used scratch copies/throw-away databases.
* Backup/restore and import/export (Phase 8.2) were NOT started.

---
# Phase 7.1 progress - Android final build attempt, compilation fixes (app v0.8.1, backend unchanged at 0.7.0)

**State: Android source corrected by review and ready for a first real Gradle build on a machine with the Android SDK. NOT built here. NO APK.**
Blocker: this environment has no Android SDK and cannot reach Google Maven / Maven Central (`docs/PHASE71_GRADLE_ATTEMPT.txt`). Nothing was stubbed to fake a build.

## Done
* Inspected the whole Android project (Gradle, manifests, resources, 24 Kotlin source files, 2 test files). Versions are mutually compatible on paper: Gradle 8.10.2, AGP 8.7.3, Kotlin 2.0.21 + Compose compiler plugin, Compose BOM 2024.12.01 (Material3 1.3.1), Navigation 2.8.5, Lifecycle 2.8.7, Retrofit 2.11 / OkHttp 4.12, Coroutines 1.9, compileSdk/targetSdk 35, minSdk 26, Java 17.
* **Fixed** (would have broken `assembleDebug`): missing `rememberSaveable` import in `StaffScreens.kt`; missing `@OptIn(ExperimentalMaterial3Api)` for `PullToRefreshBox` in `Components.kt` and `AlertsScreens.kt`.
* **Fixed** logic bug: hall-location text in the seat sheet (`StudentScreens.kt`).
* Gradle: heap raised, `nonTransitiveRClass`, version 0.8.1/3; added `android/build_debug.bat` and `build_debug.sh` (run the 4 tasks, print APK size + SHA-256).
* Verified the project's Gradle wrapper works (Gradle 8.10.2 starts; Kotlin DSL scripts compile up to plugin resolution).
* Re-ran Android core tests with real kotlinc: **25/25 passed**. Ran the **full backend suite: 477 passed, 0 failed** (API compatibility preserved; no backend code changed).
* Security review by source inspection (encrypted storage, no password persistence, no logging, HTTPS-only release, cache wipe, role gating) - see `docs/TEST_REPORT.md`.
* Updated `android/README.md`, `docs/TEST_REPORT.md`, `docs/PHASE_STATUS.md`.

## Not done (could not be done here)
`./gradlew clean|testDebugUnitTest|assembleDebug|lintDebug`; `DataLayerTest.kt` execution; Compose/manifest/resource compilation; lint; emulator/device testing; APK generation and checksum; release signing.

## Remaining steps for you (about 10 minutes with Android Studio installed)
1. Install Android Studio (or JDK 17 + SDK Platform 35). Create `android/local.properties` with `sdk.dir=...` if needed.
2. `cd android` then `build_debug.bat` (or the four `gradlew.bat` commands in `android/README.md`).
3. Send me the first `error:` / `e:` lines if anything fails (most likely `ui/` Compose code or a `lintDebug` finding) - I will fix them.
4. Install `app/build/outputs/apk/debug/app-debug.apk` on an emulator/phone and walk `docs/PHASE7_ANDROID.md` ("Manual test checklist").

---
# Phase 7 progress - Android application (app v0.8.0, backend unchanged at 0.7.0)

**State: Android source complete and integrated with the existing API; NOT compiled with the Android toolchain, no APK.**
Details: `android/README.md`, `docs/PHASE7_ANDROID.md`.

## Verification (actually run)
| Check | Result |
|---|---|
| New backend contract tests for every endpoint the app calls + role/permission boundaries + student isolation + notification workflow (`backend/tests/test_phase7_android_contract.py`) | **10 passed** (found and fixed a wrong report path prefix in my first draft: `/api/admin/reports/...`) |
| Focused backend regression: contract + notifications + auth + phase4 auth + frontend contract + static/startup (`docs/PHASE7_FOCUSED_TEST_RESULTS.xml`) | **84 passed, 0 failed** |
| Android core tests (25) compiled with kotlinc 2.0.21 and run on the JVM via a JUnit shim | **25 passed** (`docs/PHASE7_ANDROID_CORE_TEST_RESULTS.txt`) |
| Kotlin type-check of core/data/AppContainer/ViewModels against hand-written stubs of Retrofit/OkHttp/Gson/AndroidX | no errors (stubs are my approximation of those APIs) |
| Compose UI, Navigation, manifest/resources, Gradle sync/build, `DataLayerTest.kt` (MockWebServer), APK, emulator, device | **NOT run** (no Android SDK; Google/Maven unreachable) |
| Full backend suite | **NOT run** (standing rule: wait for "AUTHORIZE FINAL TESTING AND VERIFICATION"); no backend code was changed in Phase 7 |

## Implemented
Login (all roles), secure token storage (EncryptedSharedPreferences), session restore/expiry/logout, forced password change, forgot/reset (paste link/code), role-based tabs, student dashboard/timetable/seat/details/results/announcements/profile,
staff/admin/invigilator dashboards, exam list/detail (summary, halls, allocations), student seat lookup (staff), publish/unpublish with confirmation, notification centre (list, unread badge, read/unread, archive, mark-all, paging, detail, preferences),
light/dark/system theme, loading/empty/error states, pull-to-refresh, encrypted per-user cache with stale banner, safe GET-only retry, double-submit guards, response validation, HTTPS-only release builds, Gradle wrapper 8.10.2.

## Changed / removed
Old single-screen `MainActivity` replaced (its public lookup, timetable and announcement features are preserved inside the new student screens). Dependencies, manifest, themes and icons replaced. No backend source changed.

## Not done / pending
Push notifications (no FCM/backend device-token API - documented as pending), deep-link password reset, R8 minification, certificate pinning, signing, TalkBack audit, tablet layouts, DataLayerTest execution.

## Continue with
1. On a machine with Android Studio: `cd android && ./gradlew testDebugUnitTest assembleDebug`; fix any compile errors (most likely in `ui/`), run `DataLayerTest`.
2. Walk the manual checklist in `docs/PHASE7_ANDROID.md` on an emulator, then a physical device.
3. After you send "AUTHORIZE FINAL TESTING AND VERIFICATION": run the full backend suite.

---
# Phase 6 progress - Notifications, e-mail delivery & communication (v0.7.0)

**State: complete, working checkpoint.** Details: `docs/PHASE6_NOTIFICATIONS.md`.

## Verification (actually run)
| Check | Result |
|---|---|
| New Phase 6 tests (54): notifications API, isolation/IDOR, preferences, SMTP against a **real local SMTP server** (success, bad password, refused recipient, connection failure + back-off + give-up, timeout, TLS-verify failure), retry/never-resent, log redaction, admin controls, templates, workflow targeting, seats, results, announcements, reminders, timezone, worker thread, migration 0009 up/down | **54 passed** |
| Focused regression: Phase 6 files + auth, admin, authorization, security, migrations, static/startup, allotments, students, results, exams, phase2 (exams/allocation/reports), phase3 documents, phase4 (4 files), phase5 (2 files), cli/seed - `docs/PHASE6_FOCUSED_TEST_RESULTS.xml` | **397 passed, 0 failed, 0 skipped** |
| jsdom DOM test against a live server (`tests/e2e_jsdom`, 30 new checks: bell badge, notification centre, escaping, mark read/archive, preferences, communications page, student refused) | **193 checks passed** |
| `node --check` on all JS; frontend<->API contract test (covers new JS) | passed |
| **Full backend suite** | **NOT run**: your standing rule says to wait for "AUTHORIZE FINAL TESTING AND VERIFICATION". Not re-run: test_allocation_engine, test_regno, test_docmodels, test_phase3_extract (no Phase 6 code touched). |
| Real SMTP provider, real browser/visual/a11y, Android, Windows .bat, PostgreSQL | **Not tested** |

## Changed behaviour
* Version 0.7.0. `mailer.send_mail` keeps its signature/return values; messages are now logged in `email_deliveries` (reset/activation bodies never stored).
* Announcement API gained optional fields; old clients keep working. Targeted announcements are hidden from `/api/announcements`.
* Bell badge refreshes on navigation/focus, never on a timer (so it cannot defeat the idle timeout).

## Migration
`0009_notifications_email` (additive). New files: `notifications.py, notify_templates.py, delivery.py, scheduler.py, routers/{notifications,communications}.py, static/js/pages-notify.js, tests/test_phase6_*.py`.

## Continue with
Run the full suite after you send the authorization phrase; verify a real SMTP provider; browser/a11y pass.

---
# Phase 5 progress — Professional web front end & feature integration (v0.6.0)

**State: complete, working checkpoint.** Nothing is half-migrated; backend suite and UI test are green.

## Verification (actually run)
| Check | Result |
|---|---|
| Full backend suite `python -m pytest` | **413 passed** (392 earlier + 21 new) — `docs/PHASE5_TEST_RESULTS.xml` |
| `compileall`, `node --check` on all JS, `alembic heads` (single head 0008) | passed |
| jsdom DOM-level test against a live server (`backend/tests/e2e_jsdom`) | **163 checks passed**, covering all five roles, access refusals, and the main workflows (see `docs/TEST_REPORT.md`) |
| Real browser / visual / responsive / accessibility audit | **NOT done** (no browser installable here) |
| File-picker upload, PDF preview image, downloads in a browser | **Not driven in UI test** (API covered by backend tests) |
| Android, Windows `.bat`, PostgreSQL, SMTP, load, real-PDF OCR accuracy | **Not tested** |

## Implemented
* New build-free SPA (`static/css/app.css`, `static/js/*`): design system (light/dark, responsive sidebar/topbar, dialogs, toasts, tables with search/sort/pagination), hash router, role-aware navigation, five role dashboards.
* Every Phase 1–4 feature reachable from the UI against its real API: exams + audience, subjects, years/terms, students, halls/directory/seats, allocation (preview → admin commit → corrections → history), reports/print, timetable PDF upload/OCR review/import/history, seating-PDF import, Phase 1 register-candidate queue, accounts & permissions, security dashboard, audit, results, announcements, student portal, invigilator rosters, my account/sessions.
* UX safety: double-submit guard, confirmations for destructive/irreversible actions, field-level backend validation errors (also inside dialogs), expired session → sign-in with message, forced password change flow, refresh/back keeps page, all dynamic text escaped, no inline scripts (CSP), PDF previews via data: URLs (the old blob: preview was blocked by the CSP).
* Backend (additive only): `GET /api/results/admin/list` (admin) so results can be published/unpublished; `register_number`/`student_name` in `/api/auth/profile` for linked student accounts. Version 0.6.0. No migration.

## Defects fixed from the old UI
`isAdmin()` excluded `super_admin` in phase2/3 scripts; duplicate-PDF upload error (409 object) displayed as "Request failed"/[object]; PDF page preview used `blob:` URLs blocked by the CSP; results could not be published from the UI (no way to list result ids); students had no way to learn their register number; raw numeric IDs for building/block/floor; `prompt()` dialogs; global monkey-patched handlers across four scripts. Found by the jsdom run and fixed: nav crash after sign-out, undefined helper on seating-import page, unbound audience Save button, duplicate `id` attributes in form fields.

## Removed (after confirming no references)
`static/app.js`, `phase2.js`, `phase3.js`, `phase4.js`, `style.css` (replaced). Tests asserting their strings were rewritten to the equivalent new assertions.

## Remaining limitations
See README "Remaining limitations". Top items: no real-browser/visual/a11y verification; results cannot be edited/deleted (backend unchanged); department scope only on the endpoints listed in PHASE4_SECURITY.md; in-process rate limiting; Android untouched.

## Files
New: `static/css/app.css`, `static/js/{core,main,pages-*}.js`, `tests/test_phase5_*.py`, `tests/e2e_jsdom/*`, `docs/FRONTEND.md`, `docs/PHASE5_TEST_RESULTS.xml`. Changed: `static/index.html`, `routers/auth.py`, `routers/results.py`, `main.py` (version), tests tied to old UI strings, README and docs.

---
# Earlier phases (preserved)

# Phase 4 progress — Authentication, access control & security (v0.5.0)

## Verification (actually run in this session)
| Check | Result |
|---|---|
| Focused run: 4 new Phase 4 files + auth/admin/authorization/security/migrations/static/allotments/students/results/phase2-reports/phase3-documents/cli test files | **284 passed, 0 failed, 0 skipped** (junit: `docs/PHASE4_FOCUSED_TEST_RESULTS.xml`) |
| New Phase 4 tests | 71: `test_phase4_auth.py` (24), `test_phase4_rbac.py` (34), `test_phase4_security.py` (7), `test_phase4_seating_import.py` (6) |
| Migrations 0007/0008: upgrade from 0006 keeps users (status back-filled), downgrade, model/schema parity | Passed |
| `phase4.js`, `app.js` syntax (`node --check`) | Passed |
| **Full backend suite** | **NOT run as a complete final verification** (your standing rule: wait for "AUTHORIZE FINAL TESTING AND VERIFICATION"). One early full-suite run happened by mistake; it stopped at its first failure (a response-key name clash, fixed) and was not used as evidence. Remaining Phase 1–3 test files not in the focused list (e.g. `test_exams.py`, `test_phase2_*` other than reports, `test_phase3_extract.py`) were not re-run after the Phase 4 changes. |
| Browser click-through of the new UI | **NOT done** (no browser here) |
| E-mail delivery (SMTP), real PDFs for seating import | **Not tested** (mail is monkeypatched in tests; seating parser tested only on synthetic text) |

## Implemented
See `docs/PHASE4_SECURITY.md` for details. Authentication (server-side sessions, idle timeout, logout/logout-all, registration + activation, forgot/reset, administrator reset with forced change, throttling), five-role RBAC on backend routes with department scope, security controls (Origin check, headers, CORS/production config checks, secret scrubbing), security-event log + dashboard API, account-management and security UI, audit search, seating-allotment PDF import with review/confirmation.

## Behaviour changes to know about
* `/api/auth/me` unchanged; new `/api/auth/profile`. Login response gained `role_label`, `pw_change_required`.
* Tokens issued before the upgrade stop working (users sign in again). `/logout` now ends only the current session; use `/logout-all` for everywhere.
* New roles `super_admin`, `invigilator`; `admin` unchanged. UI "Administrator" label still maps to `admin`.
* Admin user JSON gained `status`, `email`, `department`, `role_label`, etc. The key for the forced-change flag is `pw_change_required` (an older test forbids the word "password" in those responses).
* Phase 1 `/api/admin/documents` seating-register candidates remain separate from the new seating import.

## Known limitations
* Seating parser handles line-based text/OCR layouts (hall label + register + seat). Multi-column tables with several students per line get no seat (flagged); handwriting/low-quality scans unreliable. Needs tuning on real college PDFs.
* Seating import creates allotments only for an exam you choose; it does not create halls or seats, and halls must already be verified.
* Activation/reset need SMTP (`SMTP_HOST`) in production; in development messages are written to `backend/outbox/` (git-ignored). Without either, self-registration cannot complete — administrators can still create/approve accounts.
* Rate limiting is in-process (see `docs/SECURITY.md`); put a shared limiter in front for multi-worker deployments. Account lockout is stored in the database.
* No multi-factor authentication. No cookie sessions (by design, see PHASE4_SECURITY.md). Android app untouched.
* Department scope applies to the endpoints listed in PHASE4_SECURITY.md; other staff endpoints (e.g. exam editing, documents) remain institution-wide.

## Migration
`0007_auth_security_rbac`, `0008_seating_import` — back up, then `python -m app.cli migrate`. To create the first super administrator: `python -m app.cli create-admin --username <name> --role super_admin`.

---

# Phase 3 progress — Official document processing, OCR & timetable automation (v0.4.0)

## Verification (actually run in this session)
| Check | Result |
|---|---|
| Full backend suite (`cd backend && python -m pytest`) | **321 passed, 0 failed, 0 skipped** (junit: `docs/PHASE3_TEST_RESULTS.xml`) |
| New Phase 3 tests | 17 extraction/OCR tests (`tests/test_phase3_extract.py`) + 27 API tests (`tests/test_phase3_documents.py`), run against real Tesseract 5 |
| Alembic upgrade/downgrade/model parity incl. migration 0006 | Passed (`tests/test_migrations.py`) |
| `phase3.js` syntax (`node --check`) and every `$("id")` exists in `index.html` | Passed |
| Browser/UI click-through | **NOT done** (no browser here). The UI is wired to tested endpoints but never visually exercised — expect small cosmetic issues. |
| Real college PDFs | **Not tested.** Only synthetic PDFs (digital table, digital free text, rasterised scans, blurred 80-dpi scan). |

Phase 2 note: the earlier "not run" Phase 2 suite now runs and passes. Two Phase 2 report tests failed only because of a test-fixture collision (duplicate student); fixed in `tests/test_phase2_reports.py`.

## Implemented
1. **Upload & storage** — `.pdf` only, magic bytes, size limit, structural open (never executed), encrypted and JavaScript/Launch PDFs rejected, SHA-256 duplicate detection (409 with existing id), random filenames, 0600, outside static dir, path-traversal guard, sanitised display names. Metadata: title, source, exam name, term, kind, uploader, upload date, status.
2. **Extraction/OCR** (`app/doc_extract.py`) — text layer + table reading, OCR fallback per page (300 dpi, preprocessing, orientation, confidence), force-OCR, language validation. Parses exam name, academic year, department, semester, instructions, 12-digit register-number count, and rows (date, time, FN/AN, code, name, dept, year, semester). Never invents values; inherited dates, assumed DD/MM, inferred AM/PM, session-only rows and all OCR rows are flagged and score lower.
3. **Review workspace** — page preview, extracted text, header edit, per-row edit/approve/reject, manual row, bulk approve (complete + confident only), document approve/reject; editing resets approval. Correction trail in `extraction_edits`, history in `document_events`, plus `audit_logs`.
4. **Import** — preview (catalogue mapping with suggestions, duplicates in document/existing, time/audience conflicts, term window, missing subjects) then admin-confirmed import guarded by a state signature (stale → 409). Creates **draft** exams only, optional audience rule when the department matches real students, optional subject creation, explicit "update existing" per row (re-checked with existing `_check_schedule`). Existing records are otherwise untouched.
5. **Roles** — admin+staff: upload, process, view, preview, download, preview-import. Admin only: edit, approve, import. Students/anonymous: none.
6. **UI** — "Document processing" panel (Documents, Review & correction, Import preview, Processing history) in `static/phase3.js`.

## Dependencies added
PyMuPDF 1.26.3, pytesseract 0.3.13, Pillow 11.3.0 (now in `requirements.txt`). Tesseract binary is a separate install (docs/OCR.md). Config: `DOCUMENT_STORAGE_DIR`, `MAX_UPLOAD_MB`, `OCR_DEFAULT_LANGUAGE`.

## Database migration
`0006_document_processing` (additive): new columns on `official_documents`, `pdf_pages`; tables `document_extractions`, `timetable_entries`, `extraction_edits`, `document_events`. Back up, then `python -m app.cli migrate`.

## Known limitations
- Multi-line wrapped table cells in OCR output can split a row (flagged incomplete, needs manual fix).
- Handwriting, heavy skew, very low-DPI scans, unsupported language packs, several timetables per page: unreliable/unsupported.
- Sessions printed only as FN/AN (no times) cannot be imported until an admin enters times.
- Imported exams use venue "To be announced"; venue-overlap check is skipped for them. Seat allocation is not created from PDFs.
- Processing runs synchronously in the request (large scanned PDFs can take minutes; no background queue). Max 300 pages.
- `/JS` byte-pattern check for active content is heuristic.
- Phase 1 `/api/admin/documents` endpoints and UI remain (seating-register candidates); not merged with the new flow.
- Android app, Windows scripts untouched/untested; lock file hand-appended, not regenerated.

## Remaining for Phase 4 (not started)
Seating/hall-allotment PDF import into `register_entries`/`seat_positions` and reconciliation with `allotments`; background job queue; browser end-to-end tests; real-document tuning; multi-language OCR evaluation; PDF-sourced venue assignment.

---

# (Earlier) Phase 2 progress — Examination Management & Seat Allocation (v0.3.0)

## Checkpoint 2 (packaging session)
No new upload or new feature request arrived, so this archive contains the same source as the previous Phase 2 ZIP, repackaged as `Exam_Monitor_Ultimate_Latest_Updated.zip`. Network access was still unavailable (pip could not install FastAPI), so the API/database tests and migration 0005 have **still not been executed**. Re-run in this session: engine unit tests (16 passed), whole-project compile, JS syntax check.
**Resume:** `cd backend && pip install -r requirements-dev.txt && python -m app.cli migrate && python -m pytest -q`, fix any failures, then start Phase 3 per the instructions below.

## Verification status (read first)
The build environment had **no network access**, so FastAPI, SQLAlchemy, Alembic and pytest could not be installed.
Therefore:

| Check | Result |
|---|---|
| `allocation_engine.py` unit tests (`tests/test_allocation_engine.py`, 16 tests) | **Run, all passed** (with a small pytest shim) |
| CSV / XLSX / PDF export code (`app/exports.py`) | **Run with the real openpyxl + reportlab**: valid files, formula-injection neutralised |
| Python syntax of every module, migration and test; JavaScript syntax; every `$("id")` in `phase2.js` exists in `index.html` | **Passed** |
| New API tests (`test_phase2_exams.py`, `test_phase2_allocation.py`, `test_phase2_reports.py`) | **Written, NOT run** |
| Existing Phase 1 test suite (223 tests), Alembic upgrade/downgrade/parity test, app start-up, browser UI | **NOT run** |

**First thing to do on your machine:** `cd backend && pip install -r requirements-dev.txt && python -m app.cli migrate && python -m pytest -q`.
Expect to fix small defects the offline build could not catch (most likely in the new SQL/ORM code, the 0005
migration parity test, or UI wiring). Do not treat Phase 2 as verified until that run is green.

## Features implemented
**Examination management**
- Create / edit / publish / unpublish / delete (draft-only, no allotments/results) — `POST /api/exams/{id}/publish|unpublish`, `DELETE /api/exams/{id}`.
- Subject catalogue (code + name, department, semester, credits, active) — `/api/admin/subjects`; exams link via `subject_id`.
- Academic years (one "current") and examination terms (semester, date window) — `/api/admin/academic-years`, `/api/admin/terms`; an exam's date must fall inside its term.
- Audience mapping: department / course / year rules (any-match, blank = any) plus per-student include/exclude — `GET|PUT /api/exams/{id}/eligibility`. No rules = all active students (Phase 1 behaviour). `students.course` added.
- Date/time validation; duration stored/returned; FN/AN session derived from start time; publish refuses past dates.
- Overlap prevention: same venue (existing), and **intersecting audiences at overlapping times** (checked when saving the audience or rescheduling); rescheduling is refused if it would create simultaneous seats/students.
- Filters: `GET /api/admin/exams?q&status&term_id&subject_id&department&session&date_from&date_to&limit&offset` (+ `X-Total-Count`).

**Seat allocation** (`allocation_engine.py` pure logic + `services_allocation.py` DB layer)
- Eligible students only; verified halls; active seat inventory; capacity respected; unavailable seats skipped.
- Rules: `strategy` (balanced | sequential), `seat_gap` 0–5, `department_separation` (off | preferred | strict).
- Seats used by any **simultaneous** exam are unavailable; students already seated in a simultaneous exam are not allocated again.
- Existing allotments are never moved; existing allotments that became invalid (inactive seat, unverified hall, ineligible student) are *reported* in the preview, not changed.
- Preview → approve → commit: `POST /api/allotments/plans` (admin/staff) stores a plan; `POST /api/allotments/plans/{id}/commit` (**admin only**) re-computes from current data and saves only if identical, else marks the plan `stale`; insufficient capacity blocks commit unless `allow_partial=true`. One transaction; DB unique constraints are the backstop.
- Phase 1 endpoints `/auto-preview` and `/auto-allocate` kept (same response shape/status codes) and now use the new engine.
- Manual allocation (`POST /api/allotments`) uses the same checks; correction `PATCH /api/allotments/{id}` (reason mandatory); delete takes an optional `?reason=`.
- History: every create/auto/move/delete writes `allotment_history` **and** `audit_logs` in the same transaction — `GET /api/allotments/history`.

**Reports** (`/api/admin/reports/…`, admin/staff only, `?format=json|csv|xlsx|pdf`)
- `exams` (examination-wise summary), `exams/{id}/summary`, `/allocations?order=register|hall|name&hall&department&q`, `/unallocated`, `/halls` (occupancy & capacity), `/seating?hall&columns` (hall-wise charts; PDF = one printable page per hall), `students/seats?q` (staff student-wise lookup across all exams).
- Browser "Print" for seating plans; XLSX/PDF need `openpyxl`/`reportlab` (now in `requirements.txt`; the API answers 501 if missing, CSV always works).

**Admin UI** — new "Examination workspace" in the dashboard (`static/phase2.js`): Examinations (filters, form, publish, audience editor), Subjects, Academic years & terms, Seat allocation (hall picker, rules, preview, approve/discard, corrections, history), Reports (views, downloads, print, student lookup). The Phase 1 auto-allocation block was removed from the page because the Allocation tab replaces it; the quick exam form and manual seat form remain.

## Features still incomplete / known limitations
- Seat adjacency is **linear** (previous/next seat label); there is no row/column hall geometry, so "separation" cannot consider front/back rows.
- No bulk "clear all allocations of an exam", no re-allocation of invalid existing seats (reported only), no CSV import of subjects/eligibility, no academic-year/term edit UI (API `PATCH` exists).
- PDF export uses the built-in Latin font: non-Latin names (e.g. Tamil) will not render in PDFs (CSV/XLSX are fine).
- Plans store assignments as JSON text; very large runs (>10 000) are untested. Preview responses are capped at 500 rows (full list is stored).
- `requirements-py312.lock.txt` was not regenerated (needs network) — add `openpyxl` and `reportlab` pins when you next freeze.
- Android app and Windows scripts untouched and untested.

## Files and database changes
New: `app/allocation_engine.py`, `app/services_allocation.py`, `app/exports.py`, `app/routers/catalogue.py`, `app/routers/reports.py`, `app/static/phase2.js`, `migrations/versions/0005_exam_management_and_allocation.py`, `tests/test_allocation_engine.py`, `tests/test_phase2_{exams,allocation,reports}.py`.
Changed: `app/models.py`, `app/schemas.py`, `app/main.py` (version 0.3.0, routers), `app/routers/{exams,allotments,students}.py`, `app/static/{index.html,app.js,style.css}`, `requirements.txt`, `docs/*`.
Migration **0005** (additive, nullable columns, existing rows kept; durations back-filled): new tables `subjects`, `academic_years`, `exam_terms`, `exam_eligibility_rules`, `exam_student_overrides`, `allocation_plans`, `allotment_history`; new columns `students.course`, `exams.subject_id/term_id/duration_minutes`, `allotments.source/plan_id`. **Back up the database before migrating** (`backup.bat`), then `python -m app.cli migrate`.
Backward compatibility: `subject_code` is still accepted without `subject_id`; public endpoints and responses unchanged; `/api/admin/exams` still returns a JSON list (new fields are additive).

## Continuation instructions for Phase 3 (PDF / OCR)
1. Run the test suite (above) and fix any failures first; commit that as the Phase 2 baseline.
2. Phase 3 should populate the existing `doc_models` tables (`seating_sheets`, `register_entries`, `seat_positions`) via `routers/documents.py`; do not write to `allotments` directly from extraction.
3. Reconcile extracted seating with computed allocations: for an approved sheet, compare `register_entries` (hall/seat) with `allotments` using `services_allocation.check_placement` and surface differences as `review_issues`; only an administrator-approved import should create `Allotment` rows with `source="pdf"` and an `allotment_history` row.
4. Add row/column geometry from `seat_positions` to improve the engine's adjacency (`allocation_engine._HallState.find` is the single place that defines "neighbour").
5. Reuse `exports.tabular` for any new report; keep the public lookup name-free.

## Phase 8.2 — implementation checkpoint (15 Nov 2026)

Implemented in this checkpoint:
- Verified ZIP backups containing a consistent SQLite online snapshot or PostgreSQL custom dump, uploads, and SHA-256 manifest.
- Backup verification, listing, explicit CLI restore, pre-restore safety backup, SQLite quick-check + staged replacement, and PostgreSQL `pg_restore` path.
- Optional scheduled backup interval and verified-backup retention policy (disabled by default).
- Administrator-only status, integrity, backup, export and student-import APIs.
- CSV/XLSX/JSON student import with preview, row-level validation, duplicate detection, explicit commit and atomic transaction.
- Students/exams/results/allotments exports in JSON/CSV/XLSX/PDF; sensitive authentication data is excluded.
- Read-only data-integrity checks for duplicate registers/account links/seats, orphan records, invalid marks, invalid exam schedules, overlapping student allocations and SQLite FK violations.

Verification:
- Python compileall passed.
- Phase 8.2 focused tests: 12 passed.
- Phase 8.1 DB tests plus Phase 8.2 tests passed in the local SQLite test environment; PostgreSQL-only tests were skipped.
- Full backend suite was not completed: `aiosmtpd` is missing at collection, and a run excluding its test module exceeded the available execution time.
- PostgreSQL `pg_dump` / `pg_restore`, real Windows restore, production scheduler behaviour and browser downloads remain unverified.

Next: Phase 8.3 should integrate the admin UI, run full regression with test dependencies installed, and perform available PostgreSQL backup/restore tests. Do not describe Phase 8 as complete until that work is done.


# Phase 10 — Advanced Analytics, Intelligence & Reporting (2026-11-15)

## Implemented
- Added `backend/app/routers/analytics.py` and registered it in the existing FastAPI app.
- Added a database-backed examination analytics dashboard with date, department, semester, subject, academic-year and configurable pass-threshold filters.
- Added subject/department aggregations, pass/fail counts, chronological examination trend points and allocation totals.
- Added individual published-result history and subject progression endpoints, plus a student-only self-service endpoint constrained to the authenticated linked student.
- Added transparent at-risk screening with configurable minimum result count, average threshold and recent percentage-point drop; each flag includes explicit reasons and a disclaimer.
- Added allocation analytics by hall/department/exam, with capacity utilization only for verified halls with recorded capacities.
- Added CSV/XLSX/PDF/JSON performance report exports through the project's existing export helper.
- Added explicit attendance-unavailable and no-estimation/data-quality metadata.
- Added targeted Phase 10 API tests and `docs/PHASE10_ANALYTICS.md`.

## Data preservation and compatibility
- No existing model/table was modified and no migration was added.
- Existing Phase 1–9 routes, Android sources, database schema and records are retained.
- New routes use existing authentication, role checks and department scoping.

## Verification status
- Python `compileall` passed for backend application code and the new Phase 10 tests.
- Targeted Phase 10 API tests: **7 passed** (dashboard, student self-scope, at-risk rules, unusual-change insights, academic comparisons, CSV/XLSX/PDF exports, and unallocated-seat reporting).
- JavaScript syntax check (`node --check`) passed for all existing frontend JavaScript files, including the updated dashboard and reports pages.
- The full Phase 1–9 test suite was not rerun, in accordance with the instruction not to repeat previously completed tests.
- No production database or real student records were used in verification; tests use the project's isolated SQLite test harness.
- Added academic-year/semester comparison endpoint and unusual-change insight detection with configurable minimum cohort size and percentage-point threshold.

---

# Phase 12 — final release packaging

**State: source package finalized; no builds, tests, audits, or deployment verification performed.**

## Release preparation
- Preserved the Phase 1–11 application source, migrations, frontend assets, Android project, deployment configuration, scripts,
  and historical documentation.
- Added a release-operator guide and a documentation index to make installation, production configuration, migration,
  backup/recovery, and user guidance discoverable.
- Added optional Android release signing inputs supplied through Gradle properties or environment variables. Signing material
  remains external to the source tree; release API endpoints must use HTTPS when explicitly configured.
- Clarified that the Android project is source-only and that no APK/AAB build is included or claimed.
- Retained the SQLite migration fixture because it is a historical test input, not a runtime database.

## Packaging boundaries
- Environment examples remain templates with placeholders. No real credentials, TLS private keys, production databases,
  backups, virtual environments, dependency caches, or generated build outputs are part of the release archive.
- Existing feature code and migration history were not intentionally removed or rewritten.
- No tests, audits, builds, static checks, or runtime verification were run for Phase 12.

---

# Phase 12.1 — release corrections (FINAL_RELEASE_FIXED)

**State: corrections applied directly in the existing project; no tests, builds, audits, Docker/Gradle runs or deployments were executed.**
See `docs/RELEASE_FIXES.md` for the itemised list. Highlights: Android release signing is now wired to the four `RELEASE_*` inputs, `gradlew` keeps its
executable bit in the ZIP, Windows batch files are CRLF, Docker `/tmp` tmpfs mode and scheduled-backup default fixed, Nginx HTTP/2 syntax modernised,
Dockerfile gains the Tesseract binary, and documentation that misdescribed start-up migration and the signing configuration was corrected.

---

# Phase 12.2 — VSB Karur final release (FINAL_RELEASE)

**State: corrections applied in the existing project by reading the code; no tests, builds, audits, Docker/Gradle runs or deployments were executed.**
See `docs/FINAL_RELEASE_NOTES.md`: Python 3.14-compatible dependency ranges, de-duplicated Nginx security headers, stale head-revision documentation (`0013`), VSB quick start, regenerated manifest.


# Phase 13 — official verification status safeguards

**State: implementation and documentation updated; focused tests passed. Full backend suite and Windows/runtime verification remain incomplete.**

- Expose `verification_status` in VSB record API responses.
- Block individual approval and bulk approval unless status is `FULLY_VERIFIED`; flags and duplicate-seat checks remain additional safeguards.
- Invalidate verification to `UNRESOLVED` when hall, seat, or subject code is materially changed. Department-only edits do not reset it.
- Add a publication-time server-side guard against previously approved records with non-fully-verified status.
- Add an audited administrator verification endpoint requiring official-host PDF references; full verification requires both hall-list and seat-sheet references.
- Focused importer and allocation workflow tests: 30 passed. Full backend suite was not completed because `aiosmtpd` was unavailable and the retry exceeded the execution time limit.
- Update overall verification limitations, official verification report, hall-label variant review, and CSV status classification (377 / 772 / 950).
- Historical official-source limitations remain explicit: source PDF binary files and hashes are not included; some seat sheets and all 16 Nov official PDFs were unavailable.
