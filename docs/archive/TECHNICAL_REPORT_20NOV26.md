# VSB 20-Nov-2026 AN — parser, student lookup and verification report

Working copy of the protected release (original ZIP sha256 `b6e484b1…665d94`, re-hashed after the work: unchanged).

## 1. What I could and could not do (read first)
* The build sandbox cannot reach vsbec.edu.in. I obtained the **text layer** of both official PDFs through a web-fetch tool, not the binary PDFs.
  Fixtures: `backend/tests/vsb/real_20nov26/*.pages.txt` (real text, one page per form-feed).
* PDF-level tests (PyMuPDF word boxes, page rendering) use PDFs **generated from that real text**; geometry is approximate, not TCPDF's.
* Live official-source discovery/download was **not demonstrated**. The existing crawler tests (mocked transport) pass; auto-staging was demonstrated on the two documents.

## 2. Findings about the "parser errors"
The shipped parser, run on the real 20-Nov text, already read everything correctly: 42 hall blocks, 11 programme totals (all match), 16 seat sheets,
390 students, heading "CODE TITLE OF THE PAPER TOTAL REGISTER NUMBERS" accepted, no `hall_sheet_missing`. **I could not reproduce your reported errors from the text layer**, so I make no claim they are gone on VSB's binary files.
Defects that were real and are fixed:
1. `reconcile.py`: a hall-PDF block whose hall label is unreadable has hall=None; the cross-check then reported *"None is on the hall PDF … has no seating sheet"*, a bogus `hall_check_failed`, and *"hall PDF says None"* mismatches. Now: one `hall_unreadable` error, records flagged `hall_missing` (blocking). Nothing hidden.
2. `seat_parser.py`: heading regex only matched `CODE TITLE`; now also `CODE / TITLE`, `CODE - TITLE`, `SUBJECT|PAPER|COURSE CODE …`. If no heading is found the table is located from its first subject-code line with a `table_header_variant` warning (previously the whole subject table was dropped).
Not changed: hall capacities/directory (nothing invented; halls absent from the directory only produce an info note — I had no authoritative hall directory, so MB III 02/03/04/101 etc. are **not validated** against one).

## 3. New functionality
* `app/vsb_alloc/pagepreview.py` + `GET /api/portal/pdf-page/{reg}?ref=&source=hall|seat`: server-rendered PNG of the exact page (hall/seat page numbers stored per record), own number highlighted, **every other register number covered** (full numbers and abbreviated suffixes). Fails closed (404) with no text layer, unpublished/unapproved/unverified records, unmatched students; seat sheet only for FULLY_VERIFIED.
  Design decision: the raw PDF is not embedded, because each page lists 25–80 other students; "Open original PDF#page=N" links to the college site instead.
* Lookup entries gain `pdf_pages` (additive). Portal UI: "View this page" / "Open original PDF". Empty state now starts with "Your examination hall allotment is not yet available. Please check again later."
* `GET /api/vsb-allocation/batches/{id}/roster-report`: matched/unmatched register numbers, separate from parse issues. Roster import already existed (`/api/data/import/students`).

## 4. Independent comparison (tests/vsb/independent_compare.py, shares no code with the parser)
| Item | Result |
|---|---|
| Pages | hall 11, seat 16 |
| Register numbers extracted / unique | hall 390 / 390; seat grids 390 / 390 |
| Duplicates, missing, incorrect | 0 / 0 / 0 |
| Department totals (printed = extracted) | CIVIL 34, EEE 79, ECE 34, MECH 75, CCE 4, BME 27, CSE(AIML) 4, CHEM 28, BIOTECH 33, AIDS 8, CSBS 64 = 390 |
| Hall totals | 15 halls × 25, MB III A104 = 15 (= 390) |
| Hall PDF vs seat PDF | 0 students on one only; 0 hall disagreements; 39 (hall, subject) pairs all equal printed subject totals |
| Seat grid | all 16 sheets follow the 4×7 serpentine numbering; 0 duplicate seats; abbreviated-range tables expand to exactly the grid |
| Parser vs reference | all 390 hall/seat/subject/programme/page values equal |
| Roster (test DB, 3 students loaded) | 3 matched, 387 unmatched — reported as roster gaps |
| Unresolved parser issues | none on the text layer |
Note: without word boxes the text path flags every seat `seat_from_text_order` (kept, not weakened). With word boxes (generated PDFs) seats are unflagged.

## 5. Commands and results (from `backend/`)
```
python -m pytest tests/vsb/test_vsb_real_20261120.py tests/vsb/test_vsb_pdf_roundtrip.py tests/test_vsb_20nov26_end_to_end.py -o addopts= -p no:cacheprovider
   -> new tests: 21 + 3 + 8 = 32 passed
python -m pytest tests/vsb tests/test_vsb_alloc_workflow.py tests/test_vsb_crawler.py tests/test_vsb_defects_a_b.py \
   tests/test_vsb_verification_enforcement.py tests/test_phase13_portal.py tests/test_portal_disclosure.py tests/test_regno.py -o addopts= 
   -> 152 passed, 6 skipped (pre-existing skips: operator private data), 0 failed
python tests/portal_dom/run_portal_dom.py   (jsdom)
   -> 25 passed, 1 failed ("unpublished allotment noted without details"). Identical 25/1 on the pristine original: pre-existing, not caused by this work.
```
Full suite, PostgreSQL, Android, browser suites were not rerun.

## 6. Limitations
* Reported parser errors not reproducible; binary PDFs unseen; real-PDF coordinates untested.
* Automation is off by default: set `VSB_AUTO_DISCOVER_ENABLED=true` and `VSB_STAGE_DRAFTS_ON_SCHEDULE=true`. Approval/publication stays manual by design.
* Existing rule kept: HALL_LIST_CONFIRMED records cannot be approved via review (only imported rows have that state), so hall-only display is tested with a directly set row. New drafts reach students only after FULLY_VERIFIED + approval + publish.
* A student must exist in the roster to look anything up. No hall directory validation (see §2).
