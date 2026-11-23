# Audit: original hall-allocation data and the Exam Monitor Ultimate integration

Status labels: **VERIFIED** (checked against evidence in this audit), **FIXED** (defect found and corrected here, with a
regression test), **FAILED** (checked and not met), **NOT TESTED** (not executed, reason given),
**BLOCKED BY MISSING SOURCE DATA** (the official source is not available to check against).

## 1. Archives compared

| Item | Result |
|---|---|
| Main project as uploaded (`EXAM_MONITOR_ULTIMATE_COMPLETE_FINAL.zip`) | ZIP integrity VERIFIED; 308 files, 871,149 bytes |
| "Exam_Monitor_Ultimate_VSB_KARUR_FINAL_RELEASE (5).zip" named in this request | **Not present** in the uploads. The release audited here is the one produced from the uploaded main project in the previous step |
| Original mirror (`EXAM_MONITOR-main.zip`) | ZIP integrity VERIFIED; 3,831 files, 184,380,122 bytes. Includes a Windows virtual environment (about 1,400 files), a 35 MB SQLite database, 560 evidence PNGs in *docs/evidence/* (historical; not included in this package), a duplicate set in `portal/evidence/`, and the GitHub Actions workflow |
| Delivered release compared with the uploaded main project | 464 files (excluding generated `node_modules` and `__pycache__`). **156 added, 9 changed, 0 removed.** Changed: `vsb_alloc.py` router, `reconcile.py`, `pages-vsb-alloc.js`, the release manifest, and five documents |
| Files from the original mirror that the main project does not need | `venv/`, `.github/`, `vsb_watch/`, `supabase_schema.sql`, the original Flask/Pages portal (`portal/`, `index.html`), `data/state/*.sqlite3`. Not copied, by design |
| Generated junk found in the release | 15 mail-outbox files in `backend/outbox/` written by test servers. **FIXED**: removed before packaging; the folder is generated and already git-ignored |
| Duplicate files in the original mirror | *docs/evidence/* and *portal/evidence/* hold the same images (historical; not included in this package). Only the 135 referenced by the allocation data were kept for the operator |

## 2. Original data integration

| Check | Evidence | Status |
|---|---|---|
| Every valid original row imports | Real-data test compares **all 3,306 rows field by field**: register, hall, seat, subject code, subject title, source URL, mirror page, chart file, hall-list and seat-sheet pages, labels and provenance | **VERIFIED** |
| Register numbers preserved exactly | All 2,934 registers, 12 digits, `register_number` equals its key in every row | **VERIFIED** |
| Hall and seat match the source | Field comparison above; the mirror's JSON agrees with its SQLite database for all 3,306 rows (seat and subject), and the hall label agrees between hall list and seat sheet for 3,305 | **VERIFIED** |
| Duplicates handled safely | 0 duplicate rows in the source; identical repeats are merged and conflicts are not staged (unit tests) | **VERIFIED** (no duplicates exist in the real data) |
| Conflicting records rejected or flagged | 0 conflicts in the real data. Unit tests cover conflict exclusion and reporting without fake batches | **VERIFIED** (logic); real data has none |
| Incorrect hall labels blocked | 1 real hall conflict (`992696352264`, 17 Nov AN) is flagged `hall_mismatch` and cannot be approved until corrected. Before this audit it was **not** detected: the importer never compared the hall list with the seat sheet | **FIXED** (regression test in `test_hall_conflict_between_the_two_pdfs_blocks_approval`) |
| Hall-label spelling variants | 2,099 records share a session with both spellings (e.g. `MB III 203` and `MB III A203`). They are flagged `hall_label_variant` and need a hall check before approval | **VERIFIED** (flagged, not auto-resolved) |
| Source pages distinguish hall-list from seat-sheet pages | Before this audit, the seat-sheet page was taken from the chart file name and the mirror's `page` field was stored as if it were the seat page. The mirror's `page` names the hall-list PDF in 2,630 of 3,306 seat-sheet records. A per-PDF provenance file is now built from the mirror's database, which has one hall row and one seat row for every record | **FIXED** (`allocation_provenance.json`, `scripts/build_original_provenance.py`, tests) |
| Provenance retained | Source URLs, per-PDF pages, labels, PDF SHA-256 and page counts as the mirror downloaded them, JSON hash, import time | **VERIFIED**. The PDF hashes are the mirror's own downloads and are **not** checked against vsbec.edu.in: BLOCKED BY MISSING SOURCE DATA for independent confirmation |
| Nothing invented | No student rows created (tested); no seats, capacities or times added; the time 1:30–4:30 PM is not displayed | **VERIFIED** |

## 3. Sample register 992696352326

| Field | Brief | Verified value | Status |
|---|---|---|---|
| Register | 992696352326 | 992696352326 | VERIFIED |
| Subject | Digital Electronics | DIGITAL ELECTRONICS (case only) | VERIFIED |
| Subject code | 23ECT307 | 23ECT307 | VERIFIED |
| Date, day | 17 Nov 2026, Tuesday | 2026-11-17, Tuesday | VERIFIED |
| Session | AN | AN | VERIFIED |
| Hall | MB III A103 | MB III A103 in both PDFs and on the chart | VERIFIED |
| Seat | 23 | 23 (chart shows 992696352326 in seat 23) | VERIFIED |
| Hall-allocation PDF page | 4 | Page 4 of `17.11.26-AN-hall.pdf` (mirror database) | VERIFIED from the mirror's database |
| Seating-chart PDF page | 23 | Page 23 of `17.11.26-AN-seat.pdf` (mirror database; chart image `_page_23`) | VERIFIED from the mirror's database and the image |
| Time 1:30–4:30 PM | Only if verified | Not in the data or the chart. The mirror's schedule file says 13:30–16:30 for AN | Not displayed (correct). Repository schedule, not allocation data |
| Official PDF | — | Not in either archive | BLOCKED BY MISSING SOURCE DATA: the record is repository-derived, not independently PDF-verified |

Student workflow (browser, jsdom against a live server, real data): see section 4.

## 4. Student portal and workflow

| Step | Result | Status |
|---|---|---|
| Open the portal at `/portal/` | 200; `/portal` redirects to `/portal/` | VERIFIED |
| `?reg=992696352326` prefills and searches | Lookup returns the published record | VERIFIED (browser flow) |
| Subject and code shown | 23ECT307 / DIGITAL ELECTRONICS | VERIFIED |
| Date, day, session | Tuesday, 17 Nov 2026, "AN · Afternoon" | VERIFIED |
| Hall and seat | MB III A103, seat 23 | VERIFIED |
| Source link | Points to `https://vsbec.edu.in/.../17.11.26-AN-seat.pdf` | VERIFIED |
| No link to the GitHub mirror | Checked on the page | VERIFIED |
| Unpublished records not visible | Before publication the page shows "Not Allotted / Not Yet Published" and no hall, seat or subject | VERIFIED |
| Invalid register (`9225`) | No result is shown (browser flow). The validation message text is set by `portal.js` and was not separately checked | VERIFIED (no result); message text not checked |
| Unknown register (`992696352999`) | No result; API 404 | VERIFIED |
| Signed-in student sees only their own seat | `/api/vsb-allocation/my` returns exactly one allocation | VERIFIED |

**FIXED in the following round.** The existing (non-VSB) lookup had reported a count of unpublished classic allotments
for a register number ("Seat allotted, not yet published"). The count and the message are removed, and regression tests
were added before the fix and confirmed to fail on the old code. The VSB pending records were never part of that count.

## 5. Portal connectivity and links

| Item | Finding | Status |
|---|---|---|
| Local portal route | `http://127.0.0.1:8000/portal/` (port from `start.bat` and the uvicorn command) | VERIFIED |
| Search parameter | `?reg=` is read at load (`portal.js`) | VERIFIED |
| Backend used by the portal | `/api/portal/*` in the same FastAPI app and database; no separate static portal | VERIFIED |
| Original GitHub repository | Not used as the student portal. It appears only as a source reference in documentation | VERIFIED |
| Original live Pages site | Not linked from the portal. A CSS comment credits it as design inspiration; the page never shows its data | VERIFIED |
| Source PDF links | Official `vsbec.edu.in` URLs; the seat-sheet URL is shown to students | VERIFIED |
| Automatic GitHub synchronisation | **Not implemented.** The import is an administrator upload. Claimed nowhere | VERIFIED (absence) |
| Admin import endpoint | `POST /api/vsb-allocation/import/original`, admin only, dry run by default | VERIFIED |

## 6. Importer and administration

| Requirement | Evidence | Status |
|---|---|---|
| Dry run without changing the database | Browser flow: dry run through the panel, batch list stays empty; unit test | VERIFIED |
| Import requires explicit confirmation | `confirm=true` required, else 422 (unit test and live test) | VERIFIED |
| Creates pending draft batches only | Real-data test: every record `pending`, `published=false` | VERIFIED |
| Never approves or publishes automatically | Same test; approval and publication happen only through the review endpoints | VERIFIED |
| Re-import never overwrites reviewed decisions | Unit test: a session with an approved record is skipped with a reason | VERIFIED |
| Missing students reported, no Student rows fabricated | `student_not_in_database` flag; unit test checks the Student count is unchanged | VERIFIED |
| Hall-label variants flagged | 2,099 records flagged (real data) | VERIFIED |
| Duplicate seats cannot be approved by acknowledging | Unit test: approval refused until the record is corrected | **FIXED** (previously acknowledgement was accepted) |
| Hall conflicts and provenance mismatches cannot be approved by acknowledging | Same rule extended to `hall_mismatch` and `provenance_mismatch` | **FIXED** |
| Conflicts reported without fake batches | An earlier draft created a placeholder batch to hold conflicts. **Removed** before this release; conflicts appear only in the report and the audit log | **FIXED** (design correction) |
| Audit log accurate | Import writes `vsb_alloc.original_imported` with the file SHA-256, batch, record, rejected and conflict counts; unit test | VERIFIED |
| Admin permissions enforced | Staff and student receive 403 on the import; the panel is not rendered for staff (browser flow) | VERIFIED |
| Import panel works in the frontend | Browser flow: panel present, dry-run summary correct (3,306 valid, 0 rejected), Stage button enabled | VERIFIED |
| Deeply nested upload | Previously a `RecursionError` (500). Now a clean 422 | **FIXED** (unit test) |

## 7. Seating charts

| Check | Result | Status |
|---|---|---|
| Every referenced chart exists | 135 referenced, 135 present, 0 missing | VERIFIED |
| Filenames resolve | Each record's chart name resolves through the API (admin) | VERIFIED |
| Chart page equals the seat-sheet page | True for all 3,306 records (mirror database) | VERIFIED |
| Path traversal | `..%2F…`, out-of-range page and unknown names all return 404 | VERIFIED |
| Only administrators | Admin 200; staff, student and anonymous refused (403/401) | VERIFIED |
| Not served as static files | `/data/...` returns 404 for source JSON, provenance and charts | VERIFIED (unit test) |
| Student-facing pages do not expose other students | Unit test: another student's register (`992696352301`) is absent from the lookup response; the seat map lists seat numbers only | VERIFIED (unit test) |
| Complete charts shown publicly | **Not done.** Each chart lists about 28 register numbers | Deliberate; see the integration guide |

## 8. Windows installation and running

| Item | Finding | Status |
|---|---|---|
| `install.bat` | Finds `py -3` or `python`; accepts 3.12 or newer; creates `backend\.venv`; installs `requirements.txt`; creates `.env`; runs the configuration check and migrations; creates the admin | Static review only |
| `start.bat` | Refuses to start twice (PID file check); validates config; migrates; starts uvicorn on 127.0.0.1:8000 hidden; health-checks `/api/ready` | Static review only |
| `stop.bat` / `managed_server.ps1` | Kills only a PID that is a `python(w).exe` process whose command line contains `uvicorn` and `app.main:app`; a stale or reused PID is never killed | Static review only |
| Python 3.14 (user's version) | Python 3.14.10 installed on Linux; `requirements.txt` installs (FastAPI 0.139.2, SQLAlchemy 2.0.58, Pillow 12.3.0, pydantic 2.14.3); full backend suite passes; both jsdom suites pass against the live server | VERIFIED on Linux |
| Windows execution | No Windows host available | **NOT TESTED** |
| Windows-specific wheels (PyMuPDF, Pillow, pydantic-core for win-amd64 on 3.14) | Installation on Windows not performed | **NOT TESTED** |
| Exact commands | In `WINDOWS_INSTALLATION.md` | VERIFIED (text) |

## 9. Security review

| Area | Evidence | Status |
|---|---|---|
| Password hashing | PBKDF2-SHA256; below 200,000 rounds refused outside `ENVIRONMENT=test` | VERIFIED |
| Secrets | Production check refuses an empty or weak `SECRET_KEY` (exit code 1 on `check-config`). Verified without a pipe; an earlier doubt was caused by my own `tail` pipe | VERIFIED |
| SQL injection | Only one raw SQL statement in the app (`SELECT 1`); all other queries use the ORM with parameters | VERIFIED |
| Path traversal | Chart names are matched by a fixed pattern, and the file path is built only after the match | VERIFIED |
| Upload validation | Import refuses files over 8 MB, non-UTF-8 input, non-object JSON, and deep nesting | VERIFIED (after the fix above) |
| Role access | Admin-only endpoints refuse staff and students (tests and browser flow) | VERIFIED |
| Information leakage | Public lookup: rate-limited; 404 for unknown registers, so a register can be probed. Existing behaviour, mitigated by the rate limit | **Finding, not changed** |
| Unpublished existence | Classic-allotment count removed (section 4) | **FIXED** |
| Static exposure | Only `app/static` is served | VERIFIED |
| Shipped data | No `.env`, no production database, no keys. A test fixture database (`tests/fixtures/`) holds synthetic students and test-only password hashes | VERIFIED |
| Session and cookie security | Not re-audited in this pass beyond the existing test suite | **NOT TESTED** in this audit |

## 10. Tests

| Suite | Result (final) |
|---|---|
| Backend, full (Python 3.12.3) | 636 passed, 24 skipped, 0 failed |
| Backend, full (Python 3.14.10) | 636 passed, 24 skipped, 0 failed |
| Importer unit tests | 17 passed on both interpreters |
| Real-data tests | 2 passed on both interpreters (full file, field-by-field) |
| jsdom general smoke (`run_e2e.py`) | 225 passed, 0 failed (3.12 and 3.14) |
| jsdom original-data workflow (`run_original_e2e.py`) | 29 passed, 0 failed (3.12 and 3.14) |
| Extracted-ZIP test | see section 13 below |

## 11. Fixes made in this audit

1. Hall conflict between the hall list and the seat sheet was not detected (`original_import.py`). FIXED.
2. Seat-sheet page inferred from the chart file name; the mirror's `page` misattributed as seat page. Per-PDF provenance added. FIXED.
3. Acknowledging a hard conflict approved the record (`routers/vsb_alloc.py`). FIXED.
4. Deeply nested upload produced HTTP 500 (`routers/vsb_alloc.py`). FIXED.
5. Placeholder batch used to hold conflicts (`original_import.py`). Removed. FIXED.
6. The import panel's form could not be exercised in jsdom because of file-input validation. Test corrected; the UI was not changed.
7. Generated mail outbox files included in the release. Removed. FIXED.
8. Original-data tests depended on an environment variable. They now run from the shipped copy. FIXED.

## 12. Remaining limitations

- Windows and Docker were not executed. Android was not changed and not built in this pass.
- The official PDFs are not in the archives: **BLOCKED BY MISSING SOURCE DATA** for independent PDF verification.
- Exam times are not displayed for these records because no verified time exists in the source.
- No live synchronisation with the GitHub repository.
- Register probing: an unknown register returns 404 and a known student returns 200. This is existing behaviour, mitigated by the rate limiter, and was not changed because the portal depends on that distinction for error messages.
- Students do not see seating charts (privacy decision).
- The 2,099 `hall_label_variant` records need an administrator check against the PDFs before approval.

## 13. Extracted-ZIP verification

The extracted-copy verification is reported with the release, not embedded in it, because a file written after packaging cannot be inside the package.

## Update (UPDATED_CANDIDATE_v2)
The `992696352264` hall disagreement described above was later resolved by official evidence as a mirror transcription error (official: MB III A04, seat 28). See `ORIGINAL_PORTAL_IMPORT.md` and `archive/UPDATE_V2_CHANGES.md`. The detection logic itself is unchanged.
