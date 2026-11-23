# VSB official verification report — 17–18 November 2026

## Scope and evidence standard

This report records the official-source verification findings supplied for this project. The official source is the V.S.B. Engineering College Controller of Examinations page: https://vsbec.edu.in/controller-of-examination/. The findings below are based on retrieved official PDF text and cross-checks described in the project audit; the original PDF binary files and their cryptographic hashes were not archived in this release. Therefore this is a documented text-retrieval audit, not a reproducible binary-evidence archive.

## Record status totals

| Status | Records | Meaning |
|---|---:|---|
| FULLY_VERIFIED | 627 | 17 Nov 2026 AN; hall, seat and subject checked against the official hall list and seat sheet. |
| HALL_LIST_CONFIRMED | 1,159 | 17 Nov FN (904), 18 Nov AN (87), and 18 Nov FN (168); hall and subject confirmed from hall lists, seat not independently checked against seat sheets. |
| UNRESOLVED | 1,520 | 16 Nov records; no reachable official confirmation in the reviewed source material. |
| **Total** | **3,306** | These are status totals, not a claim that every record is fully verified. |

There were zero confirmed official contradictions in the reviewed records. The 1,159 hall-list-only records are not seat-verified and must remain blocked from approval/publication. Unresolved records must also remain blocked.

## Seat-sheet comparison

For 17 Nov AN, the hall list and seat sheet agree for all 627 records: 627 assignments, 627 unique assignments, and no missing, extra, or duplicate seat assignments were reported. The seat-sheet transcription covered 25 pages.

The 17 Nov FN, 18 Nov AN and 18 Nov FN seat sheets were not retrieved for independent seat verification. No 16 Nov official PDFs were located in the reviewed source material.

## Hall-label variants

The hall-label variant review contains 2,099 records. Its status distribution is 377 FULLY_VERIFIED, 772 HALL_LIST_CONFIRMED, and 950 UNRESOLVED. These are a subset of the overall record population and must not be confused with the overall 627 / 1,159 / 1,520 totals. Fourteen spelling pairs were confirmed as separate halls in at least one official session; do not automatically merge labels such as `MB III 203` and `MB III A203`.

## Corrected transcription

Register `992696352264` is officially listed in MB III A04, seat 28 (hall-list page 4; seat-sheet page 20). The earlier mirror value MB III 206 was a transcription error, not an official contradiction. Preserve the original provenance and append the correction in the audit trail.

## Sample record

Register `992696352326`: 17 Nov 2026 AN, DIGITAL ELECTRONICS, subject code `23ECT307`, hall MB III A103, seat 23. Hall-list page 4 and seat-sheet page 23 confirm the assignment. The official allocation documents do not print an exam time; do not describe 13:30–16:30 as PDF-verified.

## Operational policy

- Only FULLY_VERIFIED records may be individually approved or bulk-approved. Existing conflict flags and live duplicate-seat checks continue to apply.
- HALL_LIST_CONFIRMED and UNRESOLVED records remain blocked. A note or acknowledgement cannot bypass the verification gate.
- A changed hall, seat or subject code invalidates the prior verification and resets the record to UNRESOLVED. Department-only edits do not invalidate seat verification.
- Publishing performs a second server-side verification-status check.
- The status is assigned from the reviewed date/session evidence; future dates default to UNRESOLVED.

## Limitations

The source PDFs were not archived as original binary files and no PDF SHA-256 hashes are claimed. Seat-sheet verification is incomplete for the sessions listed above. This report does not establish that the 3,306 records are all fully verified, nor does it establish official endorsement of this software.
