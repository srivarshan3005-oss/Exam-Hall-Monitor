# Database architecture and schema audit (Phase 8.1)

The backend uses SQLAlchemy 2.x and Alembic. **SQLite** (a single file, `backend/exam_monitor.db`) is the default and is what the Windows scripts use. **PostgreSQL** is supported for larger or shared deployments. Run `python -m app.cli migrate` from `backend` to bring the database to the current revision; startup refuses to serve requests if the revision is behind. Never delete the database to get past a migration error: read [MIGRATIONS.md](MIGRATIONS.md). Backups are a separate topic: [BACKUP_RECOVERY.md](BACKUP_RECOVERY.md).

## 1. Engine support (what was actually tested)
| | SQLite | PostgreSQL |
|---|---|---|
| Status | Default, used by `start.bat`. | Supported; **tested** on PostgreSQL 16.15 with psycopg 3.3.9 (SQLAlchemy 2.0.57, Alembic 1.20.1). Other versions are untested. |
| Install | included | `pip install -r requirements-postgres.txt`, create an **empty** database, set `DATABASE_URL=postgresql://user:pw@host:5432/db` (also accepted: `postgres://`, `postgresql+psycopg://`). |
| New database | released revisions 0001-0010 run in order | the current schema is created and stamped at revision 0010 in one transaction (section 6) |
| Existing database | ordered upgrade, atomic per revision, safety copy first | ordered upgrade from the revision it is at |
| Test evidence | the whole backend suite (536 tests) | the whole backend suite (536 tests) run against PostgreSQL, plus the PostgreSQL-only cases in `tests/test_phase8_database.py` |

