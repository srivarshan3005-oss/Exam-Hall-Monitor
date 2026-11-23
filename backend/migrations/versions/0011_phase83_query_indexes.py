"""Phase 8.3 query-path indexes (additive, data-preserving)."""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

INDEXES = [
    ("ix_students_department_year", "students", ["department", "year"]),
    ("ix_exams_date_status", "exams", ["exam_date", "status"]),
    ("ix_allotments_exam_student", "allotments", ["exam_id", "student_id"]),
    ("ix_results_student_exam", "results", ["student_id", "exam_id"]),
    ("ix_audit_logs_created_actor", "audit_logs", ["created_at", "actor"]),
    ("ix_security_events_created_type", "security_events", ["created_at", "event_type"]),
    ("ix_auth_sessions_active_user", "auth_sessions", ["user_id", "revoked_at", "expires_at"]),
]

def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for name, table, columns in INDEXES:
        if table not in insp.get_table_names():
            continue
        available = {c["name"] for c in insp.get_columns(table)}
        if not set(columns).issubset(available):
            continue
        if name not in {i["name"] for i in insp.get_indexes(table)}:
            op.create_index(name, table, columns)

def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for name, table, _ in reversed(INDEXES):
        if table in insp.get_table_names() and name in {i["name"] for i in insp.get_indexes(table)}:
            op.drop_index(name, table_name=table)
