from app.vsb_alloc.common import PageInput, parse_exam_header, ocr_suspect
from app.vsb_alloc.hall_parser import parse_hall_pdf, split_tail
from . import fixtures_hall as F


def _doc(texts):
    return parse_hall_pdf([PageInput(i, t) for i, t in enumerate(texts)])


def test_header_date_and_session():
    d, s, bad = parse_exam_header(F.REAL_CIVIL)
    assert (d.isoformat(), s, bad) == ("2026-11-14", "FN", False)
    assert parse_exam_header("DATE OF EXAMINATION: 31-02-2026 SESSION : AN")[2] is True


def test_civil_page_exact():
    d = _doc([F.REAL_CIVIL])
    assert [g.hall for g in d.groups] == ["MB III A204", "MB III A204", "MB III 202", "MB III 203", "MB III 206", "MB III 207"]
    assert sum(len(g.register_numbers) for g in d.groups) == 35
    assert all(g.department == "BE-CIVIL" for g in d.groups)
    assert d.dept_totals[0].declared == 35 and d.dept_totals[0].ok
    assert not d.all_issues()
    assert d.groups[1].subject_code == "23GET401R" and d.groups[1].subject_title == "ENVIRONMENTAL SCIENCE AND ENGINEERING"


def test_hall_on_next_line_and_wrapped_lists():
    d = _doc(F.REAL_ECE_BME_PAGES)
    assert [t.department for t in d.dept_totals] == ["BE-ECE", "BE-BME"]
    assert all(t.ok for t in d.dept_totals)
    g = [g for g in d.groups if g.hall == "MB III 209"][0]
    assert len(g.register_numbers) == 13 and g.declared_count == 13


def test_programme_continues_over_pages():
    d = _doc(F.REAL_CSE_SPLIT_PAGES)
    t = d.dept_totals[0]
    assert (t.department, t.declared, t.extracted, t.ok) == ("BE-CSE", 46, 46, True)
    assert {g.department for g in d.groups} == {"BE-CSE"}


def test_trailing_comma_wrap():
    d = _doc([F.REAL_WRAP_TRAILING_COMMA])
    assert d.groups[0].hall == "MB III 202" and len(d.groups[0].register_numbers) == 7 and not d.all_issues()


def test_wrong_group_total_is_reported_not_fixed():
    bad = F.REAL_CIVIL.replace("MB III 203 12", "MB III 203 11")
    d = _doc([bad])
    kinds = [i.kind for i in d.all_issues()]
    assert "group_count_mismatch" in kinds and "department_total_mismatch" not in kinds


def test_wrong_department_total():
    d = _doc([F.REAL_CIVIL.replace("TOTAL 35", "TOTAL 36")])
    assert any(i.kind == "department_total_mismatch" for i in d.issues)


def test_duplicate_in_group_and_nonstandard():
    t = F.HEADER + "[23XYT101] TEST\n994687003001, 994687003001, AB1234567 MB III 1 3\nBE-CIVIL\nTOTAL 3\n"
    d = _doc([t])
    kinds = {i.kind for i in d.all_issues()}
    assert "duplicate_in_group" in kinds and "nonstandard_register_number" in kinds
    assert "AB1234567" in d.groups[0].register_numbers


def test_compressed_ranges_in_hall_list():
    t = F.HEADER + "[23XYT101] TEST\n994687003001 - 003, 005, 994687003010 - 012 MB III 5 7\nBE-CIVIL\nTOTAL 7\n"
    d = _doc([t])
    assert len(d.groups[0].register_numbers) == 7 and not d.all_issues()


def test_ocr_damaged_number_not_used():
    assert ocr_suspect("9946870O3001") == "994687003001"
    t = F.HEADER + "[23XYT101] TEST\n9946870O3001, 994687003002 MB III 5 2\nBE-CIVIL\nTOTAL 2\n"
    d = parse_hall_pdf([PageInput(0, t, method="ocr")])
    g = d.groups[0]
    assert g.register_numbers == ["994687003002"]
    kinds = {i.kind for i in g.issues}
    assert {"ocr_ambiguous_register", "group_count_mismatch", "ocr_text"} <= kinds


def test_missing_date_is_error():
    d = _doc([F.REAL_CIVIL.replace("DATE OF EXAMINATION: 14-11-2026 SESSION : FN", "")])
    assert any(i.kind == "exam_date_missing" for i in d.issues)


def test_not_a_hall_pdf():
    d = _doc(["Some other notice\nwith text"])
    assert any(i.kind == "no_groups" for i in d.issues)


def test_split_tail():
    assert split_tail("MB III A204 2") == ("", "MB III A204", 2)
    assert split_tail("994687003005,") is None
