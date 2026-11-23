# Database migrations: rules, failure handling and recovery (Phase 8.1)

This page is the runbook for upgrading the database and for what to do when an upgrade goes wrong. Architecture and schema details: [DATABASE.md](DATABASE.md). Backup and restore tooling is a separate topic (not part of Phase 8.1): [BACKUP_RECOVERY.md](BACKUP_RECOVERY.md).

## Rules
1. **Released migrations (0001-0009) are history and are never edited.** the test `test_released_migrations_are_byte_for_byte_unchanged` in `backend/tests/test_phase8_database.py` pins their SHA-256, and a second test replays them and compares the result with a database file written by the released Phase 7.1 build. Every change is a **new** revision (the next is 0013; 0012 added the VSB source tables), chained to the previous head.
2. Revisions must be written to work on **both** SQLite and PostgreSQL (portable boolean defaults, no SQLite-only SQL), idempotent where practical, and must not delete or rewrite user data.
3. Always use `python -m app.cli migrate` (or the Windows start scripts, which call it). It adds the safety measures below that plain `alembic upgrade` does not.

## What `migrate` does
* Takes a lock so only one process migrates at a time (PostgreSQL advisory lock; for SQLite a `<db>.migrate.lock` file next to the database). A second process waits and then finds the database current. Safe to run twice.
* SQLite: copies an existing database file to `exam_monitor.db.pre-migration-<from>-to-<to>-<UTC time>.bak` **before** upgrading (SQLite online-backup API, consistent even if the file is in use). A brand-new database gets no copy. `MIGRATION_SNAPSHOT=false` turns this off.
* Runs each revision in its own transaction (DDL and the version stamp commit together). If revision N fails, revisions before N stay applied, N is rolled back completely, and the database is at the last good revision. This is tested on both engines with a deliberately failing revision.
* A legacy 0.1.0 database (tables, no version table) is stamped as the baseline first, then upgraded; it is copied first too.
* PostgreSQL: an **empty** database is initialised at the head revision in one transaction (why: DATABASE.md section 6). A database that already has migration history is upgraded normally.

`python -m app.cli db-audit` is read-only and can be run any time (exit code 0 = fine, 1 = needs attention).

## Before an upgrade (checklist)
1. Stop the application. 2. SQLite: `backup.bat` (or copy `exam_monitor.db` together with any `-wal`/`-shm` files while stopped). PostgreSQL: `pg_dump -Fc`. 3. `python -m app.cli db-audit` to see the starting point. 4. `python -m app.cli migrate`. 5. `python -m app.cli db-audit` again; it must print `Database schema OK`.

## When something goes wrong
| Symptom | Meaning | What to do |
|---|---|---|
| `Database schema is at revision X but the application needs Y` | Code is newer than the database. Nothing is wrong with the data. | `python -m app.cli migrate`. |
| A revision raises an error during `migrate` | That revision was rolled back; the database is at the last good revision and still works with the *old* code. | Read the first error line, fix the cause (disk space, permissions, a data problem it names), run `migrate` again. If you cannot fix it, stay on the old version or restore (below). Do not edit the version table by hand. |
| `Timed out waiting for another process to finish migrating` | Another migration really is running, or a crashed one left its lock. | Wait. If no migration is running (check the process list), stop the application, delete `<db>.migrate.lock` and retry. On PostgreSQL a crashed process releases its advisory lock automatically. |
| Warning `0010: N row(s) in <table> violate <constraint>; constraint NOT added` or `students [...] are linked to more than one user account` | Old data breaks a rule the application now enforces. The migration succeeded; **no data was changed**; only that one constraint was skipped. | Section "Skipped constraints" below. |
| `This PostgreSQL database has no migration history ...` (raw alembic) | You ran `alembic upgrade` on an empty PostgreSQL database. Nothing was created. | Run `python -m app.cli migrate` instead. |
| `This PostgreSQL database contains tables but no migration history` | Someone created tables without Alembic. The tool refuses to guess and changes nothing. | Restore a backup taken before that happened, or ask for help; do not stamp it by hand. |
| SQLite: power cut or crash during an upgrade | The in-flight revision is rolled back by SQLite on the next open. | `PRAGMA integrity_check;` (must say `ok`), then run `migrate` again. If it does not say `ok`, restore the `.bak` file. |

