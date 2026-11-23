"""Core tables (users, students, exams, allotments, results, audit log)."""
from datetime import date, datetime, timezone
from sqlalchemy import (String, Integer, Float, Boolean, Date, ForeignKey, Text,
                        UniqueConstraint, Index, CheckConstraint, false as sa_false)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates
from .database import Base
from .dbtypes import UTCDateTime


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        # one login account per student record (migration 0010; created as a plain index if legacy data has duplicates)
        Index("uq_users_student_id", "student_id", unique=True),
        CheckConstraint("role IN ('super_admin','admin','staff','invigilator','student')", name="ck_users_role"),
        CheckConstraint("status IN ('active','pending','suspended')", name="ck_users_status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(20), default="student")
    student_id: Mapped[int | None] = mapped_column(ForeignKey("students.id"), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # --- security fields (migration 0002) ---
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=utcnow, nullable=True)
    # --- Phase 4 (migration 0007) ---
    email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    status: Mapped[str] = mapped_column(String(15), default="active", server_default="active")  # active | pending | suspended
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    password_changed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)  # department staff scope (blank = institution-wide)
    status_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)


class AuthSession(Base):
    """Server-side record of every issued access token (revocable, idle-timeout aware)."""
    __tablename__ = "auth_sessions"
    __table_args__ = (Index("ix_auth_sessions_user_id", "user_id"),
                      Index("ix_auth_sessions_active_user", "user_id", "revoked_at", "expires_at"))
    id: Mapped[str] = mapped_column(String(32), primary_key=True)          # the token's sid claim
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(200), nullable=True)


