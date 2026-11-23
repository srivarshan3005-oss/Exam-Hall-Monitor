# V7 release report - implementation summary

Built on the supplied V6 project; the V6 management dashboard and every V6 feature were kept. Reference comparison: `docs/V7_REFERENCE_COMPARISON.md`.
Limitations: `docs/V7_KNOWN_LIMITATIONS.md`. Tests: `docs/V7_TEST_REPORT.md`.

## Backend
* `app/vsb_live/` (new): `discovery.py`, `pipeline.py`, `cycle.py`, `render.py`, `locations.py`, `notify.py`, `supabase_sync.py`.
* `app/routers/public_live.py` (public register-number API, page image, slip, status, published sessions) and `live_admin.py` (management API).
* Crawler (`vsb_sources.py`): multi-method discovery hook, per-host robots.txt, second allowed host, content-type and empty-response checks, size limit setting, round-robin recheck, minutes-based polling with back-off and start-up scan; fixed lost counters after a failed download.
* `scheduler.py` runs the same cycle as the dashboard/CLI. `main.py`: new routers, cache purge at start-up, database errors answered as 503 without internals.
* `mailer.attempt_message()` for e-mail with attachments. `config.py`: V7 settings (poll minutes clamp, session times, Supabase, cache version).
* Removed: `vsb_alloc/pagepreview.py` (masking) and four obsolete dev scripts. Legacy `/api/portal/pdf-page` now serves the unmasked page.

## Database (migration `0016_v7_live_monitoring`, additive, reversible, safe to repeat)
New tables `live_allotments`, `live_ingests`, `vsb_source_health`, `live_watches`, `live_notifications`, `live_sync_log`, `campus_points`, `hall_location_history`; new nullable columns on `halls` (latitude, longitude, directions, location_source, entrance_id). Unique constraints, FK indexes, check constraints; tested up/down and schema audit. `migrate` snapshots a SQLite database before changing it (V6 mechanism).

## PDF extraction
V6 parsers reused (no duplicate). Added: OCR fallback in the automatic path, programme/department split, status classification from parser flags, per-student cross-document disagreement check, material-revision rule.

## Frontend
* `/portal/` rewritten: register number only, status banners, record cards (hall/seat large, status, revised badge, unverified box, location/map), original page images with zoom viewer + highlight toggle + PNG download + official PDF link, print slip, auto-refresh (60 s, never overlapping, never while hidden, keeps last verified results on errors), deep link `?reg=`, no `innerHTML`.
* Admin SPA: new **Live monitoring** page (6 tabs); the old public home form hands valid numbers to `/portal/`.

## Deployment
`install.bat` (Python check, venv, deps, config, migrate, health, optional admin), `start.bat`, `stop.bat`, `health_check.bat`, `test.bat`; `docker-compose.local.yml` (SQLite) and the existing production `docker-compose.yml`; `.github/workflows/vsb-monitor.yml`; `docs/DEPLOYMENT.md`, `docs/ENVIRONMENT.md`.

## Security
Register-number validation/normalisation, rate limits (lookup and image), miss throttling, record/number binding on images, escaped slip, admin-only e-mail data, secrets only from environment and redacted in stored errors, https + host allow-list + robots.txt crawler, safe XML parsing, Supabase RLS without public policy, no bulk endpoint, DB errors hidden. Documented trade-off: unmasked pages (requirement).

## Command line (from `backend/`; on Windows use `.venv\Scripts\python`)
```
python -m app.cli search 922523105015          # same result as the website (add --json)
python -m app.cli run-cycle [--rebuild]        # discover, download, validate, parse, index, notify
python -m app.cli discover                     # discover PDF links only
python -m app.cli download                     # download new/changed PDFs only
python -m app.cli ingest-pdf FILE.pdf --kind hall|seat [--source-url URL]
python -m app.cli test-pair HALL.pdf SEAT.pdf  # parse + reconcile two PDFs, no database
python -m app.cli status                       # last scan, source health
python -m app.cli test-email you@example.org
python -m app.cli health                       # exit code 0 = healthy
python -m app.cli migrate | db-audit | backup | backup-list | restore-backup FILE.zip
```
