"""Operations overview for the admin dashboard: publication readiness, allocation completeness, hall utilisation
and consistency warnings.

Every figure and warning is computed from stored records with explicit, explainable rules (listed in `rules`).
Nothing is estimated, no external service is used, and nothing is written.
"""
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import doc_models as dm, models
from ..database import get_db
from ..deps import department_scope, require_roles
from ..notifications import local_tz
from ..services_allocation import eligible_students, load_audience, session_of

router = APIRouter(prefix="/api/operations", tags=["Operations overview"])

RULES = {
    "no_allotments": "Examination has zero seat allotments.",
    "incomplete_allocation": "Eligible active students exist who have no seat for this examination.",
    "unknown_hall": "An allotment names a hall that is not in the hall directory.",
    "unverified_hall": "An allotment uses a hall whose directory record is not administrator-verified (students see no building/room).",
    "over_capacity": "More students are seated in a hall than its verified capacity.",
    "duplicate_seat": "The same seat in the same hall is given to more than one student for one examination.",
    "student_clash": "A student has seats in two examinations whose times overlap on the same date.",
    "not_eligible": "A seat is held by a student who does not match the examination's eligibility rules.",
    "bad_time": "Examination end time is not after its start time.",
    "no_subject": "Examination is not linked to a subject record (subject name cannot be shown to students).",
}
SEVERITY = {"no_allotments": "error", "incomplete_allocation": "warning", "unknown_hall": "warning", "unverified_hall": "info",
            "over_capacity": "error", "duplicate_seat": "error", "student_clash": "error", "not_eligible": "warning",
            "bad_time": "error", "no_subject": "info"}


def _overlap(a: models.Exam, b: models.Exam) -> bool:
    return a.exam_date == b.exam_date and a.start_time < b.end_time and b.start_time < a.end_time


