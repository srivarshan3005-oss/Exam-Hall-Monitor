# Architecture (0.2.0)

## Layout
```
backend/app/
  main.py            app factory, security headers, startup checks (secret key, migrated DB)
  config.py          settings from env/.env           security.py   passwords, policy, tokens
  deps.py            auth dependencies (roles)         ratelimit.py  sliding-window limiter
  audit.py           audit helper (same transaction)   regno.py      register-number toolkit
  models.py          core tables                       doc_models.py Smart Hall Finder tables
  dbcheck.py         Alembic helpers (migrate, legacy stamp, "is DB current?")
  cli.py / seed.py   admin & maintenance commands; synthetic demo data
  routers/           auth, students, exams, allotments, results, admin
  static/            student site + admin dashboard (plain HTML/CSS/JS)
backend/migrations/  0001 baseline (= 0.1.0 schema), 0002 security + hall-finder tables
backend/tests/       217 tests
```

## Smart Hall Finder data model (schema only in 0.2.0; filled by Phase 3)
```
official_documents 1─* document_versions 1─* pdf_pages 1─* seating_sheets ─* seat_positions
        (source URL,       (sha256, file, page_count,    (page_index 0-based,   │   (seat_number, bbox, is_empty,
         kind, date,        processing + review status)   size, rotation, OCR)    │    method, confidence, verified)
         FN/AN)                                                                  ├─* register_entries (search index)
exam_sessions (date+FN/AN) ─* seating_sheets ─* sheet_subjects                   │    (register_number, id_kind, seat_number?,
halls (directory; building/floor/room NULL until verified)                       │     bbox, source_text, method, confidence, review)
review_issues (conflicts, count mismatches, low confidence, OCR gaps)            └─* sheet_subjects (printed subject summary lines)
```
Rules enforced by the schema: every extracted fact stores **how** it was obtained (`text_layer | ocr | manual`), its confidence,
its coordinates on the original page and a review status; `seat_number` is NULL when it cannot be determined; hall
building/floor/room stay NULL unless an admin verified them; page numbers are 0-based internally (`display = page_index + 1`).

## What the real VSB PDFs look like (observed 11 Nov 2026 from the public notice page, text layer only)
* Separate "Hall Allotment" and "Seating Allotment" PDFs per date and FN/AN session, linked from the Controller of Examination page.
* One page per hall (code like `MB III 01`); a 28-seat grid where each seat number sits beside the register number occupying it;
  empty seats show a seat number with no register number.
* A summary table lists subject code, title, a **compressed** register list (`…006, 008, 042 - 116`, wraps across lines) and a count.
* 12-digit register numbers, plus occasional non-standard ids (e.g. 11 digits) and a hall page with missing seat numbers in its text.
* Not yet verified (needs page images / word coordinates, Phase 3): which cell each register number occupies, rotated pages, scanned PDFs.

`regno.py` already implements the register-list rules (prefix inheritance, ranges, wrapped ranges, non-standard ids, duplicates)
and **refuses to guess** (ambiguous items become issues). The seat grid will be read from word coordinates and checked against
the printed totals and the subject summary; anything that does not reconcile goes to review, never to the public search.

## Trust boundaries
Public: health, config, published exams, rate-limited lookup. Signed-in student: own results. Staff: exams, allotments, read-only student list.
Admin: everything else incl. users and audit. See SECURITY.md.

## Expanded campus and document modules

The Phase 2 metadata now also includes `Announcement`, normalized `Building`, `Block`, `Floor`, and `HallSeat` models. Existing `Hall` records retain their original text labels and now optionally reference normalized hierarchy rows, preserving existing rows. A configured hall must be verified before it can be used for a new allotment; if an inventory exists, the requested seat must be active and present. Database unique constraints remain the concurrency backstop for seat conflicts.

`routers.campus` owns directory and announcement APIs. `routers.documents` owns admin-only PDF intake, text/OCR processing and human review. Original PDF files are stored under `backend/uploads` outside the static directory. Database rows keep SHA-256, version, page and review metadata; candidate register entries remain pending until an administrator reviews them. Public student lookup joins only approved entries from approved document versions.
