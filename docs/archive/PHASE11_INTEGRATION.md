# Phase 11 — cross-module integration

## Delivered in this source package

Phase 11 adds an integration layer over the existing Phase 1–10 modules rather than replacing their domain APIs.

### Web workflow centre

The signed-in staff navigation includes **Workflow centre**. It loads live counts from `GET /api/integration/overview`, then allows staff to select an examination and load `GET /api/integration/exams/{id}/readiness`.

The readiness view combines the existing examination and term records, eligible active student audience, verified hall capacities, committed seat allotments, result publication state and workflow actions. Department staff are limited to their assigned department for student, allocation and result counts. It links to the established examination, campus, allocation, reports and results pages.

The integration view is read-only. It does not silently publish an exam, approve OCR output, allocate seats, publish marks or replace existing approval flows. Those state changes continue to use the existing protected APIs and their audit/validation rules.

### Backend integration API

- `GET /api/integration/overview` — permission-scoped counts for active students, examinations, published timetables, allotments, published results, verified halls, processed PDF versions and the caller's unread notifications.
- `GET /api/integration/exams/{exam_id}/readiness` — exam-day readiness, audience/capacity/allocation totals, result publication totals and actionable workflow links.

Both endpoints require a staff, administrator or invigilator session. Unknown examination IDs return 404. The API deliberately identifies attendance as unavailable; no attendance data is fabricated.

### Android API integration

The Retrofit API now exposes the Phase 11 workflow overview, per-exam readiness and authenticated student's own Phase 10 analytics endpoint. `IntegrationRepository` converts responses through the app's existing typed `ApiResult` error path, and is exposed through the existing `Services` container. JSON aggregation responses remain forward-compatible with additive server fields.

### Preservation

No database migration was introduced. Existing tables, migration history, stored records, authentication and permission dependencies, OCR/document review, result publication, notification delivery, backup/export tools and Android screens remain in place. The integration layer composes existing records and delegates mutations to their original modules.

## External-service and data limitations

- SMTP delivery still requires institution-provided SMTP settings and credentials.
- OCR quality for scanned institutional PDFs depends on Tesseract/language data and human review.
- PostgreSQL backup/restore requires the corresponding PostgreSQL client binaries in the maintenance environment.
- Attendance is not represented by a supported source table/API and is reported as unavailable.
- Android source integration is included; this delivery does not claim a device build or Play Store release.

## Verification status

As explicitly requested for Phase 11, no tests, audits, verification runs, builds or repeated checks were performed for this phase. Treat the new integration code as implementation delivered but not independently verified. Existing historical test reports describe earlier phases only and are not Phase 11 results.
