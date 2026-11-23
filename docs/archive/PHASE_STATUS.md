# Implementation status — Phase 8.2 checkpoint

Legend — **Impl**: source exists and is reachable from the UI. **Auto-tested**: covered by the automated backend/contract tests. **UI-checked**: driven through the jsdom DOM test (`backend/tests/e2e_jsdom`, not a real browser). **Unverified**: not exercised in this environment.

| Area | Impl | Auto-tested | UI-checked | Notes |
|---|---|---|---|---|
| Authentication, sessions, logout/logout-all, forced password change, expiry handling | yes | yes | sign-in, wrong password, logout, server-revoked session → redirect | Registration/activate/forgot/reset pages exist; e-mail delivery unverified |
| Role-based access (5 roles) | yes | yes (matrix incl. new endpoints) | sidebar items + allowed/forbidden pages for every role; server 403 asserted | |
| Examinations (CRUD, filters, publish/unpublish, delete draft) | yes | yes | create (with backend error shown), publish | |
| Audience / eligibility editor | yes | yes | rule add + save | |
| Subjects, academic years, terms | yes | yes | create | |
| Students | yes | yes | list, create | edit/seat-lookup actions not driven in UI test |
| Halls, seat inventory, verification, building/block/floor directory | yes | yes | create hall, generate seats, verify | directory dialogs not driven |
| Seat allocation: preview → approve → commit, manual seats, move/remove, history | yes | yes | preview (nothing saved) → commit → move → history | |
| Reports & seating plans (view, CSV/XLSX/PDF, print) | yes | yes (API) | seating chart view, print view | downloads not driven (jsdom) |
| Timetable PDF upload, extraction/OCR, review & correct, approve, import preview/confirm, history | yes | yes (API; OCR on synthetic PDFs) | review, correct, approve, import creating draft exams; upload via API | file chooser + page-image preview not driven |
| Seating-allotment PDF import | yes | yes (API) | page loads with a processed document | extract/approve/import not driven in UI test |
| Phase 1 register-candidate queue | yes | yes (API) | page loads | kept because approved entries feed the public lookup |
| Accounts & permissions (create, suspend/restore, role, reset, unlock, force logout, activity) | yes | yes | create, weak-password error, reset (temp password shown once) | |
| Security dashboard, audit history | yes | yes | both pages load with data | |
| Results (admin list/add/publish/unpublish) | yes | yes (new list endpoint) | add + publish | |
| Student portal (seats, results, timetable) / invigilator rosters | yes | yes | dashboard, results, roster | |
| Announcements | yes | yes | create | |
| Responsive layout, dark mode, keyboard/ARIA semantics | yes | no | no | **Unverified visually.** Written to WCAG-oriented practice (labels, aria-live, focus ring, skip link, dialog element) but not audited |
| Android client | Phase 7.1 (v0.8.1): 3 compile defects + 1 logic bug fixed by review | partially (core 25/25 + backend contract; full backend 477/0) | no | Gradle build never run (no SDK / Maven unreachable); no APK; see docs/PHASE71_GRADLE_ATTEMPT.txt |

Phase 5 changes to the backend are additive only: `GET /api/results/admin/list` (administrator) and `register_number`/`student_name` in `/api/auth/profile` for linked student accounts.

## Phase 8 status (15 Nov 2026)

| Area | Implementation | Verification | Notes |
|---|---|---|---|
| Phase 8.1 database architecture, schema audit, migrations | implemented in the Phase 8.1 checkpoint | Claude-reported SQLite/PostgreSQL migration and regression evidence is retained in `PHASE81_*` files; current sandbox reran `test_phase8_database.py` with Phase 8.2 tests | PostgreSQL compatibility bootstrap is specific to empty PostgreSQL databases; released migration history remains immutable |
| Verified database + uploads backups | implemented | SQLite backup creation, manifest verification, listing and restore tested in `test_phase82_data_management.py` | PostgreSQL path requires `pg_dump` / `pg_restore`; not exercised in this run |
| Scheduled backups and retention | implemented, disabled by default | code compiled; scheduled PostgreSQL/production scheduler behaviour not integration-tested | configure `BACKUP_SCHEDULE_ENABLED`, `BACKUP_INTERVAL_HOURS`, `BACKUP_RETENTION_COUNT` |
| CSV/XLSX/JSON student import | implemented with preview and explicit commit | parser, validation, 125-row transaction, invalid-batch rollback and API flow tested | PDF import is not supported for structured student data |
| CSV/XLSX/JSON/PDF exports | implemented for students, exams, results and allotments | API JSON export tested; existing `tabular` helper provides file formats | browser download behaviour not tested |
| Data-integrity report | implemented, read-only | empty-database report and API contract tested | PostgreSQL-specific FK diagnostic is enforced by DB constraints, not PRAGMA |
| Restore from HTTP UI | intentionally not exposed | not applicable | restore is CLI-only because live sessions/workers make in-request DB replacement unsafe |
| Admin data-management UI | not implemented in Phase 8.2 | pending | reserved for Phase 8.3 integration |
| Android Gradle build / APK | still unverified | no Android SDK build in this environment | see `docs/PHASE71_GRADLE_ATTEMPT.txt` |


## Phase 9 — Deployment and operations

Implemented source package: Windows install/configure/start/stop scripts; Dockerfile; Compose PostgreSQL/API/Nginx topology; production env template; TLS/security-header proxy configuration; deployment, Docker, Windows and troubleshooting guides. **Not deployed or target-environment verified.** Previous tests were not rerun by request. See `docs/PHASE9_DEPLOYMENT.md`.


## Phase 11 — cross-module integration (implementation checkpoint)

| Area | Implementation | Verification | Notes |
|---|---|---|---|
| Backend integration API | Implemented | Not run by request | Permission-scoped module overview and exam readiness summary |
| Web workflow centre | Implemented | Not run by request | Live overview, exam selector, checklist and links to existing modules |
| Android API/repository | Implemented in source | Not built by request | Retrofit overview/readiness/student analytics endpoints |
| Database compatibility | No migration added | Not checked | Existing schema and migration files preserved |
| SMTP/OCR/PostgreSQL/attendance | Existing capability retained | External environment dependent | Credentials/tooling required; attendance explicitly unavailable |

Phase 11 tests, audits, builds and verification were intentionally not run. See `docs/PHASE11_INTEGRATION.md`.
