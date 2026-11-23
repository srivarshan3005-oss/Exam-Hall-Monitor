# VSB hall & seat allocation (parsers, review, publishing)

Official source (unchanged, verified): <https://vsbec.edu.in/controller-of-examination/> — the only page crawled.

## What the official PDFs look like (checked 15 Nov 2026, text layer of `14.11.26-FN-HALL.pdf` and `14.11.26-FN-SEAT.pdf`)
* **Hall PDF** – header `DATE OF EXAMINATION: 14-11-2026 SESSION : FN`; per programme: `[23CST302R] TITLE`, wrapped comma lists of full register numbers, then `MB III 202 13` (hall label + hall total); footer `BE-CSE` (repeated on a continuation page) and `TOTAL 202` on the programme's last page. A short list may have the hall on the next line.
* **Seat PDF** – one page per hall: `EXAM HALL : MB III 02`, a 4-column serpentine grid of *seat | register number* (seats 1–7, 14–8, 15–21, 28–22), then a `CODE / TITLE / TOTAL / REGISTER NUMBERS` table with compressed lists (`994177572092 - 093, 095 - 105`, two prefixes in one row). Empty seats print only their seat number, so `1 14 15 28 994177572013` cannot be mapped from text alone. Register lines of a row can be printed *before* its code line (halls A203/A204).

## Code (`backend/app/vsb_alloc/`, pure Python)
| module | job |
|---|---|
| `hall_parser.py` | date, FN/AN, programme, subject, register numbers, hall, hall/programme totals; wrapped lines; hall-on-next-line; continuation pages |
| `seat_parser.py` | seat grid → register numbers using **word coordinates** (row + column); subject table rows attached by their printed TOTAL; text-order fallback marks every seat *unconfirmed* |
| `reconcile.py` | merges both PDFs per session; duplicates, conflicting halls, missing students (either direction), per-hall / per-subject / per-programme totals, OCR damage, seat conflicts |
| `service.py` | stores a **draft** batch; `auto_stage` (only unambiguous hall+seat pairs, drafts only) |
| `routers/vsb_alloc.py` | API `/api/vsb-allocation/*` |

Nothing is guessed: unreadable seat → seat left empty + flag; contradictory hall → hall left empty; OCR-damaged number (e.g. `9946870O3001`) is **not used** (suggested reading shown only in the issue).
Flags that block approval without a note/acknowledgement: `missing_in_seating_pdf`, `missing_in_hall_pdf`, `hall_mismatch`, `conflicting_halls`, `seat_label_missing/ambiguous`, `seat_cell_ambiguous`, `ocr_ambiguous`, count/total mismatches. Warnings: `seat_from_text_order`, `department_inferred`, `student_not_in_database`, `nonstandard_register_number`.

## Workflow (UI: *Seating → VSB hall & seat*)
1. **Discover/download** on *VSB official notices* (existing). 2. **Build draft** from one hall PDF + one seat PDF (or let discovery stage it). 3. **Review**: issues list, filter by register no./hall/decision/uncertain; **Correct** (hall, seat, subject, department – reason required, history kept); **Approve** per record (flagged ones need a note, blocking ones need a correction or an explicit "verified against the PDF"); *Approve clean records* only touches records with **no flag at all** and a matching student. 4. **Preview & publish**: only approved records, bound to a signature; open error issues need an explicit acknowledgement. 5. Students see **only approved + published** records (signed-in `GET /api/vsb-allocation/my`, page *My hall & seat*, and the public register-number lookup unless `VSB_PUBLIC_LOOKUP=false`). 6. Optional **Bridge** writes `allotments` (source `vsb`) through the normal `check_placement` rules; the examination is matched by date + subject code, never created. *Withdraw* hides everything again; edits are blocked while published.
Publishing is never automatic: not at build, not at discovery, not on schedule.

## Scheduled discovery – how to enable
In `backend/.env` (restart the server; `SCHEDULER_ENABLED` must not be `false`):
```
VSB_AUTO_DISCOVER_ENABLED=true     # check the official page every VSB_DISCOVER_INTERVAL_HOURS (default 6)
VSB_STAGE_DRAFTS_ON_SCHEDULE=true  # optional: also stage DRAFT batches for new hall+seat PDFs
```
Other knobs: `VSB_REQUEST_DELAY_SECONDS`, `VSB_MAX_DOWNLOADS_PER_RUN`, `VSB_MAX_RETRIES`, `VSB_HTTP_TIMEOUT_SECONDS`. Run history, failures and per-link document versions are on *VSB official notices*. A changed file at the same address becomes a new version (older kept); a new address for the same type/date/session is a new link and both are flagged; batches show "PDF replaced since" when their source version is no longer current. Check the college's terms/robots policy before enabling.

## Tests
`tests/vsb/` (hall, seat, reconcile – pure), `tests/test_vsb_crawler.py` (real link list), `tests/test_vsb_alloc_workflow.py` (API: stage/approve/publish/student view/permissions/bridge), `tests/test_references.py` (+ `scripts/check_references.py`). Fixtures reuse the real layout with register-number year digits rewritten (`92252x → 92259x`); no real student ID is stored.

## Hall capacity check (final inspection)
When a batch is staged, the number of students placed in each hall is compared with the capacity in the hall directory. A hall over capacity raises a blocking `hall_capacity_exceeded` issue and flag on every record in it; a hall missing from the directory raises an info note only (capacity is never guessed). Not executed or tested in this session.
