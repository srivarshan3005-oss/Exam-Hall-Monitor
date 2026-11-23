from app import models
from conftest import make_user, make_student, make_exam, login


def test_dashboard_uses_only_persisted_results_and_marks_attendance_unavailable(client, db):
    make_user(db, "analytics_admin", "admin")
    student = make_student(db)
    exam = make_exam(db)
    db.add(models.Result(student_id=student.id, exam_id=exam.id, marks=75, max_marks=100, published=True))
    db.commit()
    headers = login(client, "analytics_admin")
    response = client.get("/api/analytics/dashboard", headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["performance"]["result_records"] == 1
    assert data["performance"]["average_percent"] == 75
    assert data["performance"]["pass_count"] == 1
    assert data["attendance"]["available"] is False
    assert data["data_quality"]["estimates_used"] is False


def test_student_analytics_is_scoped_to_linked_student(client, db):
    student = make_student(db)
    make_user(db, "analytics_student", "student", student=student)
    headers = login(client, "analytics_student")
    response = client.get("/api/analytics/me", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["student"]["register_number"] == student.register_number


def test_at_risk_rules_are_exposed_and_need_published_history(client, db):
    make_user(db, "analytics_staff", "staff")
    student = make_student(db)
    exam1 = make_exam(db, date="2027-01-15")
    exam2 = make_exam(db, date="2027-02-15")
    db.add_all([
        models.Result(student_id=student.id, exam_id=exam1.id, marks=70, max_marks=100, published=True),
        models.Result(student_id=student.id, exam_id=exam2.id, marks=40, max_marks=100, published=True),
    ])
    db.commit()
    headers = login(client, "analytics_staff")
    response = client.get("/api/analytics/students/at-risk?minimum_results=2&threshold=60&recent_drop=20",
                          headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rules"]["average_below_percent"] == 60
    assert body["total"] == 1
    assert len(body["items"][0]["reasons"]) == 2


def test_insights_detect_only_large_changes_with_minimum_cohort(client, db):
    make_user(db, "insight_admin", "admin")
    first = make_exam(db, date="2027-01-15")
    second = make_exam(db, date="2027-02-15")
    for index in range(5):
        student = make_student(db, reg=f"9900251060{index:02d}", name=f"Student {index}")
        db.add_all([
            models.Result(student_id=student.id, exam_id=first.id, marks=80, max_marks=100, published=True),
            models.Result(student_id=student.id, exam_id=second.id, marks=50, max_marks=100, published=True),
        ])
    db.commit()
    headers = login(client, "insight_admin")
    response = client.get("/api/analytics/insights?minimum_records=5&change_threshold=15", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["finding_count"] >= 1
    assert body["findings"][0]["direction"] == "decrease"
    assert body["findings"][0]["change_percentage_points"] == -30


def test_academic_comparisons_keep_unassigned_exams_visible(client, db):
    make_user(db, "compare_admin", "admin")
    student = make_student(db)
    exam = make_exam(db)
    db.add(models.Result(student_id=student.id, exam_id=exam.id, marks=60, max_marks=100, published=True))
    db.commit()
    headers = login(client, "compare_admin")
    response = client.get("/api/analytics/comparisons", headers=headers)
    assert response.status_code == 200, response.text
    row = response.json()["comparisons"][0]
    assert row["academic_year"] == "Unassigned academic year"
    assert row["semester"] == "Unassigned semester"
    assert row["average_percent"] == 60


def test_performance_report_supports_csv_xlsx_and_pdf(client, db):
    make_user(db, "export_admin", "admin")
    student = make_student(db)
    exam = make_exam(db)
    db.add(models.Result(student_id=student.id, exam_id=exam.id, marks=88, max_marks=100, published=True))
    db.commit()
    headers = login(client, "export_admin")
    for fmt, content_type in [("csv", "text/csv"), ("xlsx", "spreadsheetml"), ("pdf", "application/pdf")]:
        response = client.get(f"/api/analytics/reports/performance?format={fmt}", headers=headers)
        assert response.status_code == 200, response.text
        assert content_type in response.headers.get("content-type", "")
        assert len(response.content) > 100


def test_allocation_analytics_reports_unallocated_eligible_students(client, db):
    make_user(db, "allocation_analytics", "admin")
    make_student(db)
    exam = make_exam(db)
    headers = login(client, "allocation_analytics")
    response = client.get("/api/analytics/allocation", headers=headers)
    assert response.status_code == 200, response.text
    row = next(item for item in response.json()["examinations"] if item["exam_id"] == exam.id)
    assert row["eligible"] == 1
    assert row["allocated"] == 0
    assert row["unallocated"] == 1
