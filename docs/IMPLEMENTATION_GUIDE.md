# Phase 2 completion implementation guide

## New capabilities in this update

- Scheduled announcements with publication and expiry windows.
- Admin hall directory management. Newly created halls are deliberately unverified until an administrator explicitly verifies them.
- PDF upload with size/type/signature validation, SHA-256 duplicate detection, server-generated storage names, metadata/version records and an admin-only review queue.
- Conservative PDF text-layer extraction. Register-number candidates are stored as **pending**; nothing becomes student-visible until every candidate has been reviewed and the document version is approved.
- Optional local OCR endpoint, requiring the packages in `backend/requirements-ocr.txt` and a separately installed Tesseract executable.
- Student lookup response can include page references for administrator-approved source-document entries.
- Public timetable and announcements panels; expanded Android student client with editable API base URL, lookup, timetable and announcements.
- Readiness endpoint (`GET /api/ready`) and Windows install/start/stop/test/backup scripts.

## PDF workflow

1. Sign in with an administrator or staff account.
2. Upload a PDF in the dashboard or `POST /api/admin/documents/upload` (multipart fields `file`, `title`, `doc_kind`). Maximum upload size is 25 MiB.
3. Process the returned version ID with `POST /api/admin/documents/{version_id}/process`.
4. Review candidates with `GET /api/admin/documents/{version_id}/review`.
5. Approve or reject each candidate using `POST /api/admin/documents/entries/{entry_id}/review` with form field `decision`.
6. Once no pending candidates remain, an administrator may approve the document version using `POST /api/admin/documents/{version_id}/approve`.

The text extractor intentionally does not guess dates, sessions, subject titles, seat numbers or hall locations. It does not infer a seating layout. Extracted register numbers have no confidence score unless a future extractor supplies one. OCR is an optional local operation and still requires human review. The original PDF is preserved in `backend/uploads`; backups include this folder.

## OCR setup (optional)

Install `backend/requirements-ocr.txt` into the same virtual environment and install the Tesseract OCR application separately. Ensure `tesseract.exe` is available on PATH (or configure `pytesseract.pytesseract.tesseract_cmd` in a controlled deployment-specific extension). Call `POST /api/admin/documents/{version_id}/ocr?lang=eng` (use `lang=tam+eng` when the corresponding Tesseract Tamil and English language packs are installed). OCR candidates remain pending. OCR quality depends on source resolution and language packs; no accuracy guarantee is made.

## Hall directory

`GET /api/halls` exposes only verified halls. Administrators/staff can inspect the full directory at `GET /api/admin/halls`; administrators create/update halls and explicitly verify them. Buildings, blocks and floors have normalized tables; hall records can reference each level while retaining legacy text labels. Individual numbered seats can be generated from hall capacity. Existing allotment rows continue to use their legacy hall/seat text columns for backward compatibility.

## Announcements

Admin/staff manage announcements under `/api/admin/announcements`. Student clients read `/api/announcements`, which filters unpublished, not-yet-published and expired notices. Dates should be supplied as ISO-8601 values with timezone information.

## Backup

Run `backup.bat` to create a verified ZIP with a SHA-256 manifest. SQLite uses the online backup API; PostgreSQL uses `pg_dump` when the PostgreSQL client tools are installed. Restore only while the application is stopped using `restore_backup.bat`; the restore workflow creates a safety backup first. See `docs/archive/PHASE82_DATA_MANAGEMENT.md`.

## Important limitations

- No external institutional PDF crawler is included; PDFs are uploaded by authorized users.
- OCR requires a local Tesseract installation and is not bundled.
- Hall hierarchy and seat inventory are normalized, while legacy allotment records continue to store hall and seat labels as text for compatibility. A full automatic seat allocation optimizer is not included; administrators create individual allotments against the configured inventory.
- Timetable entries use the existing `Exam` model and published status. Separate normalized subject catalogue and academic term management are not present.
- Password reset is administrator/CLI mediated; no email/SMS delivery integration is configured.
- The Android project source has been expanded, but no claim is made that it compiles until Android SDK/Gradle verification is authorized and run.
- This project is not production-certified. Deploy behind HTTPS, use institution-approved data, configure backups, and review privacy/legal requirements before handling real student records.
