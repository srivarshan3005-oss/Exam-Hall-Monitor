"""Pure unit tests for the allocation engine (no database needed)."""
import pytest
from app.allocation_engine import (Config, HallRec, StudentRec, allocate, natural_key,
                                   REASON_CAPACITY, REASON_RULES)


def studs(spec):  # spec: list of (reg, dept)
    return [StudentRec(i + 1, reg, f"S{i}", dept) for i, (reg, dept) in enumerate(spec)]


def hall(code, n, hid=1):
    return HallRec(hid, code, tuple(str(i) for i in range(1, n + 1)))


def test_natural_order():
    assert sorted(["10", "2", "1"], key=natural_key) == ["1", "2", "10"]


def test_sequential_fills_first_hall_first():
    r = allocate(studs([(f"R{i}", "A") for i in range(3)]), [hall("B", 2, 2), hall("A", 2, 1)], {},
                 Config(strategy="sequential"))
    assert [(a.hall, a.seat) for a in r.assignments] == [("A", "1"), ("A", "2"), ("B", "1")]


def test_balanced_spreads_across_halls():
    r = allocate(studs([("R1", "A"), ("R2", "A")]), [hall("H1", 1, 1), hall("H2", 1, 2)], {}, Config())
    assert {a.hall for a in r.assignments} == {"H1", "H2"} and r.sufficient


def test_occupied_seats_are_never_reused():
    r = allocate(studs([("R1", "A")]), [hall("H", 2)], {"H": {"1": "A"}}, Config(strategy="sequential"))
    assert r.assignments[0].seat == "2"


def test_insufficient_capacity_reported_not_raised():
    r = allocate(studs([("R1", "A"), ("R2", "A"), ("R3", "A")]), [hall("H", 2)], {}, Config())
    assert len(r.assignments) == 2 and [u.reason for u in r.unallocated] == [REASON_CAPACITY]
    assert not r.sufficient


def test_seat_gap_leaves_empty_seats():
    r = allocate(studs([(f"R{i}", "A") for i in range(3)]), [hall("H", 7)], {}, Config(seat_gap=1))
    assert [a.seat for a in r.assignments] == ["1", "3", "5"]


def test_seat_gap_respects_neighbouring_occupied_seat_and_rule_reason():
    r = allocate(studs([("R1", "A"), ("R2", "A")]), [hall("H", 3)], {"H": {"2": "B"}}, Config(seat_gap=1))
    assert r.assignments == [] and {u.reason for u in r.unallocated} == {REASON_RULES}


def test_strict_department_separation_never_adjacent():
    sp = [(f"A{i}", "CSE") for i in range(3)] + [(f"B{i}", "ECE") for i in range(3)]
    r = allocate(studs(sp), [hall("H", 6)], {}, Config(strategy="sequential", department_separation="strict"))
    by_seat = {int(a.seat): a.department for a in r.assignments}
    assert len(by_seat) == 6
    assert all(by_seat[i] != by_seat[i + 1] for i in range(1, 6))


def test_strict_leaves_students_unallocated_when_impossible():
    r = allocate(studs([(f"A{i}", "CSE") for i in range(3)]), [hall("H", 3)], {},
                 Config(strategy="sequential", department_separation="strict"))
    assert len(r.assignments) == 2 and len(r.unallocated) == 1   # seats 1 and 3, never 1-2-3


def test_preferred_relaxes_with_warning():
    r = allocate(studs([(f"A{i}", "CSE") for i in range(3)]), [hall("H", 3)], {},
                 Config(strategy="sequential", department_separation="preferred"))
    assert r.sufficient and r.warnings


def test_deterministic():
    sp = [(f"R{i:02d}", "ABC"[i % 3]) for i in range(12)]
    cfg = Config(department_separation="preferred", seat_gap=0)
    a = allocate(studs(sp), [hall("X", 6, 1), hall("Y", 6, 2)], {}, cfg)
    b = allocate(studs(sp), [hall("Y", 6, 2), hall("X", 6, 1)], {}, cfg)
    assert [vars(x) for x in a.assignments] == [vars(x) for x in b.assignments]


def test_no_duplicate_seats_or_students():
    sp = [(f"R{i:03d}", "ABCD"[i % 4]) for i in range(100)]
    r = allocate(studs(sp), [hall("X", 40, 1), hall("Y", 40, 2), hall("Z", 40, 3)], {"X": {"1": None, "2": None}},
                 Config(department_separation="preferred"))
    seats = [(a.hall, a.seat) for a in r.assignments]
    assert len(seats) == len(set(seats)) == 100
    assert ("X", "1") not in seats and len({a.student_id for a in r.assignments}) == 100


@pytest.mark.parametrize("cfg", [Config(strategy="x"), Config(seat_gap=-1), Config(seat_gap=99),
                                 Config(department_separation="maybe")])
def test_invalid_config_rejected(cfg):
    with pytest.raises(ValueError):
        allocate([], [], {}, cfg)
