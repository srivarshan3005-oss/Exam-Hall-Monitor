# V7 - known limitations and items not verified

Nothing below is hidden by the test results; "not verified" means exactly that.

## Not verified in the build environment
1. **Live VSB websites were unreachable** from the build sandbox (connections to `vsbec.edu.in` and `coe.vsbec.edu.in` return no response). Therefore **live discovery, live download, live processing and live lookup are PENDING**. All of them are tested only against saved fixtures (`tests/v7_fakesite.py`, `tests/v7_pdfs.py`). `tests/test_live_vsb.py` (opt-in: `VSB_LIVE_TESTS=1`) performs the live check on your machine; run it once the server can reach the college site.
2. **Fixture PDFs are generated, not VSB's binaries.** They are rebuilt from the page text captured from the real 20-Nov-2026 AN hall list and seating sheets (390 students, 42 halls, 16 sheets) with approximate geometry. The real PDFs' exact layout may differ; the parser flags uncertainty (MANUAL_REVIEW) instead of guessing, but real-PDF behaviour is unproven.
3. **WordPress REST / sitemap endpoints** of the real site may be disabled or restricted; V7 records each method's health and falls back to the HTML listing. Which methods really work on vsbec.edu.in is unknown until run live.
4. **Windows scripts were not executed** (Linux build environment). They were extended minimally from V6's scripts and reviewed by reading; test them with `install.bat` -> `start.bat` -> `health_check.bat`.
5. **Docker image was not built** (no Docker in the environment). Compose files were only YAML-parsed.
6. **GitHub Actions workflow was not run on GitHub** (YAML parsed only).
7. **Supabase** was tested against a stubbed HTTP call, not a real project; `supabase/schema.sql` was not executed on PostgreSQL.
8. **PostgreSQL** tests (`TEST_POSTGRES_URL`) were skipped (no server).
9. Python **3.12.3** is the only verified version. 3.13/3.14 were not tested; do not assume compatibility.
10. Browser tests use jsdom (a DOM simulation), not a real browser; mobile layout was not checked on devices.

## Design limits
* **Unmasked pages expose other students' register numbers** - by requirement; identical to the college's public PDF. See `docs/SECURITY.md`.
* The public index is **automatic**; correctness depends on the parser. Conflicts and uncertain records are labelled, not hidden, and the page image is always the evidence. There is no per-record administrator override (correct the PDF at the source, then scan). The legacy verified/published workflow still exists for administrators but does not feed the public `/portal/`.
* **Session times** are not in the PDFs; none is shown unless `SESSION_TIMES` is configured.
* **Hall locations/maps ship empty.** An administrator must enter and verify them (with a source); the map is a schematic, not a tile map.
* Highlighting works only where the full number exists in the PDF text layer (not on OCR pages or abbreviated table entries).
* Two documents for the same session under different URLs: the newest is used; per-student disagreements between them become CONFLICT.
* GitHub Actions state lives in `actions/cache` (best-effort, evicted after 7 idle days).
* The legacy student-database portal API (`/api/portal/*`, used by the Android app) is unchanged; the Android app was not rebuilt or tested in V7.
