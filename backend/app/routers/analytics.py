"""Phase 10 analytics and reporting.

All metrics are computed from persisted project records. Missing values remain missing;
attendance is explicitly reported as unavailable until an attendance source is integrated.
"""
from datetime import date, timedelta
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import Session
from .. import models, doc_models
from ..database import get_db
from ..deps import require_roles, department_scope
from ..exports import tabular
from ..services_allocation import eligible_students

router = APIRouter(prefix="/api/analytics", tags=["Phase 10 analytics"])
STAFF = ("admin", "staff")
READ = ("admin", "staff", "invigilator")


def _scope(user, department):
    own = department_scope(user)
    if own:
        return own
    return department.strip() if department else ""


def _filters(stmt, *, date_from, date_to, department, semester, subject_id, academic_year_id):
    stmt = stmt.join(models.Exam, models.Exam.id == models.Result.exam_id)
    if date_from: stmt = stmt.where(models.Exam.exam_date >= date_from.isoformat())
    if date_to: stmt = stmt.where(models.Exam.exam_date <= date_to.isoformat())
    if department:
        stmt = stmt.join(models.Student, models.Student.id == models.Result.student_id).where(
            func.lower(models.Student.department) == department.lower())
    if semester is not None:
        stmt = stmt.join(models.ExamTerm, models.ExamTerm.id == models.Exam.term_id).where(models.ExamTerm.semester_no == semester)
    if academic_year_id is not None:
        stmt = stmt.join(models.ExamTerm, models.ExamTerm.id == models.Exam.term_id).where(
            models.ExamTerm.academic_year_id == academic_year_id)
    if subject_id is not None:
        stmt = stmt.where(models.Exam.subject_id == subject_id)
    return stmt


def _result_rows(db, date_from, date_to, department, semester, subject_id, academic_year_id, published_only=False):
    stmt = select(models.Result, models.Student, models.Exam).join(
        models.Student, models.Student.id == models.Result.student_id).join(
        models.Exam, models.Exam.id == models.Result.exam_id)
    if date_from: stmt = stmt.where(models.Exam.exam_date >= date_from.isoformat())
    if date_to: stmt = stmt.where(models.Exam.exam_date <= date_to.isoformat())
    if department: stmt = stmt.where(func.lower(models.Student.department) == department.lower())
    if semester is not None: stmt = stmt.join(models.ExamTerm, models.ExamTerm.id == models.Exam.term_id).where(models.ExamTerm.semester_no == semester)
    if academic_year_id is not None:
        if semester is None: stmt = stmt.join(models.ExamTerm, models.ExamTerm.id == models.Exam.term_id)
        stmt = stmt.where(models.ExamTerm.academic_year_id == academic_year_id)
    if subject_id is not None: stmt = stmt.where(models.Exam.subject_id == subject_id)
    if published_only: stmt = stmt.where(models.Result.published.is_(True))
    return db.execute(stmt.order_by(models.Exam.exam_date, models.Student.register_number)).all()


