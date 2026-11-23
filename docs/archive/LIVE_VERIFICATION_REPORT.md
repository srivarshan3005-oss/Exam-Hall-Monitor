# Live VSB verification — 20-Nov-2026 (final task)

## Verdicts
| | Stage | Verdict | Evidence |
|---|---|---|---|
| A | Official website access | **FAIL (environment)** | Sandbox: `curl https://vsbec.edu.in/` -> `Could not resolve host`. The app's own discovery run recorded `status=failed: robots.txt could not be read right now; not fetching until it can be checked` (fail-closed, correct). A third-party fetch tool could read the two PDF URLs (text only), which shows they exist, but that is not the app accessing the site. |
| B | Automatic PDF discovery | **NOT TESTED live** | Needs A. Mocked crawler tests pass (not counted as PASS). |
| C | Automatic PDF downloading / hashes | **NOT TESTED live** | I have no PDF bytes, so no real hash exists. Hash handling is covered only with generated files. |
| D | Scheduled monitoring | **PASS for start/run/record; NOT TESTED for a successful run** | Real uvicorn process, `SCHEDULER_ENABLED=true`: the worker started, ran a cycle within seconds and wrote a `vsb_crawl_runs` row (trigger=scheduler, status=failed, message above). Change made: a failed run is retried after 15 min instead of the full 6 h (test added). Interval unchanged (6 h). Detection of new/changed PDFs live: NOT TESTED. |
| E | PDF parsing accuracy | **PASS on the official text layer; NOT TESTED on the binary PDFs** | 390 register numbers, 390 unique, 11 department totals and 16 hall totals equal printed totals; independent comparator agrees (see TECHNICAL_REPORT_20NOV26.md). |
| F | Student roster matching | **PASS in a test DB (3 matched / 387 unmatched, reported separately)** | No real roster was available; students in tests are synthetic stand-ins, not real people. |
| G | Hall and seat accuracy | **PASS on text layer and on generated PDFs; NOT TESTED on VSB's binary PDFs** | All 390 hall/seat/subject values equal the reference; 0 missing, 0 duplicate, 0 incorrect. |
| H | Student register-number lookup | **PASS (API, generated PDFs)** | Lookup returns date, session, hall, seat, official link; unmatched/unpublished/unverified -> 404 or empty. |
| I | Original PDF page preview | **PASS (generated PDFs, pixel-checked)** | Other numbers covered, own highlighted, fails closed without text layer. Not tested on VSB's binary PDF. |
| J | Complete end-to-end | **NOT TESTED live; PASS only for the offline chain** (staged files -> auto_stage -> approve -> publish -> lookup -> preview) | The first link (website -> download) could not run here. |

## Changes this round
* `VSB_AUTO_DISCOVER_ENABLED` and `VSB_STAGE_DRAFTS_ON_SCHEDULE` now default to **true** (config.py and .env.example). Interval `VSB_DISCOVER_INTERVAL_HOURS=6` untouched. Nothing is auto-approved or published.
* Scheduler staged drafts only in a cycle that also downloaded something; it now runs the (idempotent) staging every due run, so a transient staging failure is retried.
* Failed discovery runs retry after 15 minutes.
* `backend/scripts/verify_live_vsb.py`: run it on a machine with internet to produce the real A/B/C/E/G (and F if a roster is loaded) verdicts in a throwaway database. Verified here only up to the network failure.

## Tests (from backend/)
`python -m pytest tests/vsb tests/test_vsb_20nov26_end_to_end.py tests/test_vsb_alloc_workflow.py tests/test_vsb_crawler.py tests/test_vsb_defects_a_b.py tests/test_vsb_verification_enforcement.py tests/test_phase13_portal.py tests/test_portal_disclosure.py tests/test_release_config.py tests/test_static_and_startup.py -o addopts=` -> **157 passed, 6 skipped, 0 failed** (skips: operator private data, pre-existing).
Live scheduler: `SCHEDULER_ENABLED=true SCHEDULER_INTERVAL_SECONDS=5 uvicorn ...` -> `/api/ready` ok, one scheduler row in `vsb_crawl_runs`.
No screenshots: no browser in the sandbox.

## Still needs you
1. On your Windows PC (internet): `python scripts\verify_live_vsb.py` and send me the JSON.
2. Import your authorised student roster (Data -> import students) before expecting any student to find a result.
3. An administrator must verify, approve and publish each batch.
4. If the site's robots.txt blocks automated reads, discovery will keep failing closed; I did not bypass that.