### Restoring a SQLite database from the automatic safety copy
1. Stop the application. 2. Rename the current `exam_monitor.db` (keep it, do not delete) and delete stale `exam_monitor.db-wal` / `-shm` files. 3. Copy `exam_monitor.db.pre-migration-...bak` to `exam_monitor.db`. 4. Start the **previous** version of the application (the database is at the older revision), or fix the problem and run `migrate` again. Everything entered after the copy was taken is not in the copy.

### Skipped constraints (data that breaks a rule)
1. `python -m app.cli db-audit` lists the constraints that are missing and how many rows break each. 2. Find the rows (run in `sqlite3 exam_monitor.db` or `psql`):
```
SELECT student_id, COUNT(*) FROM users WHERE student_id IS NOT NULL GROUP BY student_id HAVING COUNT(*) > 1;   -- two accounts, one student
SELECT id, username, role   FROM users   WHERE role   NOT IN ('super_admin','admin','staff','invigilator','student');
SELECT id, username, status FROM users   WHERE status NOT IN ('active','pending','suspended');
SELECT id, title, status    FROM exams   WHERE status NOT IN ('draft','published','completed');
SELECT id, student_id, exam_id, marks, max_marks FROM results WHERE NOT (marks >= 0 AND max_marks > 0 AND marks <= max_marks);
SELECT id, hall, seat FROM allotments WHERE length(trim(hall)) = 0 OR length(trim(seat)) = 0;
```
3. Correct those rows through the application (or carefully in SQL after a backup): decide which of two accounts keeps the student link, set a valid role/status, correct the marks. 4. Re-apply the skipped constraints: stop the application, then `python -m alembic downgrade 0009` followed by `python -m app.cli migrate` (revision 0010 is idempotent and now finds clean data; this exact sequence is tested on both engines and changes no row). 5. `python -m app.cli db-audit` must print `Database schema OK`.

### Undoing the latest upgrade (0010)
Revision 0010 is reversible and removes only what it added: `python -m alembic downgrade 0009` (tested on both engines; data unchanged). Reverting further than that, or on PostgreSQL below 0009, is not supported: restore the backup instead.

### Migration 0015: verification status and the legacy-record audit (fail closed)
Renames `HALL_LIST_ONLY` to `HALL_LIST_CONFIRMED`, widens `vsb_alloc_records.verification_status`, and records an audit
row for each legacy record that was published before verification statuses existed (`review_status='approved'`,
`published`, `UNRESOLVED`). No record is deleted or upgraded, and those records stay hidden from students until an
administrator verifies them.

The audit write has no error suppression. If it fails, the migration stops and Alembic rolls back the whole revision,
so the database stays at `0014`. If legacy records exist and the `audit_logs` table is missing or lacks required
columns, the migration refuses to start, again leaving the database at `0014`. Re-running after a downgrade never
duplicates an audit row. Regression tests: `backend/tests/test_phase8_database.py` (the `migration_0015` cases), which
run on SQLite and PostgreSQL.

## Running the database tests
From `backend` with the dev requirements installed: `python -m pytest tests/test_phase8_database.py` (SQLite). To include PostgreSQL create a role that may `CREATE DATABASE`, then set `TEST_POSTGRES_URL=postgresql://role:pw@host/postgres` (scratch databases are created and dropped automatically); set `TEST_DATABASE_URL=postgresql://role:pw@host/emptydb` as well to run the **entire** suite on PostgreSQL. Without PostgreSQL the PostgreSQL cases are reported as *skipped*, never as passed.
