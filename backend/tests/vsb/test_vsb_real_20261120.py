"""Regression tests on the REAL 20-Nov-2026 AN pages (20.11.26-AN-HALL.pdf, 20.11.26-AN-SEAT.pdf).

Fixtures (tests/vsb/real_20nov26/*.pages.txt) are the official PDFs' text layer, one page per '\\f'. They contain real register
numbers that VSB itself publishes on its website. Success is NOT 'records were extracted': every figure is compared with
independent_compare.py, which shares no code with the parser, and with totals printed in the PDFs.
Limits: text layer only. No word boxes, so the coordinate (PyMuPDF) seat path is exercised by test_vsb_pdf_roundtrip.py on PDFs
generated from this same text, not on VSB's binary files.
"""
import re
from datetime import date

import pytest

from app.vsb_alloc.common import PageInput
from app.vsb_alloc.hall_parser import parse_hall_pdf
from app.vsb_alloc.reconcile import reconcile
from app.vsb_alloc.seat_parser import parse_seat_page, parse_seat_pdf
from vsb import independent_compare as IC

D, S = date(2026, 11, 20), "AN"


def _pages(name):
    return [PageInput(i, t) for i, t in enumerate(IC.pages(name))]


@pytest.fixture(scope="module")
def ref():
    return IC.report()


@pytest.fixture(scope="module")
def hall():
    return parse_hall_pdf(_pages("20.11.26-AN-HALL.pages.txt"))


@pytest.fixture(scope="module")
def seat():
    return parse_seat_pdf(_pages("20.11.26-AN-SEAT.pages.txt"))


@pytest.fixture(scope="module")
def rec(hall, seat):
    return reconcile(hall, seat, D, S)


# ---------------------------------------------------------------- the independent reference itself is internally consistent
def test_reference_is_self_consistent(ref):
    assert ref["hall_register_occurrences"] == ref["hall_unique"] == ref["seat_grid_occurrences"] == ref["seat_unique"] == 390
    assert ref["programme_totals_sum"] == 390 and ref["programme_extracted"] == ref["programme_totals"]
    assert not (ref["block_count_mismatch"] or ref["seat_declared_vs_grid"] or ref["table_vs_grid_mismatch"] or ref["hall_disagreements"]
                or ref["only_on_hall_pdf"] or ref["only_on_seat_pdf"] or ref["subject_hall_count_mismatch"] or ref["seat_duplicate_seats"])
    assert ref["serpentine_layout_ok"] and ref["seat_sheets"] == 16 and ref["hall_blocks"] == 42 and ref["subject_hall_pairs_checked"] == 39


# ---------------------------------------------------------------- hall PDF parser vs the PDF
def test_hall_pdf_departments_and_totals(hall, ref):
    got = {t.department: (t.declared, t.extracted, t.ok) for t in hall.dept_totals}
    assert got == {p: (n, n, True) for p, n in ref["programme_totals"].items()}
    assert len(hall.groups) == 42 and hall.total_students() == 390
    assert [i for i in hall.all_issues() if i.severity in ("error", "warning")] == []


def test_hall_pdf_hall_totals_and_subjects(hall, ref):
    assert {k[2]: v for k, v in hall.hall_totals().items()} == ref["hall_totals"]
    # every block carries the subject code and title printed above it
    ems = [g for g in hall.groups if g.subject_code == "23MET303"]
    assert ems and all(g.subject_title == "ENGINEERING MATERIALS AND METALLURGY" for g in ems)
    assert {g.department for g in hall.groups if g.subject_code == "23CST402"} == {"BE-CCE", "BE-CSE (AIML)", "B.TECH. - AIDS", "B.TECH. - CSBS"}


def test_numbers_that_are_not_register_numbers_are_not_students(hall):
    """Department totals (34, 79...), hall totals, seat/page numbers and subject codes never become register numbers."""
    regs = {r for g in hall.groups for r in g.register_numbers}
    assert all(re.fullmatch(r"9225\d{8}", r) for r in regs)
    assert not regs & {"34", "79", "75", "000000000034"}


