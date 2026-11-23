"""A page-total mismatch must not hide a student whose own hall (both documents) and own seat cell are consistent."""
from datetime import date

from app.vsb_alloc.common import Issue
from app.vsb_alloc.hall_parser import HallDocument, HallGroup
from app.vsb_alloc.reconcile import reconcile
from app.vsb_alloc.seat_parser import SeatAssignment, SeatDocument, SeatSheet
from app.vsb_live.pipeline import classify

D, S = date(2026, 11, 20), "FN"
REG = "922525106326"


def build(seat_flags=(), dup_seat=False, declared=3):
    regs = [REG, "922525106318", "922525104046"]
    g = HallGroup(0, D, S, "ECE", "23ITT301R", "DATA STRUCTURES", "MB III 308", declared, regs, "raw")
    g.issues.append(Issue("group_count_mismatch", "error", "printed total != read", hall="MB III 308", subject_code="23ITT301R"))
    a = [SeatAssignment(20, REG, 1, 1, flags=list(seat_flags)), SeatAssignment(2, regs[1], 2, 1), SeatAssignment(3 if not dup_seat else 20, regs[2], 3, 1)]
    sh = SeatSheet(0, "MB III 308", D, S, "coordinates", a, [], [], 3, [Issue("hall_total_mismatch", "error", "total", hall="MB III 308")])
    return reconcile(HallDocument("t", [g], [], [], [(D, S)], 1), SeatDocument([sh], [], [(D, S)], 1), D, S)


def rec(res):
    return next(r for r in res.records if r.register_number == REG)


def test_clean_cell_with_failed_totals_is_confirmed():
    r = rec(build())
    assert not r.blocking and "page_total_unmatched" in r.flags
    assert r.hall == "MB III 308" and r.seat == 20
    assert classify(r.flags, hall_doc_present=True, seat_doc_present=True, has_hall=True, has_seat=True) == "CONFIRMED"


def test_guessed_seat_still_needs_review():
    r = rec(build(seat_flags=("seat_from_text_order",)))
    assert "group_check_failed" in r.flags or "hall_check_failed" in r.flags
    assert classify(r.flags, hall_doc_present=True, seat_doc_present=True, has_hall=True, has_seat=True) in ("MANUAL_REVIEW", "CONFLICT")


def test_duplicate_seat_is_not_confirmed():
    r = rec(build(dup_seat=True))
    assert "page_total_unmatched" not in r.flags
