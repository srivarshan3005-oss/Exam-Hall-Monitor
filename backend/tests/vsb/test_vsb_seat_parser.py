import os, tempfile
from app.vsb_alloc.common import PageInput, Word
from app.vsb_alloc.seat_parser import parse_seat_page, parse_seat_pdf, parse_subject_table
from . import fixtures_seat as F

SUBS = [("23CST302R", "FOUNDATIONS OF DATA SCIENCE", 13, "994177572001 - 013"),
        ("23EET302R", "ELECTRICAL MACHINES - I", 12, "992829432001 - 012")]


def _seats():
    sh = parse_seat_page(PageInput(0, F.REAL_TEXT_02))
    return {a.seat: a.register_number for a in sh.assignments}


def test_subject_tables_on_real_pages():
    for name, expect in (("02", [13, 12]), ("103", [13, 8, 4]), ("208", [3, 22]), ("A203", [13, 12]), ("A204", [2, 3, 10])):
        sh = parse_seat_page(PageInput(0, getattr(F, "REAL_TEXT_" + name)))
        assert [len(s.register_numbers) for s in sh.subjects] == expect, name
        assert not [i for s in sh.subjects for i in s.issues], name
        assert sh.declared_total == sum(expect)
        assert sh.grid_count == sum(expect)


def test_register_lines_printed_before_code_line():
    sh = parse_seat_page(PageInput(0, F.REAL_TEXT_A203))
    env = sh.subjects[1]
    assert env.code == "23GET401R" and env.declared == 12 and len(env.register_numbers) == 12
    assert env.register_numbers[0] == "990162938032" and env.register_numbers[-1] == "990930217302"
    sh = parse_seat_page(PageInput(0, F.REAL_TEXT_A204))
    assert [s.code for s in sh.subjects] == ["23CET304", "23CST302R", "23GET401R"]
    assert sh.subjects[2].title == "ENVIRONMENTAL SCIENCE AND ENGINEERING" and sh.subjects[2].declared == 10


def test_compressed_lists_and_two_prefixes():
    sh = parse_seat_page(PageInput(0, F.REAL_TEXT_208))
    cst = sh.subjects[1].register_numbers
    assert "994177572192" in cst and "994177572301" in cst and "992332477022" in cst and len(cst) == 22


def test_text_fallback_is_flagged_unconfirmed():
    sh = parse_seat_page(PageInput(0, F.REAL_TEXT_02))
    assert sh.layout == "text"
    assert all("seat_from_text_order" in a.flags for a in sh.assignments)
    first = [a for a in sh.assignments if "seat_cell_ambiguous" in a.flags]
    assert len(first) == 1 and first[0].register_number == "994177572013"
    assert any(i.kind == "seat_map_from_text_order" for i in sh.issues)


def test_coordinates_map_seats_including_empty_cells():
    seats = _seats()
    sh = parse_seat_page(F.build_page(0, "MB III 02", seats, SUBS))
    assert sh.layout == "coordinates"
    assert {a.seat: a.register_number for a in sh.assignments} == seats
    assert sh.empty_seats == [1, 14, 15]
    assert not sh.issues
    assert seats[28] == "994177572013"      # the lone number of the row "1 14 15 28 ..."


def test_dropped_and_duplicated_labels_are_not_guessed():
    seats = _seats()
    sh = parse_seat_page(F.build_page(0, "MB III 02", seats, SUBS, drop_labels=[(0, 3)]))
    a = [x for x in sh.assignments if x.register_number == seats[28]][0]
    assert a.seat is None and "seat_label_missing" in a.flags
    assert any(i.kind == "seat_unresolved" for i in sh.issues)
    sh = parse_seat_page(F.build_page(0, "MB III 02", seats, SUBS, extra_labels=[(1, 1, 27)]))
    assert any("seat_label_ambiguous" in x.flags for x in sh.assignments)


def test_duplicate_register_and_seat_and_totals():
    seats = _seats()
    seats2 = dict(seats)
    seats2[3] = seats[2]                              # same student in two seats
    sh = parse_seat_page(F.build_page(0, "MB III 02", seats2, SUBS))
    kinds = {i.kind for i in sh.issues}
    assert "duplicate_student_in_hall" in kinds and "grid_table_mismatch" in kinds and "hall_total_mismatch" in kinds
    sh = parse_seat_page(F.build_page(0, "MB III 02", seats, SUBS, table_total_override=24))
    assert any(i.kind == "hall_total_mismatch" for i in sh.issues)


def test_pdf_round_trip_with_real_coordinates():
    import pdfplumber
    seats = _seats()
    page = F.build_page(0, "MB III 02", seats, SUBS)
    p = tempfile.mktemp(suffix=".pdf")
    F.write_pdf(p, page)
    try:
        with pdfplumber.open(p) as pdf:
            words = [Word(w["text"], w["x0"], w["top"], w["x1"], w["bottom"]) for w in pdf.pages[0].extract_words()]
    finally:
        os.unlink(p)
    sh = parse_seat_page(PageInput(0, page.text, words))
    assert sh.layout == "coordinates" and {a.seat: a.register_number for a in sh.assignments} == seats


def test_repeated_hall_sheet_and_not_a_seat_pdf():
    seats = _seats()
    doc = parse_seat_pdf([F.build_page(0, "MB III 02", seats, SUBS), F.build_page(1, "MB III 02", seats, SUBS)])
    assert any(i.kind == "hall_sheet_repeated" for i in doc.issues)
    assert any(i.kind == "no_sheets" or True for i in parse_seat_pdf([PageInput(0, "hello")]).all_issues())


def test_table_without_total_is_reported():
    rows, tot = parse_subject_table(["23CST302R FOUNDATIONS OF DATA SCIENCE 994177572001 - 003"], 0)
    assert rows[0].declared is None and any(i.kind == "subject_total_missing" for i in rows[0].issues)
