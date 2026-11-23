"""Combine a parsed hall-allotment PDF and a parsed seating-allotment PDF into one record per (session, register number).

The result is only a *proposal*: every record starts unapproved, uncertain ones carry flags, and nothing here knows about
publishing. Cross-checks: duplicate students, conflicting halls, students present in only one document, per-hall and
per-subject totals, programme totals, OCR damage and seat conflicts.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date

from ..regno import id_kind
from .common import Issue, dept_code, norm_hall
from .hall_parser import HallDocument, HallGroup
from .seat_parser import SeatAssignment, SeatDocument, SeatSheet

ERROR_FLAGS = frozenset({
    "conflicting_halls", "multiple_subjects", "hall_mismatch", "subject_mismatch", "missing_in_seating_pdf",
    "missing_in_hall_pdf", "seat_label_missing", "seat_label_ambiguous", "seat_cell_ambiguous", "seat_missing",
    "ocr_ambiguous", "duplicate_seat", "hall_check_failed", "group_check_failed", "department_total_mismatch",
    "conflicting_seats", "hall_missing", "subject_missing", "session_unknown", "hall_capacity_exceeded",
    "hall_label_variant", "source_not_official", "provenance_mismatch"})
WARNING_FLAGS = frozenset({
    "seat_from_text_order", "nonstandard_register_number", "department_inferred", "student_not_in_database",
    "ocr_text", "duplicate_student", "seating_chart_missing"})


@dataclass
class AllocRecord:
    exam_date: date | None
    session: str | None
    register_number: str
    id_kind: str
    department: str | None = None
    department_source: str | None = None        # hall_pdf | register_prefix
    subject_code: str | None = None
    subject_title: str | None = None
    hall: str | None = None
    seat: int | None = None
    hall_pdf_hall: str | None = None
    seat_pdf_hall: str | None = None
    hall_page: int | None = None
    seat_page: int | None = None
    sources: str = "both"                        # hall | seat | both
    flags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    confidence: float = 0.0

    @property
    def uncertain(self) -> bool:
        return any(f in ERROR_FLAGS or f in WARNING_FLAGS for f in self.flags)

    @property
    def blocking(self) -> bool:
        return any(f in ERROR_FLAGS for f in self.flags)


@dataclass
class Reconciliation:
    exam_date: date | None
    session: str | None
    exam_name: str | None
    records: list[AllocRecord]
    issues: list[Issue]
    stats: dict


def _hall_key(h: str | None) -> str | None:
    return norm_hall(h)


def reconcile(hall_doc: HallDocument | None, seat_doc: SeatDocument | None, exam_date: date, session: str,
              known_registers: set[str] | None = None) -> Reconciliation:
    groups: list[HallGroup] = [g for g in (hall_doc.groups if hall_doc else []) if g.exam_date == exam_date and g.session == session]
    sheets: list[SeatSheet] = [s for s in (seat_doc.sheets if seat_doc else []) if s.exam_date == exam_date and s.session == session]
    issues: list[Issue] = []
    if hall_doc:
        issues += [i for i in hall_doc.issues if i.severity != "info" or True]
    if seat_doc:
        issues += seat_doc.issues
    for g in groups:
        issues += g.issues
    for sh in sheets:
        issues += sh.issues + [i for sub in sh.subjects for i in sub.issues]
    if hall_doc is None:
        issues.append(Issue("hall_pdf_missing", "error", "No hall-allotment PDF was supplied; halls and departments are unverified."))
    if seat_doc is None:
        issues.append(Issue("seat_pdf_missing", "error", "No seating-allotment PDF was supplied; no seat numbers are available."))

    H: dict[str, list[HallGroup]] = defaultdict(list)
    for g in groups:
        for r in g.register_numbers:
            H[r].append(g)
    S: dict[str, list[tuple[SeatSheet, SeatAssignment]]] = defaultdict(list)
    for sh in sheets:
        for a in sh.assignments:
            S[a.register_number].append((sh, a))

    # which halls / (hall, subject) / departments already carry an error, so their records are not called clean
    bad_halls = {i.hall for i in issues if i.severity == "error" and i.kind in ("hall_total_mismatch", "grid_table_mismatch", "duplicate_seat",
                                                                                "hall_sheet_repeated", "hall_count_mismatch")}
    bad_groups = {(i.hall, i.subject_code) for i in issues if i.kind in ("group_count_mismatch", "subject_count_mismatch",
                                                                         "subject_hall_count_mismatch")}
    bad_depts = {i.detail.get("department") for i in issues if i.kind == "department_total_mismatch"}

    # department label learned from the hall PDF, keyed by the register-number programme code (used only as a flagged fallback)
    votes: dict[str, Counter] = defaultdict(Counter)
    for g in groups:
        if g.department:
            for r in g.register_numbers:
                c = dept_code(r)
                if c:
                    votes[c][g.department] += 1
    prefix_dept = {c: cnt.most_common(1)[0][0] for c, cnt in votes.items() if len(cnt) == 1}

    records: list[AllocRecord] = []
    for reg in sorted(set(H) | set(S)):
        rec = AllocRecord(exam_date, session, reg, id_kind(reg))
        hs, ss = H.get(reg, []), S.get(reg, [])
        rec.sources = "both" if hs and ss else "hall" if hs else "seat"
        # --- hall PDF side
        if hs:
            places = {(_hall_key(g.hall), g.subject_code) for g in hs}
            rec.hall_page = hs[0].page
            if len(hs) > 1:
                if len(places) == 1:
                    rec.flags.append("duplicate_student")
                    rec.notes.append(f"listed {len(hs)} times on the hall PDF (same hall and subject)")
                    issues.append(Issue("duplicate_student", "warning", f"{reg} is listed {len(hs)} times for {hs[0].hall} / {hs[0].subject_code}.",
                                        register_number=reg, hall=hs[0].hall, subject_code=hs[0].subject_code))
                else:
                    halls = sorted({h for h, _ in places if h})
                    kind = "conflicting_halls" if len(halls) > 1 else "multiple_subjects"
                    rec.flags.append(kind)
                    rec.notes.append("listed in: " + "; ".join(f"{h or '?'} / {c or '?'}" for h, c in sorted(places, key=str)))
                    issues.append(Issue(kind, "error", f"{reg} appears in more than one place on the hall PDF: "
                                                       + "; ".join(f"{h or '?'} / {c or '?'}" for h, c in sorted(places, key=str)),
                                        register_number=reg, detail={"places": [list(p) for p in sorted(places, key=str)]}))
            if kind_ok := len(places) == 1:
                g = hs[0]
                rec.hall_pdf_hall, rec.subject_code, rec.subject_title, rec.department = g.hall, g.subject_code, g.subject_title, g.department
                rec.department_source = "hall_pdf" if g.department else None
                if (g.hall, g.subject_code) in bad_groups:
                    rec.flags.append("group_check_failed")
                if g.department in bad_depts:
                    rec.flags.append("department_total_mismatch")
                if g.method == "ocr":
                    rec.flags.append("ocr_text")
                if not g.subject_code:
                    rec.flags.append("subject_missing")
                if not g.hall:
                    rec.flags.append("hall_missing")
        # --- seat PDF side
        if ss:
            rec.seat_page = ss[0][0].page
            places = {(_hall_key(sh.hall), a.seat) for sh, a in ss}
            if len(ss) > 1 and len(places) > 1:
                rec.flags.append("conflicting_seats")
                rec.notes.append("seated on the seat PDF at: " + "; ".join(f"{h or '?'} seat {s or '?'}" for h, s in sorted(places, key=str)))
                issues.append(Issue("conflicting_seats", "error", f"{reg} has several seats on the seat PDF: "
                                    + "; ".join(f"{h or '?'} seat {s or '?'}" for h, s in sorted(places, key=str)), register_number=reg))
            elif len(ss) > 1:
                rec.flags.append("duplicate_student")
            sh, a = ss[0]
            if len(places) == 1:
                rec.seat_pdf_hall = sh.hall
                rec.seat = a.seat
                for f in a.flags:
                    rec.flags.append({"ocr_ambiguous": "ocr_ambiguous"}.get(f, f))
                if a.seat is None and not any(f in rec.flags for f in ("seat_label_missing", "seat_label_ambiguous")):
                    rec.flags.append("seat_missing")
                if a.subject_code and not rec.subject_code:
                    rec.subject_code = a.subject_code
                    rec.subject_title = next((x.title for x in sh.subjects if x.code == a.subject_code), None)
                if sh.hall in bad_halls:
                    rec.flags.append("hall_check_failed")
                if sh.method == "ocr":
                    rec.flags.append("ocr_text")
        # --- cross-document decisions
        if hs and ss and len({_hall_key(g.hall) for g in hs}) == 1 and len({_hall_key(sh.hall) for sh, _ in ss}) == 1:
            hh, sh_ = _hall_key(hs[0].hall), _hall_key(ss[0][0].hall)
            if hh is None or sh_ is None:
                # an unreadable hall label is reported as 'hall_missing' (block-level issue + record flag), not as a mismatch with "None"
                if "hall_missing" not in rec.flags:
                    rec.flags.append("hall_missing")
            elif hh != sh_:
                rec.flags.append("hall_mismatch")
                rec.notes.append(f"hall PDF says {hs[0].hall}, seat PDF says {ss[0][0].hall}")
                issues.append(Issue("hall_mismatch", "error", f"{reg}: hall PDF says {hs[0].hall} but the seat PDF says {ss[0][0].hall}.",
                                    register_number=reg, detail={"hall_pdf": hs[0].hall, "seat_pdf": ss[0][0].hall}))
            if ss[0][1].subject_code and hs[0].subject_code and ss[0][1].subject_code != hs[0].subject_code:
                rec.flags.append("subject_mismatch")
                issues.append(Issue("subject_mismatch", "error",
                                    f"{reg}: hall PDF lists subject {hs[0].subject_code}, seat PDF lists {ss[0][1].subject_code}.",
                                    register_number=reg))
        elif hs and not ss:
            rec.flags.append("missing_in_seating_pdf")
            issues.append(Issue("missing_in_seating_pdf", "error", f"{reg} is on the hall PDF ({hs[0].hall}) but on no seat sheet.",
                                register_number=reg, hall=hs[0].hall))
        elif ss and not hs:
            rec.flags.append("missing_in_hall_pdf")
            issues.append(Issue("missing_in_hall_pdf", "error", f"{reg} has a seat in {ss[0][0].hall} but is not on the hall PDF.",
                                register_number=reg, hall=ss[0][0].hall))
        # --- resolved fields
        h1 = _hall_key(rec.hall_pdf_hall)
        h2 = _hall_key(rec.seat_pdf_hall)
        if "hall_mismatch" in rec.flags or "conflicting_halls" in rec.flags or "conflicting_seats" in rec.flags:
            rec.hall = None
        else:
            rec.hall = h1 or h2
        if rec.department is None:
            c = dept_code(reg)
            if c and c in prefix_dept:
                rec.department, rec.department_source = prefix_dept[c], "register_prefix"
                rec.flags.append("department_inferred")
        if rec.id_kind != "standard12":
            rec.flags.append("nonstandard_register_number")
        if known_registers is not None and reg not in known_registers:
            rec.flags.append("student_not_in_database")
        if any(i.kind == "ocr_ambiguous_register" and i.register_number == reg for i in issues):
            rec.flags.append("ocr_ambiguous")
        rec.flags = sorted(set(rec.flags))
        rec.confidence = 0.3 if rec.blocking else 0.65 if rec.uncertain else 0.97
        records.append(rec)

    # --- per-hall / per-subject cross-document totals
    h_by_hall: Counter = Counter()
    h_by_hall_sub: Counter = Counter()
    for g in groups:
        h_by_hall[_hall_key(g.hall)] += len(g.register_numbers)
        h_by_hall_sub[(_hall_key(g.hall), g.subject_code)] += len(g.register_numbers)
    s_by_hall = {_hall_key(sh.hall): sh for sh in sheets}
    if hall_doc and seat_doc:
        # A hall-PDF block whose hall label could not be read has hall=None. It is already reported (once, with its page and
        # subject) as 'hall_or_total_missing'; counting "None" as if it were a hall produced the misleading
        # "None is on the hall PDF ... but has no seating sheet" error and a bogus hall_check_failed on unrelated records.
        unreadable = h_by_hall.pop(None, 0)
        if unreadable:
            issues.append(Issue("hall_unreadable", "error",
                                f"{unreadable} register number(s) on the hall PDF belong to block(s) whose hall label could not be read; "
                                "they cannot be matched to a seating sheet until the hall label is corrected.",
                                detail={"students": unreadable}))
        for h, n in sorted(h_by_hall.items(), key=lambda kv: str(kv[0])):
            sh = s_by_hall.get(h)
            if sh is None:
                issues.append(Issue("hall_sheet_missing", "error", f"{h} is on the hall PDF ({n} students) but has no seating sheet.", hall=h))
            elif sh.grid_count != n:
                issues.append(Issue("hall_count_mismatch", "error",
                                    f"{h}: hall PDF lists {n} students, the seat sheet holds {sh.grid_count}.", hall=h,
                                    detail={"hall_pdf": n, "seat_pdf": sh.grid_count}))
        for h in sorted(set(s_by_hall) - set(h_by_hall), key=str):
            issues.append(Issue("hall_not_in_hall_list", "error", f"{h} has a seating sheet but is not on the hall PDF.", hall=h))
        for h, sh in s_by_hall.items():
            for sub in sh.subjects:
                n = h_by_hall_sub.get((h, sub.code))
                if n is not None and n != len(sub.register_numbers):
                    issues.append(Issue("subject_hall_count_mismatch", "error",
                                        f"{h} / {sub.code}: hall PDF lists {n}, the seat sheet table lists {len(sub.register_numbers)}.",
                                        hall=h, subject_code=sub.code, detail={"hall_pdf": n, "seat_pdf": len(sub.register_numbers)}))
    # recompute bad_* after the cross-document checks so those records are flagged too
    late_halls = {i.hall for i in issues if i.kind in ("hall_count_mismatch", "hall_sheet_missing") and i.hall}
    late_groups = {(i.hall, i.subject_code) for i in issues if i.kind == "subject_hall_count_mismatch"}
    for rec in records:
        h = _hall_key(rec.hall_pdf_hall or rec.seat_pdf_hall)
        if h in late_halls and "hall_check_failed" not in rec.flags:
            rec.flags = sorted(set(rec.flags) | {"hall_check_failed"})
        if (h, rec.subject_code) in late_groups and "group_check_failed" not in rec.flags:
            rec.flags = sorted(set(rec.flags) | {"group_check_failed"})
        rec.confidence = 0.3 if rec.blocking else 0.65 if rec.uncertain else 0.97

    by_dept: Counter = Counter(r.department or "unknown" for r in records)
    by_subject: Counter = Counter(r.subject_code or "unknown" for r in records)
    by_hall: Counter = Counter(r.hall or "unknown" for r in records)
    stats = {"students": len(records), "clean": sum(1 for r in records if not r.uncertain),
             "uncertain": sum(1 for r in records if r.uncertain), "blocking": sum(1 for r in records if r.blocking),
             "halls": len(by_hall), "by_department": dict(sorted(by_dept.items())), "by_subject": dict(sorted(by_subject.items())),
             "by_hall": dict(sorted(by_hall.items())),
             "hall_pdf_students": len(H), "seat_pdf_students": len(S),
             "issues": dict(Counter(i.severity for i in issues))}
    return Reconciliation(exam_date, session, hall_doc.title if hall_doc else None, records, _dedupe(issues), stats)


def _dedupe(issues: list[Issue]) -> list[Issue]:
    seen, out = set(), []
    for i in issues:
        k = (i.kind, i.message, i.register_number, i.hall, i.page)
        if k not in seen:
            seen.add(k)
            out.append(i)
    return out
