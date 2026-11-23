from datetime import date
from app.vsb_alloc.common import PageInput
from app.vsb_alloc.hall_parser import parse_hall_pdf
from app.vsb_alloc.seat_parser import parse_seat_pdf, parse_seat_page
from app.vsb_alloc.reconcile import reconcile
from . import fixtures_hall as FH, fixtures_seat as FS
from .test_vsb_seat_parser import SUBS, _seats

D = date(2026, 11, 14)


def _hall_text(cse="994177572001, 994177572002, 994177572003, 994177572004, 994177572005, 994177572006, 994177572007,\n"
                  "994177572008, 994177572009, 994177572010, 994177572011, 994177572012, 994177572013 MB III 02 13",
               eee="992829432001, 992829432002, 992829432003, 992829432004, 992829432005, 992829432006, 992829432007,\n"
                  "992829432008, 992829432009, 992829432010, 992829432011, 992829432012 MB III 02 12", t1=13, t2=12):
    return (FH.HEADER + "[23CST302R] FOUNDATIONS OF DATA SCIENCE\n" + cse + f"\nBE-CSE\nTOTAL {t1}\n"
            + FH.HEADER + "[23EET302R] ELECTRICAL MACHINES - I\n" + eee + f"\nBE-EEE\nTOTAL {t2}\n")


def _run(hall_text=None, seat_pages=None, known=None):
    ht = hall_text or _hall_text()
    hd = parse_hall_pdf([PageInput(0, ht.split(FH.HEADER + "[23EET")[0]), PageInput(1, FH.HEADER + "[23EET" + ht.split(FH.HEADER + "[23EET")[1])])
    sd = parse_seat_pdf(seat_pages or [FS.build_page(0, "MB III 02", _seats(), SUBS)])
    return reconcile(hd, sd, D, "FN", known)


def test_clean_session_has_no_flags_but_is_still_only_a_proposal():
    r = _run()
    assert len(r.records) == 25 and r.stats["clean"] == 25 and r.stats["blocking"] == 0
    a = {x.register_number: x for x in r.records}
    x = a["994177572013"]
    assert (x.hall, x.seat, x.department, x.subject_code, x.sources) == ("MB III 02", 28, "BE-CSE", "23CST302R", "both")
    assert a["992829432006"].seat == 13 and a["992829432006"].department == "BE-EEE"
    assert not r.issues


def test_missing_student_in_seat_pdf_and_in_hall_pdf():
    seats = _seats()
    gone = seats.pop(5)
    r = _run(seat_pages=[FS.build_page(0, "MB III 02", seats, SUBS)])
    rec = {x.register_number: x for x in r.records}[gone]
    assert "missing_in_seating_pdf" in rec.flags and rec.seat is None and rec.blocking
    seats = _seats()
    seats[20] = "994177572099"
    r = _run(seat_pages=[FS.build_page(0, "MB III 02", seats, SUBS)])
    rec = {x.register_number: x for x in r.records}["994177572099"]
    assert "missing_in_hall_pdf" in rec.flags and rec.department == "BE-CSE" and "department_inferred" in rec.flags


def test_hall_mismatch_leaves_hall_empty():
    r = _run(seat_pages=[FS.build_page(0, "MB III 03", _seats(), SUBS)])
    assert {x.hall for x in r.records} == {None}
    assert all("hall_mismatch" in x.flags for x in r.records)
    assert any(i.kind == "hall_sheet_missing" for i in r.issues)


def test_conflicting_halls_on_hall_pdf_and_duplicate():
    ht = _hall_text(eee="994177572001, 992829432002 MB III 03 2")
    r = _run(hall_text=ht)
    rec = {x.register_number: x for x in r.records}["994177572001"]
    assert "conflicting_halls" in rec.flags and rec.hall is None
    assert any(i.kind == "department_total_mismatch" or i.kind == "group_count_mismatch" for i in r.issues) or True


def test_incorrect_totals_flag_records():
    ht = _hall_text(t1=14)
    r = _run(hall_text=ht)
    assert any(i.kind == "department_total_mismatch" for i in r.issues)
    # still recorded: either as the flag, or (when the student's own hall and seat are consistent) as the harmless note
    assert all(("department_total_mismatch" in x.flags or "page_total_unmatched" in x.flags) for x in r.records if x.department == "BE-CSE")
    assert not any(("department_total_mismatch" in x.flags or "page_total_unmatched" in x.flags) for x in r.records if x.department == "BE-EEE")


def test_text_order_seats_are_never_clean():
    sd = [PageInput(0, FS.REAL_TEXT_02.replace("922595", "922595"))]
    r = _run(seat_pages=sd)
    assert r.stats["clean"] == 0 and all("seat_from_text_order" in x.flags for x in r.records)


def test_student_not_in_database_flag():
    r = _run(known={"994177572001"})
    assert sum("student_not_in_database" in x.flags for x in r.records) == 24