@router.get("/dashboard")
def dashboard(date_from: date | None = None, date_to: date | None = None,
              department: str = Query("", max_length=100), semester: int | None = Query(None, ge=1, le=12),
              subject_id: int | None = Query(None, ge=1), academic_year_id: int | None = Query(None, ge=1),
              pass_percent: float = Query(40, ge=0, le=100),
              db: Session = Depends(get_db), user: models.User = Depends(require_roles(*READ))):
    """Aggregated performance and allocation KPIs for the caller's permitted department."""
    if date_from and date_to and date_from > date_to: raise HTTPException(422, "date_from must not exceed date_to")
    dept = _scope(user, department)
    rows = _result_rows(db, date_from, date_to, dept, semester, subject_id, academic_year_id, published_only=True)
    total = len(rows); passed = sum((r.marks / r.max_marks * 100) >= pass_percent for r, _, _ in rows)
    scored = [r.marks / r.max_marks * 100 for r, _, _ in rows if r.max_marks]
    by_dept, by_subject, by_exam = defaultdict(list), defaultdict(list), defaultdict(list)
    for r, st, ex in rows:
        pct = r.marks / r.max_marks * 100 if r.max_marks else None
        if pct is None: continue
        by_dept[st.department].append(pct); by_subject[ex.subject_code].append(pct)
        by_exam[ex.id].append(pct)
    def agg(groups):
        return [{"name": k, "records": len(v), "average_percent": round(sum(v)/len(v), 2),
                 "pass_count": sum(x >= pass_percent for x in v),
                 "fail_count": sum(x < pass_percent for x in v)} for k, v in sorted(groups.items())]
    exam_cond = []
    if date_from: exam_cond.append(models.Exam.exam_date >= date_from.isoformat())
    if date_to: exam_cond.append(models.Exam.exam_date <= date_to.isoformat())
    if subject_id: exam_cond.append(models.Exam.subject_id == subject_id)
    if semester is not None: exam_cond.append(models.Exam.term_id.in_(select(models.ExamTerm.id).where(models.ExamTerm.semester_no == semester)))
    if academic_year_id: exam_cond.append(models.Exam.term_id.in_(select(models.ExamTerm.id).where(models.ExamTerm.academic_year_id == academic_year_id)))
    exams = db.scalars(select(models.Exam).where(*exam_cond)).all()
    if dept:
        exams = [e for e in exams if db.scalar(select(func.count()).select_from(models.ExamEligibilityRule).where(
            models.ExamEligibilityRule.exam_id == e.id,
            func.lower(models.ExamEligibilityRule.department) == dept.lower())) or
            not db.scalar(select(func.count()).select_from(models.ExamEligibilityRule).where(models.ExamEligibilityRule.exam_id == e.id))]
    eligible_counts = {}
    total_eligible = 0
    total_alloc = 0
    for e in exams:
        eligible = eligible_students(db, e)
        if dept:
            eligible = [student for student in eligible if (student.department or "").casefold() == dept.casefold()]
        eligible_counts[e.id] = len(eligible)
        total_eligible += len(eligible)
        alloc_stmt = select(func.count()).select_from(models.Allotment).join(
            models.Student, models.Student.id == models.Allotment.student_id).where(models.Allotment.exam_id == e.id)
        if dept:
            alloc_stmt = alloc_stmt.where(func.lower(models.Student.department) == dept.lower())
        total_alloc += db.scalar(alloc_stmt) or 0
    return {"filters": {"date_from": date_from, "date_to": date_to, "department": dept or None,
                        "semester": semester, "subject_id": subject_id, "academic_year_id": academic_year_id,
                        "pass_percent": pass_percent},
            "performance": {"result_records": total, "students_with_results": len({st.id for _, st, _ in rows}),
                            "average_percent": round(sum(scored)/len(scored), 2) if scored else None,
                            "pass_count": passed, "fail_count": total-passed,
                            "pass_rate_percent": round(passed/total*100, 2) if total else None},
            "by_department": agg(by_dept), "by_subject": agg(by_subject),
            "trend": [{"exam_id": eid, "exam_title": next((e.title for e in exams if e.id == eid), ""),
                       "date": next((e.exam_date for e in exams if e.id == eid), ""),
                       "records": len(v), "average_percent": round(sum(v)/len(v), 2)}
                      for eid, v in sorted(by_exam.items(), key=lambda x: next((e.exam_date for e in exams if e.id == x[0]), ""))],
            "allocation": {"examinations": len(exams), "eligible_student_exam_entries": total_eligible,
                           "allocated_student_exam_entries": total_alloc,
                           "unallocated_student_exam_entries": max(0, total_eligible-total_alloc),
                           "allocation_rate_percent": round(total_alloc/total_eligible*100, 2) if total_eligible else None},
            "attendance": {"available": False, "reason": "No attendance records/source exist in the current schema."},
            "data_quality": {"source": "persisted Result, Student, Exam, ExamTerm, Allotment and eligibility records",
                             "estimates_used": False, "missing_scores_fabricated": False,
                             "pass_threshold_percent": pass_percent}}


