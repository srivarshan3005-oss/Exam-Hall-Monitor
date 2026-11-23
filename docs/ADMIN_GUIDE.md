# Administrator guide

## First administrator

Create the initial administrator interactively during `install.bat`. No default administrator password is embedded. Additional accounts are created from the dashboard or `python -m app.cli create-admin --username <username>`.

## Daily operations

- Create and publish examinations. Draft exams are not visible on the student timetable.
- Add student records. Create student accounts linked to an existing register number when login is required.
- Optionally create building, block and floor records on the **Halls & campus** page (they appear as one location dropdown in the hall form; no IDs to copy).
- Create a hall, set capacity, link hierarchy IDs, then verify the hall after checking the physical details.
- Generate numbered seat inventory for a hall. Existing inventory is never silently overwritten.
- Allocate students to an exam using a verified hall and an active seat. Duplicate student/exam and duplicate exam/hall/seat combinations are rejected by the database constraints.
- Create announcements with timezone-aware publication and expiry timestamps.
- Upload official PDFs, process text, review each candidate, and approve the version only after review.
- Create and publish results only after institutional approval to do so.
- Review audit events. Audit entries avoid recording marks/passwords; document review records page references and decisions.

## Permissions

Admin can manage users, students, examinations, hall hierarchy, halls, seats, results, documents and audit history. Staff can access operational features where routes allow. Student accounts are limited to their linked records. The public lookup does not expose a full student list.

Use only institution-authorized student data. This independent project has no institutional endorsement built in.

## Examination workspace (sidebar pages since 0.6.0)
1. **Subjects** tab: add the subject catalogue. **Academic years & terms** (admin): add a year, then terms with date windows.
2. **Examinations** tab: create exams (pick a catalogue subject and term), set the **Audience** (department/course/year rules; none = all students), then **Publish**.
3. Prepare halls (Hall directory): save, **generate seat inventory**, **verify**.
4. **Seat allocation** tab: choose exam, halls and rules → **Build preview** → review capacity warnings, unallocated students and existing-seat problems → an administrator **approves**. Use **Current allocations and corrections** to move/remove seats (reason required); every change is in the history and audit log.
5. **Reports** tab: view, download (CSV/XLSX/PDF) or print allocation lists, unallocated students, hall occupancy and hall-wise seating charts; look up a student's seats.

## Document processing workspace (Phase 3)
Sidebar → *Timetable PDFs* (Documents group). 1) Upload the PDF (duplicates are refused). 2) Extraction runs automatically; scanned pages use OCR. 3) *Review*: compare each row with the original page preview; amber fields are uncertain; correct values and add a reason; approve or reject rows; approve the document. 4) *Import*: build the preview (subject mapping, duplicates, conflicts), tick any "update existing" rows, confirm. Imported exams are drafts — publish from *Examinations*. 5) *History* shows events and every correction.

## Web interface map (Phase 5)
Sign in at `/`. The sidebar shows only the pages your role may use (see `docs/FRONTEND.md`). Destructive or irreversible actions (publish, delete, commit allocation, import, reset password, suspend, force sign-out) ask for confirmation. Password resets show the temporary password once. Account role changes sign the user out. Results: *Examinations → Results* lists every result (published or not) so it can be published/unpublished.

## Database administration (Phase 8.3)
See `archive/PHASE83_DATABASE_ADMIN.md` for the administrator database console, migration ledger, verified backup download, integrity reporting, import/export, and safe offline restore workflow. Apply new migrations with `python -m app.cli migrate` from `backend`.
