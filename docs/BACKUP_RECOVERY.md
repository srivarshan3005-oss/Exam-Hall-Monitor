# Backup and recovery

Phase 8.2 provides verified database + uploaded-document ZIP backups with a SHA-256 manifest. See [`archive/PHASE82_DATA_MANAGEMENT.md`](archive/PHASE82_DATA_MANAGEMENT.md) for the full workflow and PostgreSQL requirements.

## Windows quick commands

- `backup.bat` — create and verify a backup.
- `backup_list.bat` — list backups and verify their manifests/checksums.
- `restore_backup.bat` — restore a selected backup. Stop the app and all workers first; the script requires an explicit `RESTORE` confirmation and the CLI creates a safety backup before replacement.

Equivalent CLI commands from `backend\`:

```bat
python -m app.cli backup
python -m app.cli backup-list
python -m app.cli restore-backup exam-monitor-backup-YYYYMMDDTHHMMSSffffffZ.zip --confirm-restore
python -m app.cli db-audit
```

SQLite uses the online backup API and validates the staged database before replacement. PostgreSQL uses `pg_dump` and `pg_restore`; install PostgreSQL client tools (the supplied Docker image does not include them, so `BACKUP_SCHEDULE_ENABLED` is `false` by default in `docker-compose.yml`; the client major version must match the server, 16) and verify a restore in a separate environment before relying on it. Never overwrite the only backup. Store off-device copies in an access-controlled, institution-approved encrypted location.
