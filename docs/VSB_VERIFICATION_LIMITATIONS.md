# VSB verification limitations

The official reference is the V.S.B. Engineering College Controller of Examinations page: https://vsbec.edu.in/controller-of-examination/. Verification findings are documented in [VSB_OFFICIAL_VERIFICATION_REPORT.md](VSB_OFFICIAL_VERIFICATION_REPORT.md).

## Current record status totals

- **627 FULLY_VERIFIED:** 17 Nov 2026 AN; hall, seat and subject checked against hall-list and seat-sheet evidence.
- **1,159 HALL_LIST_CONFIRMED:** 17 Nov FN (904), 18 Nov AN (87), 18 Nov FN (168); hall and subject checked against hall lists, but seat-sheet confirmation is not available.
- **1,520 UNRESOLVED:** 16 Nov records without reachable official confirmation in the reviewed source material.
- **3,306 total records.** These categories are mutually exclusive. Only 627 are fully verified.

## Evidence limitations

The findings are based on retrieved official PDF text and manual cross-checks. Original PDF binary bytes and their SHA-256 hashes were not archived. Seat sheets for 17 Nov FN, 18 Nov AN and 18 Nov FN were not retrieved. No 16 Nov official PDFs were found in the reviewed material. Consequently, hall-list-only records are not seat-verified and unresolved records have no official confirmation.

## Release safeguards

Only FULLY_VERIFIED records can be approved. HALL_LIST_CONFIRMED and UNRESOLVED records are blocked from individual approval, bulk approval and publication. Acknowledgements do not bypass the status gate. Changes to hall, seat or subject code reset status to UNRESOLVED. Future sessions default to UNRESOLVED until explicit evidence is reviewed.

See [VSB_OFFICIAL_VERIFICATION_REPORT.md](VSB_OFFICIAL_VERIFICATION_REPORT.md) for the sample record, corrected transcription, seat-sheet comparison, and hall-label variant distribution.

## Administrator verification workflow

After checking the original official PDFs, an administrator can record the result through `POST /api/vsb-allocation/records/{record_id}/verification`. The request requires an HTTPS PDF reference hosted on `vsbec.edu.in` for the hall list and, for FULLY_VERIFIED, a second official seat-sheet PDF reference plus a note. The operation is audited and returns the updated status. This records the administrator's attestation and source references; it does not download or cryptographically archive the PDF bytes. A material edit to hall, seat, or subject code resets the status and requires verification again.

## Additional limitations recorded in UPDATED_CANDIDATE_v2
* The server does not fetch or compare the official PDFs when an administrator records verification; it checks only that each reference is an HTTPS `.pdf` on `vsbec.edu.in` and writes an audit entry. Correctness depends on the administrator.
* Register `992696352264` (17 Nov 2026 AN) is officially listed in MB III A04, seat 28 (hall list p.4, seat sheet p.20). The mirror's `MB III 206` was a transcription error, not an official contradiction. The mirror value stays in `allocation_provenance.json`; the correction is appended in `provenance_corrections.json`. The record still carries the `hall_mismatch` flag (computed from the unchanged mirror data) until an administrator confirms the hall with a recorded reason.
* Seat sheets for 17 Nov FN and 18 Nov, and any 16 Nov confirmation, were not independently verified; those records remain HALL_LIST_CONFIRMED / UNRESOLVED.
* Rows that existed before migration 0014 default to UNRESOLVED. Since v3 (migration 0015 + `app/vsb_alloc/visibility.py`) such rows are **hidden from every student-facing view** even if they were published; they are never deleted or upgraded, and an administrator can verify them through the normal workflow. HALL_LIST_CONFIRMED rows show the hall only (seat withheld). See `docs/DEFECT_FIXES_A_B.md`.
* None of the v2 changes has been executed against a database or test run yet.
