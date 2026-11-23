# Live monitoring and register-number lookup (V7)

## What the student sees
`/portal/` - one field: **register number**. Nothing else is asked. The result shows every examination found for that number
(regular and arrear, FN and AN, several dates, several subjects), sorted by date, each with:
date + weekday, session (FN/AN; a time only when `SESSION_TIMES` is configured), subject code and name, programme, department,
hall, seat, status, source PDF + page, last-verified time, verified building/floor/map (only when an administrator verified it),
and the **original, complete, unmasked page** of the hall list and of the seating chart (zoom viewer, highlight toggle, PNG
download, official PDF link). `Print slip` opens `/api/public/slip/<register>`.

Statuses (per record): `CONFIRMED` (hall list and seat sheet agree) - `HALL_ONLY` (seat not published/verified; no seat shown) -
`SEAT_ONLY` - `CONFLICT` (documents disagree; nothing is chosen silently, both pages shown) - `MANUAL_REVIEW` (the parser
flagged uncertainty; values are shown only as "unverified"). Result-level states: found, no_match, not_yet_published,
processing, source_unavailable, conflict, manual_verification.

## Pipeline (one implementation, `app/vsb_live/cycle.py`)
`discover -> download -> validate -> parse -> reconcile -> index -> notify -> optional Supabase sync`

1. **Discovery** (`vsb_live/discovery.py`, over `https://vsbec.edu.in/controller-of-examination/` and `https://coe.vsbec.edu.in/`):
   HTML links, `<iframe>/<embed>/<object>` PDFs and `viewer?file=` wrappers, WordPress REST `wp/v2/media?mime_type=application/pdf`,
   `wp/v2/search`, XML sitemaps. Only https URLs on the allow-listed hosts are requested; robots.txt is honoured per host; the
   request rate is limited. Every method's health is stored (`vsb_source_health`) and shown on the dashboard.
2. **Download** (`vsb_sources.py`): conditional requests (ETag/Last-Modified), retry with back-off, timeouts, size limit
   (`VSB_MAX_DOWNLOAD_MB`), content-type check, empty-body rejection, `%PDF-` signature and a real open with PyMuPDF,
   SHA-256. Same URL + new bytes = new version (modified document detected); same bytes under another URL = duplicate.
3. **Parse** (`vsb_alloc/hall_parser.py`, `seat_parser.py`, `pdfwords.py`): page-level word boxes (PyMuPDF), table-aware
   parsing, register-number pattern validation, OCR fallback (Tesseract) for image-only pages. Seats are mapped from word
   coordinates only - never guessed from "the nearest number".
4. **Reconcile** (`vsb_alloc/reconcile.py`): hall list and seat sheets are joined on date + session + register number, with subject
   and hall cross-checks and per-hall counts. Ambiguity becomes a flag, never a guess.
5. **Index** (`vsb_live/pipeline.py`): rows in `live_allotments` with the exact source versions and 0-based pages. A changed PDF
   supersedes rows (history kept, `revision` + 1). A *revision* means a changed hall/seat/subject; adding the seat to a
   hall-only record is "new detail", not a revision.
6. **Failure policy**: a failed scan, download or parse never removes data. Rows of a (date, session) change only when that
   session was re-parsed successfully. The public footer shows the last **successful** scan time; a failed latest scan is shown as failed.

## Scheduling
Default **5 minutes** (`VSB_POLL_MINUTES`, clamped 5-1440), plus a scan at start-up (`VSB_SCAN_ON_STARTUP`). After failures the
wait grows 5, 10, 20, 30 minutes (cap) and resets on success. A background thread runs it - the website is never blocked.
`Run scan now` (dashboard), `python -m app.cli run-cycle` and the GitHub workflow call the same function; one cycle runs at a time.

## Original page image
`app/vsb_live/render.py`: PyMuPDF renders the whole page. The searched number is highlighted by a separate overlay confined to
that word's own box (multiply blend + 1 px outline). If it cannot be located reliably (OCR page, abbreviated in a table) the page is
returned with no highlight. `?hl=0` returns the pristine render byte-for-byte. Cache directory `page_cache/<PREVIEW_CACHE_VERSION>/`;
older directories are deleted at start-up, so no earlier (masked) image can be served. Regression tests:
`tests/test_v7_original_page_image.py` (pixel-identical other numbers, whole page, OCR legibility, cache purge).

## Hall locations
Dashboard -> Live monitoring -> Hall locations. A hall is shown to students **only when `verified`**, only with the values stored,
and verifying needs a recorded source. Map coordinates are optional; the map is a schematic SVG (hall marker, optional verified
entrance, link to OpenStreetMap). No coordinate, building or direction is ever invented; otherwise the student sees
"Building/floor location has not yet been verified." Every edit is kept in `hall_location_history`.

## E-mail watch (optional)
Administrators add `register number + e-mail` pairs. When an allotment for that number appears or is revised, one message is
sent (original PDF + highlighted unmasked page attached). `live_notifications` has a unique (watch, allotment fingerprint) key, so
a message is never repeated. Transient SMTP errors are retried with back-off; the failure text is redacted; lookups are unaffected.
SMTP settings come only from environment variables (`SMTP_*`). Public visitors cannot subscribe.

## Supabase mirror (optional)
`SUPABASE_URL` (https) + `SUPABASE_SERVICE_KEY` enable a backend-only upsert mirror of `live_allotments`
(`supabase/schema.sql`: RLS enabled, no policy for anon/authenticated => the public key can neither read nor write). Failures are
logged (`live_sync_log`) and the backlog is sent on the next cycle. SQLite works without any of this.

## Commands
See `README.md` (section "Command line"). Dashboard API: `/api/live/*` (staff read, administrators write).
