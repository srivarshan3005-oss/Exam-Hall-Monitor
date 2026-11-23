# Original repository (Sabareesh2008 `EXAM_MONITOR-main`) vs this project

Compared on the uploaded archives `EXAM_MONITOR-main_5.zip` (original) and the previous candidate ZIP. The original was **not** merged
into this project and must not replace it. This is a static comparison: neither code base was executed during it.

## What was inspected in the original (complete inventory)
The ZIP lists 3,831 entries (3,597 files, 234 directories); every one was extracted and inventoried.

| Part | Files | Notes |
|---|---:|---|
| `venv/` (a committed Windows virtualenv) | 1,864 | Third-party packages only; not project code. Not carried over and should not be committed. |
| `evidence/`, *docs/evidence/* (not included in this package), `portal/evidence/` | 559 / 560 / 559 | Seating-sheet page images. The three copies are byte-identical except *docs/evidence/test_page_1.png* (extra) and `…05.11.26-SEATING-AN_page_20.png` (differs in `docs/` and `portal/` vs `evidence/`). |
| Project code and config | 52 | `main.py`, `vsb_watch/` (config, database, monitoring, allotment parser, notifications, dashboard, Supabase client), 6 test files, Dockerfile, compose, `.github/workflows/vsb-exam-watch.yml`, `supabase_schema.sql`, BAT files, README |
| Data | 4 | `allotments.json`/`.js` and static portal `index.html` (each duplicated in root, `docs/`, `portal/`, byte-identical), `data/state/vsb_exam_watch.sqlite3` (tables: checks 227, documents 70, allotments 152,688, notifications 4) |

`allotments.json` (identical in all three copies and identical to `original_portal/(operator-supplied)/source/allotments.json`, SHA-256 `feb63d6b…4950`):
2,934 register numbers, **3,306 records**: 16 Nov AN 725, FN 795; 17 Nov AN 627, FN 904; 18 Nov AN 87, FN 168.
These give exactly 627 / 1,159 / 1,520 under the verification rules (17 Nov AN; 17 Nov FN + 18 Nov; 16 Nov).
All 135 distinct seating charts referenced by those records are present in `original_portal/(operator-supplied)/seating_charts/` and byte-identical to the original's.
The other 424 images in the original `evidence/` belong to earlier exam dates (file names show 05–14 Nov, plus some synthetic test images) that are not part of the 3,306-record import.

## Feature comparison
| Original feature | In this project | Verdict |
|---|---|---|
| Single-student register-number lookup (static GitHub Pages + Supabase) | `/api/portal/lookup/{reg}` and the signed-in student views, served only for approved + published + fully verified records | Superseded. Do not adopt the static portal: it publishes the whole data file. |
| Supabase sync | None | **Do not adopt as-is.** `supabase_schema.sql` creates the policy "Public Manage Allotments" (`FOR ALL TO anon, authenticated … USING (true) WITH CHECK (true)`), which lets anyone holding the public anon key write or delete allotments. |
| Scheduled monitoring (GitHub Actions cron every 5 min, `website_monitor.py`) | `vsb_sources.py` crawler + `scheduler.py` + document versioning | Equivalent in purpose. The Actions workflow is not included; adopting it would need review of its `contents: write` permission and secret handling. |
| PDF parsing (`pdf_parser.py`, 410 lines, label/regex heuristics) | `vsb_alloc/hall_parser.py`, `seat_parser.py`, `reconcile.py` (cross-checks both PDFs, flags conflicts) | Superseded; not compared on real PDFs (none are in either archive). |
| Single-student SMTP alert (`REGISTER_NUMBER` env) | Multi-user notification centre and mail service with delivery log | Superseded. |
| Evidence PNG per match | Admin-only chart endpoint `/api/vsb-allocation/charts/{name}` | Carried over, access-restricted because charts list other students' register numbers. |
| CLI (`--search-allotment`, `--ingest-all`, `--once`) | `python -m app.cli` (migrate, create-admin, check-config, …) | Different scope; nothing needed. |
| Docker / compose | `backend/Dockerfile`, `docker-compose.yml`, Nginx template | Present. |
| Committed SQLite state (152,688 allotment rows from earlier dates) | Not imported | Possible future import, but those rows have no verification evidence; they must enter as UNRESOLVED and go through review. |

## Compatibility notes
* The original JSON is `{register: [ {exam_date, session, hall_number, seat_number, subject_code, subject_name, page, source_url, seating_image}, … ]}`; the importer (`vsb_alloc/original_import.py`) reads exactly this shape.
* The original's `page` field is not always the seat-sheet page; the provenance file records both PDF pages (see `docs/ORIGINAL_PORTAL_IMPORT.md`).
* The original `.gitignore` re-includes `data/state/**`, so a SQLite file with 152k rows is committed to the repository. Treat it as data to review, not to publish.
* Register `992696352264` in the original JSON already reads `MB III A04`, seat 28, matching the corrected official value.

## Things in the original not worth porting
The committed `venv/`, the three duplicated portal copies, the public-write Supabase policy, and the personal-email-only alert design.
