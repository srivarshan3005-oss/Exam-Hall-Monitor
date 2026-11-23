# V7 - comparison with the reference project (`EXAM_MONITOR-main.zip`)

The reference is a small Flask project ("VSB Exam Watch V2.3", ~1,300 lines of Python in `vsb_watch/`) with a static GitHub-Pages
portal. The main project is the large FastAPI "Exam Monitor Ultimate". Status of each reference feature **in the V6 archive that was
supplied** (`..._V6_AUTO_LIVE_20NOV26.zip`; the brief called it "V7_UNMASKED_LIVE_REFRESH", but that is not what was uploaded - V7 was
built on the V6 archive) and **in this V7 release**.

| # | Reference feature (what the reference does) | In V6 as supplied | In V7 |
|---|---|---|---|
| 1 | Student enters only a register number, sees every exam (regular/arrear, FN/AN, several dates) | **Partial** - needed a student record plus an administrator-verified, administrator-published batch | **Done** - `/portal/`, `/api/public/lookup/{reg}`; no student record or publishing step; all dates/sessions/subjects listed |
| 2 | Date + day of week, session, subject code/title, hall, seat | Present (behind publishing) | **Done**; weekday computed; session *time* only if `SESSION_TIMES` is set (the reference hard-codes 09:30/13:30; the PDFs do not print times, so V7 does not assume them) |
| 3 | Printable slip | Browser print only | **Done** - `/api/public/slip/{reg}` (escaped HTML, print CSS) + page print CSS |
| 4 | Page image as "evidence" (reference renders pages to `evidence/*.png`; 1,680 PNG files are in the archive, several folders of them under the published `docs/` and `portal/` trees) | Page image existed but **masked other students' numbers** | **Done, unmasked** - rendered on demand from the stored PDF; highlight is a separate overlay; versioned cache; legacy endpoint also unmasked; masking module deleted |
| 5 | 5-minute scheduler (GitHub Actions cron `*/5`, `POLL_INTERVAL_MINUTES >= 5`) | Hours-based interval | **Done** - `VSB_POLL_MINUTES` default 5, clamp 5-1440, start-up scan, back-off after failures, manual "Run scan now" |
| 6 | Discover new PDFs on the COE page | HTML links, one host | **Done+** - HTML, embedded PDFs, WordPress media + search, sitemaps, two hosts, per-method health |
| 7 | Modified-PDF detection | SHA-256 + versions + conditional GET | Kept; **fixed** lost run counters after a failed download; round-robin re-check so old files are still noticed |
| 8 | Parse hall list and seating chart (PyMuPDF, OCR fallback) | **Present and stronger** (coordinate-based seat mapping, reconcile, flags) | Reused (no second parser); OCR fallback wired into the automatic path |
| 9 | Automatic ingestion without a human | **Missing** (drafts only; manual verification required) | **Done** - `live_allotments` built automatically, classified CONFIRMED / HALL_ONLY / SEAT_ONLY / CONFLICT / MANUAL_REVIEW; legacy manual workflow kept for administrators |
| 10 | Persistent history | Documents + versions | + allotment revisions, ingest queue, source health, scan runs, sync log |
| 11 | E-mail alert for one register number from `.env` with attachment | Per-user reminder e-mails only | **Done** - admin-managed watch list (any number of register numbers), once per event, revised allotments, PDF + unmasked page attached, retry/back-off, history, test button; credentials only from environment |
| 12 | Supabase sync (`supabase_schema.sql`) | **Missing** | **Done, optional** - backend-only upsert mirror; schema with RLS and **no public policy** (the reference schema lets `anon` insert/update and read everything) |
| 13 | GitHub Actions workflow | Missing | `.github/workflows/vsb-monitor.yml` (cache, Tesseract, state, secrets, failure issue); *not executed on GitHub* |
| 14 | Dashboard (Flask) | **Superior** SPA admin dashboard | Preserved; new **Live monitoring** page (overview/scan, sources, documents + queue + failures + duplicates, records, hall locations, e-mail, system + logs) |
| 15 | CLI (`--once`, `--search-allotment`, `--ingest-all`, `--test-email`, `--test-allotment`) | Different CLI | `search`, `run-cycle`, `discover`, `download`, `ingest-pdf`, `test-pair`, `status`, `test-email`, `health`, `migrate`, `backup`, `restore-backup` |
| 16 | Windows `start.bat`, `scan_once.bat`, `test_email.bat` | Present (richer) | `install.bat`, `start.bat`, `stop.bat`, `health_check.bat`, `test.bat` |
| 17 | Public `allotments.json` / `allotments.js` bulk data on GitHub Pages | n/a | **Deliberately not reproduced** - a public bulk export of student records violates the stated requirement |
| 18 | Hall building/floor/map | Verified-only hall directory | + map coordinates, entrance, directions, source, history; nothing shown unless verified |

## Not reproducible / deliberately different
* GitHub-Pages-only hosting: a static host cannot render PDF pages, run the parser or monitor; V7 needs the Python backend (documented).
* Reference `DASHBOARD_SECRET = change-this-secret`, default Gmail SMTP host, `anon` write policy: not carried over (insecure defaults).
* Hard-coded session times: replaced by explicit configuration.

## Honest gaps found in the supplied V6 (fixed in V7)
1. The public lookup could not answer without an administrator publishing step.
2. Page previews masked other students' numbers (reversed on request).
3. Scan interval in hours; one listing page; one host.
4. `run_discovery` lost its failure/download counters after a failed download (rolled back).
5. Time-dependent UI test (exam on 2026-11-20 had become "past"); fixed with fixed far-future dates.
