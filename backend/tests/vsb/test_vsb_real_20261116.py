"""Regression test on text extracted from the REAL official V.S.B. PDFs 16.11.26-FN-HALL.pdf / 16.11.26-FN-SEAT.pdf.

Source: https://vsbec.edu.in/controller-of-examination/ (fetched 16 Nov 2026 through a text-extraction fetch tool).
Only a SUBSET of pages is stored (small programmes and 7 hall sheets). Register numbers are the genuine printed ones.
This validates parsing of the text layer, NOT the raw-PDF/OCR path (raw PDF bytes could not be downloaded in the build sandbox).
"""
import os, re

import pytest
from app.vsb_alloc.common import PageInput
from app.vsb_alloc.hall_parser import parse_hall_pdf
from app.vsb_alloc.seat_parser import parse_seat_pdf

D = os.path.join(os.path.dirname(__file__), "real_20261116")
# The real-notice fixtures contain genuine register numbers and are NOT shipped in public release packages.
# Without them these tests are skipped (they were run and passed on the build copy: see docs/archive/TEST_REPORT_V6.md).
pytestmark = pytest.mark.skipif(not os.path.isdir(D), reason="real-notice fixtures are intentionally not distributed")
def _pages(name): return [PageInput(i, t) for i, t in enumerate(open(os.path.join(D, name), encoding="utf-8").read().split("\n\f\n"))]

def test_hall_subset_totals_reconcile():
    d = parse_hall_pdf(_pages("hall_FN_16.11.26_subset.txt"))
    assert d.total_students() == 282 and not d.all_issues()
    assert all(t.ok for t in d.dept_totals) and len(d.dept_totals) == 10
    assert {g.session for g in d.groups} == {"FN"} and {g.exam_date.isoformat() for g in d.groups} == {"2026-11-16"}

def test_seat_subset_matches_hall_for_complete_halls():
    h = parse_hall_pdf(_pages("hall_FN_16.11.26_subset.txt"))
    s = parse_seat_pdf(_pages("seat_FN_16.11.26_subset.txt"))
    hall = {}
    for g in h.groups: hall.setdefault(g.hall, set()).update(g.register_numbers)
    for sh in s.sheets:
        regs = {a.register_number for a in sh.assignments}
        assert len(regs) == len(sh.assignments) == sh.declared_total == sh.grid_count
        if sh.hall in ("MB III A202", "MB III A203", "MB III A204", "MB III A303", "MB III A304"):
            assert regs == hall[sh.hall], sh.hall
    a304 = {a.seat: a.register_number for a in s.sheets[5].assignments}
    assert len(a304) == 20 and 27 not in a304 and 28 not in a304   # seats 24-28 are blank on this sheet

def test_text_order_pairing_is_flagged_unconfirmed():
    s = parse_seat_pdf(_pages("seat_FN_16.11.26_subset.txt"))
    assert all(any(i.kind == "seat_map_from_text_order" for i in sh.issues) for sh in s.sheets)