Phase 8.1 found that the released SQLite-era migrations 0007 and 0009 **cannot run on PostgreSQL** (integer boolean defaults, `WHERE active = 1`), that no PostgreSQL driver was listed in any requirements file, and that admin search was case-sensitive on PostgreSQL (SQLite's `LIKE` is not). All three are fixed; released migration files were deliberately **not** edited.

## 2. Connection configuration (`app/database.py`)
* **SQLite:** `foreign_keys=ON`, WAL journal (readers never block the writer; not used for `:memory:`), `busy_timeout` 15 s (a writer waits for the write lock instead of failing), `synchronous=NORMAL`. Settings: `SQLITE_BUSY_TIMEOUT_MS`, `SQLITE_WAL`. Do not put a WAL-mode database on a network share; keep it on a local disk.
* **PostgreSQL:** pooled connections (`DB_POOL_SIZE` 5, `DB_MAX_OVERFLOW` 10, `DB_POOL_TIMEOUT_SECONDS` 30, `DB_POOL_RECYCLE_SECONDS` 1800), `pool_pre_ping`, session time zone forced to UTC, optional `DB_STATEMENT_TIMEOUT_MS`.
* **Transactions:** one session per request (`get_db`), rolled back on any error and always closed. `session_scope()` (commit on success, roll back on error) is for scripts and background jobs. Each request that changes data commits once, so a failed request leaves nothing behind.

## 3. Schema inventory (40 tables, verified from a freshly migrated database)
46 foreign keys (27 `ON DELETE CASCADE`, 12 `SET NULL`, 7 `RESTRICT`), 24 unique constraints, 26 CHECK constraints, 63 indexes. Every table has a primary key; **every foreign-key column is now backed by an index** (enforced by a test).

Groups: accounts and security (`users`, `auth_sessions`, `password_tokens`, `security_events`, `audit_logs`); people and exams (`students`, `subjects`, `academic_years`, `exam_terms`, `exams`, `exam_eligibility_rules`, `exam_student_overrides`); halls (`buildings`, `blocks`, `floors`, `halls`, `hall_seats`); allocation (`allotments`, `allotment_history`, `allocation_plans`); results (`results`); communication (`announcements`, `notifications`, `notification_preferences`, `email_deliveries`, `email_templates`); document processing (`official_documents`, `document_versions`, `document_extractions`, `pdf_pages`, `timetable_entries`, `extraction_edits`, `document_events`, `register_entries`, `exam_sessions`, `sheet_subjects`, `seating_sheets`, `seating_entries`, `seat_positions`, `review_issues`).

Key business constraints (all enforced by the database, not only by the API): one allotment per student per exam; one student per seat per exam; one result per student per exam; one notification per user per event key; one login account per student record; usernames and register numbers unique.

### Phase 8.1 schema changes (migration 0010, additive, no row is touched)
* Indexes on 8 foreign-key columns that had none: `official_documents.term_id`, `register_entries.session_id`, `review_issues.entry_id` and `.page_id`, `seat_positions.entry_id`, `seating_sheets.hall_id`, `timetable_entries.subject_id` and `.imported_exam_id`.
* `users.student_id`: UNIQUE index `uq_users_student_id` (the activation flow already assumed one account per student; the administrator "create user" path now answers 409 instead of silently creating a second account).
* CHECK constraints for rules the application already enforced: `ck_users_role`, `ck_users_status`, `ck_exams_status`, `ck_results_marks_range` (`0 <= marks <= max_marks`, `max_marks > 0`), `ck_allotments_hall_seat_nonblank`.
* If an **existing** database already contains rows that would violate one of these, the migration does **not** fail and does **not** change data: it skips that single constraint (a non-unique index is created for duplicate student links), logs a warning, and `python -m app.cli db-audit` lists exactly what to fix. See [MIGRATIONS.md](MIGRATIONS.md).
* An allotment's `hall` and `seat` are stored in one canonical form (trimmed, upper-case) by the model, so `a12` and `A12` can no longer occupy the same seat. The API schemas already did this; the PDF-import path did not normalise seats itself, so every code path now goes through the model.

### Deliberate design decisions (reviewed, not changed)
* `allotment_history`, `email_deliveries` (and `allotments.plan_id`) deliberately have **no foreign key** so the audit trail survives deletion of the thing it describes.
* `exams` and `allotments` use `RESTRICT`: an exam or student that still has allotments or results cannot be deleted by accident.
* `exams.exam_date`, `start_time`, `end_time` are text in the institution's **local wall time** (they are schedule labels, not instants). Changing them to date/time columns would be a risky data rewrite and was left alone.
* Three columns declared `unique=True` (`halls.code`, `document_extractions.version_id`, `official_documents.source_url`) have no constraint name in SQLite databases, because the released migrations created them unnamed. Nothing may refer to them by name.

## 4. Seat allocation and concurrency
Seat uniqueness is guaranteed by unique constraints. The other rules ("a student may not sit two simultaneous exams", "a hall may not exceed its capacity", "no seat shared by simultaneous exams") are decided by *reading* first and *writing* afterwards, so two simultaneous requests could both pass the read. Phase 8.1 adds `lock_allocation()` (`app/dbutil.py`), called at the start of every operation that decides a seat (create, move, commit plan, legacy auto-allocate, seating import): on PostgreSQL a transaction-scoped advisory lock, on SQLite a write-lock-taking no-op `UPDATE`; both are released automatically at commit or rollback.

Measured (actual results in [archive/PHASE81_CONCURRENCY_RESULTS.txt](archive/PHASE81_CONCURRENCY_RESULTS.txt)): with the lock, every race scenario was correct in every repetition on both engines; with the lock deliberately disabled, capacity and clash rules were violated in most or all attempts (PostgreSQL 12 of 12 in each scenario). A race for the *same seat* was never violated even without the lock, because the unique constraint alone covers it.

## 5. Time stamps and time zones
Every instant is stored in UTC. The `UTCDateTime` column type (`app/dbtypes.py`) makes SQLite (which has no time-zone type and returns naive values) behave like PostgreSQL (`TIMESTAMPTZ`): application code always receives an **aware UTC** datetime, and a naive value written to the database is interpreted as UTC. No schema change; existing rows read exactly as before. `APP_TIMEZONE` only affects how times are shown and when reminders fire.

## 6. Migrations in one page (details: [MIGRATIONS.md](MIGRATIONS.md))
| Rev | Content |
|---|---|
| 0001-0009 | released history (baseline, security/hall finder, announcements, hall inventory, exam management and allocation, document processing, auth/RBAC, seating import, notifications and e-mail). **Immutable**: a test pins their SHA-256. |
| 0010 | Phase 8.1 schema hardening (above) |

* Each revision is atomic on both engines (its DDL and the version stamp commit together). A failure leaves the database at the last good revision.
* Only one process migrates at a time (PostgreSQL advisory lock / lock file next to the SQLite database); a second process waits, then finds the database current.
* SQLite: an existing database file is copied to `<name>.pre-migration-<from>-to-<to>-<UTC time>.bak` before it is upgraded.
* **PostgreSQL bootstrap:** the released revisions 0001-0009 were written for SQLite and cannot be replayed on PostgreSQL, so no PostgreSQL database can exist below 0010. An empty PostgreSQL database therefore gets the current schema and is stamped `0010` in one transaction (all or nothing); tables are verified equal to the SQLite chain by a test. A PostgreSQL database that has migration history is upgraded normally. One that has tables but no history is refused untouched. Running raw `alembic upgrade head` on an empty PostgreSQL database is refused with instructions; always use `python -m app.cli migrate`.

## 7. Auditing a database
`python -m app.cli db-audit` (read-only, exit code 1 on findings) reports the revision, drift between the database and the models, constraints that could not be added because of existing data, duplicate student/account links, and (SQLite) foreign-key violations.

## 8. Known limitations
* PostgreSQL databases have no history below 0010 (there are no PostgreSQL installations of earlier releases to preserve). Downgrading below 0009 on PostgreSQL is untested and unsupported; 0010 itself is reversible (tested).
* The pre-upgrade safety copy exists for SQLite only. For PostgreSQL take a `pg_dump` first.
* SQLite remains a single-writer database: writers queue (up to the busy timeout). That is fine for one college; use PostgreSQL for many simultaneous staff.
* Only PostgreSQL 16 was tested. No load testing was done.

## Earlier notes
Migration 0006 (Phase 3) is additive: `official_documents` + source_label, exam_name, term_id, uploaded_by, original_filename; `pdf_pages` + text_content, extraction_method, page_warning; new tables `document_extractions`, `timetable_entries`, `extraction_edits`, `document_events`. Existing hall text fields and legacy allotment records are retained for compatibility.

## Phase 8.3
See `archive/PHASE83_DATABASE_ADMIN.md` for the administrator database console, migration ledger, verified backup download, integrity reporting, import/export, and safe offline restore workflow. Apply new migrations with `python -m app.cli migrate` from `backend`.
