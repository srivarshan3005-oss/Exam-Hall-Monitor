# Upgrading from the 0.1.0 starter

1. Back up `backend/exam_monitor.db` (copy the file) if it holds anything you care about. It should only contain demo data.
2. Replace the project files with this release, keep your old DB file in `backend/`.
3. `setup_windows.bat` (creates `.env` with a new `SECRET_KEY` and runs the migrations).
   `python -m app.cli migrate` detects a database created by 0.1.0 (tables but no `alembic_version`), marks it as
   revision `0001` (the exact 0.1.0 schema — verified by an automated test) and then upgrades it to the latest revision.
4. Create an administrator: `python -m app.cli create-admin --username admin`.

**If migration fails with a UNIQUE constraint error:** 0.1.0 allowed duplicate results for the same student+exam.
Delete the duplicates (keep one row) and run `migrate` again. A test (`test_duplicate_results_in_legacy_data_block_migration_loudly`)
confirms this failure is loud rather than silent.

## The old demo admin account
A database created by 0.1.0 still contains `admin / ChangeMe123!`. The app **refuses to start** while any active account still has that
password. Fix it once (this was tested against the database from your original ZIP):

```bat
backend\.venv\Scripts\python -m app.cli reset-password admin
```
It asks for a new password (12+ characters, letters and digits) and signs out every old session.

## Old demo students
The 0.1.0 demo students `922525106` and `922525107` are 9-digit prefixes, not real 12-digit register numbers. They stay in an upgraded DB
(and still work for lookup). New synthetic data uses `9900…` numbers (`python -m app.cli seed-demo`); delete the old rows or the whole DB if you do not want them.

Simplest path for demo-only data: delete `backend/exam_monitor.db` and run `setup_windows.bat`.


## Expanded Phase 2 migrations

The expanded checkpoint adds revisions `0003` (announcements) and `0004` (normalized building/block/floor hierarchy, hall references and hall seat inventory). Back up the database before upgrading, then run `python -m app.cli migrate` from `backend`. Existing hall labels and existing allotment rows are retained; the new hierarchy references are nullable so existing rows are not silently rewritten. New halls are unverified until an administrator verifies them.
