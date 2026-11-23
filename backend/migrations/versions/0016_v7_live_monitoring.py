"""V7 live monitoring: automatic allotment index, ingest queue, source health, e-mail watch, sync log, hall map data.

Revision ID: 0016
Revises: 0015

Additive only. No existing row is changed or removed.
  * new tables: live_allotments, live_ingests, vsb_source_health, live_watches, live_notifications, live_sync_log,
    campus_points, hall_location_history
  * new nullable columns on halls: latitude, longitude, directions, location_source, entrance_id
Re-running is safe (every step checks what already exists).
"""
from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

LIVE = "'CONFIRMED', 'HALL_ONLY', 'SEAT_ONLY', 'CONFLICT', 'MANUAL_REVIEW'"


def _dt():
    return sa.DateTime(timezone=True)


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    names = set(insp.get_table_names())

    if "campus_points" not in names:
        op.create_table(
            "campus_points",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("kind", sa.String(20), nullable=False),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("latitude", sa.Float(), nullable=True),
            sa.Column("longitude", sa.Float(), nullable=True),
            sa.Column("verified", sa.Boolean(), nullable=False),
            sa.Column("verified_by", sa.String(80), nullable=True),
            sa.Column("verified_at", _dt(), nullable=True),
            sa.Column("source", sa.String(300), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name", name="uq_campus_points_name"))

    cols = {c["name"] for c in insp.get_columns("halls")}
    with op.batch_alter_table("halls") as b:
        if "latitude" not in cols:
            b.add_column(sa.Column("latitude", sa.Float(), nullable=True))
        if "longitude" not in cols:
            b.add_column(sa.Column("longitude", sa.Float(), nullable=True))
        if "directions" not in cols:
            b.add_column(sa.Column("directions", sa.Text(), nullable=True))
        if "location_source" not in cols:
            b.add_column(sa.Column("location_source", sa.String(300), nullable=True))
        if "entrance_id" not in cols:
            b.add_column(sa.Column("entrance_id", sa.Integer(), nullable=True))
            b.create_foreign_key("fk_halls_entrance_id", "campus_points", ["entrance_id"], ["id"], ondelete="SET NULL")
            b.create_index("ix_halls_entrance_id", ["entrance_id"])

    if "live_allotments" not in names:
        op.create_table(
            "live_allotments",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("register_number", sa.String(20), nullable=False),
            sa.Column("exam_date", sa.Date(), nullable=False),
            sa.Column("session", sa.String(2), nullable=False),
            sa.Column("subject_code", sa.String(30), nullable=False),
            sa.Column("subject_name", sa.String(300), nullable=True),
            sa.Column("programme", sa.String(30), nullable=True),
            sa.Column("department", sa.String(150), nullable=True),
            sa.Column("hall", sa.String(100), nullable=True),
            sa.Column("seat", sa.String(20), nullable=True),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("flags", sa.Text(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("hall_version_id", sa.Integer(), nullable=True),
            sa.Column("seat_version_id", sa.Integer(), nullable=True),
            sa.Column("hall_page", sa.Integer(), nullable=True),
            sa.Column("seat_page", sa.Integer(), nullable=True),
            sa.Column("hall_source_url", sa.String(1000), nullable=True),
            sa.Column("seat_source_url", sa.String(1000), nullable=True),
            sa.Column("hall_filename", sa.String(200), nullable=True),
            sa.Column("seat_filename", sa.String(200), nullable=True),
            sa.Column("fingerprint", sa.String(64), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("revised_from_id", sa.Integer(), nullable=True),
            sa.Column("is_current", sa.Boolean(), nullable=False),
            sa.Column("first_seen_at", _dt(), nullable=False),
            sa.Column("last_verified_at", _dt(), nullable=False),
            sa.Column("superseded_at", _dt(), nullable=True),
            sa.CheckConstraint(f"status IN ({LIVE})", name="ck_live_allotments_status"),
            sa.CheckConstraint("session IN ('FN','AN')", name="ck_live_allotments_session"),
            sa.ForeignKeyConstraint(["hall_version_id"], ["document_versions.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["seat_version_id"], ["document_versions.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("register_number", "exam_date", "session", "subject_code", "fingerprint", name="uq_live_allotments_identity"))
        op.create_index("ix_live_allotments_reg_current", "live_allotments", ["register_number", "is_current"])
        op.create_index("ix_live_allotments_date_session", "live_allotments", ["exam_date", "session"])
        op.create_index("ix_live_allotments_hall_version_id", "live_allotments", ["hall_version_id"])
        op.create_index("ix_live_allotments_seat_version_id", "live_allotments", ["seat_version_id"])

    if "live_ingests" not in names:
        op.create_table(
            "live_ingests",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("version_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(12), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("records", sa.Integer(), nullable=False),
            sa.Column("pages", sa.Integer(), nullable=False),
            sa.Column("ocr_pages", sa.Integer(), nullable=False),
            sa.Column("error", sa.String(500), nullable=True),
            sa.Column("created_at", _dt(), nullable=False),
            sa.Column("processed_at", _dt(), nullable=True),
            sa.CheckConstraint("status IN ('pending', 'processing', 'ok', 'failed')", name="ck_live_ingests_status"),
            sa.ForeignKeyConstraint(["version_id"], ["document_versions.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("version_id", name="uq_live_ingests_version"))
        op.create_index("ix_live_ingests_version_id", "live_ingests", ["version_id"])

    if "vsb_source_health" not in names:
        op.create_table(
            "vsb_source_health",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("source_key", sa.String(300), nullable=False),
            sa.Column("method", sa.String(20), nullable=False),
            sa.Column("url", sa.String(1000), nullable=False),
            sa.Column("last_attempt_at", _dt(), nullable=True),
            sa.Column("last_success_at", _dt(), nullable=True),
            sa.Column("last_status", sa.String(10), nullable=False),
            sa.Column("last_error", sa.String(500), nullable=True),
            sa.Column("last_http_status", sa.Integer(), nullable=True),
            sa.Column("consecutive_failures", sa.Integer(), nullable=False),
            sa.Column("items_found", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("source_key", name="uq_vsb_source_health_key"))

    if "live_watches" not in names:
        op.create_table(
            "live_watches",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("register_number", sa.String(20), nullable=False),
            sa.Column("email", sa.String(200), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False),
            sa.Column("created_by", sa.String(80), nullable=False),
            sa.Column("created_at", _dt(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("register_number", "email", name="uq_live_watches_reg_email"))
        op.create_index("ix_live_watches_register_number", "live_watches", ["register_number"])

    if "live_notifications" not in names:
        op.create_table(
            "live_notifications",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("watch_id", sa.Integer(), nullable=False),
            sa.Column("allotment_id", sa.Integer(), nullable=True),
            sa.Column("event_type", sa.String(12), nullable=False),
            sa.Column("fingerprint", sa.String(64), nullable=False),
            sa.Column("subject", sa.String(200), nullable=False),
            sa.Column("status", sa.String(10), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("last_error", sa.String(300), nullable=True),
            sa.Column("next_attempt_at", _dt(), nullable=True),
            sa.Column("sent_at", _dt(), nullable=True),
            sa.Column("created_at", _dt(), nullable=False),
            sa.CheckConstraint("status IN ('pending', 'sent', 'outbox', 'failed', 'skipped')", name="ck_live_notifications_status"),
            sa.ForeignKeyConstraint(["watch_id"], ["live_watches.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["allotment_id"], ["live_allotments.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("watch_id", "fingerprint", name="uq_live_notifications_once"))
        op.create_index("ix_live_notifications_watch_id", "live_notifications", ["watch_id"])
        op.create_index("ix_live_notifications_allotment_id", "live_notifications", ["allotment_id"])

    if "live_sync_log" not in names:
        op.create_table(
            "live_sync_log",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("target", sa.String(20), nullable=False),
            sa.Column("started_at", _dt(), nullable=False),
            sa.Column("finished_at", _dt(), nullable=True),
            sa.Column("status", sa.String(10), nullable=False),
            sa.Column("records", sa.Integer(), nullable=False),
            sa.Column("error", sa.String(500), nullable=True),
            sa.PrimaryKeyConstraint("id"))

    if "hall_location_history" not in names:
        op.create_table(
            "hall_location_history",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("hall_id", sa.Integer(), nullable=False),
            sa.Column("actor", sa.String(80), nullable=False),
            sa.Column("action", sa.String(20), nullable=False),
            sa.Column("before", sa.Text(), nullable=True),
            sa.Column("after", sa.Text(), nullable=True),
            sa.Column("source", sa.String(300), nullable=True),
            sa.Column("created_at", _dt(), nullable=False),
            sa.ForeignKeyConstraint(["hall_id"], ["halls.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"))
        op.create_index("ix_hall_location_history_hall_id", "hall_location_history", ["hall_id"])


def downgrade():
    for t in ("hall_location_history", "live_sync_log", "live_notifications", "live_watches", "vsb_source_health",
              "live_ingests", "live_allotments"):
        op.drop_table(t)
    with op.batch_alter_table("halls") as b:
        b.drop_index("ix_halls_entrance_id")
        b.drop_constraint("fk_halls_entrance_id", type_="foreignkey")
        for c in ("entrance_id", "location_source", "directions", "longitude", "latitude"):
            b.drop_column(c)
    op.drop_table("campus_points")
