# VSB automation reliability fixes — 24 November 2026

This is a targeted reliability patch to the supplied Exam Hall Monitor archive. It does not claim that a GitHub Actions deployment has been run from this environment.

## Changes

1. **Official label takes precedence over filename keywords.** The live Controller of Examinations page currently labels the 24-November FN PDF `HALL ALLOTMENT - FN`, while its file name is `24.11.26-FN-HALL-SEAT.pdf`. The previous classifier saw `SEAT` in the filename first and could classify that hall document as a seating document. Classification now checks explicit `SEATING ALLOTMENT` / `HALL ALLOTMENT` link text before falling back to filename heuristics. Regression tests cover both precedence directions.
2. **A failed scan cannot be hidden by `tee`.** The Pages workflow now enables `set -o pipefail` and no longer marks the monitoring step `continue-on-error`.
3. **Publication is gated on fresh, successful source processing.** `scripts/publish_gate.py` checks the current cycle JSON. It blocks deployment if discovery failed or was partial, no PDF links were found, ingestion crashed, or any PDF parse failed. Cached records alone are not accepted as proof that the current scan succeeded; the previously published site remains in place when the gate blocks publication.
4. **Removed assumed FN/AN clock times.** The Pages workflow no longer injects fixed session times. The application default is to leave session times unset unless an official source supplies them.

## Verification performed

- Targeted regression suite: `tests/test_publish_gate.py`, `tests/test_vsb_crawler.py`, `tests/test_live_vsb.py`, and `tests/test_vsb_20nov26_end_to_end.py` — **23 passed, 1 skipped**.
- Python full-suite collection is blocked in this environment because the development-only dependency `aiosmtpd` is not installed. Network access is unavailable here, so it could not be installed.
- A broader run excluding the SMTP test file exceeded the execution time limit; it is not reported as passed.
- The live official COE page was opened on 24-Nov-2026 and showed hall and seating links for 24, 25 and 26 November, both FN and AN. The 24-Nov FN hall PDF link was opened and its official link label and filename were checked. This validates the classifier regression case, not the entire GitHub Actions deployment.

## Remaining external verification

After uploading this patch to the repository's `main` branch, run **Publish student portal (automatic)** from GitHub Actions. Confirm the scan gate reports success, the workflow uploads and deploys the Pages artifact, and the published portal reflects the newly discovered records. GitHub-hosted execution and the final live Pages deployment cannot be verified from this local archive review.
