# Phase 8.2 — Backup, restore, import/export and data integrity

Phase 8.2 adds administrator-only data-management APIs and offline restore tooling. It does not change the database schema and adds no migration.

## Backup contents and verification

A backup is a ZIP archive in `backend/backups/` containing:

- `database.sqlite3` created with SQLite's online backup API, or `database.dump` created with PostgreSQL `pg_dump --format=custom`;
- uploaded documents copied under `uploads/`;
- `manifest.json` with format version, database type, creation time and SHA-256 hashes for every payload file.

The archive is checked for ZIP CRC errors, duplicate/unsafe paths and manifest checksum mismatches before it is reported as verified. On POSIX systems, the archive is created with owner-only file permissions. Backups contain sensitive student and examination information: restrict access to the backend folder and encrypt off-device copies using an institution-approved method.

### Create and list backups (Windows)

```bat
cd backend
python -m app.cli backup
python -m app.cli backup-list
```

PostgreSQL backups require `pg_dump` from the PostgreSQL client tools to be installed and available on `PATH`. The configured database password is passed through the child process environment, not embedded in the command line. SQLite backups require no external executable.

### Restore (offline only)

**Stop the web application and every worker before restoring.** Restore is intentionally a CLI operation, not an HTTP endpoint, because a live multi-worker server may hold open database sessions.

```bat
cd backend
python -m app.cli backup-list
python -m app.cli restore-backup exam-monitor-backup-YYYYMMDDTHHMMSSffffffZ.zip --confirm-restore
```

The restore command validates the archive and checks that its database type matches the configured database. It creates a fresh safety backup of the current database and uploads before replacement. SQLite payloads pass `PRAGMA quick_check` and are staged before an atomic file replacement. PostgreSQL restore requires `pg_restore`; it uses `--clean --if-exists --no-owner --no-acl` against the configured database. If PostgreSQL restore fails, retain the safety backup and inspect the `pg_restore` error before retrying.

The restore merges archived upload files into the configured upload directory; it does not delete files that were added after the backup. This avoids accidental removal of unrelated/newer documents. Validate document availability and run `python -m app.cli db-audit` after restore.

## Scheduled backups and retention

Scheduled backups are disabled by default. Set these values in `backend/.env`:

```dotenv
BACKUP_SCHEDULE_ENABLED=true
BACKUP_INTERVAL_HOURS=24
BACKUP_RETENTION_COUNT=14
```

When the existing application scheduler is enabled, it checks the configured interval during its normal cycle and creates a verified backup when due. The retention policy deletes only older archives that pass verification; corrupt archives are retained for investigation. `BACKUP_RETENTION_COUNT=0` disables pruning. Scheduled backups require the same `pg_dump` availability for PostgreSQL as manual backups.

## Export

Administrator-only endpoints:

- `GET /api/admin/data/export/students?format=csv|xlsx|json|pdf`
- `GET /api/admin/data/export/exams?format=...`
- `GET /api/admin/data/export/results?format=...`
- `GET /api/admin/data/export/allotments?format=...`

Exports are capped at 10,000 rows per request. They omit credentials, password hashes, access tokens and security-session data. Spreadsheet exports neutralize formula-leading text cells. CSV is UTF-8 with a BOM for common spreadsheet compatibility. XLSX requires `openpyxl`; PDF requires `reportlab`.

## Student import

`POST /api/admin/data/import/students?mode=preview` accepts CSV, XLSX or JSON (10 MB maximum, 10,000 rows maximum). The required fields are `register_number`, `full_name`, `department` and `year`; `email` and `course` are optional. The preview reports row-level errors and duplicate register numbers without writing data.

After reviewing and correcting the source file, upload the same corrected file with:

`POST /api/admin/data/import/students?mode=commit&confirm=true`

Commit revalidates against current database contents and inserts the batch in one transaction. Any validation or uniqueness conflict rejects the whole batch. Rejected rows are never silently discarded. The import action is written to the audit log.

## Data integrity report

`GET /api/admin/data/integrity` is read-only. It checks duplicate register numbers, duplicate student-account links, orphan allocations/results/student-account links, invalid result marks, blank hall/seat values, duplicate seats within an exam, invalid exam dates/times, overlapping exams assigned to the same student, and SQLite foreign-key violations. It does not repair or delete records automatically. PostgreSQL foreign keys are enforced by the database; the report notes that the SQLite `PRAGMA foreign_key_check` is SQLite-specific.

## API authorization and limitations

All `/api/admin/data/*` endpoints require the administrator role (super-admin inherits administrator permissions through the existing role policy). Restore is not exposed over HTTP. Automatic backup scheduling runs in the existing scheduler process; deployments with multiple independent API worker processes should use one designated scheduler/worker to avoid redundant interval checks. PostgreSQL restore/backup requires the PostgreSQL client executables. Off-site encryption and external backup replication remain deployment responsibilities.
