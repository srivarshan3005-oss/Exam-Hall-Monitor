# V7 test report

Every number below was produced by running the command shown, on **Linux (kernel 6.18), Python 3.12.3, Tesseract 5.3.4**, from the
**ZIP extracted into an empty directory with a brand-new virtual environment** (`pip install -r requirements.txt -r requirements-dev.txt`).
Nothing here was run on Windows, in Docker, on GitHub, against PostgreSQL, in a real browser, or against the live VSB websites.

## 1. Backend suite
```
cd backend
python -m pytest -p no:cacheprovider -q
```
| Executed | Passed | Failed | Errors | Skipped | Time |
|---|---|---|---|---|---|
| 826 | 788 | 0 | 0 | 38 | 146 s |

Skipped (38), all by design and visible in the run: PostgreSQL-only checks (no PostgreSQL server; set `TEST_POSTGRES_URL`) - real 16-Nov notice
fixtures and operator-supplied original-portal data (intentionally not distributed) - the opt-in live-source test (`VSB_LIVE_TESTS=1`).

New in V7 (77 tests, 76 executed + 1 opt-in live test skipped):

| File | Tests | Covers |
|---|---|---|
| `test_v7_live.py` | 19 | discovery (HTML, embedded, WordPress, sitemap, two hosts, health), empty/non-PDF/corrupt/wrong-type/off-site downloads, total-outage behaviour, end-to-end lookup, all 390 hall+seat pairs vs the independent re-derivation, normalisation, processing/not-published states, hall-only, seat-only, **conflict**, **modified PDF at the same URL**, duplicate PDF, OCR, corrupt stored PDF, seat-added-is-not-a-revision |
| `test_v7_original_page_image.py` | 10 | **whole page returned; every other register number pixel-identical to PyMuPDF's own render (hall and seat pages); changes confined to the highlight box; OCR still reads other students' numbers; pristine image byte-equal to the direct render; correct page chosen; no highlight when not locatable; wrong-owner/out-of-range 404; obsolete cache purged; poisoned cache ignored; masking module gone** |
| `test_v7_features.py` | 19 | printable slip (+ escaping), e-mail watch (once per event, revised, attachments, no repeat, failure/retry/redaction, SMTP path, test e-mail, unconfigured production), Supabase (optional, batches, failure + retry, RLS SQL), hall locations (hidden until verified with source, map, history), management API roles, no bulk endpoint, rate limit, safe status, no `.env`/DB served, **no notification for students whose allotment did not change** |
| `test_v7_units.py` | 28 | register normalisation/rejection, weekday, programme split, classification matrix, fingerprint, material-change rule, embedded-PDF parsing, safe sitemap XML (no external entities), coordinate/e-mail validation, **database unavailable -> 503 without internals** |
| `test_live_vsb.py` | 1 (skipped) | live official-site cycle - see section 4 |

V6 tests that asserted behaviour V7 deliberately changed were rewritten, not deleted: masking assertions -> unmasked assertions; hours-based
schedule -> 5-minute + back-off; subdomain rule (`coe.` now allowed); migration head 0015 -> 0016 (additive-column aware). A time-dependent UI test
(exam date 2026-11-20 had become "past") now uses fixed far-future dates.

## 2. Browser-less UI tests (jsdom against a real uvicorn server)
```
cd backend/tests/e2e_jsdom && npm ci && cd ../..
python tests/portal_dom/run_portal_dom.py     # student portal: 39 passed, 0 failed
python tests/e2e_jsdom/run_e2e.py             # admin SPA incl. Live monitoring page: 247 passed, 0 failed
```
`node --check` on all 15 JavaScript files: no syntax errors. jsdom is a DOM simulation: layout, real fonts, touch, print preview and mobile
rendering were **not** exercised.

## 3. Real server process (clean extraction, fixture "official site")
A launcher (`/tmp/serve_fake.py`, not shipped) started the real application with the real scheduler and the real crawler code, only replacing the network call with
the fixture site. Observed: automatic scan at start-up (no click) -> status ok, 2 documents, 390 records; `/portal/` 200; `/.env`, `/exam_monitor.db`, `/uploads` 404;
original page image 200 with `x-original-page: unmasked` and `x-highlight-count`; slip contains hall/weekday/subject; unauthenticated `/api/live/overview` 401;
after the fixture site published a revised hall list/seat chart, **Run scan now** downloaded both, 25 records revised (hall MB III 02 -> MB III 09, `revised = true`),
365 unchanged; no tracebacks in the server log.

## 4. Live verification (official VSB websites) - **PENDING**
From the build environment `https://vsbec.edu.in/controller-of-examination/` and `https://coe.vsbec.edu.in/` returned no response (connection could not be established), so:
website connectivity - **not verified**; live PDF discovery - **not verified**; live download - **not verified**; processing of an actual college PDF - **not verified**
(only fixtures rebuilt from the real 20-Nov-2026 page text were processed); live register-number lookup and live original-page verification - **not verified**.
Run on a machine that can reach the site: `VSB_LIVE_TESTS=1 python -m pytest tests/test_live_vsb.py -v -s`, or `python -m app.cli run-cycle` then `python -m app.cli status`.

## 5. Not executed
Windows `install.bat/start.bat/stop.bat/health_check.bat/test.bat` - `docker build` / `docker compose` - GitHub Actions workflow - PostgreSQL suite - real Supabase project - real browsers/devices - Android app.
