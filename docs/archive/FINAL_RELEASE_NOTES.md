# Release notes - FINAL RELEASE (production-readiness build, 16 Nov 2026)

> **Historical record.** This document describes an earlier build. Its test counts and status statements are not the current verification status. For the current commands, results and limitations see `docs/VALIDATION_REPORT_v6.md` (or `VALIDATION_REPORT_v6.md` from the top-level folder).

Package: `Exam_Monitor_Ultimate_VSB_KARUR_FINAL_RELEASE.zip`. Evidence and limits: `docs/TEST_REPORT.md` (first section).

What changed since the previous build: domain, PostgreSQL password, SECRET_KEY and SMTP are environment-driven (`DOMAIN_NAME` etc.; Nginx config is now a template); production `check-config` rejects example placeholders; Android release builds require an explicit HTTPS `API_BASE_URL` and a complete signing configuration; new guides `WINDOWS_INSTALLATION.md`, `ANDROID_RELEASE.md`, `VSB_VERIFICATION_LIMITATIONS.md`; Windows PID handling via `scripts/managed_server.ps1`; website fixes from the previous session retained. No migration or data change (head 0013); all Phase 1-12 features kept.

Executed: backend SQLite 590 passed / 24 skipped (21 PostgreSQL-gated + 3 private-fixture); jsdom 214 passed and JS syntax 13 files OK (previous session, no later JS change); PostgreSQL 601 and migrations 0001-0013 from the earlier session (not re-run).

To go live you must supply: a domain, TLS certificate and key, `SECRET_KEY`, `POSTGRES_PASSWORD`, SMTP credentials, and (Android) the HTTPS API URL and signing keystore. None are included.

**Not verified:** Windows script execution, Android build/APK (none exists), Docker build/run and nginx syntax, OCR, AN sessions, 14 Nov PDFs, most of the 16 Nov PDFs, manual browser testing. This is a release candidate, not a declared production release.

---

# Release notes — Exam_Monitor_Ultimate_VSB_KARUR_VERIFIED_RELEASE

> The file name says "VERIFIED" at the requester's choice. **No test, build, audit or deployment was run for this package;** nothing in it is verified by execution.

## Final inspection (this package)
Read the VSB allocation service, router, models, role checks and frontend calls again: consistent with each other. One missing requirement found and implemented: hall **capacity-violation detection** when a batch is staged (`vsb_alloc/service.py::check_capacity`, flag `hall_capacity_exceeded` in `reconcile.py`, label in `pages-vsb-alloc.js`, `docs/VSB_ALLOCATION.md`). Syntax of the two edited Python files was parsed only; the new code was not executed.

## Previous release (FINAL_RELEASE)

Continues `Exam_Monitor_Ultimate_VSB_KARUR_FINAL_FIXED`; the project was not recreated. No feature, migration (`0001`–`0013`) or database record was removed.

