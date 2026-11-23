# Phase 8.3 — Database performance and administration

## Delivered in this checkpoint
- Additive Alembic revision `0011` adds guarded composite/query-path indexes. It checks table and column existence and does not modify rows.
- Administrator-only database administration page: engine/revision/table status, integrity report, migration ledger, verified backup listing, backup creation, verification and authenticated download, dataset export, and student import preview/commit.
- Read-only migration history endpoint (`GET /api/admin/data/migrations`).
- Backup verification endpoint (`GET /api/admin/data/backups/{filename}/verify`) and authenticated download endpoint (`.../download`). Both reject path traversal; download is allowed only after archive verification.
- Existing Phase 8.2 backup format, checksum manifest, SQLite online snapshot, PostgreSQL `pg_dump`, import validation, exports and integrity reporting are reused rather than replaced.
- Restore remains offline CLI-only by design. Replacing a live database over HTTP while workers hold connections is unsafe. Use the documented restore command during maintenance, then verify the schema and integrity.
- All database-management routes remain administrator protected. Existing backup creation audit records are retained. No secrets are exposed in the status response.

## Query and transaction notes
- The Phase 8.1 engine/session layer remains authoritative: SQLite WAL, foreign keys and busy timeout; PostgreSQL bounded pool, pre-ping and UTC session timezone; rollback-on-error session lifecycle.
- Revision 0011 adds indexes for student department/year, exam date/status, allotment and result lookup pairs, audit chronology, security-event chronology, and active-session lookup where the corresponding schema exists.
- Existing API pagination contracts are preserved. The import endpoint still requires a preview and explicit `confirm=true` commit.

## Apply
From `backend`:
`python -m app.cli migrate`
Then sign in as an administrator and open **Administration → Database**.

## Verification status
This delivery deliberately does not rerun previous tests, per request. New Phase 8.3 changes have been reviewed and packaged but are **not represented as test-verified**. Run focused migration/API/browser checks in a later authorized verification pass. PostgreSQL restore requires PostgreSQL client tools; Android source and Windows scripts are retained unchanged.
