# Original hall-allocation portal: import and integration

This release stages the data of the original public portal (`sabareesh2008/EXAM_MONITOR`) into the existing VSB review
workflow. It does **not** replace the backend and it never publishes anything by itself. The full audit is in
`AUDIT_ORIGINAL_INTEGRATION.md`.

## Where the data comes from

| File (operator-supplied, NOT in the public package) | What it is |
|---|---|
| `original_portal/(operator-supplied)/source/allotments.json` | Copy of the original repository's `allotments.json` (3,306 rows, 2,934 register numbers) |
| `original_portal/(operator-supplied)/allocation_provenance.json` | Per-record provenance built from the mirror's own SQLite database: hall-list PDF URL and page, seat-sheet PDF URL and page, the labels printed in each PDF, and the SHA-256 and page count of each PDF as the mirror downloaded it |
| `original_portal/(operator-supplied)/seating_charts/` | The 135 seating-chart PNGs referenced by the records (rendered pages of the seat sheets) |
| `backend/scripts/build_original_provenance.py` | Reproduces the provenance file from the mirror's files. It refuses to build if any record cannot be traced to exactly one hall row and one seat row |

The mirror's SQLite database itself (35 MB) is not part of the package. The provenance file is the part the importer needs; it is held by the operator with the rest of the original-portal data.

## What is integrated

| Original portal feature | Where it lives now |
|---|---|
| Register-number search | `/portal/?reg=…` (public API `GET /api/portal/lookup/{register}`); published and approved records only |
| Examination date and FN/AN session | Notices and lookup (`/api/portal/notices`, `/api/portal/lookup`) |
| Examination time | **Not displayed for these records.** VSB records carry no time, and the mirror's data does not store one |
| Building, block, hall, seat | Lookup entries (hall and seat); the seat-number map from `GET /api/portal/seatmap/...` never identifies other students |
| Print slip / save as PDF | The existing "Print Slip / Save PDF" button |
| Seating-chart images | **Administrators only** (see the privacy decision below) |
| Source documents | Each published record links to its official seat-sheet PDF, and the import keeps the hall-list PDF too |

## Privacy decision: seating charts are not shown to students

Each chart lists about 28 students' register numbers next to their seats. The main portal deliberately shows only seat
numbers, never another student's register number, so the charts are available only to administrators
(`GET /api/vsb-allocation/charts/{name}`, admin role, `Cache-Control: private, no-store`). They are also not served by
the static file server; a test checks that. Student-safe charts would need redaction from the PDF coordinates, which the
mirror does not contain. Publishing charts to students is a policy decision for the Controller of Examinations.

## Import procedure

1. Sign in as an administrator, open **VSB hall & seat**, and choose `allotments.json`. The operator's copy goes in
   `original_portal/(operator-supplied)/source/` on the authorised machine (see `original_portal/(operator-supplied)/README.md`).
2. Run **Dry run**. It validates every row and reports rejected rows, conflicts, duplicate seats and what would be
   staged. Nothing is written.
3. Click **Stage as drafts**. One draft batch is created per exam date and session. Every record starts *pending*.
4. Review each batch. Check flagged records against the official PDFs, correct anything wrong (each change is audited
   with a reason), approve, then use **Preview & publish**.

Re-running an import replaces an unreviewed import draft. It refuses to touch a draft that holds reviewed or corrected
records, and it never touches a published batch.

## Validation and flags

Rows are rejected (not staged) when the register number is not 12 digits, the key and `register_number` differ, the
date or session is invalid, the hall or seat is missing or malformed, or the source URL is not `https`. A file that is
not a register-keyed JSON object, or nested too deeply to parse, is refused with 422.

Identical repeated rows are merged. Conflicting allocations for one register number on one date and session are **not
staged**; they are listed in the report and the audit log.

Flags on staged records:

| Flag | Meaning | How it can be cleared |
|---|---|---|
| `hall_mismatch` | The hall list and the seat sheet name different halls | The hall must be **corrected** to the value confirmed in the PDF (with a reason). Acknowledging is not enough |
| `provenance_mismatch` | The uploaded seat or subject differs from the mirror's own database | The value must be **corrected** against the PDF. Acknowledging is not enough |
| `duplicate_seat` | Two register numbers share one seat in one hall and session | One record must be **corrected**. Acknowledging is not enough |
| `hall_label_variant` | The same session lists a hall both as `MB III 203` and `MB III A203` (or `03` and `A03`) | Check the hall against the PDF, then approve with a note and the acknowledgement |
| `source_not_official` | Source URL is not on `vsbec.edu.in` | Approve with a note and acknowledgement after checking the source |
| `subject_missing` | No subject code | Correct the subject, or approve with a note after checking |
| `student_not_in_database` | No student account for that register number | Warning only. The record stays unlinked until the student exists |
| `seating_chart_missing` | No chart linked | Warning only |

The first three rules are deliberate: a conflict between two official PDFs, or between an upload and the mirror's own
database, cannot be settled by ticking a box. The administrator must record the corrected value and the reason, which is
audited.

## Provenance kept per record

For every record the import keeps: the source URL and file name; the hall-list PDF URL and page; the seat-sheet PDF URL
and page; the labels printed in each PDF; the SHA-256 and page count of each PDF as the mirror downloaded it; the mirror's
own page field (`json_page`); the seating-chart file; the SHA-256 of the imported JSON; the import time; and notes.

