# Validation report: Exam Monitor Ultimate v6 public release candidate

**Verdict: NOT a production release, and NOT 100% complete.** Every automated suite that can run in the verification
environment passes on the final extracted package. Four of the eight mandatory completion tasks could not be completed in
full because they need an environment this sandbox does not have (a Windows host, registry access to the official Docker
images, the Android toolchain, an SMTP server with credentials). Those are listed exactly in section 3 and section 11, and
nothing in them is reported as a pass.

All numbers below were read from JUnit XML files or from the console output of the stated commands. The "extracted ZIP"
runs were made from a clean extraction of the candidate package whose 347 file hashes all matched the manifest.

## 1. Status by mandatory task

| # | Task | Status | What the evidence covers |
|---|---|---|---|
| 1 | Windows install, start, login, CRUD, shutdown | **BLOCKED** | No Windows host or VM exists here. Scripts were only parsed and linted (section 8). Nothing was executed on Windows. |
| 2 | Docker image build and full Compose stack | **PARTIALLY VERIFIED** | The real docker-compose.yml and backend/Dockerfile ran end to end, but on **local substitute base images**, because the container registries are unreachable. The pinned official images were never pulled or run (section 9). |
| 3 | Android build, Kotlin tests, install, API connectivity | **PARTIALLY VERIFIED** | 25 of 25 pure-Kotlin core tests pass on the JVM. No Gradle build, no APK, no install, no API connectivity, and the data-layer test did not run (section 10). |
| 4 | Real SMTP delivery | **BLOCKED** | Outbound SMTP is closed on every tested port and no credentials were supplied. Mail is tested only against an in-process SMTP server. |
| 5 | Operator-data tests on the private dataset | **VERIFIED** | Full suite with the private data restored: 0 operator-data tests skipped, 0 failures, on both databases. |
| 6 | Independent synthetic identifiers; no leakage | **VERIFIED** (caveat in section 5) | Random block mapping applied; 0 real identifiers or reversible pseudonyms in any file type. |
| 7 | Browser compatibility | **PARTIALLY VERIFIED** | Chromium 141 and Firefox 160 pass 262 of 262 each. Safari/WebKit is untested (needs macOS). |
| 8 | Documentation references (the 47) | **VERIFIED** | All 47 resolved, none deleted; checker reports 0 broken references (section 6, Appendix A). |

## 2. Environment

| Component | Version / note |
|---|---|
| OS | Ubuntu 24.04, Linux x86_64 (sandbox) |
| Python | 3.12.3 (the Windows guide mentions 3.14; this verification used 3.12, which install.bat also accepts and the Docker image uses); pytest 9.2.0, SQLAlchemy 2.0.58, Alembic 1.20.1, FastAPI 0.139.2 |
| PostgreSQL | 16.15 (Ubuntu package) for the pytest runs |
| Node.js | v22; puppeteer-core 24 |
| Chromium | HeadlessChrome/141.0.7390.0 via @sparticuz/chromium (a headless build, not branded Chrome) |
| Firefox | firefox/160.0 from conda-forge (a repackaging of Mozilla's build, MPL-2.0), geckodriver 0.37.1, driven over WebDriver BiDi |
| Docker | Engine 29.1.3, Compose 2.40.3; Docker Hub and the common mirrors unreachable |
| Docker substitutes | Ubuntu noble via debootstrap: Python 3.12.3, PostgreSQL 16 (Ubuntu), nginx 1.24 (Ubuntu) |
| Kotlin / JVM | Kotlin 2.0.21 (the version the project declares), JUnit 4.13.2, JRE 21.0.13 |
| PowerShell | 7.4.6 (Linux build, used as a parser only) |
| Not available | Windows, macOS/Safari, Gradle, Android SDK, Maven/Google Maven, SMTP egress |

Infrastructure notes. The sandbox stops background processes (PostgreSQL, the Docker daemon) between tool calls. An early
PostgreSQL run in an earlier phase produced 20 connection-refused failures for that reason; every run in this report starts
the service in the same command. The sandbox's egress gateway re-signs HTTPS with its own CA, so containers needed that CA
inside the **test** images only; it is never added to the production Dockerfile or the package.

## 3. Test results (all from the extracted ZIP unless stated)

| Suite | Collected | Passed | Failed | Errors | Skipped |
|---|---:|---:|---:|---:|---:|
| Backend, SQLite, public package | 714 | 677 | 0 | 0 | 37 |
| Backend, PostgreSQL 16.15, public package | 714 | 697 | 0 | 0 | 17 |
| Backend, SQLite, package + private data | 714 | 686 | 0 | 0 | 28 |
| Backend, PostgreSQL 16.15, package + private data | 714 | 706 | 0 | 0 | 8 |
| Migration 0015 cases (both databases, inside the rows above) | 8 | 8 | 0 | 0 | 0 |
| jsdom front end, run_e2e.py | 225 checks | 225 | 0 | - | - |
| jsdom original workflow, run_original_e2e.py (public package) | - | - | - | - | explicitly SKIPPED, exit 0 |
| Real browser, Chromium 141 | 262 checks | 262 | 0 | - | - |
| Real browser, Firefox 160 | 262 checks | 262 | 0 | - | - |
| Kotlin core unit tests (JVM, not Gradle) | 25 | 25 | 0 | - | - |
| Docker stack: 28 end-to-end checks, plus 2 persistence runs of 3 checks each | 34 | 34 | 0 | - | - |

Skips are all explicit. Public SQLite (37): 20 need PostgreSQL, 9 need the operator's data (7 marked tests and 2 in the
real-data module), 3 are real-notice fixtures that are not distributed, 5 are PostgreSQL-only checks. Public PostgreSQL (17):
the same minus the 20. With the private data restored the 9 operator-data skips disappear. The 28 (SQLite) and 8 (PostgreSQL) that remain
are the real-notice fixtures, the PostgreSQL-only checks and, on SQLite only, the 20 tests that need a PostgreSQL server. Skipped tests are never
counted as passed.

