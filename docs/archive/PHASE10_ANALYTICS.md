# Phase 10 — Advanced Analytics, Intelligence & Reporting

## Overview
Phase 10 adds live, database-backed analytics APIs to the existing FastAPI application. It does not add replacement tables or alter Phase 1–9 records. All values are calculated from the current `students`, `exams`, `results`, `exam_terms`, `allotments`, eligibility rules and verified hall directory.

## Access and privacy
- `admin`: institution-wide analytics.
- `staff`: analytics are restricted to the staff account's configured department when one is assigned. A caller cannot override that scope with a query parameter.
- `invigilator`: read-only aggregate dashboard.
- `student`: `/api/analytics/me` returns only published results for the student linked to the authenticated account.
- Detailed individual student history and at-risk screening are restricted to admin/staff.
- All endpoints use the existing bearer-token authentication and role dependency layer.

## Endpoints

### `GET /api/analytics/dashboard`
Optional filters: `date_from=YYYY-MM-DD`, `date_to=YYYY-MM-DD`, `department`, `semester`, `subject_id`, `academic_year_id`, `pass_percent` (0–100; default 40).

Returns result count, distinct students represented, average percentage, pass/fail counts and rate, department/subject aggregates, chronological exam trend, allocation totals, and data-quality metadata. Pass/fail is computed from each stored result's `marks / max_marks * 100` against the supplied threshold. Only published, stored result rows are counted; missing scores are not imputed.

Attendance is returned as `available: false` with an explanation because the Phase 9 schema has no attendance records. It must not be interpreted as zero attendance.

### `GET /api/analytics/comparisons`
Optional filters: `date_from`, `date_to`, `department`, `subject_id`, `pass_percent`. Compares average percentage and pass/fail rates by academic year and semester. Exams not linked to an academic term remain visible as "Unassigned" rather than being discarded.

### `GET /api/analytics/insights`
Optional filters: `date_from`, `date_to`, `department`, `subject_id`, `change_threshold` (percentage points; default 15), `minimum_records` (default 5). Compares consecutive examinations within the same subject. It flags only changes meeting the threshold when both examinations meet the minimum cohort size. Findings include the two observed averages, sample counts, direction and limitations. It does not claim causation.

### `GET /api/analytics/students/{register_number}
Admin/staff only. Returns a student's published result history and subject progression. Department-scoped staff can only query students in their assigned department. A subject's change is latest published percentage minus first published percentage; one-attempt subjects are identified by `attempts: 1`.

### `GET /api/analytics/me`
Student role only. Uses the authenticated account's linked `student_id`; the caller cannot provide another register number. Only published results are returned.

### `GET /api/analytics/students/at-risk`
Admin/staff only. Configurable screening:
- `minimum_results` (default 2): minimum published result count.
- `threshold` (default 45): flag when the student's published-result average is below this percentage.
- `recent_drop` (default 15): flag when the latest result is at least this many percentage points below the preceding result.
- `department`, `limit` (1–500), `offset`.

The response includes the exact configured rules and human-readable reasons. This is a review aid, not a diagnosis or final academic decision. Staff must review context before intervention.

### `GET /api/analytics/allocation`
Admin/staff only. Optional `exam_id` and `department`. Returns allocation counts by hall and department, per-exam eligible/allotted/unallocated totals, and hall capacity utilization only where a verified hall has a recorded capacity. Unknown capacity is `null`, never estimated.

### `GET /api/analytics/reports/performance`
Admin/staff only. Supports `format=json|csv|xlsx|pdf` and the dashboard date, department, semester, subject and academic-year filters. Exports student performance rows using the existing professional export implementation.

## Filters, pagination and data interpretation
The at-risk list supports limit/offset pagination. Existing examination and allocation list endpoints retain their established pagination/search behavior. The analytics dashboard returns aggregates rather than an unbounded student-level listing. Date filters use the examination's local calendar date stored in `YYYY-MM-DD` form.

- A result is a published record, not necessarily a unique student. The API separately reports `students_with_results`.
- Averages and pass rates use only rows returned by the selected filters.
- No attendance data, missing score, estimated capacity or inferred student profile is generated.
- Historical trend points are grouped by examination and ordered by exam date.
- Department and subject groupings reflect the values on persisted student/exam records.

## Administrator guide
1. Sign in with an authorized administrator or staff account.
2. Open `/docs` in a development environment (if API docs are enabled) or call the endpoints from the authorized admin client.
3. Set date/department/semester/subject/academic-year filters before comparing periods.
4. Review the dashboard's `data_quality` and attendance availability fields.
5. For student review, use the register-number history endpoint and inspect source result records.
6. For at-risk screening, choose and record thresholds appropriate to institutional policy; do not treat flags as decisions.
7. Download performance reports as CSV for data exchange, Excel for analysis, or PDF for printing.

## Report guide
- **Performance report:** published result-level rows; filters apply to exam dates, department, semester, subject and academic year.
- **Allocation analytics:** hall/department occupancy and unallocated eligible counts.
- **Existing examination/seating reports:** remain available under `/api/admin/reports`; their existing CSV/XLSX/PDF functionality is unchanged.
- Printed PDF reports are generated by the existing ReportLab export helper.

## Deployment and operational notes
No new third-party runtime dependency or database migration is required. The router uses existing SQLAlchemy models, indexes, authorization dependencies and export helpers. For large installations, apply the date/department/subject filters, keep result exports scoped, and use the database's existing indexes on result student/exam IDs, exam term/subject IDs and allotment exam IDs. Run the targeted Phase 10 tests plus the existing full suite in the target deployment environment before release.