@router.get("/students/at-risk")
def at_risk(minimum_results: int = Query(2, ge=1, le=20), threshold: float = Query(45, ge=0, le=100),
            recent_drop: float = Query(15, ge=0, le=100), department: str = Query("", max_length=100),
            limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
            db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    """Transparent flags: average below threshold OR last result at least recent_drop pp below previous result."""
    dept = _scope(user, department)
    stmt = select(models.Result, models.Exam, models.Student).join(models.Exam, models.Exam.id == models.Result.exam_id).join(
        models.Student, models.Student.id == models.Result.student_id).where(models.Result.published.is_(True))
    if dept: stmt = stmt.where(func.lower(models.Student.department) == dept.lower())
    rows = db.execute(stmt.order_by(models.Student.register_number, models.Exam.exam_date)).all()
    grouped = defaultdict(list)
    for r, e, st in rows:
        if r.max_marks: grouped[st.id].append((r.marks/r.max_marks*100, e.exam_date, e.subject_code))
    candidates = []
    students_by_id = {st.id: st for r, e, st in rows}
    for sid, vals in grouped.items():
        if len(vals) < minimum_results: continue
        st = students_by_id[sid]
        avg = sum(x[0] for x in vals)/len(vals); drop = vals[-2][0]-vals[-1][0] if len(vals) >= 2 else 0
        reasons = []
        if avg < threshold: reasons.append(f"published-result average {avg:.1f}% is below configured {threshold:.1f}%")
        if drop >= recent_drop: reasons.append(f"latest result fell {drop:.1f} percentage points from the previous result")
        if reasons: candidates.append({"register_number": st.register_number, "student_name": st.full_name,
                                       "department": st.department, "result_count": len(vals),
                                       "average_percent": round(avg, 2), "latest_percent": round(vals[-1][0], 2),
                                       "reasons": reasons})
    total = len(candidates)
    return {"rules": {"minimum_results": minimum_results, "average_below_percent": threshold,
                      "recent_drop_percentage_points": recent_drop},
            "total": total, "items": candidates[offset:offset+limit], "offset": offset, "limit": limit,
            "disclaimer": "A screening indicator only, not a diagnosis or final academic decision. Review context with authorized staff."}



@router.get("/students/{register_number}")
def student_history(register_number: str, db: Session = Depends(get_db),
                    user: models.User = Depends(require_roles(*STAFF))):
    st = db.scalar(select(models.Student).where(models.Student.register_number == register_number.strip().upper()))
    if not st: raise HTTPException(404, "Student not found")
    scope = department_scope(user)
    if scope and st.department.casefold() != scope.casefold(): raise HTTPException(403, "Student belongs to another department")
    rows = db.execute(select(models.Result, models.Exam).join(models.Exam, models.Exam.id == models.Result.exam_id)
                      .where(models.Result.student_id == st.id, models.Result.published.is_(True))
                      .order_by(models.Exam.exam_date, models.Exam.id)).all()
    history = [{"exam_id": e.id, "exam": e.title, "subject_code": e.subject_code, "date": e.exam_date,
                "marks": r.marks, "max_marks": r.max_marks, "percent": round(r.marks/r.max_marks*100, 2),
                "grade": r.grade} for r, e in rows if r.max_marks]
    by_subject = defaultdict(list)
    for h in history: by_subject[h["subject_code"]].append(h["percent"])
    progress = [{"subject_code": k, "attempts": len(v), "first_percent": v[0], "latest_percent": v[-1],
                 "change_percentage_points": round(v[-1]-v[0], 2)} for k, v in sorted(by_subject.items())]
    return {"student": {"register_number": st.register_number, "full_name": st.full_name, "department": st.department,
                        "course": st.course, "year": st.year},
            "published_result_count": len(history), "history": history, "subject_progress": progress,
            "indicators": {"improved_subjects": sum(x["change_percentage_points"] > 0 for x in progress),
                           "declined_subjects": sum(x["change_percentage_points"] < 0 for x in progress),
                           "insufficient_history_subjects": sum(x["attempts"] < 2 for x in progress)}}


@router.get("/me")
def my_student_analytics(db: Session = Depends(get_db), user: models.User = Depends(require_roles("student"))):
    """Student-only view: published results belonging to the authenticated account."""
    if not user.student_id:
        raise HTTPException(403, "This account is not linked to a student record")
    st = db.get(models.Student, user.student_id)
    if not st: raise HTTPException(404, "Linked student record not found")
    rows = db.execute(select(models.Result, models.Exam).join(models.Exam, models.Exam.id == models.Result.exam_id)
                      .where(models.Result.student_id == st.id, models.Result.published.is_(True))
                      .order_by(models.Exam.exam_date, models.Exam.id)).all()
    history = [{"exam_id": e.id, "exam": e.title, "subject_code": e.subject_code, "date": e.exam_date,
                "marks": r.marks, "max_marks": r.max_marks, "percent": round(r.marks/r.max_marks*100, 2),
                "grade": r.grade} for r, e in rows if r.max_marks]
    progress = defaultdict(list)
    for item in history: progress[item["subject_code"]].append(item["percent"])
    return {"student": {"register_number": st.register_number, "full_name": st.full_name,
                        "department": st.department, "year": st.year},
            "history": history,
            "subject_progress": [{"subject_code": k, "attempts": len(v), "first_percent": v[0],
                                  "latest_percent": v[-1], "change_percentage_points": round(v[-1]-v[0], 2)}
                                 for k, v in sorted(progress.items())]}


@router.get("/comparisons")
def academic_comparisons(date_from: date | None = None, date_to: date | None = None,
                         department: str = Query("", max_length=100), subject_id: int | None = Query(None, ge=1),
                         pass_percent: float = Query(40, ge=0, le=100),
                         db: Session = Depends(get_db), user: models.User = Depends(require_roles(*READ))):
    """Compare stored result performance by academic year and semester."""
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "date_from must not exceed date_to")
    dept = _scope(user, department)
    rows = _result_rows(db, date_from, date_to, dept, None, subject_id, None, published_only=True)
    grouped = defaultdict(list)
    for result, student, exam in rows:
        term = db.get(models.ExamTerm, exam.term_id) if exam.term_id else None
        year = db.get(models.AcademicYear, term.academic_year_id) if term else None
        # Keep unlinked examinations visible as explicitly unclassified instead of dropping them.
        key = (year.label if year else "Unassigned academic year",
               term.semester_no if term and term.semester_no is not None else "Unassigned semester")
        grouped[key].append(result.marks/result.max_marks*100 if result.max_marks else None)
    output = []
    for (year, sem), values in sorted(grouped.items(), key=lambda x: (x[0][0], str(x[0][1]))):
        scores = [v for v in values if v is not None]
        passed = sum(v >= pass_percent for v in scores)
        output.append({"academic_year": year, "semester": sem, "result_records": len(scores),
                       "average_percent": round(sum(scores)/len(scores), 2) if scores else None,
                       "pass_count": passed, "fail_count": len(scores)-passed,
                       "pass_rate_percent": round(passed/len(scores)*100, 2) if scores else None})
    return {"pass_threshold_percent": pass_percent, "comparisons": output,
            "note": "Only stored result rows are compared; unlinked exam terms are shown as unassigned."}