The OCR and parser regression file (13 tests) and all 68 tests in the suite matching the OCR, parser, regno or register
keywords passed in the development tree and are included in the totals above.

Commands (from the extracted package):
```
cd backend && python -m pytest tests -p no:cacheprovider -rfE --junitxml=out.xml          # SQLite
TEST_POSTGRES_URL=postgresql://user:pass@127.0.0.1:5432/postgres python -m pytest tests ... # PostgreSQL
cd tests/e2e_jsdom && npm ci && cd ../.. && python tests/e2e_jsdom/run_e2e.py
cd tests/browser_e2e && npm ci && cd ../.. && python tests/browser_e2e/run_browser_e2e.py   # Chromium
BROWSER=firefox FIREFOX_PATH=/path/to/firefox python tests/browser_e2e/run_browser_e2e.py  # Firefox
scripts/verification/docker_substitute/run_substitute_verification.sh                        # Docker, substitutes
```
The browser script prints `browser under test: <version>` so a run cannot silently fall back to another browser. A negative
control with a nonexistent Firefox path was confirmed to fail.

## 4. Findings and fixes in this phase

| # | Finding | Cause | Fix | Re-verified |
|---|---|---|---|---|
| 1 | OCR test failed after the random remap | The remap rewrote the expected value but not the OCR-damaged input, whose block contains the letter O | Applied the same block mapping to the damaged form in the test and in the doc example | 13 of 13 parser tests; full suites |
| 2 | A damaged real identifier was left in my own report | I quoted it while describing the bug | Removed | Privacy verifier: 0 hits |
| 3 | Docker: migrate crashed with a TypeError | **My substitute PostgreSQL image** initialised SQL_ASCII, so psycopg returned bytes for text. I first called this a project defect; that was wrong. Confirmed with SHOW server_encoding | Substitute image now initialises UTF8, as the official image does | migrate to 0015, 28 of 28 checks |
| 4 | Docker check script failed one assertion | The script expected the public student lookup to return the full name. The app hides names by design (PUBLIC_SHOW_NAMES=false) | The script now asserts the stronger privacy property and reads the full record through the admin list. The application was not changed | 28 of 28 |
| 5 | Browser suite had no Firefox path | Chromium-only launch and one CDP call | BROWSER=firefox option added; Chromium default unchanged | Firefox 262 of 262; Chromium 262 of 262 after the edit |
| 6 | 47 broken documentation references | Runtime paths and stale history | Section 6 and Appendix A | Checker: 0 broken |
| 7 | A bearer-token-shaped value in a historical failure log | pytest printed a test request header | Redacted (see section 5) | Secrets scan: 0 token-shaped strings |

