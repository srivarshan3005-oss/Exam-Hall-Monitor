"""Synthetic demo data. NEVER put real student records here.

The register numbers use the prefix 9900, which is not a VSB college code, so they cannot
collide with real register numbers while keeping the realistic 12-digit shape.
"""
from datetime import date, timedelta
from sqlalchemy import select
from sqlalchemy.orm import Session
from . import models

DEMO_STUDENTS = [
    ("990025106001", "Demo Student One", "Electronics and Communication", 2),
    ("990025106002", "Demo Student Two", "Electronics and Communication", 2),
    ("990025205001", "Demo Student Three", "Computer Science", 2),
    ("990024106003", "Demo Student Four", "Electronics and Communication", 3),
]


def seed_demo(db: Session) -> dict:
    """Idempotent. Creates synthetic students, one published exam and two seat allotments.
    Does NOT create any login account."""
    created = {"students": 0, "exams": 0, "allotments": 0}
    students = {}
    for reg, name, dept, year in DEMO_STUDENTS:
        s = db.scalar(select(models.Student).where(models.Student.register_number == reg))
        if not s:
            s = models.Student(register_number=reg, full_name=name, department=dept, year=year)
            db.add(s)
            created["students"] += 1
        students[reg] = s
    exam = db.scalar(select(models.Exam).where(models.Exam.title == "DEMO End Semester Examination",
                                               models.Exam.subject_code == "DEMO101"))
    if not exam:
        exam = models.Exam(title="DEMO End Semester Examination", subject_code="DEMO101",
                           exam_date=(date.today() + timedelta(days=14)).isoformat(),
                           start_time="09:30", end_time="12:30", venue="DEMO BLOCK (synthetic)",
                           status="published")
        db.add(exam)
        created["exams"] += 1
    db.flush()
    for reg, seat in (("990025106001", "1"), ("990025106002", "2")):
        s = students[reg]
        if not db.scalar(select(models.Allotment).where(models.Allotment.student_id == s.id,
                                                        models.Allotment.exam_id == exam.id)):
            db.add(models.Allotment(student_id=s.id, exam_id=exam.id, hall="DEMO HALL 01", seat=seat))
            created["allotments"] += 1
    db.commit()
    return created
