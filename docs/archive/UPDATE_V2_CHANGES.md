# UPDATED_CANDIDATE_v2 — what changed since the previous candidate

> **Historical record.** This document describes an earlier build. Its test counts and status statements are not the current verification status. For the current commands, results and limitations see `docs/VALIDATION_REPORT_v6.md` (or `VALIDATION_REPORT_v6.md` from the top-level folder).

**Status: candidate. Runtime verification is still outstanding** (see `WINDOWS_TEST_RUNBOOK.md`). The changes below were made and checked
only by source inspection and by byte-compiling the Python files (`python -m py_compile`, Python 3.12.3). No pytest run, migration run, server start,
Windows run or Android build was possible in the environment used to produce this package, so no test result is claimed.

## Defects found by reading the enforcement code, and fixes
Files read in full: `backend/app/routers/vsb_alloc.py`, `backend/app/vsb_alloc/original_import.py`, `backend/app/doc_models.py` (column),
`backend/migrations/versions/0014_vsb_verification_status.py`, `backend/tests/test_vsb_alloc_workflow.py`, `backend/tests/test_original_import.py`.

Confirmed as already correct: individual approval requires FULLY_VERIFIED before any flag/acknowledgement logic (acknowledgement cannot bypass it);
critical-field edits (hall, seat, subject_code) that actually change a value reset to UNRESOLVED and return the record to `pending`; department-only edits do not;
verification requires HTTPS `.pdf` references hosted on `vsbec.edu.in`; `publish` refuses when any approved row is not FULLY_VERIFIED; published batches reject edits, verification changes and decisions; every action calls `audit.record`.

| # | Finding | Fix |
|---|---|---|
| 1 | Bulk approval (`approve-confident`) did not apply the live seat-clash check that individual approval applies, so the two paths were not equivalent. (Unreachable today because clashes are flagged at import/edit, but the rule was not enforced where it should be.) | `approve_confident` now skips any record whose hall+seat is held by another non-rejected record, and reports `skipped_seat_clash` in its audit row. |
| 2 | Bulk approval wrote one audit row for the whole batch (a count only), so individual record status changes were not traceable. | One `vsb_alloc.record_approve` audit row per approved record (`{"via": "bulk"}`), plus the batch summary row. |
| 3 | The publish loop marked every *approved* row `published` and relied only on an earlier guard to stop unverified rows. | The loop itself now also requires `verification_status == 'FULLY_VERIFIED'`; the publish audit row also stores the previewed signature. |
| 4 | The bridge into the allocation engine selected published + approved rows without checking verification. | The bridge query now also requires FULLY_VERIFIED. |
| 5 | The correction for `992696352264` was only prose in documents; the importer still described it as an unresolved conflict. | New append-only `original_portal/(operator-supplied)/provenance_corrections.json` (mirror value `MB III 206` kept in `allocation_provenance.json`; correction to `MB III A04`, seat 28, with evidence pages 4 and 20, `is_official_contradiction: false`). `load_provenance` merges it as `corrections` (malformed file is refused); staged records carry `provenance_correction` in their detail, a reviewer note, and the API field `provenance_correction`. Flag behaviour is unchanged. |
| 6 | `backend/run_test.bat` had LF-only line endings. | Converted to CRLF. All other `.bat`/`.ps1` files were already CRLF (checked byte-wise). |
| 7 | README stated database head `0013`; the head is `0014`. | README corrected. |
| 8 | A pytest cache folder was shipped. | Removed. |

Not changed on purpose (limitations): an administrator can still promote a record to FULLY_VERIFIED by supplying any `vsbec.edu.in` PDF URL; the server does not
fetch or compare the PDF. That step relies on administrator diligence and is audited. After upgrading an old database, rows that existed before migration 0014 get UNRESOLVED,
and students keep seeing already-published rows (the student view does not re-check verification); withdraw and re-verify such batches if that matters.

## Files modified
`backend/app/routers/vsb_alloc.py`, `backend/app/vsb_alloc/original_import.py`, `backend/run_test.bat` (line endings), `README.md`,
`docs/ORIGINAL_PORTAL_IMPORT.md`, `docs/AUDIT_ORIGINAL_INTEGRATION.md`, `docs/VSB_VERIFICATION_LIMITATIONS.md`, `docs/TEST_REPORT.md`, `RELEASE_MANIFEST_SHA256.txt` (regenerated).

## Files added
`backend/tests/test_vsb_verification_enforcement.py` (15 tests, **not run**), `original_portal/(operator-supplied)/provenance_corrections.json`,
`docs/ORIGINAL_REPO_COMPARISON.md`, `docs/UPDATE_V2_CHANGES.md`, `docs/WINDOWS_TEST_RUNBOOK.md`.

## Features added
Per-record audit rows for bulk approval; append-only provenance corrections (file, importer wiring, API field `provenance_correction`). Nothing was removed.

## New tests (all unexecuted)
Status assignment by session; HALL_LIST_CONFIRMED/UNRESOLVED refused with and without acknowledgement; bulk approval limited to FULLY_VERIFIED; per-record bulk audit rows;
critical edit invalidation vs. department edit; verification reference validation and audit; admin-only; publish gating, privacy and unverified-row refusal;
published-batch immutability; 627/1,159/1,520 recomputed from the real source file; 377/772/950 from the hall-variant CSV (2,099 rows, kept separate);
the 992696352264 correction; malformed corrections file; CRLF on Windows scripts.
If any of them fails when you run it, treat that as a finding about either the test or the code; do not weaken the assertion without understanding why.
