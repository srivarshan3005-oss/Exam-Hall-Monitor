"""Phase 4: account lifecycle columns, server-side sessions, one-time tokens, security events.

Revision ID: 0007
Revises: 0006

Additive only. Existing accounts keep working: status is back-filled from `active`
(active -> 'active', inactive -> 'suspended'), the 'admin' role keeps its meaning
(Examination administrator) and no password is touched. Sessions issued before the
upgrade are not in auth_sessions, so users sign in once again.
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("email", sa.String(150)))
        b.add_column(sa.Column("status", sa.String(15), nullable=False, server_default="active"))
        b.add_column(sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.text("0")))
        b.add_column(sa.Column("password_changed_at", sa.DateTime(timezone=True)))
        b.add_column(sa.Column("department", sa.String(100)))
        b.add_column(sa.Column("status_reason", sa.String(200)))
    op.execute("UPDATE users SET status = CASE WHEN active = 1 THEN 'active' ELSE 'suspended' END")
    op.create_table("auth_sessions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("ip_address", sa.String(64)), sa.Column("user_agent", sa.String(200)),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"))
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_table("password_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(12), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"))
    op.create_index("ix_password_tokens_user_id", "password_tokens", ["user_id"])
    op.create_index("ix_password_tokens_hash", "password_tokens", ["token_hash"], unique=True)
    op.create_table("security_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("username", sa.String(80)), sa.Column("role", sa.String(20)),
        sa.Column("ip_address", sa.String(64)), sa.Column("user_agent", sa.String(200)),
        sa.Column("path", sa.String(200)), sa.Column("detail", sa.String(500)))
    op.create_index("ix_security_events_created_at", "security_events", ["created_at"])
    op.create_index("ix_security_events_type", "security_events", ["event_type"])


def downgrade():
    op.drop_table("security_events")
    op.drop_table("password_tokens")
    op.drop_table("auth_sessions")
    with op.batch_alter_table("users") as b:
        for c in ("status_reason", "department", "password_changed_at", "must_change_password", "status", "email"):
            b.drop_column(c)