# ---------------------------------------------------------------- seat PDF parser vs the PDF
def test_seat_sheets_match_reference(seat, ref):
    assert len(seat.sheets) == 16
    assert {s.hall: s.grid_count for s in seat.sheets} == ref["seat_hall_totals"]
    assert {s.hall: s.declared_total for s in seat.sheets} == ref["seat_hall_totals"]
    assert [i for i in seat.all_issues() if i.severity == "error"] == []


def test_subject_table_abbreviated_ranges_expand_correctly(seat, ref):
    """'922523105015, 017, 021 ...', '922525105052 - 055, 057 - 063, 301 - 302' etc. reproduce the grid exactly."""
    for sh in seat.sheets:
        table = {r for sub in sh.subjects for r in sub.register_numbers}
        assert table == {a.register_number for a in sh.assignments} == set(IC.seat_pdf()[sh.hall]["grid"]), sh.hall
        assert all(len(sub.register_numbers) == sub.declared for sub in sh.subjects), sh.hall


def test_subject_table_text_order_and_wrapped_titles(seat):
    """MB III 02 prints the first subject's numbers BEFORE its code line; MB III A103 does so for 23CST402 and wraps titles."""
    by = {s.hall: s for s in seat.sheets}
    s02 = {x.code: x for x in by["MB III 02"].subjects}
    assert len(s02["23EET301"].register_numbers) == 13 and s02["23EET301"].register_numbers[0] == "922523105015"
    s103 = {x.code: x for x in by["MB III A103"].subjects}
    assert len(s103["23CST402"].register_numbers) == 9 and "922524243025" in s103["23CST402"].register_numbers
    assert s103["23BMT301"].title == "FUNDAMENTALS OF ELECTRONIC DEVICES AND CIRCUITS"


# ---------------------------------------------------------------- reconciliation vs the PDFs
def test_hall_and_seat_assignments_equal_the_reference(rec, ref):
    assert len(rec.records) == 390 and rec.exam_date == D and rec.session == S
    wrong, missing = [], []
    for r in rec.records:
        want = ref["assignments"].get(r.register_number)
        if want is None:
            missing.append(r.register_number)
            continue
        if (r.hall, r.seat) != (want[0], want[1]) and (r.hall, r.seat) != (want[0], None):
            wrong.append((r.register_number, r.hall, r.seat, want))
        assert r.subject_code == ref["subject_of"][r.register_number]
        assert r.department == ref["programme_of"][r.register_number]
        assert r.hall_page == ref["page_of_hall"][r.register_number] - 1 and r.seat_page == ref["page_of_seat"][r.register_number] - 1
    assert wrong == [] and missing == []


def test_no_hall_sheet_missing_and_no_none_hall(rec):
    kinds = {i.kind for i in rec.issues}
    assert "hall_sheet_missing" not in kinds and "hall_unreadable" not in kinds
    assert all(r.hall for r in rec.records) and "None" not in " ".join(i.message for i in rec.issues)
    assert {i.kind for i in rec.issues if i.severity == "error"} == set()


def test_text_layer_seats_are_not_called_confirmed(rec):
    """Without word boxes the seat comes from text order: every record must say so (warning) - never FULLY clean."""
    assert all("seat_from_text_order" in r.flags for r in rec.records)
    assert not any(r.confidence > 0.9 for r in rec.records)


def test_partial_hall_a104_keeps_only_real_seats(seat, ref):
    a104 = next(s for s in seat.sheets if s.hall == "MB III A104")
    assert a104.grid_count == 15 and a104.declared_total == 15
    assert sorted(a.seat for a in a104.assignments) == [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 16, 17, 18]
    assert {1, 14, 15, 28, 27, 26, 25, 19, 24, 20, 23, 21, 22} <= set(a104.empty_seats)


# ---------------------------------------------------------------- heading variants / malformed pages
def _page(name, n):
    return PageInput(n, IC.pages(name)[n])


@pytest.mark.parametrize("heading", ["CODE TITLE OF THE PAPER TOTAL REGISTER NUMBERS", "CODE / TITLE OF THE PAPER TOTAL REGISTER NUMBERS",
                                     "SUBJECT CODE TITLE OF THE PAPER TOTAL REGISTER NUMBERS", "CODE - TITLE OF THE PAPER TOTAL REGISTER NUMBERS"])
