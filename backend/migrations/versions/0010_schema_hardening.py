"""Phase 8.1: schema hardening - missing foreign-key indexes, one account per student, CHECK constraints.

Revision ID: 0010
Revises: 0009

Additive and data-preserving. NO row is changed or deleted.
* Adds indexes on eight foreign-key columns that had none (faster joins; faster ON DELETE SET NULL scans).
* users.student_id: a UNIQUE index (one login account per student record - the activation flow already assumed
  this, the administrator "create user" path did not enforce it). If the database already contains two accounts for
  the same student the index is created NON-unique instead, a warning lists the student ids, and the migration still
  succeeds; resolve the duplicates, then run `python -m app.cli db-audit`.
* CHECK constraints for rules the application already enforces on every write: exam status, user role/status,
  result marks range, non-blank hall/seat. Each constraint is first tested against the existing rows; one that
  would be violated is SKIPPED with a warning (never forced, never "fixed" by editing data) and is reported by
  `python -m app.cli db-audit`.
Every step is idempotent (checks what already exists), so a re-run after a partial failure is safe.
"""
import logging
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

FK_INDEXES = [
    ("official_documents", "term_id"), ("register_entries", "session_id"), ("review_issues", "entry_id"),
    ("review_issues", "page_id"), ("seat_positions", "entry_id"), ("seating_sheets", "hall_id"),
    ("timetable_entries", "subject_id"), ("timetable_entries", "imported_exam_id"),
]

# table, constraint name, SQL predicate that every valid row satisfies
CHECKS = [
    ("users", "ck_users_role", "role IN ('super_admin','admin','staff','invigilator','student')"),
    ("users", "ck_users_status", "status IN ('active','pending','suspended')"),
    ("exams", "ck_exams_status", "status IN ('draft','published','completed')"),
    ("results", "ck_results_marks_range", "marks >= 0 AND max_marks > 0 AND marks <= max_marks"),
    ("allotments", "ck_allotments_hall_seat_nonblank", "length(trim(hall)) > 0 AND length(trim(seat)) > 0"),
]


def _index_names(insp, table):
    return {i["name"] for i in insp.get_indexes(table)}


def _check_names(insp, table):
    return {c["name"] for c in insp.get_check_constraints(table) if c.get("name")}


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # 1. foreign-key indexes
    for table, col in FK_INDEXES:
        name = f"ix_{table}_{col}"
        if name not in _index_names(insp, table):
            op.create_index(name, table, [col])

    # 2. one account per student
    dupes = [r[0] for r in bind.execute(sa.text(
        "SELECT student_id FROM users WHERE student_id IS NOT NULL GROUP BY student_id HAVING COUNT(*) > 1"))]
    names = _index_names(insp, "users")
    if dupes:
        log.warning("0010: students %s are linked to more than one user account; created a NON-unique index "
                    "ix_users_student_id. Resolve the duplicates and run 'python -m app.cli db-audit'.", dupes)
        if "ix_users_student_id" not in names:
            op.create_index("ix_users_student_id", "users", ["student_id"])
    elif "uq_users_student_id" not in names:
        op.create_index("uq_users_student_id", "users", ["student_id"], unique=True)

    # 3. CHECK constraints (only where every existing row already satisfies them)
    insp = sa.inspect(bind)
    todo: dict[str, list[tuple[str, str]]] = {}
    for table, name, predicate in CHECKS:
        if name in _check_names(insp, table):
            continue
        bad = bind.execute(sa.text(f"SELECT COUNT(*) FROM {table} WHERE NOT ({predicate})")).scalar() or 0
        if bad:
            log.warning("0010: %d row(s) in %s violate %s; constraint NOT added (data left untouched). "
                        "Fix the rows, then run 'python -m app.cli db-audit'.", bad, table, name)
            continue
        todo.setdefault(table, []).append((name, predicate))
    for table, items in todo.items():
        with op.batch_alter_table(table) as b:
            for name, predicate in items:
                b.create_check_constraint(name, sa.text(predicate))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for table in sorted({t for t, _, _ in CHECKS}):
        present = _check_names(insp, table)
        drop = [n for t, n, _ in CHECKS if t == table and n in present]
        if drop:
            with op.batch_alter_table(table) as b:
                for n in drop:
                    b.drop_constraint(n, type_="check")
    insp = sa.inspect(bind)
    for n in ("uq_users_student_id", "ix_users_student_id"):
        if n in _index_names(insp, "users"):
            op.drop_index(n, table_name="users")
    for table, col in FK_INDEXES:
        name = f"ix_{table}_{col}"
        if name in _index_names(insp, table):
            op.drop_index(name, table_name=table)
