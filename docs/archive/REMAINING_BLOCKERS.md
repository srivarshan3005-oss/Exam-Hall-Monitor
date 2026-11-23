# Remaining blockers (final public release)

**Release verdict: release candidate with blockers. Not production ready.** Four validation areas could not be executed in the
verification environment (Ubuntu 24.04 Linux, no Windows host, no Docker, no Android SDK, no authorised SMTP account). They are
**BLOCKED**, not passed. Nothing here is claimed as verified. Status words: PASS = executed with evidence; BLOCKED = the required
environment, access or credentials were unavailable; NOT TESTED = not executed.

Evidence to send back for every task: the exact command, its console output, the exit code, and the date and machine
(Windows build number, Docker version, and so on). Never send passwords, tokens, keystores or SMTP credentials.

| # | Task | Status | Blocks production readiness |
|---|---|---|---|
| 1 | Windows install, start, shutdown, restart | BLOCKED | Yes |
| 2 | Official Docker images (runtime) | BLOCKED | Yes |
| 3 | Android debug APK build and device checks | BLOCKED | Yes, for the Android app only |
| 4 | Real SMTP delivery | BLOCKED | Yes, if e-mail delivery is required |
| 5 | Safari/WebKit, real devices, load testing | NOT TESTED | Recommended before wide use |

## 1. Windows (BLOCKED)

**Why:** no Windows 10/11 host or VM exists in the verification environment. The 15 batch files and 2 PowerShell scripts were only
parsed and linted (all CRLF, 0 parse errors). Nothing was executed on Windows.

**Needs:** Windows 10 or 11, Python 3.12 or newer from python.org (the Microsoft Store stub does not count), network access to PyPI.

**Two unconfirmed risks found by reading the scripts. No code was changed, because they cannot be confirmed without Windows:**

* **Hard-kill shutdown.** `stop.bat` calls `scripts/managed_server.ps1`, which ends the server with `taskkill /T /F`. That is a forced
  termination, so uvicorn does not run its normal shutdown and in-flight work or a SQLite write could be cut off. Confirm whether this
  causes any data or integrity problem (steps 6 to 8 below).
* **Apostrophe in the install path.** `start.bat` builds a PowerShell command with single-quoted paths taken from the current
  folder. A folder name containing an apostrophe (for example `C:\Users\O'Brien\ExamMonitor`) may break that command. Confirm in step 10.

**Commands (Windows PowerShell, from a folder whose path has no apostrophe):**

```powershell
cd C:\ExamMonitor\Exam_Monitor_Ultimate_VSB_KARUR_FINAL_PUBLIC_RELEASE
# 1. Install (answer the wizard prompts, create the admin when asked)
.\install.bat ; "install exit code: $LASTEXITCODE"
# 2. Python actually used and dependency install result
.\backend\.venv\Scripts\python.exe --version
.\backend\.venv\Scripts\python.exe -m pip check
# 3. Start
.\start.bat ; "start exit code: $LASTEXITCODE"
# 4. Health and migrations
(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/ready).StatusCode
cd backend ; .\.venv\Scripts\python.exe -m app.cli db-audit ; cd ..
# 5. Sign in at http://127.0.0.1:8000 with the admin you created; create and read back one record.
# 6. Record the server process, then stop
$id = Get-Content backend\.run.pid
Get-CimInstance Win32_Process -Filter "ProcessId=$id" | Select-Object Name, CommandLine
.\stop.bat ; "stop exit code: $LASTEXITCODE"
# 7. Confirm it is really down and see how it ended
Get-Process -Id $id -ErrorAction SilentlyContinue
try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/ready -TimeoutSec 3 } catch { "port closed: OK" }
Get-Content backend\logs\server.err.log -Tail 30
# 8. Integrity after the forced stop, then restart and sign in again
cd backend ; .\.venv\Scripts\python.exe -m app.cli db-audit ; cd ..
.\start.bat
(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/ready).StatusCode
.\stop.bat
# 9. Stale PID file: running stop.bat again must stop nothing and exit 0
.\stop.bat
```

```powershell
# 10. Apostrophe path (run only after steps 1 to 9 pass in the normal path)
Copy-Item -Recurse C:\ExamMonitor\Exam_Monitor_Ultimate_VSB_KARUR_FINAL_PUBLIC_RELEASE "C:\Test'Dir\App"
cd "C:\Test'Dir\App"
.\install.bat ; .\start.bat ; "start exit code: $LASTEXITCODE"
```

**Expected on success:** install, start and stop exit 0; `/api/ready` returns 200; `db-audit` reports no issues before and after the
forced stop; the second start and sign-in work with the earlier data present; `stop.bat` leaves no process and a closed port. For step 10,
record the result either way: if `start.bat` fails with a PowerShell parse error, that is a confirmed defect to fix.
**Python 3.14:** the verified lock file is for Python 3.12. If `py -3` resolves to 3.14, `pip check` and the install in step 2 show whether the
dependencies install there.

## 2. Official Docker images (BLOCKED)

**Why:** Docker and the container registries are unavailable here. The earlier 28 end-to-end checks ran on **local substitute images**
(Ubuntu-based Python 3.12.3, PostgreSQL 16, nginx 1.24) and are historical results; they do not show that the official images work.
Compose YAML was only parsed statically (the proxy now waits for `app` to be healthy); no container was started. The documented PostgreSQL
backup and restore procedure in `docs/DOCKER.md` has **not** been executed.

**Needs:** Docker Engine with Compose v2 and access to Docker Hub for `python:3.12-slim`, `postgres:16-alpine` and `nginx:1.27-alpine`.
The images are pinned by tag, not by digest; record the digests you tested.

