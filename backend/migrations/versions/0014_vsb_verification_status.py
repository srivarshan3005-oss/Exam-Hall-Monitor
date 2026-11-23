"""Add verification_status column to vsb_alloc_records.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-17

Additive only: adds one nullable VARCHAR column with a server default.
No existing row, table or index is modified.

Verification status values (see doc_models.VSB_VERIF_STATUSES):
  FULLY_VERIFIED — both hall-list and seat-sheet PDFs confirmed for session (17 Nov 2026 AN: 627 records).
  HALL_LIST_ONLY — hall-list PDF confirmed; seat not independently verified (17 Nov FN + 18 Nov: 1,159 records).
  UNRESOLVED     — no official PDF confirmation available (16 Nov 2026: 1,520 records).

The column is set at import time by vsb_alloc/original_import.py based on exam_date and session.
Editing a critical field (hall, seat, subject_code) resets it to UNRESOLVED (enforced by routers/vsb_alloc.py).
"""
from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

_VALID = "verification_status IN ('FULLY_VERIFIED', 'HALL_LIST_ONLY', 'UNRESOLVED')"


def upgrade():
    names = set(sa.inspect(op.get_bind()).get_table_names())
    if "vsb_alloc_records" not in names:
        return  # table not yet created; 0013 handles it
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("vsb_alloc_records")}
    if "verification_status" not in cols:
        op.add_column(
            "vsb_alloc_records",
            sa.Column(
                "verification_status",
                sa.String(length=16),
                nullable=False,
                server_default="UNRESOLVED",
            ),
        )
        # Add a check constraint only on databases that support it (SQLite ignores named checks but stores DDL).
        with op.batch_alter_table("vsb_alloc_records") as batch_op:
            batch_op.create_check_constraint("ck_vsb_alloc_records_verif", _VALID)


def downgrade():
    with op.batch_alter_table("vsb_alloc_records") as batch_op:
        try:
            batch_op.drop_constraint("ck_vsb_alloc_records_verif", type_="check")
        except Exception:
            pass
        batch_op.drop_column("verification_status")
