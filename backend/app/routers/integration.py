"""Phase 11 cross-module workflow integration.

This router composes existing examination, eligibility, campus, allocation, result,
PDF/OCR and communications records into a single permission-scoped workflow view.
It is deliberately read-only: mutations remain owned by their established domain APIs.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .. import models, doc_models
from ..database import get_db
from ..deps import require_roles, department_scope
from ..services_allocation import eligible_students

router = APIRouter(prefix="/api/integration", tags=["Phase 11 workflow integration"])
STAFF = ("admin", "staff", "invigilator")


def _exam_or_404(db: Session, exam_id: int):
    exam = db.get(models.Exam, exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Examination not found")
    return exam


@router.get("/overview")
def integration_overview(db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    """Live counts across modules, scoped to the caller's department where applicable."""
    dept = department_scope(user)
    student_q = select(func.count()).select_from(models.Student).where(models.Student.active.is_(True))
    if dept:
        student_q = student_q.where(func.lower(models.Student.department) == dept.lower())
    exam_q = select(func.count()).select_from(models.Exam)
    if dept:
        # Exams with no explicit audience remain institution-wide; otherwise require a matching rule.
        scoped = select(models.ExamEligibilityRule.exam_id).where(func.lower(models.ExamEligibilityRule.department) == dept.lower())
        rule_counts = select(models.ExamEligibilityRule.exam_id).group_by(models.ExamEligibilityRule.exam_id)
        exam_q = exam_q.where(~models.Exam.id.in_(rule_counts) | models.Exam.id.in_(scoped))
    allotment_q = select(func.count()).select_from(models.Allotment)
    result_q = select(func.count()).select_from(models.Result).where(models.Result.published.is_(True))
    if dept:
        allotment_q = allotment_q.join(models.Student, models.Student.id == models.Allotment.student_id).where(func.lower(models.Student.department) == dept.lower())
        result_q = result_q.join(models.Student, models.Student.id == models.Result.student_id).where(func.lower(models.Student.department) == dept.lower())
    return {
        "scope": {"department": dept, "role": user.role},
        "students": db.scalar(student_q) or 0,
        "examinations": db.scalar(exam_q) or 0,
        "published_examinations": db.scalar(exam_q.where(models.Exam.status == "published")) or 0,
        "allotments": db.scalar(allotment_q) or 0,
        "published_results": db.scalar(result_q) or 0,
        "verified_halls": db.scalar(select(func.count()).select_from(doc_models.Hall).where(doc_models.Hall.verified.is_(True))) or 0,
        "processed_pdf_versions": db.scalar(select(func.count()).select_from(doc_models.DocumentVersion).where(doc_models.DocumentVersion.processing_status == "processed")) or 0,
        "unread_notifications": db.scalar(select(func.count()).select_from(models.Notification).where(models.Notification.user_id == user.id, models.Notification.read_at.is_(None), models.Notification.archived_at.is_(None), models.Notification.deleted_at.is_(None))) or 0,
        "attendance": {"available": False, "reason": "No attendance source is configured in this release."},
    }


@router.get("/exams/{exam_id}/readiness")
def exam_workflow_readiness(exam_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_roles(*STAFF))):
    """One workflow checklist joining exam setup, audience, campus capacity, seats and results."""
    exam = _exam_or_404(db, exam_id)
    dept = department_scope(user)
    eligible = eligible_students(db, exam)
    if dept:
        eligible = [s for s in eligible if (s.department or "").casefold() == dept.casefold()]
    allocated_q = select(func.count()).select_from(models.Allotment).join(models.Student).where(models.Allotment.exam_id == exam.id)
    if dept:
        allocated_q = allocated_q.where(func.lower(models.Student.department) == dept.lower())
    allocated = db.scalar(allocated_q) or 0
    halls = db.scalars(select(doc_models.Hall).where(doc_models.Hall.verified.is_(True), doc_models.Hall.capacity.is_not(None))).all()
    capacity = sum(max(0, h.capacity or 0) for h in halls)
    result_q = select(func.count()).select_from(models.Result).where(models.Result.exam_id == exam.id)
    if dept:
        result_q = result_q.join(models.Student).where(func.lower(models.Student.department) == dept.lower())
    results_total = db.scalar(result_q) or 0
    results_published = db.scalar(result_q.where(models.Result.published.is_(True))) or 0
    issues = []
    if not exam.subject_code: issues.append("Assign a subject code")
    if not exam.term_id: issues.append("Link an academic term")
    if not eligible: issues.append("No eligible active students match this examination")
    if capacity < len(eligible): issues.append("Verified hall capacity is below the eligible student count")
    if allocated < len(eligible): issues.append(f"Allocate seats for {len(eligible) - allocated} remaining eligible students")
    if exam.status != "published": issues.append("Publish the examination timetable after review")
    if results_total and results_published < results_total: issues.append("Publish entered results when approved")
    return {
        "exam": {"id": exam.id, "title": exam.title, "subject_code": exam.subject_code, "date": exam.exam_date,
                 "start_time": exam.start_time, "end_time": exam.end_time, "status": exam.status},
        "scope": {"department": dept},
        "audience": {"eligible_students": len(eligible)},
        "campus": {"verified_halls": len(halls), "known_verified_capacity": capacity,
                   "capacity_sufficient": capacity >= len(eligible)},
        "allocation": {"allocated": allocated, "unallocated": max(0, len(eligible) - allocated),
                       "complete": allocated >= len(eligible)},
        "results": {"records": results_total, "published": results_published,
                    "complete": results_total > 0 and results_published == results_total},
        "workflow": {"ready_for_exam_day": exam.status == "published" and allocated >= len(eligible) and bool(eligible),
                     "issues": issues,
                     "actions": [{"label": "Edit examination", "route": f"#/exams"},
                                 {"label": "Manage halls", "route": "#/halls"},
                                 {"label": "Allocate seats", "route": f"#/allocation?exam_id={exam.id}"},
                                 {"label": "Open reports", "route": f"#/reports?exam_id={exam.id}"},
                                 {"label": "Manage results", "route": "#/results"}]}
    }