```sh
cp backend/.env.production.example backend/.env.production      # edit: DOMAIN_NAME, POSTGRES_PASSWORD, SECRET_KEY (never commit)
mkdir -p deploy/certs                                          # test certificate only; use a real one in production
openssl req -x509 -nodes -newkey rsa:2048 -days 7 -keyout deploy/certs/privkey.pem -out deploy/certs/fullchain.pem -subj "/CN=localhost"
E="--env-file backend/.env.production"
docker compose $E config
docker compose $E build
docker compose $E run --rm app python -m app.cli check-config
docker compose $E run --rm app python -m app.cli migrate
docker compose $E up -d
docker compose $E ps                                           # db, app and proxy should all become healthy/running
docker compose $E exec app python -m app.cli create-admin --username <admin-name> --role super_admin
curl -k https://localhost/api/ready
docker compose $E restart app && docker compose $E ps
docker compose $E down && docker compose $E up -d              # volumes kept; data must survive
docker compose $E logs | grep -i -E "password|secret|token"    # expect no secret values
docker image inspect --format '{{index .RepoDigests 0}}' postgres:16-alpine nginx:1.27-alpine python:3.12-slim
```

Then run the backup, check and restore commands from `docs/DOCKER.md` against a scratch deployment.
**Expected:** every command exits 0; `ps` shows `db` and `app` healthy with `proxy` started only after `app` is healthy; `/api/ready`
returns 200 over HTTPS; data created before `down` is present after `up`; the dump lists with `pg_restore --list`; after the restore `migrate`
reports the database current and `db-audit` reports no issues; the log search shows no secret values.
**Evidence:** the output of each command, the `docker version` and `docker compose version` output, and the three image digests.

## 3. Android APK build and device checks (BLOCKED)

**Why:** the Android SDK, Gradle distribution and Maven repositories are unreachable here. The 25 pure-Kotlin core tests passed earlier
(historical, run outside Gradle on a plain JVM). No Gradle build ran, no APK exists, the data-layer test did not run, and nothing was installed
on a device or emulator.

**Needs:** JDK 17 or newer, Android SDK platform 35 with build-tools and platform-tools, Internet access to `services.gradle.org`,
Google Maven and Maven Central (the wrapper downloads Gradle 8.10.2; the project uses Android Gradle Plugin 8.7.3 and Kotlin 2.0.21),
and an emulator or device. Put the SDK path in `android/local.properties` (`sdk.dir=...`).

```powershell
# Windows
cd android
.\gradlew.bat --version
.\gradlew.bat testDebugUnitTest
.\gradlew.bat assembleDebug
.\gradlew.bat lintDebug
dir app\build\outputs\apk\debug\app-debug.apk
adb install -r app\build\outputs\apk\debug\app-debug.apk
```

```sh
# Linux or macOS
cd android && ./gradlew --version && ./gradlew testDebugUnitTest assembleDebug lintDebug
ls -l app/build/outputs/apk/debug/app-debug.apk
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Run the backend locally (`start.bat` or the Linux equivalent). The debug build defaults to `http://10.0.2.2:8000/`, which is the host from an
Android emulator; on a physical device pass `-PAPI_BASE_URL=http://<your-LAN-IP>:8000/`.
**Expected:** all Gradle tasks end with BUILD SUCCESSFUL, the unit tests (including the data-layer test) pass, the APK file exists and installs,
the app starts, signs in against the running backend, and the main screens load without runtime errors in `adb logcat`.
**Evidence:** the full Gradle output, the APK size and SHA-256, `adb logcat` excerpts, and screenshots of sign-in and one data screen.
Release signing (the four `RELEASE_*` inputs and an HTTPS `API_BASE_URL`) is a separate, later step and was not exercised.

## 4. Real SMTP delivery (BLOCKED)

**Why:** outbound SMTP is closed in the verification environment and no authorised account was supplied. All e-mail tests used a local
in-process `aiosmtpd` server, so they prove the application's behaviour (success only after the server accepts, authentication failure,
TLS failure, timeout, refused recipient, retries, no credentials in logs) and **not** delivery through a real provider.

**Needs:** a reachable SMTP server, port and an account you are authorised to use, plus one mailbox you can read. Put the values in
`backend/.env` (or `backend/.env.production`), never in source control: `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY` (`starttls` or `ssl`),
`SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`. Gmail and Office 365 need an app password or SMTP AUTH enabled.

1. Run `python -m app.cli check-config` from the `backend` folder. Expect no PROBLEM line, and no warning about `SMTP_SECURITY`.
2. Start the application, sign in as an administrator, open **Communications**, and send a test e-mail to your own address.
3. Confirm the message arrives (check the spam folder and the message headers) and the delivery log shows status `sent`.
4. Repeat once with a deliberately wrong password and confirm the status is a failure (`auth_failed`), not `sent`.
5. Search `backend/logs/` and the console output for your password and user name; expect none.

**Expected:** the test message arrives; the delivery log row reads `sent`; the wrong-password attempt fails clearly; no credentials appear in logs.
Note: `SMTP_TIMEOUT_SECONDS` is a per-socket-operation timeout, not a total deadline (see `docs/PHASE6_NOTIFICATIONS.md`), so an unresponsive server can hold an
inline request open for longer than that value.

## 5. Other untested areas (not release-blocking by themselves)

* Safari/WebKit and real mobile devices, responsive layout and accessibility audits: NOT TESTED.
* Sustained load and production-scale data: NOT TESTED.
* Operator-data tests need the operator's private dataset, which is intentionally not in this package. They are skipped here with the reason
  printed, and they passed in earlier runs where that data was present (historical).
* The synthetic register numbers keep the shape of real ones (12 digits); the mapping is random and not recoverable from the package.
