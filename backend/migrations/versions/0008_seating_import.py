"""Phase 4: seating-allotment PDF import staging table.

Revision ID: 0008
Revises: 0007
Additive only.
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("seating_entries",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("row_no", sa.Integer(), nullable=False), sa.Column("page_index", sa.Integer(), nullable=False),
        sa.Column("register_number", sa.String(30), nullable=False), sa.Column("hall", sa.String(100)),
        sa.Column("seat", sa.String(30)), sa.Column("raw_text", sa.String(300)),
        sa.Column("source", sa.String(10), nullable=False), sa.Column("confidence", sa.Float()),
        sa.Column("flags", sa.Text()), sa.Column("edited", sa.Boolean(), nullable=False),
        sa.Column("review_status", sa.String(10), nullable=False),
        sa.Column("reviewed_by", sa.String(80)), sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("imported_allotment_id", sa.Integer()),
        sa.ForeignKeyConstraint(["version_id"], ["document_versions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("version_id", "row_no", name="uq_seating_entries_version_row"))
    op.create_index("ix_seating_entries_version_id", "seating_entries", ["version_id"])


def downgrade():
    op.drop_table("seating_entries")
