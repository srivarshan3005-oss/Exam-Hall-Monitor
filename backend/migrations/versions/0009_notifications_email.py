"""Phase 6: notifications, preferences, e-mail delivery log, templates, announcement targeting.

Revision ID: 0009
Revises: 0008

Additive only. Existing announcements keep working: the new columns default to 'normal' priority, no
audience (so they stay on the public list exactly as before) and notify = false (nobody is e-mailed
retroactively). Downgrade drops only what this migration added.
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("announcements") as b:
        b.add_column(sa.Column("priority", sa.String(10), nullable=False, server_default="normal"))
        b.add_column(sa.Column("audience_roles", sa.String(100)))
        b.add_column(sa.Column("audience_department", sa.String(100)))
        b.add_column(sa.Column("audience_year", sa.Integer()))
        b.add_column(sa.Column("notify", sa.Boolean(), nullable=False, server_default=sa.text("0")))
        b.add_column(sa.Column("notified_at", sa.DateTime(timezone=True)))
        b.add_column(sa.Column("remind_at", sa.DateTime(timezone=True)))
        b.add_column(sa.Column("reminded_at", sa.DateTime(timezone=True)))
    op.create_table("notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("priority", sa.String(10), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("link", sa.String(200)),
        sa.Column("event_key", sa.String(150), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "event_key", name="uq_notifications_user_event"))
    op.create_index("ix_notifications_user_created", "notifications", ["user_id", "created_at"])
    op.create_table("notification_preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("in_app", sa.Boolean(), nullable=False),
        sa.Column("email", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("user_id", "category", name="uq_notification_prefs_user_category"))
    op.create_table("email_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("user_id", sa.Integer()),
        sa.Column("notification_id", sa.Integer()),
        sa.Column("recipient", sa.String(150), nullable=False),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("body", sa.Text()),
        sa.Column("sensitive", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(15), nullable=False),
        sa.Column("mode", sa.String(10)),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(30)),
        sa.Column("last_error", sa.String(300)),
        sa.Column("dedup_key", sa.String(190)),
        sa.Column("created_by", sa.String(80)),
        sa.UniqueConstraint("dedup_key", name="uq_email_deliveries_dedup"))
    op.create_index("ix_email_deliveries_status", "email_deliveries", ["status", "next_attempt_at"])
    op.create_index("ix_email_deliveries_created", "email_deliveries", ["created_at"])
    op.create_table("email_templates",
        sa.Column("key", sa.String(40), primary_key=True),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.String(80), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table("email_templates")
    op.drop_index("ix_email_deliveries_created", "email_deliveries")
    op.drop_index("ix_email_deliveries_status", "email_deliveries")
    op.drop_table("email_deliveries")
    op.drop_table("notification_preferences")
    op.drop_index("ix_notifications_user_created", "notifications")
    op.drop_table("notifications")
    with op.batch_alter_table("announcements") as b:
        for c in ("reminded_at", "remind_at", "notified_at", "notify", "audience_year", "audience_department",
                  "audience_roles", "priority"):
            b.drop_column(c)
