"""Smart Hall Finder tables (Phase 2 schema; filled by the Phase 3 PDF pipeline).

Design rules baked into the schema:
* Nothing here is ever "guessed": every register entry and seat position records
  HOW it was obtained (extraction_method / mapping_method), a confidence value,
  its coordinates on the original page, and a review status.
* PDF page numbers are stored 0-based (`page_index`); the user-facing page number
  is always `page_index + 1`.
* Coordinates are PDF points on the *unrotated* page, origin top-left, y down.
* Register numbers are free strings: 12-digit numbers are 'standard12', anything
  else printed in a PDF (e.g. an 11-digit id) is kept verbatim as 'nonstandard'.
"""
from datetime import date, datetime
from sqlalchemy import (String, Integer, Float, Boolean, Date, DateTime, ForeignKey, Text,
                        UniqueConstraint, CheckConstraint, Index)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base
from .dbtypes import UTCDateTime
from .models import utcnow

DOC_KINDS = ("hall_allotment", "seating_allotment", "timetable", "notice", "other")
REVIEW_STATES = ("pending", "approved", "rejected", "needs_review")


def _in(col: str, values) -> str:
    return f"{col} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


class OfficialDocument(Base):
    """One logical official PDF (identified by its source URL)."""
    __tablename__ = "official_documents"
    __table_args__ = (
        CheckConstraint(_in("doc_kind", DOC_KINDS), name="ck_official_documents_kind"),
        CheckConstraint("session IS NULL OR session IN ('FN','AN')", name="ck_official_documents_session"),
        CheckConstraint(_in("status", ("active", "superseded", "withdrawn", "error")),
                        name="ck_official_documents_status"),
        CheckConstraint(_in("origin", ("crawler", "upload")), name="ck_official_documents_origin"),
        Index("ix_official_documents_exam_date", "exam_date", "session"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_url: Mapped[str] = mapped_column(String(1000), unique=True)
    listing_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    title: Mapped[str] = mapped_column(String(300))
    doc_kind: Mapped[str] = mapped_column(String(30), default="other")
    exam_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    session: Mapped[str | None] = mapped_column(String(2), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    origin: Mapped[str] = mapped_column(String(20), default="crawler")
    # --- Phase 3 (migration 0006) ---
    source_label: Mapped[str | None] = mapped_column(String(200), nullable=True)   # e.g. "Controller of Examinations"
    exam_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    term_id: Mapped[int | None] = mapped_column(ForeignKey("exam_terms.id", ondelete="SET NULL"), nullable=True, index=True)
    uploaded_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String(200), nullable=True)
    versions = relationship("DocumentVersion", back_populates="document", cascade="all, delete-orphan")


class DocumentVersion(Base):
    """One downloaded binary of a document. Changed content => new version row."""
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_no", name="uq_document_versions_doc_no"),
        UniqueConstraint("document_id", "sha256", name="uq_document_versions_doc_sha"),
        CheckConstraint(_in("processing_status", ("pending", "processing", "processed", "needs_review", "failed")),
                        name="ck_document_versions_processing"),
        CheckConstraint(_in("review_status", ("pending", "approved", "rejected")),
                        name="ck_document_versions_review"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("official_documents.id", ondelete="CASCADE"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    storage_path: Mapped[str] = mapped_column(String(500))
    downloaded_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    http_etag: Mapped[str | None] = mapped_column(String(200), nullable=True)
    http_last_modified: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    processing_status: Mapped[str] = mapped_column(String(20), default="pending")
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_used: Mapped[bool] = mapped_column(Boolean, default=False)
    extractor_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    review_status: Mapped[str] = mapped_column(String(20), default="pending")
    reviewed_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    document = relationship("OfficialDocument", back_populates="versions")
    pages = relationship("PdfPage", back_populates="version", cascade="all, delete-orphan")


class PdfPage(Base):
    __tablename__ = "pdf_pages"
    __table_args__ = (
        UniqueConstraint("version_id", "page_index", name="uq_pdf_pages_version_index"),
        CheckConstraint("page_index >= 0", name="ck_pdf_pages_index"),
        CheckConstraint(_in("review_status", REVIEW_STATES), name="ck_pdf_pages_review"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), index=True)
    page_index: Mapped[int] = mapped_column(Integer)  # 0-based; display number = page_index + 1
    width_pt: Mapped[float | None] = mapped_column(Float, nullable=True)
    height_pt: Mapped[float | None] = mapped_column(Float, nullable=True)
    rotation: Mapped[int] = mapped_column(Integer, default=0)
    text_chars: Mapped[int] = mapped_column(Integer, default=0)
    ocr_used: Mapped[bool] = mapped_column(Boolean, default=False)
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    image_dpi: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text_content: Mapped[str | None] = mapped_column(Text, nullable=True)       # Phase 3: extracted/OCR text
    extraction_method: Mapped[str | None] = mapped_column(String(20), nullable=True)  # text_layer | ocr | empty
    page_warning: Mapped[str | None] = mapped_column(String(300), nullable=True)
    hall_code_raw: Mapped[str | None] = mapped_column(String(100), nullable=True)
    text_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extraction_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_status: Mapped[str] = mapped_column(String(20), default="pending")
    version = relationship("DocumentVersion", back_populates="pages")


class ExamSession(Base):
    """A date + FN/AN session (optionally with an examination title)."""
    __tablename__ = "exam_sessions"
    __table_args__ = (
        UniqueConstraint("exam_date", "session", "title", name="uq_exam_sessions_date_session_title"),
        CheckConstraint("session IN ('FN','AN')", name="ck_exam_sessions_session"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exam_date: Mapped[date] = mapped_column(Date)
    session: Mapped[str] = mapped_column(String(2))
    title: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Hall(Base):
    """Hall directory. Building/block/floor/room stay NULL unless verified by an admin."""
    __tablename__ = "halls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(100), unique=True)  # as printed, whitespace-normalised
    display_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    building: Mapped[str | None] = mapped_column(String(100), nullable=True)
    block: Mapped[str | None] = mapped_column(String(50), nullable=True)
    floor: Mapped[str | None] = mapped_column(String(20), nullable=True)
    room: Mapped[str | None] = mapped_column(String(50), nullable=True)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    building_id: Mapped[int | None] = mapped_column(ForeignKey("buildings.id", ondelete="SET NULL"), nullable=True, index=True)
    block_id: Mapped[int | None] = mapped_column(ForeignKey("blocks.id", ondelete="SET NULL"), nullable=True, index=True)
    floor_id: Mapped[int | None] = mapped_column(ForeignKey("floors.id", ondelete="SET NULL"), nullable=True, index=True)
    # V7 (migration 0016): verified map data. Shown to students only when `verified` is true AND the value is present.
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    directions: Mapped[str | None] = mapped_column(Text, nullable=True)
    location_source: Mapped[str | None] = mapped_column(String(300), nullable=True)
    entrance_id: Mapped[int | None] = mapped_column(ForeignKey("campus_points.id", ondelete="SET NULL"), nullable=True, index=True)


class SeatingSheet(Base):
    """One hall's seating page in one PDF version."""
    __tablename__ = "seating_sheets"
    __table_args__ = (
        CheckConstraint(_in("review_status", REVIEW_STATES), name="ck_seating_sheets_review"),
        Index("ix_seating_sheets_session_hall", "session_id", "hall_id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), index=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pdf_pages.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("exam_sessions.id", ondelete="SET NULL"), nullable=True)
    hall_id: Mapped[int | None] = mapped_column(ForeignKey("halls.id", ondelete="SET NULL"), nullable=True, index=True)
    hall_code_raw: Mapped[str] = mapped_column(String(100))
    declared_total: Mapped[int | None] = mapped_column(Integer, nullable=True)   # printed "Total"
    extracted_total: Mapped[int | None] = mapped_column(Integer, nullable=True)  # what we actually found
    layout_kind: Mapped[str | None] = mapped_column(String(40), nullable=True)
    extraction_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_status: Mapped[str] = mapped_column(String(20), default="pending")
    reviewed_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    published: Mapped[bool] = mapped_column(Boolean, default=False)


class RegisterEntry(Base):
    """A register number found on a page (the search index)."""
    __tablename__ = "register_entries"
    __table_args__ = (
        CheckConstraint(_in("review_status", REVIEW_STATES), name="ck_register_entries_review"),
        CheckConstraint(_in("id_kind", ("standard12", "nonstandard")), name="ck_register_entries_kind"),
        CheckConstraint(_in("extraction_method", ("text_layer", "ocr", "manual")),
                        name="ck_register_entries_method"),
        CheckConstraint("seat_number IS NULL OR seat_number >= 1", name="ck_register_entries_seat"),
        Index("ix_register_entries_reg_session", "register_number", "session_id"),
        Index("ix_register_entries_reg_review", "register_number", "review_status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), index=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pdf_pages.id", ondelete="CASCADE"), index=True)
    sheet_id: Mapped[int | None] = mapped_column(ForeignKey("seating_sheets.id", ondelete="CASCADE"), nullable=True, index=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("exam_sessions.id", ondelete="SET NULL"), nullable=True, index=True)
    register_number: Mapped[str] = mapped_column(String(32))
    id_kind: Mapped[str] = mapped_column(String(15), default="standard12")
    seat_number: Mapped[int | None] = mapped_column(Integer, nullable=True)  # NULL = not determinable
    subject_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    x0: Mapped[float | None] = mapped_column(Float, nullable=True)
    y0: Mapped[float | None] = mapped_column(Float, nullable=True)
    x1: Mapped[float | None] = mapped_column(Float, nullable=True)
    y1: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_text: Mapped[str | None] = mapped_column(String(300), nullable=True)
    extraction_method: Mapped[str] = mapped_column(String(20), default="text_layer")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_status: Mapped[str] = mapped_column(String(20), default="pending")
    reviewed_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class SeatPosition(Base):
    """Geometry of one seat cell on a sheet (from word coordinates, OCR or manual marking)."""
    __tablename__ = "seat_positions"
    __table_args__ = (
        UniqueConstraint("sheet_id", "seat_number", name="uq_seat_positions_sheet_seat"),
        CheckConstraint("seat_number >= 1", name="ck_seat_positions_seat"),
        CheckConstraint(_in("mapping_method", ("coordinates", "ocr", "manual")), name="ck_seat_positions_method"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sheet_id: Mapped[int] = mapped_column(ForeignKey("seating_sheets.id", ondelete="CASCADE"), index=True)
    seat_number: Mapped[int] = mapped_column(Integer)
    row_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    col_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    x0: Mapped[float | None] = mapped_column(Float, nullable=True)
    y0: Mapped[float | None] = mapped_column(Float, nullable=True)
    x1: Mapped[float | None] = mapped_column(Float, nullable=True)
    y1: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_empty: Mapped[bool] = mapped_column(Boolean, default=False)
    entry_id: Mapped[int | None] = mapped_column(ForeignKey("register_entries.id", ondelete="SET NULL"), nullable=True, index=True)
    mapping_method: Mapped[str] = mapped_column(String(20), default="coordinates")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class SheetSubject(Base):
    """Subject summary line printed on a hall page (used to cross-check the seat grid)."""
    __tablename__ = "sheet_subjects"
    __table_args__ = (
        CheckConstraint(_in("count_status", ("unchecked", "ok", "mismatch", "ambiguous")),
                        name="ck_sheet_subjects_count_status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sheet_id: Mapped[int] = mapped_column(ForeignKey("seating_sheets.id", ondelete="CASCADE"), index=True)
    subject_code: Mapped[str] = mapped_column(String(30))
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    declared_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expanded_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    register_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # compressed ranges as printed
    count_status: Mapped[str] = mapped_column(String(15), default="unchecked")


class ReviewIssue(Base):
    """Anything a human must look at: conflicts, mismatches, low confidence, OCR gaps."""
    __tablename__ = "review_issues"
    __table_args__ = (
        CheckConstraint(_in("severity", ("info", "warning", "error")), name="ck_review_issues_severity"),
        CheckConstraint(_in("status", ("open", "resolved", "dismissed")), name="ck_review_issues_status"),
        Index("ix_review_issues_status_kind", "status", "kind"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), index=True)
    page_id: Mapped[int | None] = mapped_column(ForeignKey("pdf_pages.id", ondelete="SET NULL"), nullable=True, index=True)
    entry_id: Mapped[int | None] = mapped_column(ForeignKey("register_entries.id", ondelete="SET NULL"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(10), default="warning")
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(15), default="open")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    resolved_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)


# ----------------------------------------------------------------------------- Phase 3 (migration 0006)
ENTRY_STATES = ("pending", "approved", "rejected", "imported")


class DocumentExtraction(Base):
    """Document-level result of the timetable extraction (one per version)."""
    __tablename__ = "document_extractions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), unique=True)
    exam_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    session_label: Mapped[str | None] = mapped_column(String(10), nullable=True)
    academic_year: Mapped[str | None] = mapped_column(String(20), nullable=True)
    department: Mapped[str | None] = mapped_column(String(150), nullable=True)
    semester: Mapped[int | None] = mapped_column(Integer, nullable=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)      # JSON list
    register_numbers: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list (sensitive)
    flags: Mapped[str | None] = mapped_column(Text, nullable=True)             # JSON list
    issues: Mapped[str | None] = mapped_column(Text, nullable=True)            # JSON list
    ocr_language: Mapped[str | None] = mapped_column(String(40), nullable=True)
    text_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    extracted_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    imported_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    imported_by: Mapped[str | None] = mapped_column(String(80), nullable=True)


class TimetableEntry(Base):
    """One extracted timetable row. Nothing reaches `exams` until an administrator imports it."""
    __tablename__ = "timetable_entries"
    __table_args__ = (
        CheckConstraint(_in("review_status", ENTRY_STATES), name="ck_timetable_entries_review"),
        CheckConstraint("session IS NULL OR session IN ('FN','AN')", name="ck_timetable_entries_session"),
        UniqueConstraint("version_id", "row_no", name="uq_timetable_entries_version_row"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), index=True)
    row_no: Mapped[int] = mapped_column(Integer)
    page_index: Mapped[int] = mapped_column(Integer, default=0)
    exam_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    start_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    end_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    session: Mapped[str | None] = mapped_column(String(2), nullable=True)
    subject_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    subject_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    department: Mapped[str | None] = mapped_column(String(150), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    semester: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True, index=True)
    raw_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source: Mapped[str] = mapped_column(String(15), default="text_layer")   # text_layer | table | ocr | manual
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    flags: Mapped[str | None] = mapped_column(Text, nullable=True)              # JSON list
    uncertain_fields: Mapped[str | None] = mapped_column(Text, nullable=True)   # JSON list
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    review_status: Mapped[str] = mapped_column(String(15), default="pending")
    reviewed_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    imported_exam_id: Mapped[int | None] = mapped_column(ForeignKey("exams.id", ondelete="SET NULL"), nullable=True, index=True)


class ExtractionEdit(Base):
    """Audit trail of every human correction to an extracted value."""
    __tablename__ = "extraction_edits"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), index=True)
    entry_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)  # NULL = document header field
    field: Mapped[str] = mapped_column(String(40))
    old_value: Mapped[str | None] = mapped_column(String(500), nullable=True)
    new_value: Mapped[str | None] = mapped_column(String(500), nullable=True)
    edited_by: Mapped[str] = mapped_column(String(80))
    edited_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    reason: Mapped[str | None] = mapped_column(String(300), nullable=True)


class DocumentEvent(Base):
    """Processing history of a document version (upload, extraction, OCR, review, import, downloads)."""
    __tablename__ = "document_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), index=True)
    event: Mapped[str] = mapped_column(String(40))
    actor: Mapped[str] = mapped_column(String(80))
    detail: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# ----------------------------------------------------------------------------- VSB official-source integration (migration 0012)
VSB_LINK_STATUSES = ("discovered", "downloaded", "unchanged", "duplicate", "unavailable", "failed", "blocked", "skipped")


class VsbSourceLink(Base):
    """One PDF link found on the official V.S.B. Engineering College site, with its download state.
    Rows are only ever created from links actually present on an official page; nothing is guessed."""
    __tablename__ = "vsb_source_links"
    __table_args__ = (
        UniqueConstraint("url", name="uq_vsb_source_links_url"),
        CheckConstraint(_in("download_status", VSB_LINK_STATUSES), name="ck_vsb_source_links_status"),
        CheckConstraint(_in("doc_kind", DOC_KINDS), name="ck_vsb_source_links_kind"),
        CheckConstraint("session IS NULL OR session IN ('FN','AN')", name="ck_vsb_source_links_session"),
        Index("ix_vsb_source_links_kind_date", "doc_kind", "exam_date", "session"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url: Mapped[str] = mapped_column(String(1000))
    title: Mapped[str] = mapped_column(String(300))
    doc_kind: Mapped[str] = mapped_column(String(30), default="other")
    exam_date: Mapped[date | None] = mapped_column(Date, nullable=True)       # only when printed in the link text / file name
    session: Mapped[str | None] = mapped_column(String(2), nullable=True)
    listing_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    upload_month: Mapped[str | None] = mapped_column(String(7), nullable=True)  # YYYY-MM taken from /wp-content/uploads/YYYY/MM/
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)  # server Last-Modified header, if sent
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    still_listed: Mapped[bool] = mapped_column(Boolean, default=True)
    download_status: Mapped[str] = mapped_column(String(20), default="discovered")
    last_http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_downloaded_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("official_documents.id", ondelete="SET NULL"), nullable=True, index=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)


class VsbCrawlRun(Base):
    """History of every discovery run (manual or scheduled)."""
    __tablename__ = "vsb_crawl_runs"
    __table_args__ = (CheckConstraint(_in("status", ("running", "ok", "partial", "failed")), name="ck_vsb_crawl_runs_status"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    trigger: Mapped[str] = mapped_column(String(20), default="manual")
    actor: Mapped[str] = mapped_column(String(80), default="system")
    status: Mapped[str] = mapped_column(String(10), default="running")
    page_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    links_found: Mapped[int] = mapped_column(Integer, default=0)
    new_links: Mapped[int] = mapped_column(Integer, default=0)
    downloaded: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    unavailable: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)


# ----------------------------------------------------------------------------- VSB hall/seat allocation workflow (migration 0013)
VSB_BATCH_STATUSES = ("draft", "published", "superseded", "withdrawn")
VSB_REVIEW_STATES = ("pending", "approved", "rejected")

# ----------------------------------------------------------------------------- VSB Official Verification Status (migration 0014)
# Assigned at import time from the examination date/session and provenance evidence.
# FULLY_VERIFIED  — both hall-list PDF and seat-sheet PDF confirmed for this session (17 Nov 2026 AN: 627 records).
# HALL_LIST_CONFIRMED  — hall-list PDF confirmed; seat not independently verified (17 Nov FN + 18 Nov: 1,159 records).
# UNRESOLVED      — no official PDF confirmation available for this session (16 Nov 2026: 1,520 records).
VSB_VERIF_STATUSES = ("FULLY_VERIFIED", "HALL_LIST_CONFIRMED", "UNRESOLVED")


class VsbAllocBatch(Base):
    """One examination session (date + FN/AN) built from a hall-allotment PDF version and a seating-allotment PDF version.
    A batch is a PROPOSAL until an administrator publishes it; publishing only exposes records that were individually approved."""
    __tablename__ = "vsb_alloc_batches"
    __table_args__ = (
        CheckConstraint(_in("status", VSB_BATCH_STATUSES), name="ck_vsb_alloc_batches_status"),
        CheckConstraint("session IN ('FN','AN')", name="ck_vsb_alloc_batches_session"),
        Index("ix_vsb_alloc_batches_session", "exam_date", "session"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exam_date: Mapped[date] = mapped_column(Date)
    session: Mapped[str] = mapped_column(String(2))
    exam_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    hall_version_id: Mapped[int | None] = mapped_column(ForeignKey("document_versions.id", ondelete="SET NULL"), nullable=True, index=True)
    seat_version_id: Mapped[int | None] = mapped_column(ForeignKey("document_versions.id", ondelete="SET NULL"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(15), default="draft")
    parser_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)            # JSON statistics
    created_by: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    published_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    withdrawn_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    withdraw_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)


class VsbAllocRecord(Base):
    """One student's proposed hall and seat for one session. Students only ever see rows that are approved AND published."""
    __tablename__ = "vsb_alloc_records"
    __table_args__ = (
        UniqueConstraint("batch_id", "register_number", name="uq_vsb_alloc_records_batch_reg"),
        CheckConstraint(_in("review_status", VSB_REVIEW_STATES), name="ck_vsb_alloc_records_review"),
        CheckConstraint("verification_status IN ('FULLY_VERIFIED', 'HALL_LIST_CONFIRMED', 'UNRESOLVED')", name="ck_vsb_alloc_records_verif"),
        Index("ix_vsb_alloc_records_reg_pub", "register_number", "published"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("vsb_alloc_batches.id", ondelete="CASCADE"), index=True)
    register_number: Mapped[str] = mapped_column(String(32), index=True)
    id_kind: Mapped[str] = mapped_column(String(15), default="standard12")
    student_id: Mapped[int | None] = mapped_column(ForeignKey("students.id", ondelete="SET NULL"), nullable=True, index=True)
    department: Mapped[str | None] = mapped_column(String(150), nullable=True)
    department_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    subject_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    subject_title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    hall: Mapped[str | None] = mapped_column(String(100), nullable=True)
    seat: Mapped[str | None] = mapped_column(String(30), nullable=True)
    sources: Mapped[str] = mapped_column(String(10), default="both")
    flags: Mapped[str | None] = mapped_column(Text, nullable=True)              # JSON list of machine codes
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)             # JSON: pages, hall as printed in each PDF, notes
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Official verification status (migration 0014): set at import time; editing a critical field resets it to UNRESOLVED.
    # FULLY_VERIFIED = hall+seat PDFs both confirmed (17 Nov AN).
    # HALL_LIST_CONFIRMED = hall PDF confirmed, seat not independently verified (17 Nov FN, 18 Nov).
    # UNRESOLVED     = no official PDF confirmation (16 Nov all sessions).
    verification_status: Mapped[str] = mapped_column(String(24), default="UNRESOLVED")
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    review_status: Mapped[str] = mapped_column(String(10), default="pending")
    review_note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    allotment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)    # set when bridged into `allotments`


class VsbAllocIssue(Base):
    __tablename__ = "vsb_alloc_issues"
    __table_args__ = (
        CheckConstraint(_in("severity", ("info", "warning", "error")), name="ck_vsb_alloc_issues_severity"),
        CheckConstraint(_in("status", ("open", "resolved", "dismissed")), name="ck_vsb_alloc_issues_status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("vsb_alloc_batches.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(10), default="warning")
    message: Mapped[str] = mapped_column(Text)
    register_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    hall: Mapped[str | None] = mapped_column(String(100), nullable=True)
    subject_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="open")
    resolved_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(String(300), nullable=True)


class VsbAllocEdit(Base):
    """Audit trail of every administrator correction to a proposed record."""
    __tablename__ = "vsb_alloc_edits"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("vsb_alloc_records.id", ondelete="CASCADE"), index=True)
    field: Mapped[str] = mapped_column(String(40))
    old_value: Mapped[str | None] = mapped_column(String(300), nullable=True)
    new_value: Mapped[str | None] = mapped_column(String(300), nullable=True)
    edited_by: Mapped[str] = mapped_column(String(80))
    edited_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    reason: Mapped[str | None] = mapped_column(String(300), nullable=True)


# ----------------------------------------------------------------------------- V7 live monitoring (migration 0016)
LIVE_STATUSES = ("CONFIRMED", "HALL_ONLY", "SEAT_ONLY", "CONFLICT", "MANUAL_REVIEW")


class LiveAllotment(Base):
    """One register number's allotment for one (date, session, subject), derived AUTOMATICALLY from the current official
    hall-allotment and seating-allotment PDFs. It is a search index, not a source of truth: every row names the PDF versions
    and pages it came from, and the displayed page image is rendered from that very PDF. When a PDF changes, affected rows
    are superseded (is_current=False, history kept) and a new revision is written."""
    __tablename__ = "live_allotments"
    __table_args__ = (
        UniqueConstraint("register_number", "exam_date", "session", "subject_code", "fingerprint", name="uq_live_allotments_identity"),
        CheckConstraint(_in("status", LIVE_STATUSES), name="ck_live_allotments_status"),
        CheckConstraint("session IN ('FN','AN')", name="ck_live_allotments_session"),
        Index("ix_live_allotments_reg_current", "register_number", "is_current"),
        Index("ix_live_allotments_date_session", "exam_date", "session"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    register_number: Mapped[str] = mapped_column(String(20))
    exam_date: Mapped[date] = mapped_column(Date)
    session: Mapped[str] = mapped_column(String(2))
    subject_code: Mapped[str] = mapped_column(String(30), default="")
    subject_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    programme: Mapped[str | None] = mapped_column(String(30), nullable=True)
    department: Mapped[str | None] = mapped_column(String(150), nullable=True)
    hall: Mapped[str | None] = mapped_column(String(100), nullable=True)
    seat: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="MANUAL_REVIEW")
    flags: Mapped[str] = mapped_column(Text, default="[]")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    hall_version_id: Mapped[int | None] = mapped_column(ForeignKey("document_versions.id", ondelete="SET NULL"), nullable=True, index=True)
    seat_version_id: Mapped[int | None] = mapped_column(ForeignKey("document_versions.id", ondelete="SET NULL"), nullable=True, index=True)
    hall_page: Mapped[int | None] = mapped_column(Integer, nullable=True)      # 0-based
    seat_page: Mapped[int | None] = mapped_column(Integer, nullable=True)      # 0-based
    hall_source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    seat_source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    hall_filename: Mapped[str | None] = mapped_column(String(200), nullable=True)
    seat_filename: Mapped[str | None] = mapped_column(String(200), nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    revised_from_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_verified_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    superseded_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class LiveIngest(Base):
    """Processing queue / history: one row per downloaded allotment PDF version."""
    __tablename__ = "live_ingests"
    __table_args__ = (UniqueConstraint("version_id", name="uq_live_ingests_version"),
                      CheckConstraint(_in("status", ("pending", "processing", "ok", "failed")), name="ck_live_ingests_status"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(12), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    records: Mapped[int] = mapped_column(Integer, default=0)
    pages: Mapped[int] = mapped_column(Integer, default=0)
    ocr_pages: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class VsbSourceHealth(Base):
    """Health of each discovery method / listing page (HTML, WordPress REST, sitemap)."""
    __tablename__ = "vsb_source_health"
    __table_args__ = (UniqueConstraint("source_key", name="uq_vsb_source_health_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_key: Mapped[str] = mapped_column(String(300))
    method: Mapped[str] = mapped_column(String(20))
    url: Mapped[str] = mapped_column(String(1000))
    last_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_status: Mapped[str] = mapped_column(String(10), default="unknown")     # ok | failed | skipped | unknown
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    items_found: Mapped[int] = mapped_column(Integer, default=0)


class LiveWatch(Base):
    """Administrator-managed e-mail watch: tell this address when this register number gets a new/revised allotment."""
    __tablename__ = "live_watches"
    __table_args__ = (UniqueConstraint("register_number", "email", name="uq_live_watches_reg_email"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    register_number: Mapped[str] = mapped_column(String(20), index=True)
    email: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(String(80), default="system")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class LiveNotification(Base):
    __tablename__ = "live_notifications"
    __table_args__ = (UniqueConstraint("watch_id", "fingerprint", name="uq_live_notifications_once"),
                      CheckConstraint(_in("status", ("pending", "sent", "outbox", "failed", "skipped")), name="ck_live_notifications_status"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    watch_id: Mapped[int] = mapped_column(ForeignKey("live_watches.id", ondelete="CASCADE"), index=True)
    allotment_id: Mapped[int | None] = mapped_column(ForeignKey("live_allotments.id", ondelete="SET NULL"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(12), default="new")         # new | revised
    fingerprint: Mapped[str] = mapped_column(String(64))
    subject: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(10), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class LiveSyncLog(Base):
    """History of optional cloud (Supabase) synchronisation runs."""
    __tablename__ = "live_sync_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target: Mapped[str] = mapped_column(String(20), default="supabase")
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="running")          # running | ok | failed | skipped
    records: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)


class CampusPoint(Base):
    """Administrator-verified campus reference point (entrance, landmark). Coordinates are never invented."""
    __tablename__ = "campus_points"
    __table_args__ = (UniqueConstraint("name", name="uq_campus_points_name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), default="entrance")
    name: Mapped[str] = mapped_column(String(100))
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    source: Mapped[str | None] = mapped_column(String(300), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class HallLocationHistory(Base):
    """Review trail for hall-location edits (who changed what, from which source)."""
    __tablename__ = "hall_location_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hall_id: Mapped[int] = mapped_column(ForeignKey("halls.id", ondelete="CASCADE"), index=True)
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(20))
    before: Mapped[str | None] = mapped_column(Text, nullable=True)
    after: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