Carried forward from v5 and re-verified: migration 0015 fails closed (an audit-write failure rolls back the whole revision,
legacy records with no usable audit table stop the migration, reruns never duplicate an audit row). Tests that detect the
original defect fail against the original migration.

## 5. Privacy and public-package review

* **Real data stays out of the package.** The operator's allocation data, provenance and correction files, 135 seating-chart
  images and the hall-label review CSV (139 files) are only in the private archive, which is separate and unchanged: all 139
  files are byte-identical to the original upload and every hash matched again at the start of this phase and before the
  private-data runs.
* **Independent synthetic identifiers.** The earlier reversible 92-to-99 prefix change was replaced. Each of the 26 real
  9-digit blocks that appeared in public text now maps to a random block drawn with the secrets module, with uniqueness enforced
  and no collision with any existing block. Roll suffixes are kept so range expansion still works. The mapping was held in
  memory only and was never written to disk. 445 tokens in 26 files were rewritten.
* **Verification (the verifier needs the private data to know what is real, so it is not shipped).** Over every file in the package
  (text, the one SQLite fixture read cell by cell and as raw bytes, PDF streams): 0 real identifiers, 0 real 9-digit blocks,
  0 identifiers that reverse to a real one, 0 letter-damaged variants. There are 0 image or PDF files in the package.
* **Original synthetic fixtures.** 32 original synthetic identifiers, 220 occurrences: all 220 are identical to the original
  tree. All 32, and all 246 new tokens, are accepted by the application's register-number validator. No collisions.
* **Residual caveat.** The public identifiers keep the shape of real ones (12 digits, block plus 3-digit roll). The mapping is
  random and unrecoverable from the package, but fixtures that resemble real numbers are still resemblance, not anonymity.
* **Secrets.** No credentials, env files, private keys, certificates or secret literals in the package. One finding: a
  historical failure log from an early build (docs/test_results_final) contained a bearer-token-shaped value that pytest had
  printed in a request-header dump. The value was a header, a payload whose middle pytest had elided, and a complete
  signature, minted by a test app with a throwaway key, so it could not be replayed. It was **redacted** anyway; nothing else
  in that log changed. The Docker verification generates random secrets in
  a scratch copy; a scan of every container and step log for the admin password, the database password and the signing key found
  0 occurrences.
* **Superseded v5 package.** The v5 ZIP (SHA-256 beginning a34b9ae5) contained the old reversible pseudonyms and was withdrawn:
  it was moved out of the deliverables folder, not deleted and not distributed.

## 6. Documentation references (the 47)

All 47 references are resolved, and no documentation was deleted. 37 point at files the software or the operator creates at
install, run or build time. They are listed with their creator in docs/GENERATED_AND_OPERATOR_FILES.md, and the checker confirms
on every run that each creator still contains the stated code. 10 were stale or historical mentions and were reworded to say
accurately what the release contains. The checker (Markdown links plus backticked repository paths) reports 0 broken references
on the extracted package. Appendix A has every item.

## 7. Removed files (confirmed obsolete)

Removed only when nothing live referenced them: the Windows stub guide, the v4 validation report (superseded), two progress
notes and three JUnit result files from earlier builds, plus the operator-data files listed in section 5. Historical reports
were kept and carry a banner pointing here.

## 8. Windows (static only; nothing executed)

Fifteen batch files were linted: labels and referenced paths resolve or are created by the script, every app.cli subcommand
they call exists, and every .bat and .ps1 is CRLF. The two PowerShell scripts parse with 0 errors under PowerShell 7.4.6. This
proves syntax and consistency only. **Installation, startup, login, CRUD and shutdown on Windows were not tested.**

## 9. Docker (partially verified)

**What ran.** The project's real docker-compose.yml and backend/Dockerfile, with only the FROM line of a scratch copy of the
Dockerfile changed (the diff is printed by the driver). The pinned images in the shipped files are unchanged. Substitutes are
labelled substitute=true, official=false and named local-substitute/...: Ubuntu Python 3.12.3 for python:3.12-slim, Ubuntu
PostgreSQL 16 for postgres:16-alpine, Ubuntu nginx 1.24 for nginx:1.27-alpine.

