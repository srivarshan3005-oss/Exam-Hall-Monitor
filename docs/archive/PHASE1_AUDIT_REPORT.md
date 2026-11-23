> **Historical document.** Written for an earlier phase; the single-page UI files it mentions (`app.js`, `phase2-4.js`, `style.css`) were replaced in Phase 5. See `docs/PHASE_STATUS.md` and `docs/TEST_REPORT.md` for current status.

# Phase 1 — Project audit and defect report

**Checkpoint audited:** `Exam_Monitor_Ultimate_ChatGPT_Checkpoint_2026-11-12_v2.zip`  
**Project version:** `0.2.1-dev1`  
**Audit date:** 12 November 2026  
**Scope:** Source archive inspection, backend tests, static syntax/compile checks, migration graph inspection, and build-tool availability checks.

## Executive result

The existing project was retained in place. Two targeted regression protections were added, with one defensive response-serialization improvement. The backend suite passes in this environment. This is a verified development checkpoint, not a production release: Android compilation, Windows execution, PostgreSQL validation, browser end-to-end testing, and production security review remain unverified.

## Defects and resolutions

| ID | Finding | Action | Status |
|---|---|---|---|
| P1-01 | Public allotment response could serialize an empty or all-null `location` object when a verified hall had no useful hierarchy metadata. | Filter empty/null location values and omit the `location` property unless useful metadata remains. Added regression test for verified hall with no location metadata. | Fixed and tested |
| P1-02 | A simplistic administrator UI security scan could treat the literal UI role value `administrator` as an authorization bypass, despite the frontend intentionally translating it to backend role `admin`. | Kept the friendly UI label/value and explicit mapping; added regression coverage proving the UI alias exists while backend role vocabulary remains exactly `admin`, `staff`, `student`. No permission checks were weakened. | Fixed as a test-classification false positive; regression tested |
| P1-03 | Android Gradle wrapper is absent (`gradlew`, `gradlew.bat`, wrapper JAR and wrapper properties are not present). | Confirmed no Gradle executable or cached wrapper/distribution is available in this environment. Network name resolution is unavailable, so an official wrapper JAR/distribution cannot be fetched or safely fabricated. | Open — Android build cannot be verified here |

## Architecture inspection

- **Backend:** FastAPI application factory/lifespan, router registration, startup secret/database checks, health/readiness endpoints, CORS and security headers were inspected.
- **Frontend:** Static HTML/CSS/JavaScript, API calls, session-storage token handling, administrator role mapping and public lookup rendering were inspected. JavaScript syntax check passed.
- **Database:** SQLAlchemy core/document models and Alembic revisions `0001`–`0004` were inspected. Alembic reports one head: `0004`.
- **Authentication/authorization:** Password/token/security dependencies, role-gated routes, account administration and authorization tests were inspected. Automated tests pass.
- **Administrator/faculty/student:** Existing endpoints and UI integration were inspected. The source includes an administrator/staff dashboard and public/student lookup; a fully separate faculty/student authenticated interface is not present and is documented as a product limitation, not misreported as complete.
- **Exams/timetable/seats:** Exam, allotment and automatic allocation preview/commit paths and their tests were inspected. Automatic commit is administrator-only; preview is available to authorized admin/staff users.
- **Documents/PDF:** Document models, upload/review routes and PDF extraction/OCR dependencies were inspected. Candidate extraction remains review-gated; arbitrary PDF field extraction is not complete.
- **Android:** Kotlin activity, Retrofit DTO/API definitions, manifest and Gradle Kotlin DSL files were inspected. Source compilation/device behavior is unverified because the wrapper/Gradle/Android SDK toolchain is unavailable.
- **Windows/deployment:** Batch scripts and deployment documentation were inspected. They were not executed on Windows in this Linux environment.

## Automated verification evidence

Environment: Linux sandbox, Python 3.13.5, Node.js v22.16.0, SQLite test database.

| Check | Command / evidence | Result |
|---|---|---|
| Backend test suite | `cd backend && python -m pytest -q` | **225 passed, 0 failed, 0 skipped** |
| Python syntax/bytecode compilation | `python -m compileall -q app migrations tests` | Passed |
| Frontend JavaScript syntax | `node --check app/static/app.js` | Passed |
| Alembic migration graph | `alembic heads` | One head: `0004` |
| Android build | Gradle wrapper/Gradle/SDK unavailable | Not run |
| Windows batch scripts | Requires Windows | Not run |

The machine-readable JUnit report is `PHASE1_TEST_RESULTS.xml`.

## Compatibility and preservation

- No database model or migration files were changed.
- No migration revision was added; existing migration head remains `0004`.
- Existing API response shape is preserved for allotments without useful location metadata: the optional `location` key is omitted rather than emitted empty.
- Existing administrator UI value remains a presentation alias and is still mapped to the backend's canonical `admin` role.
- Existing application features and project layout were retained.

## Remaining verification / release blockers

1. Add/restore an official Gradle wrapper using a trusted Gradle distribution, then build and test the Android app on an emulator/device.
2. Execute install/start/stop/backup/test batch files on a supported Windows 10/11 host.
3. Verify PostgreSQL migrations and runtime behavior against a disposable PostgreSQL database.
4. Run browser end-to-end, accessibility, concurrency/load and deployment security tests.
5. Evaluate PDF extraction/OCR against representative authorized documents and verify human-review workflow end to end.
6. Complete institutional privacy, data-retention, HTTPS, secrets, backup and operational review before production use.

No claim is made that the above unexecuted checks passed.