class PasswordToken(Base):
    """One-time password-reset / account-activation tokens. Only a SHA-256 hash is stored."""
    __tablename__ = "password_tokens"
    __table_args__ = (Index("ix_password_tokens_hash", "token_hash", unique=True),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(12))                      # reset | activation
    token_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class SecurityEvent(Base):
    """Security-relevant events (sign-ins, failures, lockouts, denials, resets, role changes).
    Never stores passwords, tokens or other secrets."""
    __tablename__ = "security_events"
    __table_args__ = (Index("ix_security_events_created_at", "created_at"),
                      Index("ix_security_events_type", "event_type"),
                      Index("ix_security_events_created_type", "created_at", "event_type"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    event_type: Mapped[str] = mapped_column(String(50))
    severity: Mapped[str] = mapped_column(String(10), default="info")      # info | warning | critical
    username: Mapped[str | None] = mapped_column(String(80), nullable=True)
    role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(200), nullable=True)
    path: Mapped[str | None] = mapped_column(String(200), nullable=True)
    detail: Mapped[str | None] = mapped_column(String(500), nullable=True)


class Student(Base):
    __tablename__ = "students"
    __table_args__ = (Index("ix_students_department_year", "department", "year"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    register_number: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(150))
    department: Mapped[str] = mapped_column(String(100))
    year: Mapped[int] = mapped_column(Integer, default=1)
    email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=utcnow, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=utcnow,
                                                        onupdate=utcnow, nullable=True)
    course: Mapped[str | None] = mapped_column(String(100), nullable=True)  # migration 0005


class Exam(Base):
    __tablename__ = "exams"
    __table_args__ = (CheckConstraint("status IN ('draft','published','completed')", name="ck_exams_status"),
                      Index("ix_exams_date_status", "exam_date", "status"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(180))
    subject_code: Mapped[str] = mapped_column(String(30))
    exam_date: Mapped[str] = mapped_column(String(20))
    start_time: Mapped[str] = mapped_column(String(10))
    end_time: Mapped[str] = mapped_column(String(10))
    venue: Mapped[str] = mapped_column(String(150), default="To be announced")
    status: Mapped[str] = mapped_column(String(20), default="draft")
    updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=utcnow,
                                                        onupdate=utcnow, nullable=True)
    # --- Phase 2 (migration 0005) ---
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"), nullable=True, index=True)
    term_id: Mapped[int | None] = mapped_column(ForeignKey("exam_terms.id"), nullable=True, index=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Allotment(Base):
    __tablename__ = "allotments"
    __table_args__ = (
        UniqueConstraint("student_id", "exam_id", name="uq_allotments_student_exam"),
        UniqueConstraint("exam_id", "hall", "seat", name="uq_allotments_exam_hall_seat"),
        CheckConstraint("length(trim(hall)) > 0 AND length(trim(seat)) > 0", name="ck_allotments_hall_seat_nonblank"),
        Index("ix_allotments_exam_student", "exam_id", "student_id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"), index=True)
    hall: Mapped[str] = mapped_column(String(100))
    seat: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=utcnow, nullable=True)
    source: Mapped[str | None] = mapped_column(String(20), nullable=True)      # manual | auto (migration 0005)
    plan_id: Mapped[int | None] = mapped_column(Integer, nullable=True)        # allocation plan that created it
    student = relationship("Student")
    exam = relationship("Exam")

    @validates("hall", "seat")
    def _canonical_place(self, _key, value):
        """One canonical spelling, so 'a12' and 'A12' can never occupy the same seat twice: trimmed and upper-case,
        exactly what the API schemas already produce. Every code path (manual, auto, PDF import) now gets it."""
        return value.strip().upper() if isinstance(value, str) else value


class Result(Base):
    __tablename__ = "results"
    __table_args__ = (UniqueConstraint("student_id", "exam_id", name="uq_results_student_exam"),
                      Index("ix_results_student_exam", "student_id", "exam_id"),
                      CheckConstraint("marks >= 0 AND max_marks > 0 AND marks <= max_marks", name="ck_results_marks_range"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"), index=True)
    marks: Mapped[float] = mapped_column(Float)
    max_marks: Mapped[float] = mapped_column(Float, default=100)
    grade: Mapped[str] = mapped_column(String(5), default="—")
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=utcnow,
                                                        onupdate=utcnow, nullable=True)
    student = relationship("Student")
    exam = relationship("Exam")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_created_at", "created_at"),
                      Index("ix_audit_logs_action", "action"),
                      Index("ix_audit_logs_created_actor", "created_at", "actor"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(100))
    target: Mapped[str] = mapped_column(String(150))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)

class Announcement(Base):
    __tablename__ = "announcements"
    __table_args__ = (Index("ix_announcements_publication", "published", "publish_at", "expires_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(180))
    body: Mapped[str] = mapped_column(Text)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    publish_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_by: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    # --- Phase 6 (migration 0009): targeting and delivery ---
    priority: Mapped[str] = mapped_column(String(10), default="normal", server_default="normal")
    audience_roles: Mapped[str | None] = mapped_column(String(100), nullable=True)      # comma list; blank = every role
    audience_department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    audience_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notify: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    notified_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    remind_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    reminded_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Notification(Base):
    """Phase 6: one in-app notification for one user. (user_id, event_key) is unique, which is what makes
    a repeated action or a re-run scheduler unable to notify the same person twice."""
    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("user_id", "event_key", name="uq_notifications_user_event"),
                      Index("ix_notifications_user_created", "user_id", "created_at"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    category: Mapped[str] = mapped_column(String(20))
    priority: Mapped[str] = mapped_column(String(10), default="normal")
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(200), nullable=True)
    event_key: Mapped[str] = mapped_column(String(150))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)   # soft delete keeps the dedup key


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"
    __table_args__ = (UniqueConstraint("user_id", "category", name="uq_notification_prefs_user_category"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    category: Mapped[str] = mapped_column(String(20))
    in_app: Mapped[bool] = mapped_column(Boolean, default=True)
    email: Mapped[bool] = mapped_column(Boolean, default=True)


class EmailDelivery(Base):
    """Phase 6: every outgoing e-mail and what actually happened to it. `sent` is only ever written after the
    SMTP server accepted the message. Messages that carry one-time links are never stored (body is NULL)."""
    __tablename__ = "email_deliveries"
    __table_args__ = (Index("ix_email_deliveries_status", "status", "next_attempt_at"),
                      Index("ix_email_deliveries_created", "created_at"),
                      UniqueConstraint("dedup_key", name="uq_email_deliveries_dedup"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    kind: Mapped[str] = mapped_column(String(20))              # notification | account | test | announcement
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notification_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recipient: Mapped[str] = mapped_column(String(150))
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(15), default="queued")   # queued|sending|sent|retrying|failed|outbox|not_configured
    mode: Mapped[str | None] = mapped_column(String(10), nullable=True)  # smtp | outbox | none
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    dedup_key: Mapped[str | None] = mapped_column(String(190), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(80), nullable=True)


class EmailTemplate(Base):
    """Administrator overrides of the built-in notification texts (the defaults live in app/notify_templates.py)."""
    __tablename__ = "email_templates"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    updated_by: Mapped[str] = mapped_column(String(80))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Building(Base):
    __tablename__ = "buildings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Block(Base):
    __tablename__ = "blocks"
    __table_args__ = (UniqueConstraint("building_id", "code", name="uq_blocks_building_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(150))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Floor(Base):
    __tablename__ = "floors"
    __table_args__ = (UniqueConstraint("block_id", "code", name="uq_floors_block_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    block_id: Mapped[int] = mapped_column(ForeignKey("blocks.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(100))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class HallSeat(Base):
    __tablename__ = "hall_seats"
    __table_args__ = (UniqueConstraint("hall_id", "seat_label", name="uq_hall_seats_hall_label"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hall_id: Mapped[int] = mapped_column(ForeignKey("halls.id", ondelete="CASCADE"), index=True)
    seat_label: Mapped[str] = mapped_column(String(30))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


# ----------------------------------------------------------------------------- Phase 2 (migration 0005)
class Subject(Base):
    __tablename__ = "subjects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    semester: Mapped[int | None] = mapped_column(Integer, nullable=True)
    credits: Mapped[float | None] = mapped_column(Float, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=utcnow, nullable=True)


class AcademicYear(Base):
    __tablename__ = "academic_years"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(20), unique=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)


class ExamTerm(Base):
    """An examination session of an academic year (e.g. 'Nov-Dec end-semester', semester 3)."""
    __tablename__ = "exam_terms"
    __table_args__ = (UniqueConstraint("academic_year_id", "name", name="uq_exam_terms_year_name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    academic_year_id: Mapped[int] = mapped_column(ForeignKey("academic_years.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    semester_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ExamEligibilityRule(Base):
    """A student is eligible when ANY rule matches; NULL field = 'any'."""
    __tablename__ = "exam_eligibility_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"), index=True)
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    course: Mapped[str | None] = mapped_column(String(100), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ExamStudentOverride(Base):
    """Individual student forced in ('include') or out ('exclude') of an exam's audience."""
    __tablename__ = "exam_student_overrides"
    __table_args__ = (UniqueConstraint("exam_id", "student_id", name="uq_exam_student_overrides"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))


class AllocationPlan(Base):
    """A saved allocation preview awaiting administrator approval."""
    __tablename__ = "allocation_plans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(15), default="preview")  # preview|committed|discarded|stale
    config: Mapped[str] = mapped_column(Text)
    assignments: Mapped[str] = mapped_column(Text)
    unallocated: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    committed_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    committed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class AllotmentHistory(Base):
    """Per-seat change history (survives deletion of the allotment itself)."""
    __tablename__ = "allotment_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exam_id: Mapped[int] = mapped_column(Integer, index=True)
    student_id: Mapped[int] = mapped_column(Integer, index=True)
    allotment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(20))  # created|auto_created|moved|deleted
    old_hall: Mapped[str | None] = mapped_column(String(100), nullable=True)
    old_seat: Mapped[str | None] = mapped_column(String(30), nullable=True)
    new_hall: Mapped[str | None] = mapped_column(String(100), nullable=True)
    new_seat: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    actor: Mapped[str] = mapped_column(String(80))
    plan_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class SeatingEntry(Base):
    """Phase 4: one register-number / hall / seat row read from a seating-allotment PDF. Nothing here
    reaches `allotments` until an administrator approves the row and confirms the import."""
    __tablename__ = "seating_entries"
    __table_args__ = (UniqueConstraint("version_id", "row_no", name="uq_seating_entries_version_row"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), index=True)
    row_no: Mapped[int] = mapped_column(Integer)
    page_index: Mapped[int] = mapped_column(Integer)
    register_number: Mapped[str] = mapped_column(String(30))
    hall: Mapped[str | None] = mapped_column(String(100), nullable=True)
    seat: Mapped[str | None] = mapped_column(String(30), nullable=True)
    raw_text: Mapped[str | None] = mapped_column(String(300), nullable=True)
    source: Mapped[str] = mapped_column(String(10), default="text")       # text | ocr | manual
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    flags: Mapped[str | None] = mapped_column(Text, nullable=True)         # JSON list
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    review_status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | approved | rejected | imported
    reviewed_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    imported_allotment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
