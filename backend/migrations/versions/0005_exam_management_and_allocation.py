"""Phase 2: subject catalogue, academic years/terms, eligibility, allocation plans and history.

Revision ID: 0005
Revises: 0004

Additive only: existing rows and columns are untouched (new columns are nullable).
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("subjects",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("code", sa.String(30), nullable=False),
        sa.Column("name", sa.String(200), nullable=False), sa.Column("department", sa.String(100)),
        sa.Column("semester", sa.Integer()), sa.Column("credits", sa.Float()),
        sa.Column("active", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("code", name="uq_subjects_code"))
    op.create_table("academic_years",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("label", sa.String(20), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False), sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False), sa.UniqueConstraint("label", name="uq_academic_years_label"))
    op.create_table("exam_terms",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("academic_year_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(150), nullable=False), sa.Column("semester_no", sa.Integer()),
        sa.Column("start_date", sa.Date(), nullable=False), sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("academic_year_id", "name", name="uq_exam_terms_year_name"))
    op.create_index("ix_exam_terms_academic_year_id", "exam_terms", ["academic_year_id"])

    with op.batch_alter_table("students") as b:
        b.add_column(sa.Column("course", sa.String(100), nullable=True))
    with op.batch_alter_table("exams") as b:
        b.add_column(sa.Column("subject_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("term_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("duration_minutes", sa.Integer(), nullable=True))
        b.create_foreign_key("fk_exams_subject_id_subjects", "subjects", ["subject_id"], ["id"])
        b.create_foreign_key("fk_exams_term_id_exam_terms", "exam_terms", ["term_id"], ["id"])
        b.create_index("ix_exams_subject_id", ["subject_id"])
        b.create_index("ix_exams_term_id", ["term_id"])
    with op.batch_alter_table("allotments") as b:
        b.add_column(sa.Column("source", sa.String(20), nullable=True))
        b.add_column(sa.Column("plan_id", sa.Integer(), nullable=True))

    # Back-fill durations for existing examinations (HH:MM strings, already validated).
    bind = op.get_bind()
    for row in bind.execute(sa.text("SELECT id, start_time, end_time FROM exams")).fetchall():
        try:
            sh, sm = map(int, row[1].split(":")); eh, em = map(int, row[2].split(":"))
            bind.execute(sa.text("UPDATE exams SET duration_minutes=:d WHERE id=:i"),
                         {"d": (eh * 60 + em) - (sh * 60 + sm), "i": row[0]})
        except Exception:
            pass

    op.create_table("exam_eligibility_rules",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("department", sa.String(100)), sa.Column("course", sa.String(100)), sa.Column("year", sa.Integer()),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"))
    op.create_index("ix_exam_eligibility_rules_exam_id", "exam_eligibility_rules", ["exam_id"])
    op.create_table("exam_student_overrides",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False), sa.Column("kind", sa.String(10), nullable=False),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("exam_id", "student_id", name="uq_exam_student_overrides"))
    op.create_index("ix_exam_student_overrides_exam_id", "exam_student_overrides", ["exam_id"])
    op.create_index("ix_exam_student_overrides_student_id", "exam_student_overrides", ["student_id"])
    op.create_table("allocation_plans",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(15), nullable=False), sa.Column("config", sa.Text(), nullable=False),
        sa.Column("assignments", sa.Text(), nullable=False), sa.Column("unallocated", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False), sa.Column("created_by", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("committed_by", sa.String(80)), sa.Column("committed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"))
    op.create_index("ix_allocation_plans_exam_id", "allocation_plans", ["exam_id"])
    op.create_table("allotment_history",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False), sa.Column("allotment_id", sa.Integer()),
        sa.Column("action", sa.String(20), nullable=False), sa.Column("old_hall", sa.String(100)),
        sa.Column("old_seat", sa.String(30)), sa.Column("new_hall", sa.String(100)), sa.Column("new_seat", sa.String(30)),
        sa.Column("reason", sa.String(300)), sa.Column("actor", sa.String(80), nullable=False),
        sa.Column("plan_id", sa.Integer()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_allotment_history_exam_id", "allotment_history", ["exam_id"])
    op.create_index("ix_allotment_history_student_id", "allotment_history", ["student_id"])


def downgrade():
    op.drop_index("ix_allotment_history_student_id", table_name="allotment_history")
    op.drop_index("ix_allotment_history_exam_id", table_name="allotment_history")
    op.drop_table("allotment_history")
    op.drop_index("ix_allocation_plans_exam_id", table_name="allocation_plans"); op.drop_table("allocation_plans")
    op.drop_index("ix_exam_student_overrides_student_id", table_name="exam_student_overrides")
    op.drop_index("ix_exam_student_overrides_exam_id", table_name="exam_student_overrides")
    op.drop_table("exam_student_overrides")
    op.drop_index("ix_exam_eligibility_rules_exam_id", table_name="exam_eligibility_rules"); op.drop_table("exam_eligibility_rules")
    with op.batch_alter_table("allotments") as b:
        b.drop_column("plan_id"); b.drop_column("source")
    with op.batch_alter_table("exams") as b:
        b.drop_index("ix_exams_term_id"); b.drop_index("ix_exams_subject_id")
        b.drop_constraint("fk_exams_term_id_exam_terms", type_="foreignkey")
        b.drop_constraint("fk_exams_subject_id_subjects", type_="foreignkey")
        b.drop_column("duration_minutes"); b.drop_column("term_id"); b.drop_column("subject_id")
    with op.batch_alter_table("students") as b:
        b.drop_column("course")
    op.drop_index("ix_exam_terms_academic_year_id", table_name="exam_terms")
    op.drop_table("exam_terms"); op.drop_table("academic_years"); op.drop_table("subjects")
