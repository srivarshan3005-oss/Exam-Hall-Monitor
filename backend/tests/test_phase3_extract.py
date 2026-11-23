"""Phase 3: real PDF text extraction, OCR fallback and timetable parsing (no database)."""
import os, tempfile
from datetime import date
import pytest
from app import doc_extract as dx
import pdf_factory as pf

needs_ocr = pytest.mark.skipif(not dx.ocr_available(), reason="Tesseract/pytesseract not installed")


def run(data: bytes, **kw):
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(data)
    try:
        pages = dx.read_pdf(f.name, **kw)
        return pages, dx.parse_timetable(pages)
    finally:
        os.unlink(f.name)


def test_digital_table_layout():
    pages, r = run(pf.table_pdf())
    assert pages[0].method == "text_layer" and pages[0].tables
    assert [(e.subject_code, e.exam_date, e.start_time, e.end_time, e.session) for e in r.entries] == [
        ("CS3251", date(2027, 1, 15), "09:30", "12:30", "FN"),
        ("MA3151", date(2027, 1, 15), "13:30", "16:30", "AN"),
        ("EC3452", date(2027, 1, 18), "09:30", "12:30", "FN")]
    assert r.entries[1].subject_name == "Matrices and Calculus"


def test_inherited_date_is_flagged_not_silent():
    _, r = run(pf.table_pdf())
    e = r.entries[1]
    assert "date_inherited_from_previous_row" in e.flags and "exam_date" in e.uncertain_fields
    assert e.confidence < r.entries[0].confidence


def test_header_fields_and_instructions():
    _, r = run(pf.table_pdf())
    h = r.header
    assert h.exam_name.startswith("End Semester Examinations") and h.academic_year == "2026-27"
    assert h.department == "Electronics and Communication Engineering" and h.semester == 3
    assert any("hall ticket" in i for i in h.instructions) and h.register_numbers == ["990025106001"]


def test_free_text_layout_with_mixed_date_and_time_formats():
    _, r = run(pf.text_pdf())
    ok = [e for e in r.entries if e.subject_code]
    assert [(e.subject_code, e.exam_date.isoformat(), e.start_time, e.end_time) for e in ok] == [
        ("CS3251", "2027-01-15", "09:30", "12:30"), ("MA3151", "2027-01-15", "13:30", "16:30"),
        ("EC3452", "2027-01-18", "09:30", "12:30")]


def test_month_year_words_are_not_subject_codes():
    _, r = run(pf.text_pdf())
    assert all(e.subject_code not in ("DEC2026", "JAN2027", "YEAR2026") for e in r.entries)


def test_missing_information_is_never_invented():
    _, r = run(pf.text_pdf())
    bad = [e for e in r.entries if e.subject_code is None]
    assert len(bad) == 1
    e = bad[0]
    assert e.start_time is None and e.end_time is None            # session AN printed, times not printed
    assert "missing_subject_code" in e.flags and e.confidence < dx.LOW_CONF


def test_ambiguous_day_month_is_reported():
    _, r = run(pf.text_pdf(["Examinations 2026-27", "05/06/2027 FN 09:30 - 12:30 CS3251 Programming in C"]))
    assert "date_format_assumed_day_first" in r.header.flags
    assert "ambiguous_date_format" in r.entries[0].flags and r.entries[0].exam_date == date(2027, 6, 5)


def test_unambiguous_date_resolves_convention():
    assert dx.detect_dmy(["25/12/2026"]) == (True, True)
    assert dx.detect_dmy(["12/25/2026"]) == (False, True)


def test_impossible_dates_are_not_parsed():
    assert dx.find_dates("31/02/2027") == [] and dx.find_dates("99-99-2027") == []


def test_time_parsing_and_invalid_times():
    assert dx.find_time_range("9.30 am - 12.30 pm")[:2] == ("09:30", "12:30")
    assert dx.find_time_range("01:30 PM to 04:30 PM")[:2] == ("13:30", "16:30")
    assert dx.find_time_range("09:30 - 25:61")[:2] == ("09:30", None)


def test_blank_pdf_yields_no_entries_and_an_issue():
    _, r = run(pf.blank_pdf(), allow_ocr=False)
    assert r.entries == [] and r.issues


def test_register_numbers_only_standard_12_digit():
    assert dx.find_register_numbers("a 990025106001 b 12345 c 9900251060011") == ["990025106001"]


def test_invalid_language_code_rejected():
    with pytest.raises(ValueError):
        run(pf.table_pdf(), lang="eng;rm -rf")


@needs_ocr
def test_scanned_pdf_uses_ocr_and_is_lower_confidence():
    pages, r = run(pf.scanned(pf.table_pdf()))
    assert pages[0].method == "ocr" and pages[0].ocr_confidence and pages[0].ocr_confidence > 0.6
    codes = [(e.subject_code, e.exam_date.isoformat(), e.start_time) for e in r.entries if e.subject_code]
    assert ("CS3251", "2027-01-15", "09:30") in codes and ("EC3452", "2027-01-18", "09:30") in codes
    assert all("ocr_source" in e.flags and e.confidence < 0.8 for e in r.entries if e.subject_code)


@needs_ocr
def test_poor_quality_scan_never_produces_confident_data():
    pages, r = run(pf.scanned(pf.table_pdf(), dpi=80, noise=True))
    assert all(e.confidence < dx.LOW_CONF + 0.01 for e in r.entries)   # OCR output is always flagged for review


@needs_ocr
def test_force_ocr_on_digital_pdf():
    pages, _ = run(pf.table_pdf(), force_ocr=True)
    assert pages[0].method == "ocr"


def test_render_page_png():
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pf.table_pdf())
    try:
        assert dx.render_page_png(f.name, 0)[:8] == b"\x89PNG\r\n\x1a\n"
        with pytest.raises(IndexError):
            dx.render_page_png(f.name, 5)
    finally:
        os.unlink(f.name)
