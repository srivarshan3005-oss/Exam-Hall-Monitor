# Critical defect fixes A and B (UPDATED_CANDIDATE_v2 -> v3 patch)

## Defect A - approval bypass after an unrelated edit
Cause: `_approve_problem` skipped the hard-conflict check whenever `record.edited` was true; a department-only edit set it.
Fix (`backend/app/routers/vsb_alloc.py`):
* `edited` is a history marker only; nothing consults it to relax a rule.
* `_hard_conflicts()` recomputes conflicts from the current record: `duplicate_seat` live from sibling records;
  `hall_mismatch` also from the hall printed in each PDF (`detail.hall_pdf_hall` vs `seat_pdf_hall`); `provenance_mismatch` from flags.
* A hard conflict is cleared only by `POST /api/vsb-allocation/records/{id}/resolve-conflict` (admin only, official HTTPS vsbec.edu.in PDF
  reference, note >= 10 chars, record must be FULLY_VERIFIED). It is stored as an *administrator assertion*, never as independent
  verification, bound to the hall/seat/subject at that moment, and voided by any later change to them. Audited as `vsb_alloc.conflict_resolved`.
* Same check on individual approval, bulk approval (`approve-confident`), publish preview/plan and publish itself.
* "Missing value" flags (e.g. `missing_in_seating_pdf`) are cleared only by a recorded correction that supplies that field.
* `PATCH /records/{id}` accepts an optional `note`; department/note edits never change `verification_status`; audit rows list changed fields.

## Defect B - legacy published rows with UNRESOLVED verification
Policy (`backend/app/vsb_alloc/visibility.py`, used by every student/public query):
* FULLY_VERIFIED -> hall and seat shown as confirmed. HALL_LIST_CONFIRMED -> hall shown, seat withheld, labelled. UNRESOLVED -> not shown.
* Applied to: public lookup, signed-in `/api/vsb-allocation/my`, seat map, taken-seat list, notice counts.
* Nothing is deleted, upgraded or rewritten; approval/publication history is kept. Admins see and verify these rows through the existing
  verification workflow. Public lookup responses do not reveal whether a student has hidden rows (a static note only);
  `/my` returns `withheld_unverified` for the signed-in student's own rows.
* Migration `0015`: renames `HALL_LIST_ONLY` -> `HALL_LIST_CONFIRMED`, widens the column to 24 chars, replaces the CHECK constraint,
  writes one audit row per legacy published+UNRESOLVED record. Idempotent; downgrade supported.

## Tests
`backend/tests/test_vsb_defects_a_b.py` (10 tests). Two older tests were updated because they encoded the old behaviour:
`test_original_import.py::test_hall_conflict...` (now requires re-verification + explicit resolution) and the `_vsb_rec` helper in
`test_phase13_portal.py` (rows now carry an explicit FULLY_VERIFIED status). No assertion that blocks an action was removed.

## Not done in this patch
A separate PATCH_STATUS file was referenced in earlier builds but was never part of the release; the Defect A and B fixes are described in this document and in archive/VALIDATION_REPORT_v6.md.