**Documented procedure, run from the extracted ZIP, every step exit 0:** compose config; build (all 10 Dockerfile steps,
including the Tesseract install and the pip install); run check-config ("Configuration OK"); run migrate ("Database is at
revision 0015", 47 tables, UTF8); up -d; the application's own health check reports healthy; exec create-admin; 28 end-to-end
checks through the TLS proxy; application restart; down then up with volumes kept; 2 persistence checks (login and a created
and updated student survive); a scan of all logs for generated secrets (0).

**What the 28 checks cover.** HTTP-to-HTTPS redirect, /api/health and /api/ready, HSTS and nosniff headers, the frontend
served, API docs disabled in production, wrong password refused, unauthenticated request refused, admin login, /api/auth/me,
student create, public lookup hides the name, admin read, update, duplicate refused, announcement create, read, update,
publish and delete with unpublished items hidden from the public, 404 on repeated delete, logout, and token rejected after
logout. The API has no student delete endpoint, so student delete is not tested.

**Not verified.** The official images were never pulled or run. nginx 1.27 and its HTTP/2 directive were not exercised: the
substitute proxy comments out that one line because nginx 1.24 does not know it. Alpine, the official image entrypoints, real
registry pulls, scheduled backups with pg_dump, real certificates and a public hostname were not tested. Reproduce with
scripts/verification/docker_substitute/README.md. Before production, run the procedure in docs/DOCKER.md on a host with
registry access.

## 10. Android (partially verified)

* **Passed:** 25 of 25 pure-Kotlin core unit tests (3 + 8 + 7 + 7), compiled with Kotlin 2.0.21 and run with JUnit 4.13.2 on
  a JRE, outside Gradle. The count equals the number of test annotations in the file.
* **Not run:** the data-layer test (needs OkHttp, Retrofit and coroutines from Maven). Gradle, Google Maven, Maven Central and the
  Android SDK are unreachable here, so **no APK was built, nothing was installed on a device or emulator, and Android-to-API
  connectivity was not tested.** No APK exists.
* **Needed to finish:** a machine with Gradle 8.10.2 access, the Android SDK (compileSdk 35) and Maven access, or an offline
  bundle of them; then android/build_debug.bat, the unit tests, and a device or emulator pointed at a running backend.

## 11. Remaining limitations and what is needed

1. **Windows execution: blocked.** Needs a Windows 10 or 11 host or VM. Follow docs/WINDOWS_INSTALLATION.md and record the checklist.
2. **Docker with official images: blocked.** Needs registry access for python:3.12-slim, postgres:16-alpine and nginx:1.27-alpine.
3. **Android build, APK, install, data-layer tests, API connectivity: blocked.** Needs the Android toolchain and Maven access.
4. **Real SMTP delivery: blocked.** Needs a reachable SMTP server, port and authorised test credentials, supplied through
   environment variables and never committed.
5. **Safari/WebKit: untested.** Needs macOS. No real-device, responsive or accessibility testing was done.
6. Operator-data tests run only where the authorised data exists; they are skipped (with the reason) in the public package.
7. The fixtures resemble real register numbers in shape (section 5).
8. Not tested at production scale or under sustained load.

## 12. Packaged artifact verification

The candidate package (347 hashed files) was extracted to a clean directory and every hash matched its manifest. The suites in
section 3 were run from that extraction; the private-data runs used a second fresh extraction of the same ZIP with the private
data restored. The documentation, privacy and secret checks were repeated on the extraction. The delivered ZIP differs
from the tested candidate only in this report, the new install guide (so the delivered manifest lists 348 hashed files), the
two manifests and, after the secrets re-scan, the one redacted historical log. Two intermediate builds were verified before
this one (the first delivered ZIP had SHA-256 e934ca6addf2397facebda265c871218f6377d0a76c02b98e39cd566fffdcdd1 and was re-tested in full: SQLite
714/677/0/0/37, PostgreSQL 714/697/0/0/17, jsdom 225, Chromium 262, Firefox 262, Docker 0 failed steps). The final ZIP differs
from that one only in the redacted log, this report and the manifests, confirmed by a file-by-file comparison and by repeating
the backend suites on the final extraction. The SHA-256 of the ZIP is in the adjacent file (a file cannot contain its own hash).

## Appendix A. Resolution of all 47 original broken documentation references

| # | Referring file | Referenced target | Resolution |
|---|---|---|---|
| 1 | PHASE_PROGRESS.md | android/local.properties | generated, operator-supplied or build output; creator verified by the checker: developer-supplied SDK path (android/build_debug.bat) |
| 2 | PHASE_PROGRESS.md | backend/.venv | generated, operator-supplied or build output; creator verified by the checker: created by install.bat |
| 3 | PHASE_PROGRESS.md | backend/outbox | generated, operator-supplied or build output; creator verified by the checker: created on first use (backend/app/mailer.py) |
| 4 | PHASE_PROGRESS.md | deploy/nginx.conf | stale or historical: replaced by deploy/nginx.conf.template; reworded as history |
| 5 | README.md | backend/.env | generated, operator-supplied or build output; creator verified by the checker: init-env writes it (backend/app/cli.py) |
| 6 | README.md | backend/.env.production | generated, operator-supplied or build output; creator verified by the checker: operator copies backend/.env.production.example |
| 7 | README.md | backend/.venv | generated, operator-supplied or build output; creator verified by the checker: created by install.bat |
| 8 | android/README.md | android/app/build/outputs/apk/debug/app-debug.apk | generated, operator-supplied or build output; creator verified by the checker: Gradle build output (assembleDebug) |
| 9 | android/README.md | android/app/build/reports/lint-results-debug.html | generated, operator-supplied or build output; creator verified by the checker: Gradle build output (lintDebug) |
| 10 | android/README.md | android/app/build/reports/tests/testDebugUnitTest/index.html | generated, operator-supplied or build output; creator verified by the checker: Gradle build output (testDebugUnitTest) |
| 11 | android/README.md | android/local.properties | generated, operator-supplied or build output; creator verified by the checker: developer-supplied SDK path (android/build_debug.bat) |
| 12 | docs/ARCHITECTURE.md | backend/uploads | generated, operator-supplied or build output; creator verified by the checker: created on first upload (backend/app/routers/docproc.py) |
| 13 | docs/AUDIT_ORIGINAL_INTEGRATION.md | backend/outbox | generated, operator-supplied or build output; creator verified by the checker: created on first use (backend/app/mailer.py) |
| 14 | docs/AUDIT_ORIGINAL_INTEGRATION.md | docs/evidence | stale or historical: evidence folder never in this package; reworded as history |
| 15 | docs/CONFIGURATION.md | backend/.env | generated, operator-supplied or build output; creator verified by the checker: init-env writes it (backend/app/cli.py) |
| 16 | docs/DATABASE.md | backend/exam_monitor.db | generated, operator-supplied or build output; creator verified by the checker: default SQLite file, created by migrate (backend/app/config.py) |
| 17 | docs/DEFECT_FIXES_A_B.md | docs/PATCH_STATUS.md | stale or historical: stale pointer; reworded in docs/DEFECT_FIXES_A_B.md |
| 18 | docs/DELIVERY_REPORT_COMPLETE_FINAL.md | backend/.env | generated, operator-supplied or build output; creator verified by the checker: init-env writes it (backend/app/cli.py) |
| 19 | docs/DELIVERY_REPORT_COMPLETE_FINAL.md | backend/app/static/portal/.patch_main.py | stale or historical: removed developer script; reworded as history |
| 20 | docs/DOCKER.md | backend/.env.production | generated, operator-supplied or build output; creator verified by the checker: operator copies backend/.env.production.example |
| 21 | docs/DOCKER.md | deploy/certs/fullchain.pem | generated, operator-supplied or build output; creator verified by the checker: operator-supplied TLS certificate |
| 22 | docs/DOCKER.md | deploy/certs/privkey.pem | generated, operator-supplied or build output; creator verified by the checker: operator-supplied TLS key |
| 23 | docs/FINAL_RELEASE_NOTES.md | backend/outbox | generated, operator-supplied or build output; creator verified by the checker: created on first use (backend/app/mailer.py) |
| 24 | docs/IMPLEMENTATION_GUIDE.md | backend/uploads | generated, operator-supplied or build output; creator verified by the checker: created on first upload (backend/app/routers/docproc.py) |
| 25 | docs/INSTALLATION.md | backend/.env | generated, operator-supplied or build output; creator verified by the checker: init-env writes it (backend/app/cli.py) |
| 26 | docs/INSTALLATION.md | backend/.venv | generated, operator-supplied or build output; creator verified by the checker: created by install.bat |
| 27 | docs/MIGRATIONS.md | tests/test_phase8_database.py::test_released_migrations_are_byte_for_byte_unchanged | stale or historical: test id, not a path; reworded in docs/MIGRATIONS.md |
| 28 | docs/ORIGINAL_REPO_COMPARISON.md | docs/evidence | stale or historical: evidence folder never in this package; reworded as history |
| 29 | docs/ORIGINAL_REPO_COMPARISON.md | docs/evidence/test_page_1.png | stale or historical: evidence image never in this package; reworded as history |
| 30 | docs/PHASE6_NOTIFICATIONS.md | backend/.env | generated, operator-supplied or build output; creator verified by the checker: init-env writes it (backend/app/cli.py) |
| 31 | docs/PHASE6_NOTIFICATIONS.md | backend/outbox | generated, operator-supplied or build output; creator verified by the checker: created on first use (backend/app/mailer.py) |
| 32 | docs/PHASE82_DATA_MANAGEMENT.md | backend/.env | generated, operator-supplied or build output; creator verified by the checker: init-env writes it (backend/app/cli.py) |
| 33 | docs/PHASE82_DATA_MANAGEMENT.md | backend/backups | generated, operator-supplied or build output; creator verified by the checker: created on first backup (backend/app/data_management.py) |
| 34 | docs/PRODUCTION_DEPLOYMENT.md | backend/.env.production | generated, operator-supplied or build output; creator verified by the checker: operator copies backend/.env.production.example |
| 35 | docs/PRODUCTION_DEPLOYMENT.md | deploy/certs/fullchain.pem | generated, operator-supplied or build output; creator verified by the checker: operator-supplied TLS certificate |
| 36 | docs/PRODUCTION_DEPLOYMENT.md | deploy/certs/privkey.pem | generated, operator-supplied or build output; creator verified by the checker: operator-supplied TLS key |
| 37 | docs/RELEASE_FIXES.md | backend/.env.production | generated, operator-supplied or build output; creator verified by the checker: operator copies backend/.env.production.example |
| 38 | docs/RELEASE_FIXES.md | deploy/nginx.conf | stale or historical: replaced by deploy/nginx.conf.template; reworded as history |
| 39 | docs/RELEASE_PACKAGE.md | backend/.env.production | generated, operator-supplied or build output; creator verified by the checker: operator copies backend/.env.production.example |
| 40 | docs/SECURITY.md | backend/uploads | generated, operator-supplied or build output; creator verified by the checker: created on first upload (backend/app/routers/docproc.py) |
| 41 | docs/TEST_REPORT.md | backend/.env.production | generated, operator-supplied or build output; creator verified by the checker: operator copies backend/.env.production.example |
| 42 | docs/TEST_REPORT.md | deploy/nginx.conf | stale or historical: replaced by deploy/nginx.conf.template; reworded as history |
| 43 | docs/TROUBLESHOOTING_DEPLOYMENT.md | backend/logs/server.err.log | generated, operator-supplied or build output; creator verified by the checker: created by start.bat (log redirection) |
| 44 | docs/TROUBLESHOOTING_DEPLOYMENT.md | deploy/certs/fullchain.pem | generated, operator-supplied or build output; creator verified by the checker: operator-supplied TLS certificate |
| 45 | docs/UPDATE_V2_CHANGES.md | backend/.pytest_cache | stale or historical: cache folder; wording corrected |
| 46 | docs/UPGRADING.md | backend/exam_monitor.db | generated, operator-supplied or build output; creator verified by the checker: default SQLite file, created by migrate (backend/app/config.py) |
| 47 | docs/VSB_ALLOCATION.md | backend/.env | generated, operator-supplied or build output; creator verified by the checker: init-env writes it (backend/app/cli.py) |