@router.get("/overview")
def overview(exam_limit: int = Query(60, ge=1, le=200), db: Session = Depends(get_db),
             user: models.User = Depends(require_roles("admin", "staff"))):
    scope = department_scope(user)
    today = datetime.now(local_tz()).date().isoformat()

    # ---- students
    sq = select(models.Student.department, models.Student.year, func.count()).where(models.Student.active == True)  # noqa: E712
    if scope:
        sq = sq.where(func.lower(models.Student.department) == scope.lower())
    srows = db.execute(sq.group_by(models.Student.department, models.Student.year)).all()
    by_dept: dict[str, int] = defaultdict(int)
    by_year: dict[int, int] = defaultdict(int)
    for dep, yr, n in srows:
        by_dept[dep] += n
        by_year[yr] += n

    # ---- examinations
    exams = db.scalars(select(models.Exam)).all()
    exam_by_id = {e.id: e for e in exams}
    status_counts: dict[str, int] = defaultdict(int)
    for e in exams:
        status_counts[e.status] += 1
    terms = {t.id: t.semester_no for t in db.scalars(select(models.ExamTerm)).all()}
    subj_sem = {s.id: s.semester for s in db.scalars(select(models.Subject)).all()}
    by_sem: dict[str, int] = defaultdict(int)
    for e in exams:
        sem = terms.get(e.term_id) or subj_sem.get(e.subject_id)
        by_sem[str(sem) if sem else "Not set"] += 1

    # ---- allotments (one pass)
    arows = db.execute(select(models.Allotment.exam_id, models.Allotment.student_id, models.Allotment.hall,
                              models.Allotment.seat)).all()
    per_exam: dict[int, list] = defaultdict(list)
    per_student: dict[int, set] = defaultdict(set)
    hall_peak: dict[str, int] = defaultdict(int)
    hall_exam_count: dict[tuple, int] = defaultdict(int)
    for ex_id, st_id, hall, seat in arows:
        per_exam[ex_id].append((st_id, hall, seat))
        per_student[st_id].add(ex_id)
        hall_exam_count[(ex_id, hall)] += 1
    for (_ex, hall), n in hall_exam_count.items():
        hall_peak[hall] = max(hall_peak[hall], n)

    halls = {h.code.strip().upper(): h for h in db.scalars(select(dm.Hall)).all()}
    students = {s.id: s for s in db.scalars(select(models.Student)).all()}

    def in_scope(sid: int) -> bool:
        return not scope or (students[sid].department or "").casefold() == scope.casefold()

    # ---- hall utilisation (peak single-examination load vs verified capacity only)
    hall_rows = []
    for code in sorted(set(halls) | set(hall_peak)):
        h = halls.get(code)
        cap = h.capacity if (h and h.verified and h.capacity) else None
        peak = hall_peak.get(code, 0)
        hall_rows.append({"hall": code, "verified": bool(h and h.verified), "in_directory": h is not None, "capacity": cap,
                          "peak_allocated": peak, "utilization_percent": round(peak / cap * 100, 1) if cap else None})
    verified_cap = sum(r["capacity"] for r in hall_rows if r["capacity"])

    # ---- per-examination readiness checks
    upcoming = sorted((e for e in exams if e.exam_date >= today), key=lambda e: (e.exam_date, e.start_time))
    past = sorted((e for e in exams if e.exam_date < today), key=lambda e: (e.exam_date, e.start_time), reverse=True)
    selected = (upcoming + past)[:exam_limit]
    clash_students: dict[int, list] = {}
    for sid, ex_ids in per_student.items():
        if len(ex_ids) < 2 or not in_scope(sid):
            continue
        es = sorted((exam_by_id[i] for i in ex_ids if i in exam_by_id), key=lambda e: (e.exam_date, e.start_time))
        for i, a in enumerate(es):
            for b in es[i + 1:]:
                if b.exam_date != a.exam_date:
                    break
                if _overlap(a, b):
                    clash_students.setdefault(sid, []).append((a.id, b.id))

    exam_rows, total_issue = [], defaultdict(int)
    for e in selected:
        rows = per_exam.get(e.id, [])
        issues = []

        def add(code, count=1, detail=None):
            issues.append({"code": code, "severity": SEVERITY[code], "count": count, "message": RULES[code], "detail": detail})

        if not rows:
            add("no_allotments")
        elig = eligible_students(db, e)
        if scope:
            elig = [s for s in elig if (s.department or "").casefold() == scope.casefold()]
        elig_ids = {s.id for s in elig}
        allotted_ids = {r[0] for r in rows}
        missing = len(elig_ids - allotted_ids)
        if rows and missing:
            add("incomplete_allocation", missing)
        if rows:
            # Rules-less examinations are open to every active student, so "not eligible" is only meaningful otherwise.
            if load_audience(db, e.id)[0]:
                bad = [sid for sid in allotted_ids if sid in students and in_scope(sid) and sid not in elig_ids
                       and students[sid].active]
                if bad:
                    add("not_eligible", len(bad))
        seat_counts: dict[tuple, int] = defaultdict(int)
        hall_loads: dict[str, int] = defaultdict(int)
        for _sid, hall, seat in rows:
            seat_counts[(hall.strip().upper(), seat.strip().upper())] += 1
            hall_loads[hall.strip().upper()] += 1
        dup = sum(1 for n in seat_counts.values() if n > 1)
        if dup:
            add("duplicate_seat", dup)
        unknown = sorted(h for h in hall_loads if h not in halls)
        if unknown:
            add("unknown_hall", len(unknown), ", ".join(unknown[:5]))
        unverified = sorted(h for h in hall_loads if h in halls and not halls[h].verified)
        if unverified:
            add("unverified_hall", len(unverified), ", ".join(unverified[:5]))
        over = sorted(f"{h} ({n}/{halls[h].capacity})" for h, n in hall_loads.items()
                      if h in halls and halls[h].verified and halls[h].capacity and n > halls[h].capacity)
        if over:
            add("over_capacity", len(over), ", ".join(over[:5]))
        clashes = sum(1 for lst in clash_students.values() for pair in lst if e.id in pair)
        if clashes:
            add("student_clash", clashes)
        if e.end_time <= e.start_time:
            add("bad_time")
        if not e.subject_id:
            add("no_subject")
        errors = sum(1 for i in issues if i["severity"] == "error")
        warns = sum(1 for i in issues if i["severity"] == "warning")
        readiness = "blocked" if errors else ("review" if warns else "ready")
        for i in issues:
            total_issue[i["code"]] += 1
        exam_rows.append({"id": e.id, "title": e.title, "subject_code": e.subject_code, "date": e.exam_date,
                          "session": session_of(e.start_time), "status": e.status, "eligible": len(elig_ids),
                          "allocated": len(allotted_ids) if not scope else len(allotted_ids & elig_ids),
                          "completion_percent": round(len(allotted_ids & elig_ids) / len(elig_ids) * 100, 1) if elig_ids else None,
                          "readiness": readiness, "issues": issues})

    published = [r for r in exam_rows if r["status"] == "published"]
    insights = []
    blocked_pub = [r for r in published if r["readiness"] == "blocked"]
    if blocked_pub:
        insights.append({"severity": "error", "message": f"{len(blocked_pub)} published examination(s) have blocking problems "
                                                         f"(e.g. {blocked_pub[0]['title']}). Students may see incomplete or conflicting seats."})
    drafts_ready = [r for r in exam_rows if r["status"] == "draft" and r["readiness"] == "ready"]
    if drafts_ready:
        insights.append({"severity": "info", "message": f"{len(drafts_ready)} draft examination(s) pass every check and can be published."})
    if total_issue.get("incomplete_allocation"):
        insights.append({"severity": "warning", "message": f"{total_issue['incomplete_allocation']} examination(s) have eligible students without a seat."})
    if total_issue.get("student_clash"):
        insights.append({"severity": "error", "message": f"{len(clash_students)} student(s) have overlapping examinations on the same date."})
    unknown_total = [r for r in hall_rows if not r["in_directory"]]
    if unknown_total:
        insights.append({"severity": "warning", "message": f"{len(unknown_total)} hall code(s) used in allotments are missing from the hall directory."})
    unv = [r for r in hall_rows if r["in_directory"] and not r["verified"]]
    if unv:
        insights.append({"severity": "info", "message": f"{len(unv)} hall(s) are not verified, so students see no building/floor/room for them."})

    # ---- VSB staged batches (document-driven allocations)
    vsb = {k: v for k, v in db.execute(select(dm.VsbAllocBatch.status, func.count()).group_by(dm.VsbAllocBatch.status)).all()}

    out = {
        "generated_for_date": today, "scope_department": scope,
        "totals": {"students": sum(by_dept.values()), "examinations": len(exams), "published_examinations": status_counts.get("published", 0),
                   "draft_examinations": status_counts.get("draft", 0), "allotments": len(arows),
                   "halls": len(halls), "verified_halls": sum(1 for h in halls.values() if h.verified),
                   "verified_hall_capacity": verified_cap, "vsb_batches": vsb},
        "by_department": [{"department": k, "students": v} for k, v in sorted(by_dept.items())],
        "by_year": [{"year": k, "students": v} for k, v in sorted(by_year.items())],
        "exams_by_semester": [{"semester": k, "examinations": v} for k, v in sorted(by_sem.items())],
        "halls": hall_rows, "examinations": exam_rows, "examinations_checked": len(exam_rows), "examinations_total": len(exams),
        "insights": insights, "rules": RULES,
        "notes": ["Hall utilisation compares the largest single-examination load with VERIFIED capacity; unknown capacities are not estimated.",
                  "Student statistics count active students only; 'year' is the student's recorded year (semester is not stored on students).",
                  f"At most {exam_limit} examinations (upcoming first) are checked per request."],
    }
    if user.role in ("admin", "super_admin"):
        acts = db.scalars(select(models.AuditLog).order_by(models.AuditLog.id.desc()).limit(12)).all()
        out["recent_activity"] = [{"at": a.created_at.isoformat() if a.created_at else None, "actor": a.actor, "action": a.action,
                                   "target": a.target} for a in acts]
        hist = db.scalars(select(models.AuditLog).where(models.AuditLog.action.in_(("exam.published", "exam.unpublished")))
                          .order_by(models.AuditLog.id.desc()).limit(15)).all()
        out["publication_history"] = [{"at": a.created_at.isoformat() if a.created_at else None, "actor": a.actor,
                                       "action": a.action, "exam_id": a.target,
                                       "title": exam_by_id[int(a.target)].title if a.target.isdigit() and int(a.target) in exam_by_id else None}
                                      for a in hist]
    return out
