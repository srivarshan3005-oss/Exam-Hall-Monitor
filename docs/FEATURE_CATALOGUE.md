# Feature catalogue — implementation checkpoint

| ID | Feature | Implementation state | Notes |
|---|---|---|---|
| EM-001 | Student records and privacy-limited register lookup | Existing foundation preserved | Public lookup is rate-limited; no bulk student API |
| EM-002 | Authentication and role permissions | Existing foundation preserved | Admin/staff/student roles; secure password hashing and token versioning |
| EM-003 | Examination timetable | Implemented in source | Existing Exam records; only published exams are public |
| EM-004 | Legacy seat allotments | Existing foundation + configured-hall validation | Duplicate constraints preserved; inventory validation applies to configured halls |
| EM-005 | Building/block/floor hierarchy | Implemented in source | New normalized tables and hall foreign keys |
| EM-006 | Hall directory and verification | Implemented in source | Public hall directory includes verified halls only |
| EM-007 | Hall seat inventory | Implemented in source | Admin can generate capacity-based numbered seats |
| EM-008 | PDF upload/version metadata | Implemented in source | 25 MiB limit, signature check, SHA-256 deduplication |
| EM-009 | PDF text extraction | Partial | Candidate register numbers only; pending review |
| EM-010 | OCR | Optional integration source | Requires external Tesseract binary and optional Python packages |
| EM-011 | Extraction review/approval | Implemented in source | Entry review and document-version approval are separate |
| EM-012 | Announcements | Implemented in source | Scheduled publication and expiry filtering |
| EM-013 | Audit history | Existing foundation extended | New administrative actions are logged |
| EM-014 | Web portal | Expanded in source | Student timetable, announcements and admin workflows |
| EM-015 | Android student client | Expanded source, build pending | API URL setting, lookup, timetable, announcements |
| EM-016 | Windows operation scripts | Authored, execution pending | Install/start/stop/test/backup |
| EM-017 | Backup | SQLite implemented in source | PostgreSQL requires pg_dump workflow |

**Important:** “Implemented in source” is not a claim that the feature has passed tests. Final verification is pending user authorization.