@router.get("/insights")
def performance_insights(date_from: date | None = None, date_to: date | None = None,
                         department: str = Query("", max_length=100), subject_id: int | None = Query(None, ge=1),
                         change_threshold: float = Query(15, ge=1, le=100),
                         minimum_records: int = Query(5, ge=2, le=500),
                         db: Session = Depends(get_db), user: models.User = Depends(require_roles(*READ))):
    """Flag large exam-to-exam average changes for the same subject; no causal claim is made."""
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "date_from must not exceed date_to")
    dept = _scope(user, department)
    rows = _result_rows(db, date_from, date_to, dept, None, subject_id, None, published_only=True)
    grouped = defaultdict(list)
    for result, student, exam in rows:
        if result.max_marks:
            grouped[(exam.subject_code, exam.id, exam.title, exam.exam_date)].append(
                result.marks/result.max_marks*100)
    by_subject = defaultdict(list)
    for (code, eid, title, exam_date), scores in grouped.items():
        by_subject[code].append({"exam_id": eid, "exam": title, "date": exam_date,
                                 "records": len(scores), "average_percent": sum(scores)/len(scores)})
    findings = []
    for code, exams in by_subject.items():
        exams.sort(key=lambda x: (x["date"], x["exam_id"]))
        for previous, current in zip(exams, exams[1:]):
            if previous["records"] < minimum_records or current["records"] < minimum_records:
                continue
            delta = current["average_percent"] - previous["average_percent"]
            if abs(delta) >= change_threshold:
                findings.append({"subject_code": code, "previous_exam": previous, "current_exam": current,
                                 "change_percentage_points": round(delta, 2),
                                 "direction": "increase" if delta > 0 else "decrease",
                                 "evidence": f"Both examinations have at least {minimum_records} stored result records; "
                                             f"average changed by {abs(delta):.1f} percentage points.",
                                 "interpretation": "Unusual change indicator only; review cohort, assessment difficulty and context."})
    findings.sort(key=lambda x: abs(x["change_percentage_points"]), reverse=True)
    return {"rules": {"change_threshold_percentage_points": change_threshold,
                      "minimum_records_per_exam": minimum_records},
            "finding_count": len(findings), "findings": findings,
            "method": "Compare consecutive examination averages within the same subject using stored result percentages.",
            "limitations": ["This detects statistical changes, not their cause.",
                            "No estimate or missing score is inserted.",
                            "Small cohorts below the configured minimum are excluded."]}


