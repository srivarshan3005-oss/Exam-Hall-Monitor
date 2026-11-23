"""Deterministic seat-allocation engine (pure Python: no database, no web framework).

The database layer (`services_allocation.py`) gathers the inputs; this module only decides
WHO sits WHERE. Keeping it pure makes the rules unit-testable and the result reproducible:
the same inputs always give the same assignments, which is what lets the commit step verify
that an approved preview is still exactly what would be saved.

Rules implemented
* Existing allocations are never moved (they arrive as `occupied` seats).
* Seats occupied by *any* examination running at the same time are unavailable.
* `seat_gap` leaves N empty seats between occupied seats (physical spacing).
* `department_separation`: "off" | "preferred" | "strict" - students of the same department
  are not seated next to each other ("preferred" relaxes only when no other seat exists).
* `strategy`: "balanced" spreads students over halls by occupancy ratio;
  "sequential" fills halls one after another in hall-code order.
* Seat adjacency is *linear* in the hall's natural seat order (the schema stores no row/column
  geometry), so "neighbour" means the previous/next seat label.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

STRATEGIES = ("balanced", "sequential")
SEPARATION_MODES = ("off", "preferred", "strict")
MAX_SEAT_GAP = 5

REASON_CAPACITY = "insufficient_capacity"
REASON_RULES = "rules_prevent_placement"


@dataclass(frozen=True)
class StudentRec:
    id: int
    register_number: str
    name: str
    department: str


@dataclass(frozen=True)
class HallRec:
    id: int
    code: str
    seats: tuple[str, ...]          # usable (active, within capacity) seat labels in natural order


@dataclass(frozen=True)
class Config:
    strategy: str = "balanced"
    seat_gap: int = 0
    department_separation: str = "off"

    def validate(self) -> "Config":
        if self.strategy not in STRATEGIES:
            raise ValueError(f"strategy must be one of {STRATEGIES}")
        if self.department_separation not in SEPARATION_MODES:
            raise ValueError(f"department_separation must be one of {SEPARATION_MODES}")
        if not isinstance(self.seat_gap, int) or not 0 <= self.seat_gap <= MAX_SEAT_GAP:
            raise ValueError(f"seat_gap must be an integer between 0 and {MAX_SEAT_GAP}")
        return self


@dataclass
class Assignment:
    student_id: int
    register_number: str
    student_name: str
    department: str
    hall_id: int
    hall: str
    seat: str


@dataclass
class Unallocated:
    student_id: int
    register_number: str
    student_name: str
    department: str
    reason: str


@dataclass
class Result:
    assignments: list[Assignment] = field(default_factory=list)
    unallocated: list[Unallocated] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    hall_stats: list[dict] = field(default_factory=list)
    free_seats_before: int = 0

    @property
    def sufficient(self) -> bool:
        return not self.unallocated


def natural_key(label: str):
    """'2' < '10', 'A2' < 'A10' (digits compare numerically)."""
    return [int(p) if p.isdigit() else p.upper() for p in re.split(r"(\d+)", str(label)) if p != ""]


def _interleave_by_department(students: list[StudentRec]) -> list[StudentRec]:
    """Round-robin over departments (largest first) so neighbours naturally differ."""
    groups: dict[str, list[StudentRec]] = {}
    for s in sorted(students, key=lambda x: x.register_number):
        groups.setdefault(s.department.strip().upper(), []).append(s)
    queues = sorted(groups.values(), key=lambda g: (-len(g), g[0].department.strip().upper()))
    out: list[StudentRec] = []
    i = 0
    while len(out) < len(students):
        for q in queues:
            if i < len(q):
                out.append(q[i])
        i += 1
    return out


class _HallState:
    def __init__(self, hall: HallRec, occupied: dict[str, str | None]):
        self.hall = hall
        self.index = {lbl.upper(): i for i, lbl in enumerate(hall.seats)}
        self.taken: dict[int, str | None] = {}
        for label, dept in occupied.items():
            i = self.index.get(str(label).upper())
            if i is not None:
                self.taken[i] = (dept or "").strip().upper() or None
        self.placed = 0
        self._first_free = 0

    @property
    def size(self) -> int:
        return len(self.hall.seats)

    def raw_free(self) -> int:
        return self.size - len(self.taken)

    def ratio(self) -> float:
        return len(self.taken) / self.size if self.size else 1.0

    def find(self, dept: str, gap: int, enforce_dept: bool) -> int | None:
        step = gap + 1
        while self._first_free in self.taken:
            self._first_free += 1
        for i in range(self._first_free, self.size):
            if i in self.taken:
                continue
            if gap and any((i + d) in self.taken for d in range(-gap, gap + 1) if d):
                continue
            if enforce_dept and dept and (self.taken.get(i - step) == dept or self.taken.get(i + step) == dept):
                continue
            return i
        return None

    def place(self, i: int, dept: str) -> None:
        self.taken[i] = dept or None
        self.placed += 1


def allocate(students: list[StudentRec], halls: list[HallRec],
             occupied: dict[str, dict[str, str | None]], config: Config) -> Result:
    """Assign `students` to seats in `halls`.

    occupied: hall_code -> {seat_label(upper): department-or-None} for seats that are already
    taken (this exam's existing allotments and any simultaneous exam's allotments).
    """
    config.validate()
    result = Result()
    states = [_HallState(h, occupied.get(h.code, {})) for h in sorted(halls, key=lambda h: h.code) if h.seats]
    result.free_seats_before = sum(s.raw_free() for s in states)

    sep = config.department_separation
    order = _interleave_by_department(students) if sep != "off" else sorted(students, key=lambda s: s.register_number)
    relaxed_used = 0

    for student in order:
        dept = student.department.strip().upper()
        placed = False
        passes = (True, False) if sep == "preferred" else ((True,) if sep == "strict" else (False,))
        for enforce in passes:
            candidates = sorted(states, key=lambda s: (s.ratio(), s.hall.code)) if config.strategy == "balanced" else states
            for st in candidates:
                i = st.find(dept, config.seat_gap, enforce)
                if i is not None:
                    st.place(i, dept)
                    result.assignments.append(Assignment(student.id, student.register_number, student.name,
                                                         student.department, st.hall.id, st.hall.code, st.hall.seats[i]))
                    placed = True
                    if sep == "preferred" and not enforce:
                        relaxed_used += 1
                    break
            if placed:
                break
        if not placed:
            reason = REASON_RULES if any(s.raw_free() > 0 for s in states) else REASON_CAPACITY
            result.unallocated.append(Unallocated(student.id, student.register_number, student.name,
                                                  student.department, reason))
    if relaxed_used:
        result.warnings.append(f"Department separation was relaxed for {relaxed_used} student(s) because no "
                               "separated seat was available.")
    result.assignments.sort(key=lambda a: (a.hall, natural_key(a.seat)))
    result.hall_stats = [{"hall_id": s.hall.id, "hall": s.hall.code, "usable_seats": s.size,
                          "already_occupied": len(s.taken) - s.placed, "newly_placed": s.placed}
                         for s in states]
    return result
