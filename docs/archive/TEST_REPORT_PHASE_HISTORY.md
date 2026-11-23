# Test report - Phase 7.1 (Android v0.8.1, backend v0.7.0)

**Date:** 14 Nov 2026. **Environment:** Linux sandbox, JDK 21, Python 3.12, kotlinc 2.0.21, Gradle 8.10.2 (from GitHub releases).
**Android SDK: absent. Google Maven / Maven Central / dl.google.com: unreachable.** Therefore the Android build and APK could not be produced.

## Summary
| Area | Passed | Failed | Could not run |
|---|---|---|---|
| Backend full suite | 477 | 0 | `tests/e2e_jsdom` (Node UI test) not run |
| Android core logic (kotlinc + JUnit shim) | 25 | 0 | - |
| Static source review of Android code | 3 compile defects + 1 logic bug found and **fixed** | - | - |
| Gradle `clean` / `testDebugUnitTest` / `assembleDebug` / `lintDebug` | - | - | **all four** (AGP not resolvable) |
| `DataLayerTest.kt` (MockWebServer etc.) | - | - | **not run** |
| Emulator / device functional tests | - | - | **not run** |
| APK + SHA-256 | - | - | **no APK exists** |

## Commands actually run and results
| Command | Result |
|---|---|
| `cd backend && python -m pytest tests --ignore=tests/e2e_jsdom` (fresh venv from `requirements.txt` + `requirements-dev.txt`) | **477 passed, 0 failed, 0 errors, 0 skipped** in 64 s - `docs/PHASE71_BACKEND_FULL_TEST_RESULTS.xml` |
| kotlinc 2.0.21 on `core/*.kt` + `CoreLogicTest.kt`, run with a JUnit shim | **25 passed, 0 failed** - `docs/PHASE71_ANDROID_CORE_TEST_RESULTS.txt` |
| `./gradlew --version` (project wrapper) | Gradle 8.10.2 starts - wrapper jar and `gradlew` are valid |
| `./gradlew clean testDebugUnitTest assembleDebug lintDebug` | **FAILED before any task ran**: `Plugin [id: 'com.android.application', version: '8.7.3'] was not found` (Google/MavenRepo/Gradle plugin portal unreachable) - `docs/PHASE71_GRADLE_ATTEMPT.txt` |
| kotlinc syntax check of the edited UI files | No syntax errors (only unresolved-library errors, expected without Compose jars) |

## Android functional areas requested (none could be exercised on an emulator/device)
| Area | Evidence available | Status |
|---|---|---|
| Login / logout | Backend contract tests (passed); `AuthRepository` logic read; `DataLayerTest` cases written | **Not run on Android** |
| Session restoration / expiration | Backend session tests (passed); `SessionManager` + `UnauthorizedInterceptor` tests written (`DataLayerTest`) | **Not run** |
| Role-based navigation | `RoleNavigationTest` (7) | **Passed (JVM, shim)**; Compose wiring not run |
| Student timetable / exam details | `TimetableAndNotificationTest` (7) logic; backend lookup contract | Logic passed; UI not run |
| Hall and seat allocation display | Mapper tests + backend contract; one UI logic bug fixed (location text) | UI not run |
| Published results | Backend contract (student isolation); mapper tests | UI not run |
| Announcements | Backend contract | UI not run |
| Notification list / unread count / preferences | Backend notification tests (passed); reducers and paging merge tested in core tests | Logic passed; UI not run |
| API error handling | `ErrorAndValidationTest` (8) | **Passed (JVM, shim)** |
| Offline cache and account isolation | `DataIsolationAndMappingTest` (3) for key namespacing; `ReadThroughTest`/`SessionAndCacheTest` written | Key logic passed; store/session tests **not run** |

## Security review (source inspection, 14 Nov 2026)
| Check | Result |
|---|---|
| Encrypted token storage | Token, profile and cache are in `EncryptedSharedPreferences` (AES-256-GCM values, AES-256-SIV keys, Keystore master key) - **by code inspection; not verified on a device** |
| No plaintext password storage | Passwords are only passed to the login/change requests; never persisted, logged or placed in `rememberSaveable` (grep) |
| No credentials in source | No secrets/keys/keystores in `app/src/main`, `debug`, Gradle files; test literals are fake |
| HTTPS in release | Release has `ALLOW_CLEARTEXT=false`; `ApiUrl.check` rejects `http://`; no network-security override in release; cleartext only in `src/debug` (**URL check unit-tested; manifest merge not run**) |
| No private data in logs | No `Log.*`, `println`, `printStackTrace` or logging interceptor anywhere |
| Cache cleared on logout / account switch | `SessionManager.wipe()/signIn()`, per-user key namespace, `ViewModelStore.clear()` when not signed in - logic read; key isolation test passed; session tests **not run** |
| Unauthorised roles | UI gating (`Navigation`, `Permissions`) tested; **the backend remains the authority** (permission tests in the 477 passed) |
| Backups | `allowBackup=false`, extraction rules exclude everything |
Not covered: certificate pinning, root detection, FLAG_SECURE, R8 (all absent, documented as limitations).

