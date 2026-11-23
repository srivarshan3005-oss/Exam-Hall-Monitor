# Configuration guide

All local secrets and runtime settings belong in `backend/.env`; never commit it. `install.bat` creates it from `.env.example` with a fresh random `SECRET_KEY` if it does not already exist. Existing settings are not overwritten.

Important settings include:

- `SECRET_KEY`: required, randomly generated, minimum 32 characters; do not share it.
- `DATABASE_URL`: defaults to local SQLite. `postgresql://user:pw@host/db` selects PostgreSQL (needs `requirements-postgres.txt`).
- Database tuning (Phase 8.1, all optional): `SQLITE_BUSY_TIMEOUT_MS` (15000), `SQLITE_WAL` (true), `MIGRATION_SNAPSHOT` (true; copy a SQLite file before upgrading it), `DB_POOL_SIZE` (5), `DB_MAX_OVERFLOW` (10), `DB_POOL_TIMEOUT_SECONDS` (30), `DB_POOL_RECYCLE_SECONDS` (1800), `DB_STATEMENT_TIMEOUT_MS` (0 = none; PostgreSQL). See [DATABASE.md](DATABASE.md).
- `ENVIRONMENT`: use `production` only with an appropriately secured deployment configuration.
- `COLLEGE_NAME`: displayed institutional label; use only a name you are authorized to display.
- `CORS_ORIGINS`: comma-separated exact allowed origins.
- `ENABLE_DOCS`: controls interactive API documentation.
- `PUBLIC_SHOW_NAMES`: defaults false; public names should remain disabled unless institutionally approved.
- `PUBLIC_RESULTS_ENABLED`: defaults false; marks are otherwise protected by authentication.
- `SEED_DEMO`: synthetic demo data only; prohibited in production.

Do not put API secrets or passwords in source files, screenshots, issue reports or public repositories.

## Phase 8.2 backup settings

Optional settings in `backend/.env`:

- `BACKUP_SCHEDULE_ENABLED=false` — enable scheduled verified backups in the existing scheduler.
- `BACKUP_INTERVAL_HOURS=24` — minimum interval between automatic backups.
- `BACKUP_RETENTION_COUNT=14` — number of newest verified archives to retain; `0` disables pruning.

Scheduled backups are disabled by default. PostgreSQL backups require `pg_dump` and restores require `pg_restore` on `PATH`.