## Changed in this release
| Area | Change |
|---|---|
| Dependencies | `requirements.txt` pinned Pillow and PyMuPDF to exact versions while claiming Python 3.12–3.14 support; Pillow 11.3.0 has no Python 3.14 wheel, so installation on 3.14 would fail. Replaced by ranges (`Pillow>=11.3.0,<13`, `PyMuPDF>=1.26.3,<2`, `pytesseract>=0.3.13,<0.4`). `requirements-py312.lock.txt` still records the exact Python 3.12 set. |
| Nginx | The application already sends HSTS, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` and `Permissions-Policy`; Nginx added them again. Nginx now hides the upstream copies so each is sent once. |
| Documentation | README / docs index: stale database head `0011` corrected to `0013`; VSB allocation workflow and a Karur quick start added; Python-version note for Windows; Docker `--env-file` reminder; correction report moved to `docs/`. |
| Packaging | `RELEASE_MANIFEST_SHA256.txt` regenerated; ZIP built so `android/gradlew` and `android/build_debug.sh` keep their executable bit. |

## Reviewed by reading, found already correct (no change made)
Android release signing (four `RELEASE_*` inputs, partial configuration fails, none = unsigned), Gradle wrapper and `.gitattributes`; Windows `install/start/stop` scripts (CRLF); Docker Compose / Dockerfile / PostgreSQL wiring and `--env-file` usage; frontend hash-route links and `/api/vsb*` calls against the backend routers; manifest class `ExamMonitorApp`; Phase 1–12 routers all registered in `main.py`; no `.env`, keystore, database (other than the test fixture), `.venv`, `node_modules` or caches in the tree.
`backend/tests/fixtures/phase71_release.sqlite3` is a synthetic historical migration fixture required by `test_phase8_database.py`; it is not a runtime database and was kept.

## Not done / not verified
No tests, audits, builds, Docker or Gradle runs were executed in this session, and none are claimed. In particular: the backend suite (including migration `0013` and the VSB workflow tests), the Android build/APK, Docker/PostgreSQL deployment, Windows scripts on a real Windows machine, the Python 3.14 dependency install, real-PDF parsing of VSB hall/seat files, OCR on scanned PDFs, and browser behaviour of the UI. Run `test.bat` / `pytest` and `alembic upgrade head` (via `app.cli migrate`) before relying on the release.

## Original hall-allocation portal integration

* New: `POST /api/vsb-allocation/import/original` (administrator). Dry run by default; writing needs `confirm=true`. Stages
  draft batches only. See `docs/ORIGINAL_PORTAL_IMPORT.md`.
* New: `GET /api/vsb-allocation/charts/{name}` (administrator only) serves the original seating-chart images for review.
* New blocking flags: `hall_label_variant`, `source_not_official`. New warning flag: `seating_chart_missing`.
* Changed: records flagged `duplicate_seat`, `hall_mismatch` or `provenance_mismatch` can no longer be approved by
  acknowledging the flag. The value must be corrected first, with a reason, and the correction is audited.
* New: per-record provenance from the mirror's own database (`original_portal/(operator-supplied)/allocation_provenance.json`),
  including the true hall-list and seat-sheet pages. The importer also detects a real hall conflict in the source
  (register 992696352264).
* Fixed: a deeply nested upload returned HTTP 500; it now returns 422.
* Fixed: an earlier draft created a placeholder batch to hold conflicts. Conflicts are now reported only.
* Changed: a student's VSB lookup shows the source document link when a batch has no linked PDF version.
* Admin page: an import panel (dry run, then stage) and an original-chart link on each record.
* Data: the original `allotments.json` (`original_portal/(operator-supplied)/source/`), the provenance file, and the 135 referenced
  seating-chart PNGs in `original_portal/(operator-supplied)/seating_charts/` (about 14 MB).
* Not changed: the existing student portal, its routes, authentication, roles, migrations and PDF workflow.

## Release round: disclosure, outbox, hall-label review, Windows instructions

* **Fixed (information disclosure):** the public classic lookup no longer returns a `pending_unpublished` count, and the
  portal no longer says that a seat is allotted but unpublished. Before this change, any visitor who entered a register
  number learned that an unpublished allotment existed and how many. Published results are unchanged. Regression tests:
  `backend/tests/test_portal_disclosure.py`. Existing portal tests were updated to assert the field is absent.
* **Fixed (approval bypass):** a correction that moved a record onto a seat another record in the same batch already held
  could be approved. Approval now refuses any live seat clash, regardless of stored flags, edits or acknowledgement. An edit
  that creates a clash marks both records `duplicate_seat`. Regression test:
  `test_a_correction_cannot_create_a_seat_collision_that_is_then_approved`.
* **New:** `MAIL_OUTBOX_DIR` sets the development/test outbox folder. A blank value keeps `backend/outbox`. A relative path is
  taken from the backend folder. An unusable value is reported by `check-config` and fails each delivery attempt; it is
  never silently replaced by the default folder. Production never shows a folder path. Tests: `test_mail_outbox_config.py`.
* **New:** hall-label variant review report: `docs/HALL_LABEL_VARIANT_REVIEW.md` and the operator-supplied hall-label review CSV
  (2,099 rows, all UNVERIFIED), generated by `backend/scripts/report_hall_label_variants.py`. Nothing is merged or approved.
* **Fixed:** `backend/run_test.bat` used a hard-coded developer folder. It now uses the folder of the script.
* **Documentation:** `WINDOWS_INSTALLATION.md` now gives exact Windows 10 steps and a checklist for you to record results.
  It states clearly that Windows execution has NOT been verified. `TEST_REPORT.md` now states the real skip reasons.

