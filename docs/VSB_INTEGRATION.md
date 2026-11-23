# Official V.S.B. Engineering College integration

Provenance, publication rules and the exact validation limits: see [VSB_VERIFICATION_LIMITATIONS.md](VSB_VERIFICATION_LIMITATIONS.md).

## Confirmed official sources (checked live on 15 Nov 2026)
| Purpose | Address | How it is used |
|---|---|---|
| College website | https://vsbec.edu.in/ | link only |
| Controller of Examinations page (timetable, hall allotment, seating allotment PDFs) | https://vsbec.edu.in/controller-of-examination/ | **read by Discover** |
| Results portal (linked from that page as "Results") | https://coe.vsbec.edu.in/students/ | link only, never crawled |
| College downloads page (linked in the footer of that page) | https://vsbec.edu.in/downloads/ | link only, never crawled |

No other address is built in. PDF addresses are never constructed from file-name patterns: only links actually present
on the official page are recorded. `coe.vsbec.edu.in` is crawled by nothing; the COE staff-login link is deliberately not offered.

## What was added
* **Staff page "VSB official notices"** (Documents menu): official links, *Check official page now*, a table of every PDF
  found (type, exam date/session, source URL, published info, download status, stored copy), per-link *Download/Re-check*,
  *Process*, *Review PDF* and *Seating import* shortcuts, a per-document history panel and the discovery-run history.
* **Public home page card** "Official VSB examination notices": the confirmed links plus titles/dates of discovered notices,
  all pointing at the college site. It contains no register numbers or seating data.
* **API** (`/api/vsb/...`): `GET official-links` (public); staff/admin: `GET sources`, `GET links`, `GET runs`,
  `POST discover`, `POST links/{id}/download`, `GET links/{id}/history`.
* **Migration 0012** (additive: tables `vsb_source_links`, `vsb_crawl_runs`). No existing table or record is changed.
* **Optional scheduler job** (off by default): `VSB_AUTO_DISCOVER_ENABLED=true`, interval `VSB_DISCOVER_INTERVAL_HOURS`.
  Scheduled runs download only; they never process or publish anything.

## Workflow
Discover → PDF stored as an ordinary `OfficialDocument`/`DocumentVersion` (origin `crawler`, source label
"V.S.B. Engineering College – Controller of Examinations") → *Process* (text layer, OCR for scans; automatic after a manual
run unless unticked) → **Timetable PDFs** review → **Seating PDF import** (extract, human correction, admin approval,
preview, confirmed import). Nothing reaches students or seat allotments without the existing administrator approvals.

## Automatic download policy
Hall allotment, seating allotment, timetable and notice PDFs are downloaded automatically. Other PDFs on the page
(forms, academic schedule, …) are listed as "Not auto-downloaded" and can be fetched with the *Download* button.

## Dates
The COE page does not print publication dates, so none is invented. *Published* shows the server's `Last-Modified` header
when it sends one, otherwise the year-month in the file path (`/wp-content/uploads/YYYY/MM/`), labelled as such. Exam date
and FN/AN session are taken only from the link text or file name when printed there; otherwise they stay "not stated".

## Failure handling
* Page unreachable/offline: the run is recorded as *failed*; links, documents and history are untouched; nothing is marked removed.
* 404/410: link marked *Unavailable*; the stored copy and history are kept; it is retried on later runs.
* 5xx / timeouts / DNS: bounded retries with back-off, then *Failed* (retried on later runs).
* 401/403, robots.txt disallow, unreadable robots.txt, redirect off the college host, non-PDF response, encrypted/damaged PDF,
  PDFs with JavaScript/launch actions: *Blocked*, with the reason shown. Blocked links are only retried manually.
* Same bytes already stored (any URL): *Duplicate*, not stored again. Same URL with different bytes: new version, previous kept.
* A link that disappears from the page: *no longer listed*; if the same type/date/session appears at a new address a note links them.
* Conditional requests (ETag / Last-Modified) avoid re-downloading unchanged files. One run at a time (a second request gets HTTP 409).

## Settings (backend/.env, all optional)
`VSB_COE_PAGE_URL` (must stay on vsbec.edu.in over https, otherwise the confirmed address is used), `VSB_AUTO_DISCOVER_ENABLED`,
`VSB_DISCOVER_INTERVAL_HOURS`, `VSB_HTTP_TIMEOUT_SECONDS`, `VSB_REQUEST_DELAY_SECONDS`, `VSB_MAX_DOWNLOADS_PER_RUN`, `VSB_MAX_RETRIES`.

## Limits of what was verified
See the delivery notes: live access to the college server from the build environment was not available, so the first real
download run happens on your machine. Extraction patterns for the November 2026 PDFs were not validated against real files.
Check the college's terms of use and robots.txt policy before enabling scheduled downloads.


## Update (VSB_KARUR_FINAL_FIXED)
Hall/seating PDFs are now read by the dedicated parsers and reviewed on *VSB hall & seat*; see `VSB_ALLOCATION.md`. The generic *Seating PDF import* and the timetable extractor are no longer offered for these two document kinds (the timetable heuristics are skipped for them). Scheduled runs download only, unless `VSB_STAGE_DRAFTS_ON_SCHEDULE=true`, which stages drafts — never publishes.

## Hall and seat allocation (migration 0013)
Hall-allotment and seating-allotment PDFs found by Discover are parsed by the dedicated parsers in `app/vsb_alloc/` into draft batches, reviewed and published
from the staff page *VSB allocation*; students read their own published seat on *My VSB seat*. Full details and limits: [VSB_ALLOCATION.md](VSB_ALLOCATION.md).
Final-release notes: [archive/FINAL_RELEASE_NOTES.md](archive/FINAL_RELEASE_NOTES.md).
