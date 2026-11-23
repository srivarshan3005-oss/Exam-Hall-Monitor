# Release corrections — FINAL_RELEASE_FIXED

> **Historical record.** This document describes an earlier build. Its test counts and status statements are not the current verification status. For the current commands, results and limitations see `docs/VALIDATION_REPORT_v6.md` (or `VALIDATION_REPORT_v6.md` from the top-level folder).

Corrections applied directly to the existing `Exam_Monitor_Ultimate_FINAL_RELEASE` project. No module was replaced or recreated, no migration
(`0001`–`0011`) was edited, and no feature was removed.

**Not performed:** no tests, audits, Android/Gradle builds, Docker builds, Windows script runs, database migrations or deployments. Nothing below is claimed
as verified by execution. The changes were made by source inspection; a small set of static reference checks (Python relative-import resolution, `index.html`
asset references, Markdown relative links, migration `down_revision` chain, Android manifest/resource references) was run as part of the inspection and found no
broken references.

## Changes

### Android
- `android/app/build.gradle.kts`: the four `RELEASE_STORE_FILE`, `RELEASE_STORE_PASSWORD`, `RELEASE_KEY_ALIAS`, `RELEASE_KEY_PASSWORD` inputs (Gradle properties or
  environment variables) were read but never used. They now create a `release` signing configuration that is attached to the `release` build type when all four are present.
  A partially configured set, or a keystore path that does not exist, makes a release task fail with a message naming what is missing (values are never printed).
  With none set, the release artifact remains unsigned (unchanged behaviour). Debug and unit-test tasks are unaffected.
- `android/gradlew` (and `android/build_debug.sh`) carry the executable bit in the ZIP (they did not in the original archive).
- `android/README.md`, `docs/RELEASE_PACKAGE.md`, `PHASE12_PROGRESS_REPORT.md`: documentation corrected (the earlier report claimed signing was configured when it was not wired in).

### Windows
- All `.bat` files were LF-only (only `android/build_debug.bat` was CRLF). `cmd.exe` is unreliable with LF-only batch files that use labels and `goto` (`start.bat`).
  All batch files, including `android/gradlew.bat`, are now CRLF; `.gitattributes` keeps that (and LF for `gradlew` and `*.sh`) through Git checkouts.
- `test.bat`: `install.bat` installs runtime requirements only, so `pytest` was missing. `test.bat` now installs `requirements-dev.txt` on demand and returns pytest's exit code.

### Docker / Nginx / environment
- `docker-compose.yml`: the `/tmp` tmpfs was `mode=1770`, which the non-root `app` user (not in root's group) could not write to; now `1777`.
- `docker-compose.yml`, `backend/.env.production.example`: `BACKUP_SCHEDULE_ENABLED` defaulted to `true`, but PostgreSQL backups need `pg_dump` and the image does not contain it, so
  every scheduled run would fail. Default is now `false` (override in `backend/.env.production`).
- `backend/Dockerfile`: installs the `tesseract-ocr` binary, which `docs/OCR.md` lists as a separate requirement and which scanned-PDF OCR needs.
- *deploy/nginx.conf* (replaced by `deploy/nginx.conf.template` in this release): `listen 443 ssl http2;` (deprecated in the pinned nginx 1.27) replaced by `listen 443 ssl;` + `http2 on;`; `server_tokens off`; the ACME location is annotated
  (its webroot is not mounted unless you add it).
- `backend/.env.production.example`: clarified that Compose overrides the placeholder `DATABASE_URL` and that `POSTGRES_PASSWORD` should avoid URL-special characters.
- `.gitignore`: `*.sqlite3` would have excluded the synthetic migration fixture that `test_phase8_database.py` needs; an explicit exception was added.

### Documentation
- `docs/DOCKER.md`: now includes the mandatory `check-config` and `migrate` steps before `up -d` (start-up refuses an un-migrated database).
- `docs/RELEASE_PACKAGE.md`: removed the statement that application start-up runs the migration CLI (it does not).
- `README.md`: stale "v0.6.0 (Phase 5)" title, stale "413 tests" figure and the stale head-revision statement corrected; version identifiers and head revision (`0011`) stated.
- `docs/PRODUCTION_DEPLOYMENT.md`, `docs/BACKUP_RECOVERY.md`, `docs/OCR.md`, `docs/README.md`, `PHASE_PROGRESS.md`: updated to match the above.
- `RELEASE_MANIFEST_SHA256.txt`: regenerated for the final file set.

## Packaging exclusions (checked by file listing and a pattern search)
No `.env`/`.env.production`, keystores (`*.jks`, `*.keystore`), TLS keys/certificates, runtime databases, caches (`__pycache__`, `.pytest_cache`), `node_modules`, logs, backups,
uploads, APK/AAB or build outputs are in the archive.
**One deliberate exception:** `backend/tests/fixtures/phase71_release.sqlite3` is a synthetic historical migration fixture (placeholder accounts, "Student N" records, 1000-round test
password hashes) required by `test_upgrade_of_a_real_phase71_database_file`. It is not a runtime database. Delete it only if you also remove/skip that test.

## Remaining limitations
- Android signing wiring, the Gradle build, unit tests and lint have never been run (no Android SDK / Maven access was used); expect first-build fixes.
- The Windows scripts, Dockerfile (including the new apt step), Compose file and Nginx configuration have not been executed; TLS, PostgreSQL and production behaviour are unvalidated.
- PostgreSQL backup/restore inside the container still requires a `pg_dump`/`pg_restore` client of major version 16, which is not in the image; scheduled backups are off by default.
- The earlier fixed *deploy/nginx.conf* contained the placeholder host `exam.example.edu`; the release uses `deploy/nginx.conf.template`, and certificates must be supplied by the operator.
- The API still reports version `0.7.0` and the Android app `0.8.1`; no version unification was attempted (tests may assert these).
- Previous test reports under `docs/` are historical and say nothing about this package.
