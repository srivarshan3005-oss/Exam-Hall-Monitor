# API additions in expanded Phase 2 checkpoint

Existing endpoints remain available. New endpoints are listed below. All `/api/admin/*` document, hall, building and announcement management endpoints require appropriate bearer-token roles.

## Health
- `GET /api/ready` — verifies database connectivity; returns 503 when unavailable.

## Student-facing
- `GET /api/exams` — published examinations (existing endpoint, used as timetable).
- `GET /api/announcements` — currently applicable published announcements.
- `GET /api/halls` — verified hall directory only.
- `GET /api/lookup/{register_number}` — now may include `source_documents`, containing administrator-approved PDF page references only.

## Campus administration
- `GET /api/admin/buildings`
- `POST /api/admin/buildings`
- `GET /api/admin/buildings/{building_id}/blocks`
- `POST /api/admin/buildings/{building_id}/blocks`
- `GET /api/admin/blocks/{block_id}/floors`
- `POST /api/admin/blocks/{block_id}/floors`
- `GET /api/admin/halls`
- `POST /api/admin/halls`
- `PATCH /api/admin/halls/{hall_id}`
- `POST /api/admin/halls/{hall_id}/verify`
- `POST /api/admin/halls/{hall_id}/seats/generate`
- `GET /api/admin/halls/{hall_id}/seats`
- `GET /api/admin/announcements`
- `POST /api/admin/announcements`
- `PATCH /api/admin/announcements/{announcement_id}`
- `DELETE /api/admin/announcements/{announcement_id}` (admin only)

## PDF intake and review
- `GET /api/admin/documents`
- `POST /api/admin/documents/upload` — multipart: `file`, `title`, `doc_kind`.
- `POST /api/admin/documents/{version_id}/process` — text-layer extraction.
- `POST /api/admin/documents/{version_id}/ocr` — optional OCR dependencies and Tesseract required.
- `GET /api/admin/documents/{version_id}/review`
- `POST /api/admin/documents/entries/{entry_id}/review` — form field `decision=approved|rejected|needs_review` (administrator only).
- `POST /api/admin/documents/{version_id}/approve` — administrator only; refuses while pending entries remain.
- `GET /api/admin/documents/{version_id}/page/{page_number}` — page metadata for authorized staff/admin.

## New migration revisions

- `0003`: scheduled announcements.
- `0004`: normalized buildings, blocks, floors, hall references and hall seat inventory.

Apply migrations with `python -m app.cli migrate` from the backend directory. Back up existing data before migration.

## 0.3.0 — Phase 2 (examination management and seat allocation)
Additive. New: `/api/admin/subjects|academic-years|terms`; `/api/exams/{id}/publish|unpublish|eligibility`, `DELETE /api/exams/{id}`;
`/api/allotments/plans[/{id}[/commit|/discard]]`, `PATCH /api/allotments/{id}`, `GET /api/allotments/exam/{id}`, `GET /api/allotments/history`;
`/api/admin/reports/**` (json/csv/xlsx/pdf). `GET /api/admin/exams` gained filters and `X-Total-Count`; exam objects gained
`subject_id`, `term_id`, `duration_minutes`, `session`. `subject_code` is optional when `subject_id` is supplied.
`/api/allotments/auto-preview|auto-allocate` accept `strategy`, `seat_gap`, `department_separation` (defaults reproduce Phase 1).
Manual allocation now also enforces eligibility and simultaneous-exam clashes (409). See `/docs` for the full schema.

## 0.4.0 — Phase 3 (document processing)
New, admin/staff only, prefix `/api/admin/doc-processing`: `GET /capabilities`, `GET ""` (filters q,status,kind), `POST /upload`, `POST /{version}/process[?force_ocr=true&lang=eng]`, `GET /{version}`, `GET /{version}/review`, `GET /{version}/history`, `GET /{version}/download`, `GET /{version}/pages/{n}/preview|text`, `POST /{version}/import/preview`.
Admin only: `PATCH /{version}/header`, `POST /{version}/entries`, `PATCH /entries/{id}`, `POST /entries/{id}/decision`, `POST /{version}/entries/bulk-decision`, `POST /{version}/decision`, `POST /{version}/import` (requires `confirm=true` and the preview `signature`).
Upload errors: 415 wrong type, 413 too large, 422 damaged/encrypted/active-content, 409 duplicate (body has the existing document/version). Phase 1 `/api/admin/documents/*` is unchanged.


## 0.7.0 (Phase 6)
New: `/api/notifications*`, `/api/admin/communications/*`. Announcements: optional `priority, audience_roles, audience_department, audience_year, notify, remind_at`; responses add the same fields. Targeted announcements are excluded from `GET /api/announcements`.

## Phase 8.2 — administrator data-management APIs

- `GET /api/admin/data/status` — database and migration status.
- `GET /api/admin/data/integrity` — read-only data-integrity report.
- `GET /api/admin/data/backups` / `POST /api/admin/data/backups` — list/verify or create a backup.
- `GET /api/admin/data/export/{students|exams|results|allotments}?format=json|csv|xlsx|pdf` — capped exports.
- `POST /api/admin/data/import/students?mode=preview` — validate CSV/XLSX/JSON without writes.
- `POST /api/admin/data/import/students?mode=commit&confirm=true` — revalidate and atomically import a corrected file.

All endpoints require administrator authorization. Database restore is intentionally CLI-only and must run while the application is stopped; see `docs/archive/PHASE82_DATA_MANAGEMENT.md`.

## VSB official-source integration
- `GET /api/vsb/official-links` (public) - confirmed official pages and listed notice PDFs (titles, dates, college URLs only).
- Admin/staff: `GET /api/vsb/sources`, `GET /api/vsb/links`, `GET /api/vsb/runs`, `POST /api/vsb/discover`, `POST /api/vsb/links/{id}/download`, `GET /api/vsb/links/{id}/history`.
- Migration `0012` adds `vsb_source_links` and `vsb_crawl_runs` (additive).

## 0.8.0
* Added `GET /api/portal/notices`, `GET /api/portal/lookup/{register_number}`, `GET /api/portal/seatmap/{register_number}` (public, rate limited).
* Added `GET /api/operations/overview` (staff/admin/super admin, department-scoped for staff).
* `/api/lookup/{register_number}` unchanged. No database migration was needed (no schema change).
* Portal static files are now `portal/index.html`, `portal.css`, `portal.js`.
