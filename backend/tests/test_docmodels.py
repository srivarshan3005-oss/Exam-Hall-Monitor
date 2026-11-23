"""Smart Hall Finder schema: can represent 12-digit + non-standard ids, empty seats, coordinates, review state."""
from datetime import date
import pytest
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from app import doc_models as d
from app.regno import id_kind


def chain(db):
    doc = d.OfficialDocument(source_url="https://example.test/wp-content/uploads/2026/11/test-FN-SEAT.pdf",
                             title="TEST FN SEAT", doc_kind="seating_allotment", exam_date=date(2027, 1, 15),
                             session="FN", origin="upload")
    ver = d.DocumentVersion(document=doc, version_no=1, sha256="a" * 64, size_bytes=10, storage_path="x.pdf")
    page = d.PdfPage(version=ver, page_index=0, width_pt=595.0, height_pt=842.0)
    db.add_all([doc, ver, page])
    db.flush()
    hall = d.Hall(code="TEST HALL 01")
    sess = d.ExamSession(exam_date=date(2027, 1, 15), session="FN", title="TEST EXAM")
    db.add_all([hall, sess])
    db.flush()
    sheet = d.SeatingSheet(version_id=ver.id, page_id=page.id, session_id=sess.id, hall_id=hall.id,
                           hall_code_raw="TEST HALL 01", declared_total=3)
    db.add(sheet)
    db.flush()
    return doc, ver, page, sheet, sess


def test_full_chain_with_standard_nonstandard_and_unknown_seat(db):
    doc, ver, page, sheet, sess = chain(db)
    for reg, seat in (("990025106001", 2), ("26144691179", None), ("990025106003", 28)):
        db.add(d.RegisterEntry(version_id=ver.id, page_id=page.id, sheet_id=sheet.id, session_id=sess.id,
                               register_number=reg, id_kind=id_kind(reg), seat_number=seat,
                               x0=10.5, y0=20.5, x1=80.0, y1=30.0, extraction_method="text_layer", confidence=0.98))
    db.add(d.SeatPosition(sheet_id=sheet.id, seat_number=1, is_empty=True, mapping_method="coordinates"))
    db.add(d.SheetSubject(sheet_id=sheet.id, subject_code="TEST101", declared_count=3, expanded_count=3,
                          register_text="990025106001, 003", count_status="ok"))
    db.add(d.ReviewIssue(version_id=ver.id, page_id=page.id, kind="nonstandard_id", severity="warning", message="m"))
    db.commit()
    rows = db.scalars(select(d.RegisterEntry).order_by(d.RegisterEntry.register_number)).all()
    assert [(r.register_number, r.id_kind, r.seat_number, r.review_status) for r in rows] == [
        ("26144691179", "nonstandard", None, "pending"),
        ("990025106001", "standard12", 2, "pending"),
        ("990025106003", "standard12", 28, "pending")]
    assert page.page_index == 0 and ver.pages[0].image_path is None


def test_cascade_delete_removes_everything_below_a_document(db):
    doc, ver, page, sheet, sess = chain(db)
    db.add(d.RegisterEntry(version_id=ver.id, page_id=page.id, sheet_id=sheet.id, register_number="990025106001"))
    db.commit()
    db.delete(doc)
    db.commit()
    for model in (d.DocumentVersion, d.PdfPage, d.SeatingSheet, d.RegisterEntry):
        assert db.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.parametrize("make", [
    lambda ids: d.OfficialDocument(source_url="u", title="t", doc_kind="bogus"),
    lambda ids: d.OfficialDocument(source_url="u", title="t", session="XX"),
    lambda ids: d.PdfPage(version_id=ids["ver"], page_index=-1),
    lambda ids: d.RegisterEntry(version_id=ids["ver"], page_id=ids["page"], register_number="1", review_status="maybe"),
    lambda ids: d.RegisterEntry(version_id=ids["ver"], page_id=ids["page"], register_number="1", seat_number=0),
    lambda ids: d.RegisterEntry(version_id=ids["ver"], page_id=ids["page"], register_number="1", extraction_method="guess"),
    lambda ids: d.SeatPosition(sheet_id=ids["sheet"], seat_number=1, mapping_method="guess"),
    lambda ids: d.ReviewIssue(version_id=ids["ver"], kind="k", message="m", severity="fatal"),
], ids=["doc-kind", "doc-session", "page-negative", "entry-review", "entry-seat0", "entry-method", "seat-method", "issue-severity"])
def test_check_constraints_reject_invalid_values(db, make):
    doc, ver, page, sheet, sess = chain(db)
    db.commit()
    ids = {"ver": ver.id, "page": page.id, "sheet": sheet.id}
    db.add(make(ids))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_unique_constraints(db):
    doc, ver, page, sheet, sess = chain(db)
    db.commit()
    for obj in (d.PdfPage(version_id=ver.id, page_index=0),
                d.DocumentVersion(document_id=doc.id, version_no=1, sha256="b" * 64, size_bytes=1, storage_path="y"),
                d.DocumentVersion(document_id=doc.id, version_no=2, sha256="a" * 64, size_bytes=1, storage_path="y"),
                d.OfficialDocument(source_url=doc.source_url, title="dup"),
                d.Hall(code="TEST HALL 01")):
        db.add(obj)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    db.add(d.SeatPosition(sheet_id=sheet.id, seat_number=5))
    db.commit()
    db.add(d.SeatPosition(sheet_id=sheet.id, seat_number=5))
    with pytest.raises(IntegrityError):
        db.commit()


def test_hall_directory_defaults_to_unverified_unknown_location(db):
    h = d.Hall(code="MB III 01")
    db.add(h); db.commit()
    assert (h.building, h.block, h.floor, h.room, h.verified) == (None, None, None, None, False)


def test_register_number_index_lookup_uses_index(db):
    """The register-number lookup must be served by an index (SQLite: query plan; PostgreSQL: plan with seq-scan off,
    because a tiny test table would otherwise legitimately be scanned)."""
    from app.database import engine
    sql = "SELECT * FROM register_entries WHERE register_number='990025106001'"
    with engine.connect() as conn:
        if conn.dialect.name == "sqlite":
            plan = conn.exec_driver_sql("EXPLAIN QUERY PLAN " + sql).fetchall()
            assert any("ix_register_entries_reg" in str(row) for row in plan)
        else:
            conn.exec_driver_sql("SET enable_seqscan = off")
            plan = conn.exec_driver_sql("EXPLAIN " + sql).fetchall()
            assert any("ix_register_entries_reg" in str(row) for row in plan)
