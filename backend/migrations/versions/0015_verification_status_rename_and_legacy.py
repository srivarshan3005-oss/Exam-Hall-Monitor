"""Rename HALL_LIST_ONLY -> HALL_LIST_CONFIRMED, widen the column, and record the legacy-record policy.

Revision ID: 0015
Revises: 0014

Data-preserving: no row is deleted and no record is upgraded.
  * HALL_LIST_ONLY rows become HALL_LIST_CONFIRMED (same meaning, official name).
  * UNRESOLVED rows stay UNRESOLVED. Records that were approved/published before verification statuses existed
    keep their approval and publication history, but the public lookup now hides them (see app/vsb_alloc/visibility.py)
    until an administrator verifies them through the authorised workflow.
  * An audit row is written for each legacy record that is published but not FULLY_VERIFIED/HALL_LIST_CONFIRMED.

Failure policy (fail closed):
  * The audit write is NOT wrapped in a try/except. Any failure raises, and Alembic's per-migration transaction
    rolls back the status rename, the constraint change and the version stamp together. The database stays at 0014.
  * If legacy records exist but the audit table cannot take the rows, the migration refuses to run rather than
    silently continuing without its audit trail.
  * After writing, the migration re-reads the audit table and checks that every legacy record has exactly one
    audit row. A mismatch raises.
  * Re-running the migration (for example after a downgrade) never duplicates an audit row.
"""
import json
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

AUDIT_ACTOR = "migration-0015"
AUDIT_ACTION = "vsb_alloc.legacy_unresolved_hidden"
AUDIT_COLUMNS = {"actor", "action", "target", "details", "created_at"}

_NEW = "verification_status IN ('FULLY_VERIFIED', 'HALL_LIST_CONFIRMED', 'UNRESOLVED')"
_OLD = "verification_status IN ('FULLY_VERIFIED', 'HALL_LIST_ONLY', 'UNRESOLVED')"


def _check_constraint_names(bind):
    # No broad except here: if the database cannot describe its constraints, the migration must stop.
    return {c.get("name") for c in sa.inspect(bind).get_check_constraints("vsb_alloc_records")}


def _legacy_record_ids(bind):
    rows = bind.execute(sa.text(
        "SELECT id FROM vsb_alloc_records "
        "WHERE published IS TRUE AND review_status = 'approved' AND verification_status = 'UNRESOLVED' "
        "ORDER BY id")).fetchall()
    return [int(r[0]) for r in rows]


def _audit_table_is_usable(bind):
    inspector = sa.inspect(bind)
    if "audit_logs" not in set(inspector.get_table_names()):
        return False
    return AUDIT_COLUMNS <= {c["name"] for c in inspector.get_columns("audit_logs")}


def _audited_targets(bind):
    rows = bind.execute(sa.text("SELECT target FROM audit_logs WHERE action = :a"),
                        {"a": AUDIT_ACTION}).fetchall()
    return {str(r[0]) for r in rows}


def _write_legacy_audit_rows(bind, legacy_ids):
    if not legacy_ids:
        return
    already = _audited_targets(bind)
    now = datetime.now(timezone.utc).isoformat()
    for rid in legacy_ids:
        target = str(rid)
        if target in already:
            continue                      # idempotent: never a second row for the same record
        # Deliberately no try/except. A failure here must abort the whole migration.
        bind.execute(
            sa.text("INSERT INTO audit_logs (actor, action, target, details, created_at) "
                    "VALUES (:actor, :action, :target, :details, :created_at)"),
            {"actor": AUDIT_ACTOR, "action": AUDIT_ACTION, "target": target,
             "details": json.dumps({"policy": "hidden from students until verified; history preserved"}),
             "created_at": now})
    recorded = _audited_targets(bind)
    missing = [str(rid) for rid in legacy_ids if str(rid) not in recorded]
    if missing:
        raise RuntimeError(f"Migration 0015: audit rows missing for {len(missing)} legacy record(s); "
                           f"migration aborted and rolled back.")


def upgrade():
    bind = op.get_bind()
    if "vsb_alloc_records" not in set(sa.inspect(bind).get_table_names()):
        return
    # Decide everything that can fail BEFORE changing the schema, so a refusal leaves the database untouched.
    legacy_ids = _legacy_record_ids(bind)
    if legacy_ids and not _audit_table_is_usable(bind):
        raise RuntimeError(
            "Migration 0015 found published records that were never verified, but the audit_logs table is missing "
            "or incomplete, so their audit trail cannot be recorded. Migration stopped and the database was left at "
            "revision 0014. Restore audit_logs, then run `python -m app.cli migrate` again.")

    had = "ck_vsb_alloc_records_verif" in _check_constraint_names(bind)
    with op.batch_alter_table("vsb_alloc_records") as b:
        if had:
            b.drop_constraint("ck_vsb_alloc_records_verif", type_="check")
        b.alter_column("verification_status", existing_type=sa.String(16), type_=sa.String(24),
                       existing_nullable=False, existing_server_default="UNRESOLVED")
    bind.execute(sa.text(
        "UPDATE vsb_alloc_records SET verification_status='HALL_LIST_CONFIRMED' "
        "WHERE verification_status='HALL_LIST_ONLY'"))
    with op.batch_alter_table("vsb_alloc_records") as b:
        b.create_check_constraint("ck_vsb_alloc_records_verif", _NEW)

    _write_legacy_audit_rows(bind, legacy_ids)


def downgrade():
    bind = op.get_bind()
    if "vsb_alloc_records" not in set(sa.inspect(bind).get_table_names()):
        return
    if "ck_vsb_alloc_records_verif" in _check_constraint_names(bind):
        with op.batch_alter_table("vsb_alloc_records") as b:
            b.drop_constraint("ck_vsb_alloc_records_verif", type_="check")
    bind.execute(sa.text(
        "UPDATE vsb_alloc_records SET verification_status='HALL_LIST_ONLY' "
        "WHERE verification_status='HALL_LIST_CONFIRMED'"))
    with op.batch_alter_table("vsb_alloc_records") as b:
        b.create_check_constraint("ck_vsb_alloc_records_verif", _OLD)
    # Column width stays 24 on downgrade (a wider column is harmless and avoids truncating data).
    # Audit rows are append-only history and are intentionally not deleted on downgrade.