## Process note
Earlier phase notes said to run the full backend suite only after an explicit "AUTHORIZE FINAL TESTING AND VERIFICATION". The Phase 7.1 brief asked for
verification and an updated test report, so the suite was run in a scratch copy with a throw-away venv (no project files or databases were changed).
Disregard the backend figures if you did not intend that.

---

# Test report — Phase 5 (v0.6.0)

**Environment:** Linux sandbox, Python 3.12, Node 22, SQLite, Tesseract present. Run date: 14 Nov 2026.

| Check | Command | Result |
|---|---|---|
| Backend + front-end contract tests | `cd backend && python -m pytest` | **413 passed, 0 failed, 0 skipped** (392 pre-existing + 21 new; JUnit: `docs/PHASE5_TEST_RESULTS.xml`) |
| Python compilation | `python -m compileall -q app migrations tests` | passed |
| JavaScript syntax | `node --check` on every `static/js/*.js` and the e2e script | passed |
| Alembic | `alembic heads` | single head `0008` (no new migration in Phase 5) |
| DOM-level UI test (jsdom, live server, temp DB) | `python tests/e2e_jsdom/run_e2e.py` | **163 checks passed, 0 failed** |

## What the new automated tests cover
* `test_phase5_backend.py` — student profile exposes only the linked student's record; `/api/results/admin/list` allowed for admin/super admin only (403 staff/invigilator/student, 401 anonymous), filters, publish round-trip; the new path does not shadow `/api/results/{register_number}`.
* `test_phase5_frontend_contract.py` — every `/api/...` path used by the JavaScript exists in the OpenAPI schema; `index.html` references only existing assets; legacy scripts are gone; no inline scripts/handlers; no `eval`/`document.write`; the token is never put in `localStorage`; unique page routes; static assets carry the CSP/nosniff headers.
* Existing UI-string tests in `test_static_and_startup.py` and `test_phase3_documents.py` were **rewritten** (not deleted) to assert the same intent against the new files (no pre-filled credentials, numeric keyboard + Clear button, no token in localStorage, role options loaded from `/api/admin/roles`).

## What the jsdom test exercised
Public lookup; redirect of protected routes; not-found page; wrong-password error; for **each of the five roles** the exact sidebar, every permitted page loading without error, every forbidden page refused, and the server returning 403 for admin-only APIs; admin workflows (subject, year/term, exam with a backend validation error shown in the dialog, publish, audience, student, hall → seats → verify, allocation preview → commit → move → history, seating chart and print view, results add/publish, account create/weak password/reset, announcement, security, audit); timetable PDF review → correction → approval → import preview → import (creating draft exams); expired/revoked session → return to sign-in; logout; student and invigilator views.
The test found and I fixed real defects: crash in the navigation after sign-out, a missing helper on the seating-import page, a Save button without an action binding, and duplicate `id` attributes in form fields.

## NOT executed (be careful before relying on these)
* **Real browser testing** (no browser could be installed here; jsdom is not a rendering engine). Layout, CSS, responsiveness on phone/tablet, print output, focus behaviour and dialog modality are unverified.
* Accessibility audit (axe/Lighthouse/screen reader) and colour-contrast measurement.
* File-picker uploads and the PDF page-image preview through the UI; file downloads (CSV/XLSX/PDF) in a browser.
* Android Gradle build/device run; Windows `.bat` scripts; PostgreSQL; load/performance; real SMTP/SMS; OCR accuracy on real institutional PDFs.

A passing suite does not imply these passed. This is a development checkpoint, not a production release.

---

# Test report — Phase 8.2 (15 Nov 2026)

**Scope:** backup/restore services, import parsing and validation, transaction-safe student import, data-integrity checks, and administrator API routes. No schema migration was added in Phase 8.2.

| Check | Result |
|---|---|
| Python compilation (`python -m compileall -q app tests`) | passed |
| Phase 8.2 tests (`pytest -q tests/test_phase82_data_management.py`) | **12 passed** |
| Phase 8.1 DB tests + Phase 8.2 tests (`pytest -q tests/test_phase82_data_management.py tests/test_phase8_database.py`) | passed; PostgreSQL-only variants skipped because this run used SQLite |
| SQLite backup creation, manifest and payload checksums | tested |
| SQLite restore with explicit confirmation and automatic safety backup | tested on an isolated temporary database |
| Student CSV/JSON parsing, duplicate and required-field validation | tested |
| 125-row student import and invalid-batch no-partial-write behaviour | tested |
| Admin authorization, data status, integrity, JSON export, backup and import preview/commit endpoints | tested |
| PostgreSQL `pg_dump` / `pg_restore` | not run in this environment |
| Full backend suite | **not completed**: collection stops because optional test dependency `aiosmtpd` is not installed for `tests/test_phase6_mail.py`; a run excluding that module exceeded the execution time limit |
| Real Windows restore workflow / browser download / scheduled production backups | not tested |

Do not interpret this focused result as a full regression pass. The `aiosmtpd` dependency must be installed in the development/test environment to collect the full suite. PostgreSQL backup and restore require client tools and a disposable PostgreSQL database for integration testing.