The mirror's `page` field cannot be trusted to name one PDF. For seat-sheet records it is the hall-list page in 2,630 of
3,306 cases. The import therefore records both PDF pages from the mirror's database and keeps the raw `page` only as
`json_page`. Each note says which PDF the page field refers to.

The mirror's database holds the SHA-256 of each PDF it downloaded. Those hashes show which file version the mirror
used. They have **not** been checked against the official website, so they are not independent evidence of what the
college published.

## Verification of the reference record 992696352326

Checked against the mirror's `allotments.json`, the mirror's SQLite database, the provenance file and the chart image
`d12cded03485_17.11.26-AN-seat_page_23.png`.

| Field | Brief | Source value | Result |
|---|---|---|---|
| Register | 992696352326 | 992696352326 | VERIFIED (JSON, database, chart) |
| Subject | Digital Electronics | DIGITAL ELECTRONICS | VERIFIED (case differs; the stored value is the source's) |
| Subject code | 23ECT307 | 23ECT307 | VERIFIED |
| Date | 17 November 2026 | 2026-11-17 | VERIFIED (file name `17.11.26`, database) |
| Day | Tuesday | Tuesday (calendar) | VERIFIED |
| Session | AN | AN (chart header `SESSION : AN`) | VERIFIED |
| Hall | MB III A103 | Hall list: MB III A103; seat sheet: MB III A103; chart: `EXAM HALL : MB III A103` | VERIFIED |
| Seat | 23 | 23; chart shows seat 23 = 992696352326 | VERIFIED |
| Hall-allocation PDF page | 4 | Hall list `17.11.26-AN-hall.pdf`, page 4 (database row) | VERIFIED from the mirror's database |
| Seating-chart PDF page | 23 | Seat sheet `17.11.26-AN-seat.pdf`, page 23 (database row; chart file `_page_23`) | VERIFIED from the mirror's database and the chart image |
| Time 1:30–4:30 PM | Not verifiable | Not in `allotments.json`, not printed on the chart. The mirror's `schedule.py` defines AN as 13:30–16:30 | **Not displayed.** It is repository-derived schedule information, not allocation data |

**PDF status: BLOCKED BY MISSING SOURCE DATA.** The official PDFs are not in either archive. The record is therefore
repository-derived and not independently PDF-verified. The seat-sheet page and the hall are confirmed against the chart
image and the mirror's own database, not against the official PDF.

## Known conflict in the source

Register `992696352264` on 17 November 2026, AN: the seat sheet places it in `MB III A04` (seat 28) and the hall list
places it in `MB III 206`. It is staged with `hall_mismatch` and cannot be approved until an administrator corrects the
hall against the official PDFs. The import does not guess which is right.

## Testing

| Test | What it proves |
|---|---|
| `backend/tests/test_original_import.py` (17 tests) | Dry run writes nothing; confirmation required; admin-only; malformed and deeply nested files; rejected rows; identical duplicates merged and conflicts not staged; provenance and flags; hall conflict blocks approval until corrected; duplicate seat; re-import never overwrites reviewed decisions; published batches untouched; the student sees the seat only after publication; charts are admin-only; source data is not served as static files; malformed provenance refused; import audited and creates no students |
| `backend/tests/test_original_import_real_data.py` (2 tests) | The full 3,306-row file imports; **every staged record is compared field by field** with the JSON and the provenance file; exactly one hall conflict; nothing approved or published by the import |
| `backend/tests/e2e_jsdom/run_original_e2e.py` (29 checks, jsdom against a live server) | Admin import panel; dry run changes nothing; staff sees no panel; draft records invisible to the student; publication; the public portal with `?reg=992696352326` (subject, code, date, session, hall, seat, source link, no time, no GitHub link); invalid and unknown registers; student and staff restrictions; admin chart access |

Run the tests from `backend/`:

```
python -m pytest
python tests/e2e_jsdom/run_e2e.py                 (general front-end smoke, needs Node 18+ and `npm ci` in tests/e2e_jsdom)
python tests/e2e_jsdom/run_original_e2e.py        (original-data workflow)
```

## Limits

- No live synchronisation with the external repository is implemented. Updates are a manual upload of a new
  `allotments.json`, and the provenance file must be rebuilt from the mirror's database with the script.
- Exam time is not displayed for these records (see above).
- Records for register numbers with no student account stay unlinked. Nothing creates student rows.
- The seating charts are not available to students.

## Update (UPDATED_CANDIDATE_v2): the `992696352264` conflict is a mirror transcription error
The section "Known conflict in the source" above records the state when it was written. Later official evidence (hall list p.4, seat sheet p.20 of the 17 Nov AN PDFs)
lists the register in `MB III A04`, seat 28, so the mirror's `MB III 206` hall-list label was a transcription error, not an official contradiction.
The original mirror value is preserved unchanged in `allocation_provenance.json`; the correction is appended in `provenance_corrections.json`, shown on the record as `provenance_correction`, and noted for the reviewer.
The importer still raises `hall_mismatch` for it (the flag is computed from the unchanged mirror data), so approval still needs a recorded administrator confirmation.
