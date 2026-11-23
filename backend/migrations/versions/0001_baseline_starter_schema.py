"""Baseline: the exact schema created by the 0.1.0 starter (SQLAlchemy create_all).

Databases created by 0.1.0 are stamped with this revision by `python -m app.cli migrate`.

Revision ID: 0001
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("students",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("register_number", sa.String(30), nullable=False),
        sa.Column("full_name", sa.String(150), nullable=False),
        sa.Column("department", sa.String(100), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(150), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_students_register_number", "students", ["register_number"], unique=True)

    op.create_table("exams",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("subject_code", sa.String(30), nullable=False),
        sa.Column("exam_date", sa.String(20), nullable=False),
        sa.Column("start_time", sa.String(10), nullable=False),
        sa.Column("end_time", sa.String(10), nullable=False),
        sa.Column("venue", sa.String(150), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.PrimaryKeyConstraint("id"))

    op.create_table("users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(80), nullable=False),
        sa.Column("password_hash", sa.String(300), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"]),
        sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table("allotments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("hall", sa.String(100), nullable=False),
        sa.Column("seat", sa.String(30), nullable=False),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"]),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"]),
        sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_allotments_student_id", "allotments", ["student_id"])
    op.create_index("ix_allotments_exam_id", "allotments", ["exam_id"])

    op.create_table("results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("marks", sa.Float(), nullable=False),
        sa.Column("max_marks", sa.Float(), nullable=False),
        sa.Column("grade", sa.String(5), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"]),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"]),
        sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_results_student_id", "results", ["student_id"])
    op.create_index("ix_results_exam_id", "results", ["exam_id"])

    op.create_table("audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor", sa.String(80), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target", sa.String(150), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"))


def downgrade() -> None:
    for t in ("audit_logs", "results", "allotments", "users", "exams", "students"):
        op.drop_table(t)