@router.get("/allocation")
def allocation_analytics(exam_id: int | None = Query(None, ge=1), department: str = Query("", max_length=100),
                         db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    dept = _scope(user, department)
    stmt = select(models.Allotment, models.Student).join(models.Student, models.Student.id == models.Allotment.student_id)
    if exam_id: stmt = stmt.where(models.Allotment.exam_id == exam_id)
    if dept: stmt = stmt.where(func.lower(models.Student.department) == dept.lower())
    rows = db.execute(stmt).all()
    by_hall = defaultdict(int); by_dept = defaultdict(int); by_exam = defaultdict(int)
    for a, st in rows: by_hall[a.hall] += 1; by_dept[st.department] += 1; by_exam[a.exam_id] += 1
    halls = db.scalars(select(doc_models.Hall)).all()
    hall_stats = []
    for h in halls:
        used = by_hall.get(h.code, 0)
        hall_stats.append({"hall": h.code, "name": h.display_name, "verified": h.verified,
                           "capacity": h.capacity, "allocated": used,
                           "utilization_percent": round(used/h.capacity*100, 2) if h.capacity else None,
                           "capacity_source": "verified hall capacity" if h.verified and h.capacity else "unknown"})
    exam_stmt = select(models.Exam).order_by(models.Exam.exam_date.desc(), models.Exam.id.desc()).limit(500)
    if exam_id:
        exam_stmt = exam_stmt.where(models.Exam.id == exam_id)
    exams = db.scalars(exam_stmt).all()
    summaries = []
    for e in exams:
        elig = eligible_students(db, e)
        if dept:
            elig = [student for student in elig if (student.department or "").casefold() == dept.casefold()]
        allocated = db.scalar(select(func.count()).select_from(models.Allotment).join(
            models.Student, models.Student.id == models.Allotment.student_id).where(
            models.Allotment.exam_id == e.id,
            *([func.lower(models.Student.department) == dept.lower()] if dept else []))) or 0
        summaries.append({"exam_id": e.id, "exam": e.title, "eligible": len(elig),
                          "allocated": allocated, "unallocated": max(0, len(elig)-allocated)})
    return {"by_hall": hall_stats, "by_department": [{"department": k, "allocated": v} for k,v in sorted(by_dept.items())],
            "examinations": summaries, "allocated_records": len(rows),
            "capacity_note": "Utilization is calculated only where a verified hall has a recorded capacity; unknown capacities are not estimated. When department-scoped, allocated counts reflect that department's share of hall capacity."}


@router.get("/reports/performance")
def performance_report(format: str = Query("json", pattern="^(json|csv|xlsx|pdf)$"),
                       date_from: date | None = None, date_to: date | None = None,
                       department: str = Query("", max_length=100), semester: int | None = Query(None, ge=1, le=12),
                       subject_id: int | None = Query(None, ge=1), academic_year_id: int | None = Query(None, ge=1),
                       db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    if date_from and date_to and date_from > date_to: raise HTTPException(422, "date_from must not exceed date_to")
    dept = _scope(user, department)
    rows = _result_rows(db, date_from, date_to, dept, semester, subject_id, academic_year_id, published_only=True)
    cols = ["Register number", "Student", "Department", "Exam", "Subject", "Date", "Marks", "Maximum", "Percent", "Grade", "Published"]
    data = [{"register_number": st.register_number, "student": st.full_name, "department": st.department,
             "exam": e.title, "subject_code": e.subject_code, "date": e.exam_date, "marks": r.marks,
             "max_marks": r.max_marks, "percent": round(r.marks/r.max_marks*100, 2) if r.max_marks else None,
             "grade": r.grade, "published": r.published} for r, st, e in rows]
    matrix = [[d[k] for k in ["register_number","student","department","exam","subject_code","date","marks","max_marks","percent","grade","published"]] for d in data]
    if format == "json": return {"count": len(data), "filters": {"date_from": date_from, "date_to": date_to, "department": dept or None,
          "semester": semester, "subject_id": subject_id, "academic_year_id": academic_year_id}, "items": data}
    return tabular(format, "performance_analytics", "Student performance report", cols, matrix,
                   [f"Generated from {len(data)} stored result records", "No missing marks were inferred."])
