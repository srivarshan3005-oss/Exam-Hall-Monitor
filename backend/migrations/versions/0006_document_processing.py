"""Phase 3: official document metadata, extracted text, timetable extraction, edit trail, processing history.

Revision ID: 0006
Revises: 0005

Additive only: new nullable columns on official_documents / pdf_pages and new tables.
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("official_documents") as b:
        b.add_column(sa.Column("source_label", sa.String(200)))
        b.add_column(sa.Column("exam_name", sa.String(200)))
        b.add_column(sa.Column("term_id", sa.Integer()))
        b.add_column(sa.Column("uploaded_by", sa.String(80)))
        b.add_column(sa.Column("original_filename", sa.String(200)))
        b.create_foreign_key("fk_official_documents_term_id_exam_terms", "exam_terms", ["term_id"], ["id"],
                             ondelete="SET NULL")
    with op.batch_alter_table("pdf_pages") as b:
        b.add_column(sa.Column("text_content", sa.Text()))
        b.add_column(sa.Column("extraction_method", sa.String(20)))
        b.add_column(sa.Column("page_warning", sa.String(300)))
    op.create_table("document_extractions",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("exam_name", sa.String(200)), sa.Column("session_label", sa.String(10)),
        sa.Column("academic_year", sa.String(20)), sa.Column("department", sa.String(150)),
        sa.Column("semester", sa.Integer()), sa.Column("instructions", sa.Text()),
        sa.Column("register_numbers", sa.Text()), sa.Column("flags", sa.Text()), sa.Column("issues", sa.Text()),
        sa.Column("ocr_language", sa.String(40)), sa.Column("text_fingerprint", sa.String(64)),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True)), sa.Column("imported_by", sa.String(80)),
        sa.ForeignKeyConstraint(["version_id"], ["document_versions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("version_id"))
    op.create_index("ix_document_extractions_text_fingerprint", "document_extractions", ["text_fingerprint"])
    op.create_table("timetable_entries",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("row_no", sa.Integer(), nullable=False), sa.Column("page_index", sa.Integer(), nullable=False),
        sa.Column("exam_date", sa.Date()), sa.Column("start_time", sa.String(5)), sa.Column("end_time", sa.String(5)),
        sa.Column("session", sa.String(2)), sa.Column("subject_code", sa.String(30)),
        sa.Column("subject_name", sa.String(200)), sa.Column("department", sa.String(150)),
        sa.Column("year", sa.Integer()), sa.Column("semester", sa.Integer()), sa.Column("subject_id", sa.Integer()),
        sa.Column("raw_text", sa.String(500)), sa.Column("source", sa.String(15), nullable=False),
        sa.Column("confidence", sa.Float()), sa.Column("flags", sa.Text()), sa.Column("uncertain_fields", sa.Text()),
        sa.Column("edited", sa.Boolean(), nullable=False), sa.Column("review_status", sa.String(15), nullable=False),
        sa.Column("reviewed_by", sa.String(80)), sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("imported_exam_id", sa.Integer()),
        sa.ForeignKeyConstraint(["version_id"], ["document_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["imported_exam_id"], ["exams.id"], ondelete="SET NULL"),
        sa.CheckConstraint("review_status IN ('pending', 'approved', 'rejected', 'imported')",
                           name="ck_timetable_entries_review"),
        sa.CheckConstraint("session IS NULL OR session IN ('FN','AN')", name="ck_timetable_entries_session"),
        sa.UniqueConstraint("version_id", "row_no", name="uq_timetable_entries_version_row"))
    op.create_index("ix_timetable_entries_version_id", "timetable_entries", ["version_id"])
    op.create_table("extraction_edits",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("entry_id", sa.Integer()), sa.Column("field", sa.String(40), nullable=False),
        sa.Column("old_value", sa.String(500)), sa.Column("new_value", sa.String(500)),
        sa.Column("edited_by", sa.String(80), nullable=False), sa.Column("edited_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(300)),
        sa.ForeignKeyConstraint(["version_id"], ["document_versions.id"], ondelete="CASCADE"))
    op.create_index("ix_extraction_edits_version_id", "extraction_edits", ["version_id"])
    op.create_index("ix_extraction_edits_entry_id", "extraction_edits", ["entry_id"])
    op.create_table("document_events",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("event", sa.String(40), nullable=False), sa.Column("actor", sa.String(80), nullable=False),
        sa.Column("detail", sa.String(1000)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["version_id"], ["document_versions.id"], ondelete="CASCADE"))
    op.create_index("ix_document_events_version_id", "document_events", ["version_id"])


def downgrade():
    op.drop_index("ix_document_events_version_id", table_name="document_events"); op.drop_table("document_events")
    op.drop_index("ix_extraction_edits_entry_id", table_name="extraction_edits")
    op.drop_index("ix_extraction_edits_version_id", table_name="extraction_edits"); op.drop_table("extraction_edits")
    op.drop_index("ix_timetable_entries_version_id", table_name="timetable_entries"); op.drop_table("timetable_entries")
    op.drop_index("ix_document_extractions_text_fingerprint", table_name="document_extractions")
    op.drop_table("document_extractions")
    with op.batch_alter_table("pdf_pages") as b:
        b.drop_column("page_warning"); b.drop_column("extraction_method"); b.drop_column("text_content")
    with op.batch_alter_table("official_documents") as b:
        b.drop_constraint("fk_official_documents_term_id_exam_terms", type_="foreignkey")
        b.drop_column("original_filename"); b.drop_column("uploaded_by"); b.drop_column("term_id")
        b.drop_column("exam_name"); b.drop_column("source_label")
