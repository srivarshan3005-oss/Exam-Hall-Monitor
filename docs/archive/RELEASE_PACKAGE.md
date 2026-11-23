# Phase 12 — final release package (corrected: FINAL_RELEASE_FIXED)

This is the corrected package. See [RELEASE_FIXES.md](RELEASE_FIXES.md) for what changed relative to `Exam_Monitor_Ultimate_FINAL_RELEASE.zip`.

This folder is the source release package for Exam Monitor Ultimate. It preserves the existing Phase 1–11 application, migrations,
Android source, deployment files, operational scripts, and historical documentation.

## Choose an installation path

- **Windows workstation / local network:** start with [Windows installation](../WINDOWS_INSTALLATION.md), then use
  [Windows user guide](../WINDOWS_USER_GUIDE.md).
- **Docker + PostgreSQL production deployment:** follow [production deployment](../PRODUCTION_DEPLOYMENT.md) and [Docker guide](../DOCKER.md).
- **Android client:** follow [Android release and setup notes](../../android/README.md). Android source is included; no APK/AAB is bundled.
- **Extracting the ZIP on Linux/macOS:** `android/gradlew` and `android/build_debug.sh` carry the executable bit in the archive; extraction with `unzip` preserves it. If a tool dropped it, run `chmod +x android/gradlew android/build_debug.sh`.

## Release configuration checklist

Before a real deployment, an operator must:

1. Set a unique, high-entropy `SECRET_KEY` and strong `POSTGRES_PASSWORD` in a protected copy of
   `backend/.env.production.example` named `backend/.env.production`.
2. Set the institution name and `DOMAIN_NAME` (host name only). Compose derives `PUBLIC_BASE_URL`, `CORS_ORIGINS` and the Nginx `server_name` from it.
3. Place the matching `fullchain.pem` and `privkey.pem` in `deploy/certs/` (no Nginx edit is needed; `deploy/nginx.conf.template` is rendered from `DOMAIN_NAME`). Private keys must remain protected and must never be committed.
4. Keep `SEED_DEMO=false`, `ENABLE_DOCS=false`, and public visibility settings aligned with institutional policy.
5. Configure SMTP only through protected secret management if activation/reset/notification email is required.
6. Configure Android `API_BASE_URL` to the production HTTPS endpoint. To produce a signed release, provide **all four** of
   `RELEASE_STORE_FILE` (absolute path to a keystore kept outside this tree), `RELEASE_STORE_PASSWORD`, `RELEASE_KEY_ALIAS` and
   `RELEASE_KEY_PASSWORD` as Gradle properties or environment variables. With none set, the release artifact is unsigned; with only some set,
   a release task fails with a message naming the missing values. Do not add the keystore or passwords to this tree.

The example environment files contain placeholders, not usable production credentials. The package does not contain real secrets,
TLS private keys, production data, database dumps, built APKs, or AABs.

## PostgreSQL schema initialization and upgrades

For a new Docker deployment, configure the environment first, then run the `check-config` and `migrate` steps from the [Docker guide](../DOCKER.md)
**before** `up -d`: application start-up does *not* migrate; it refuses to start on a database that is not at the current revision.
For manual operations from the backend environment, install
`requirements-postgres.txt`, set `DATABASE_URL`, and run:

```bash
python -m app.cli check-config
python -m app.cli migrate
python -m app.cli db-audit
```

For an existing database, take and retain a recoverable backup before upgrading. Use only `python -m app.cli migrate` (or the
provided Windows startup flow); do not invoke raw Alembic commands. See [migration runbook](../MIGRATIONS.md) and
[backup/recovery](../BACKUP_RECOVERY.md). Migrations are additive and the application intentionally refuses ambiguous PostgreSQL
schemas without migration history.

## Windows launch scripts

- `install.bat` / `setup_windows.bat`: install dependencies, initialize local configuration, apply migrations, and create the first admin.
- `start.bat` / `run_windows.bat`: start the managed local server and wait for its readiness endpoint.
- `stop.bat`: stop the managed server.
- `backup.bat`, `backup_list.bat`, `restore_backup.bat`: database backup and recovery helpers.

The Windows local launcher binds to loopback (`127.0.0.1`). It is not a Windows service and is not intended to be exposed directly
to the public internet.

## Package contents and boundaries

- Backend, frontend/static assets, migrations, and all existing feature modules are retained.
- Android Kotlin source, Gradle wrapper, manifests, and release build configuration are retained.
- Docker Compose, PostgreSQL service definition, backend image definition, and Nginx reverse-proxy configuration are included.
- Documentation includes administrator/student guides, installation and deployment guides, database/migration guidance, security,
  backup/recovery, architecture, and phase-specific implementation notes.
- The SQLite file under `backend/tests/fixtures/` is a historical migration test fixture, not a runtime database. It is retained
  because migration compatibility tests use it.
- No build, test, audit, deployment, or runtime verification is claimed for this packaging phase.