def test_heading_variants_all_parse(heading):
    pg = _page("20.11.26-AN-SEAT.pages.txt", 8)             # MB III A01
    pg.text = pg.text.replace("CODE TITLE OF THE PAPER TOTAL REGISTER NUMBERS", heading)
    sh = parse_seat_page(pg)
    assert sh.hall == "MB III A01" and len(sh.subjects) == 2 and sh.declared_total == 25
    assert not [i for i in sh.issues if i.kind in ("table_header_missing", "table_header_variant")]


def test_missing_heading_still_reads_table_but_reports_it():
    pg = _page("20.11.26-AN-SEAT.pages.txt", 8)
    pg.text = pg.text.replace("CODE TITLE OF THE PAPER TOTAL REGISTER NUMBERS\n", "")
    sh = parse_seat_page(pg)
    assert [s.code for s in sh.subjects] == ["23CBT302", "23ECT403"] and sh.declared_total == 25
    assert any(i.kind == "table_header_variant" and i.severity == "warning" for i in sh.issues)


def test_malformed_hall_block_is_reported_not_hidden():
    pg = _page("20.11.26-AN-SEAT.pages.txt", 3)             # MB III 101
    pg.text = pg.text.replace("EXAM HALL : MB III 101 Name of the Hall Superindentent :", "Name of the Hall Superindentent :")
    sh = parse_seat_page(pg)
    assert sh.hall is None and any(i.kind == "hall_missing" and i.severity == "error" for i in sh.issues)


def test_unreadable_hall_label_on_hall_pdf_never_becomes_a_hall_named_none():
    """Regression for the reported 'hall_sheet_missing ... None'. A block whose hall cannot be read stays an error of its own."""
    pages = _pages("20.11.26-AN-HALL.pages.txt")
    pages[4].text = pages[4].text.replace("MB III A103 4", "")             # BE-CCE block loses its hall tail
    hd = parse_hall_pdf(pages)
    rc = reconcile(hd, parse_seat_pdf(_pages("20.11.26-AN-SEAT.pages.txt")), D, S)
    kinds = [i.kind for i in rc.issues]
    assert "hall_or_total_missing" in kinds or "department_total_mismatch" in kinds
    assert "hall_sheet_missing" not in kinds
    assert not any("None" in i.message for i in rc.issues)
    # the four CCE students are not published-ready, because the official hall list for them could not be read
    cce = [r for r in rc.records if r.register_number.startswith("9225241180")]
    assert cce == [] or all(r.blocking for r in cce)


def test_incorrect_hall_or_seat_assignment_is_detected():
    h = _pages("20.11.26-AN-HALL.pages.txt")
    s = _pages("20.11.26-AN-SEAT.pages.txt")
    # student 922525105045 moved to the wrong grid cell: swap two registers on the MB III 102 sheet
    s[4].text = s[4].text.replace("922525105051", "922525105045", 1)
    rc = reconcile(parse_hall_pdf(h), parse_seat_pdf(s), D, S)
    errs = {i.kind for i in rc.issues if i.severity == "error"}
    assert errs & {"duplicate_student_in_hall", "grid_table_mismatch", "hall_total_mismatch", "missing_in_seating_pdf"}
    bad = next(r for r in rc.records if r.register_number == "922525105051")
    assert bad.blocking


def test_student_listed_in_a_different_hall_on_the_seat_pdf_is_a_hall_mismatch():
    h = _pages("20.11.26-AN-HALL.pages.txt")
    s = _pages("20.11.26-AN-SEAT.pages.txt")
    s[0].text = s[0].text.replace("922524105045", "922525105051")     # 02 sheet now holds a student that belongs to 102
    rc = reconcile(parse_hall_pdf(h), parse_seat_pdf(s), D, S)
    r = next(r for r in rc.records if r.register_number == "922525105051")
    assert r.blocking and r.hall is None


def test_page_numbers_for_student_navigation(rec):
    one = next(r for r in rec.records if r.register_number == "922525105045")      # EEE, MB III 102
    assert (one.hall, one.hall_page, one.seat_page) == ("MB III 102", 1, 4)       # 0-based: hall PDF page 2, seat PDF page 5
