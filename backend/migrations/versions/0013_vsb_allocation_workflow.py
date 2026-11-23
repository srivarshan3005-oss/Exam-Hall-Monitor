"""VSB hall/seat allocation workflow: batches, proposed records, issues and the correction trail.

Revision ID: 0013
Revises: 0012

Additive only (four new tables). No existing table or record is touched.
"""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    names = set(sa.inspect(op.get_bind()).get_table_names())
    if "vsb_alloc_batches" not in names:
        op.create_table(
            "vsb_alloc_batches",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("exam_date", sa.Date(), nullable=False),
            sa.Column("session", sa.String(length=2), nullable=False),
            sa.Column("exam_name", sa.String(length=300), nullable=True),
            sa.Column("hall_version_id", sa.Integer(), nullable=True),
            sa.Column("seat_version_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=15), nullable=False),
            sa.Column("parser_version", sa.String(length=40), nullable=True),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(length=80), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("published_by", sa.String(length=80), nullable=True),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("withdrawn_by", sa.String(length=80), nullable=True),
            sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("withdraw_reason", sa.String(length=300), nullable=True),
            sa.ForeignKeyConstraint(["hall_version_id"], ["document_versions.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["seat_version_id"], ["document_versions.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.CheckConstraint("status IN ('draft', 'published', 'superseded', 'withdrawn')", name="ck_vsb_alloc_batches_status"),
            sa.CheckConstraint("session IN ('FN','AN')", name="ck_vsb_alloc_batches_session"),
        )
        op.create_index("ix_vsb_alloc_batches_session", "vsb_alloc_batches", ["exam_date", "session"])
        op.create_index("ix_vsb_alloc_batches_hall_version_id", "vsb_alloc_batches", ["hall_version_id"])
        op.create_index("ix_vsb_alloc_batches_seat_version_id", "vsb_alloc_batches", ["seat_version_id"])
    if "vsb_alloc_records" not in names:
        op.create_table(
            "vsb_alloc_records",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("batch_id", sa.Integer(), nullable=False),
            sa.Column("register_number", sa.String(length=32), nullable=False),
            sa.Column("id_kind", sa.String(length=15), nullable=False),
            sa.Column("student_id", sa.Integer(), nullable=True),
            sa.Column("department", sa.String(length=150), nullable=True),
            sa.Column("department_source", sa.String(length=20), nullable=True),
            sa.Column("subject_code", sa.String(length=30), nullable=True),
            sa.Column("subject_title", sa.String(length=300), nullable=True),
            sa.Column("hall", sa.String(length=100), nullable=True),
            sa.Column("seat", sa.String(length=30), nullable=True),
            sa.Column("sources", sa.String(length=10), nullable=False),
            sa.Column("flags", sa.Text(), nullable=True),
            sa.Column("detail", sa.Text(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("edited", sa.Boolean(), nullable=False),
            sa.Column("review_status", sa.String(length=10), nullable=False),
            sa.Column("review_note", sa.String(length=300), nullable=True),
            sa.Column("reviewed_by", sa.String(length=80), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("published", sa.Boolean(), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("allotment_id", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(["batch_id"], ["vsb_alloc_batches.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("batch_id", "register_number", name="uq_vsb_alloc_records_batch_reg"),
            sa.CheckConstraint("review_status IN ('pending', 'approved', 'rejected')", name="ck_vsb_alloc_records_review"),
        )
        op.create_index("ix_vsb_alloc_records_batch_id", "vsb_alloc_records", ["batch_id"])
        op.create_index("ix_vsb_alloc_records_register_number", "vsb_alloc_records", ["register_number"])
        op.create_index("ix_vsb_alloc_records_student_id", "vsb_alloc_records", ["student_id"])
        op.create_index("ix_vsb_alloc_records_reg_pub", "vsb_alloc_records", ["register_number", "published"])
    if "vsb_alloc_issues" not in names:
        op.create_table(
            "vsb_alloc_issues",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("batch_id", sa.Integer(), nullable=False),
            sa.Column("kind", sa.String(length=40), nullable=False),
            sa.Column("severity", sa.String(length=10), nullable=False),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("register_number", sa.String(length=32), nullable=True),
            sa.Column("hall", sa.String(length=100), nullable=True),
            sa.Column("subject_code", sa.String(length=30), nullable=True),
            sa.Column("page", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=12), nullable=False),
            sa.Column("resolved_by", sa.String(length=80), nullable=True),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resolution_note", sa.String(length=300), nullable=True),
            sa.ForeignKeyConstraint(["batch_id"], ["vsb_alloc_batches.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.CheckConstraint("severity IN ('info', 'warning', 'error')", name="ck_vsb_alloc_issues_severity"),
            sa.CheckConstraint("status IN ('open', 'resolved', 'dismissed')", name="ck_vsb_alloc_issues_status"),
        )
        op.create_index("ix_vsb_alloc_issues_batch_id", "vsb_alloc_issues", ["batch_id"])
    if "vsb_alloc_edits" not in names:
        op.create_table(
            "vsb_alloc_edits",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("record_id", sa.Integer(), nullable=False),
            sa.Column("field", sa.String(length=40), nullable=False),
            sa.Column("old_value", sa.String(length=300), nullable=True),
            sa.Column("new_value", sa.String(length=300), nullable=True),
            sa.Column("edited_by", sa.String(length=80), nullable=False),
            sa.Column("edited_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("reason", sa.String(length=300), nullable=True),
            sa.ForeignKeyConstraint(["record_id"], ["vsb_alloc_records.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_vsb_alloc_edits_record_id", "vsb_alloc_edits", ["record_id"])


def downgrade():
    for t in ("vsb_alloc_edits", "vsb_alloc_issues", "vsb_alloc_records", "vsb_alloc_batches"):
        op.drop_table(t)
