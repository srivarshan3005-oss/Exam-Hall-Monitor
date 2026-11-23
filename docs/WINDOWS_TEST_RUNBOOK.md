# Runtime test runbook for Windows 10/11 (run these yourself)

Nothing in this runbook has been executed by the package author. Record what you actually see; do not paste "PASS" for a step you skipped.
Use **Command Prompt** (cmd.exe), not PowerShell, unless a step says otherwise. Use a path with a space (for example `C:\Exam Monitor Test`) for at least one run: the scripts are meant to cope with it.

## 0. Prerequisites
* Python 3.12 or newer from python.org (tick "Add python.exe to PATH" or have the `py` launcher): `py -3.12 --version`
* For Android only: JDK 17+ (`java -version`), Android SDK with platform 35 and build-tools, and internet on the first Gradle run.
* Optional (OCR tests need it): Tesseract (`docs/OCR.md`). Without it, OCR-dependent tests report failures/skips; note them, do not hide them.

## 1. Full backend suite (required before calling this a release)
```bat
cd /d "C:\Exam Monitor Test\backend"
py -3.12 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -rsx -p no:cacheprovider --junitxml=..\docs\archive/test_results_final\BACKEND_FULL_RUN.xml > ..\docs\archive/test_results_final\backend_full_run.txt 2>&1
echo exit code %ERRORLEVEL%
```
Report: Python version, total passed / failed / skipped (from the last line of `backend_full_run.txt`), every failure, every skip and why.
Zero skips is the goal; each skip must have a stated, legitimate reason (for example PostgreSQL not configured).
Run the new file on its own first if you want a quick signal: `python -m pytest tests\test_vsb_verification_enforcement.py -v`.
If a new test fails, send me the traceback; the likely causes are a wrong assumption in the test or a real defect, and I will not guess which without the output.

Migration checks (also covered by `tests\test_migrations.py`):
```bat
set DATABASE_URL=sqlite:///./fresh_check.db
python -m app.cli migrate
python -c "import sqlalchemy as sa; e=sa.create_engine('sqlite:///./fresh_check.db'); print([r[0] for r in e.connect().execute(sa.text('select version_num from alembic_version'))])"
```
Expected head: `['0015']`. For an upgrade test, restore a database made by the earlier release, run `python -m app.cli migrate`, and confirm `vsb_alloc_records.verification_status` exists. Delete `fresh_check.db` afterwards.

## 2. Clean Windows installation
1. Extract the ZIP to a new folder, for example `C:\Exam Monitor Test`.
2. `install.bat` — expect: Python found, venv created, dependencies installed, secret generated, migrations applied, administrator prompt. Choose a strong password (never one from a document).
3. `start.bat` — expect the launcher to report `/api/ready` OK. Open http://127.0.0.1:8000
4. `curl http://127.0.0.1:8000/api/ready` and `curl http://127.0.0.1:8000/api/health`
5. Log in as the administrator. Create a staff, an invigilator and a student account (the student linked to a student record). Log in as each and open the dashboard; confirm a student cannot open admin pages or other students' data.
6. `stop.bat`, confirm the port is free (`netstat -ano | findstr :8000`), `start.bat` again, confirm it comes back and your data is still there.
7. Port clash: start something on 8000 first and confirm `start.bat` fails with a readable message.
Write down PASS/FAIL for each numbered step and the exact error text for any failure.

## 3. VSB allocation workflow on real data (administrator, in the web UI or via `/docs` if `ENABLE_DOCS=true`)
1. Import `backend\data\original_portal\source\allotments.json` with `POST /api/vsb-allocation/import/original` — first dry run, then `dry_run=false&confirm=true`.
2. Expected staged totals: 3,306 records; by status **627 FULLY_VERIFIED** (17 Nov AN), **1,159 HALL_LIST_CONFIRMED** (17 Nov FN 904 + 18 Nov 255), **1,520 UNRESOLVED** (16 Nov).
3. Try to approve a HALL_LIST_CONFIRMED and an UNRESOLVED record (with and without acknowledgement): both must be refused. Bulk-approve the batch: only FULLY_VERIFIED, flag-free, student-linked records may be approved.
4. Open register `992696352264`: it should show `provenance_correction` (MB III 206 → MB III A04, seat 28) and still carry the `hall_mismatch` flag from the unchanged mirror data.
5. Edit one critical field of a FULLY_VERIFIED record; its status must become UNRESOLVED and the approval must be cleared.
6. Publish a batch; confirm only approved + verified records are visible to the matching student and that the public lookup shows no other register numbers.
7. Check the audit history shows every step above.

## 4. Android (from `android\`)
```bat
cd /d "C:\Exam Monitor Test\android"
echo sdk.dir=<user-profile>%USERNAME%\\AppData\\Local\\Android\\Sdk> local.properties
gradlew.bat --version
gradlew.bat tasks
gradlew.bat testDebugUnitTest
gradlew.bat assembleDebug
dir app\build\outputs\apk\debug\app-debug.apk
```
or simply `build_debug.bat` (runs clean, unit tests, assembleDebug, lintDebug, prints APK size and SHA-256).
Debug builds default to `http://10.0.2.2:8000/`, which is the Android **emulator's** alias for your PC, so the emulator can reach `start.bat`'s server directly. A physical device cannot use that address, and the build script rejects any non-HTTPS `API_BASE_URL`, so testing on a real device needs an HTTPS backend URL (`-PAPI_BASE_URL=https://...`).
Release (needs your own HTTPS backend URL and, optionally, all four signing inputs):
```bat
gradlew.bat assembleRelease -PAPI_BASE_URL=https://your-host/ -PRELEASE_STORE_FILE=C:\keys\release.jks -PRELEASE_STORE_PASSWORD=*** -PRELEASE_KEY_ALIAS=*** -PRELEASE_KEY_PASSWORD=***
```
Never commit the keystore or passwords. Report: Gradle version (expected 8.10.2), AGP (declared 8.7.3), Kotlin (declared 2.0.21), compileSdk/targetSdk 35, minSdk 26, application ID `com.example.exammonitor`, the build result and the APK path/size.
Install on an emulator/device with `adb install -r app\build\outputs\apk\debug\app-debug.apk`, then log in as a student and as staff and note the result. A build alone does not prove runtime behaviour.

## 5. What to send back
The three result files from `docs\archive/test_results_final\`, the failing tracebacks (if any), the step-by-step PASS/FAIL list for sections 2–4, and the APK path and size. With that I can fix real failures and produce a release whose verification statements are backed by your runs.
