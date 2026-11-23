"""VSB official-source integration: discovered PDF links and discovery-run history.

Revision ID: 0012
Revises: 0011

Additive only (two new tables). No existing table or record is touched.
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

KINDS = "'hall_allotment', 'seating_allotment', 'timetable', 'notice', 'other'"
STATUSES = "'discovered', 'downloaded', 'unchanged', 'duplicate', 'unavailable', 'failed', 'blocked', 'skipped'"


def upgrade():
    insp = sa.inspect(op.get_bind())
    names = set(insp.get_table_names())
    if "vsb_source_links" not in names:
        op.create_table(
            "vsb_source_links",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("url", sa.String(length=1000), nullable=False),
            sa.Column("title", sa.String(length=300), nullable=False),
            sa.Column("doc_kind", sa.String(length=30), nullable=False),
            sa.Column("exam_date", sa.Date(), nullable=True),
            sa.Column("session", sa.String(length=2), nullable=True),
            sa.Column("listing_url", sa.String(length=1000), nullable=True),
            sa.Column("upload_month", sa.String(length=7), nullable=True),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("still_listed", sa.Boolean(), nullable=False),
            sa.Column("download_status", sa.String(length=20), nullable=False),
            sa.Column("last_http_status", sa.Integer(), nullable=True),
            sa.Column("last_error", sa.String(length=500), nullable=True),
            sa.Column("failure_count", sa.Integer(), nullable=False),
            sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_downloaded_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("document_id", sa.Integer(), nullable=True),
            sa.Column("note", sa.String(length=500), nullable=True),
            sa.CheckConstraint(f"doc_kind IN ({KINDS})", name="ck_vsb_source_links_kind"),
            sa.CheckConstraint(f"download_status IN ({STATUSES})", name="ck_vsb_source_links_status"),
            sa.CheckConstraint("session IS NULL OR session IN ('FN','AN')", name="ck_vsb_source_links_session"),
            sa.ForeignKeyConstraint(["document_id"], ["official_documents.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("url", name="uq_vsb_source_links_url"),
        )
        with op.batch_alter_table("vsb_source_links") as b:
            b.create_index("ix_vsb_source_links_kind_date", ["doc_kind", "exam_date", "session"], unique=False)
            b.create_index("ix_vsb_source_links_document_id", ["document_id"], unique=False)
    if "vsb_crawl_runs" not in names:
        op.create_table(
            "vsb_crawl_runs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("trigger", sa.String(length=20), nullable=False),
            sa.Column("actor", sa.String(length=80), nullable=False),
            sa.Column("status", sa.String(length=10), nullable=False),
            sa.Column("page_url", sa.String(length=1000), nullable=True),
            sa.Column("links_found", sa.Integer(), nullable=False),
            sa.Column("new_links", sa.Integer(), nullable=False),
            sa.Column("downloaded", sa.Integer(), nullable=False),
            sa.Column("duplicates", sa.Integer(), nullable=False),
            sa.Column("unavailable", sa.Integer(), nullable=False),
            sa.Column("failed", sa.Integer(), nullable=False),
            sa.Column("message", sa.Text(), nullable=True),
            sa.CheckConstraint("status IN ('running', 'ok', 'partial', 'failed')", name="ck_vsb_crawl_runs_status"),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade():
    insp = sa.inspect(op.get_bind())
    names = set(insp.get_table_names())
    if "vsb_crawl_runs" in names:
        op.drop_table("vsb_crawl_runs")
    if "vsb_source_links" in names:
        existing = {i["name"] for i in insp.get_indexes("vsb_source_links")}
        with op.batch_alter_table("vsb_source_links") as b:
            for ix in ("ix_vsb_source_links_kind_date", "ix_vsb_source_links_document_id"):
                if ix in existing:
                    b.drop_index(ix)
        op.drop_table("vsb_source_links")
