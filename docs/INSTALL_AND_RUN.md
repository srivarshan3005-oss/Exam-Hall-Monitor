# Installation and execution

Status of each path (see `docs/archive/VALIDATION_REPORT_v6.md`): Linux development and the test suites are verified; Docker is
partially verified (substitute images only); Windows is **not verified** (never executed); Android build is **not verified**.

## Windows (not verified on Windows)
1. Install Python 3.12 or newer (64-bit) from python.org with the launcher and PATH options ticked.
2. Unpack the ZIP, then run `install.bat` once (creates the virtual environment, `.env`, the database and the first administrator).
3. Run `start.bat`; open `http://127.0.0.1:8000/` (admin) and `http://127.0.0.1:8000/portal/` (public). Stop with `stop.bat`.
4. `test.bat` runs the backend tests. `backup.bat`, `backup_list.bat` and `restore_backup.bat` manage backups.
Follow `docs/WINDOWS_INSTALLATION.md`, including its checklist, and record what you actually observe.

## Linux or macOS (development)
```sh
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt          # add requirements-postgres.txt for PostgreSQL
python -m app.cli init-env && python -m app.cli check-config
python -m app.cli migrate
EM_ADMIN_PASSWORD='choose-a-strong-password-1' python -m app.cli create-admin --username admin --role super_admin
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Docker (production procedure, official images)
Follow `docs/DOCKER.md` exactly (config, build, check-config, migrate, up -d, create-admin) and `docs/PRODUCTION_DEPLOYMENT.md`.
The shipped files pin `python:3.12-slim`, `postgres:16-alpine` and `nginx:1.27-alpine`. Supply `backend/.env.production` and the
TLS certificate files yourself (they are not in the package).

## Running the tests
```sh
cd backend
python -m pytest tests -p no:cacheprovider -rfE                      # SQLite
TEST_POSTGRES_URL=postgresql://user:pass@127.0.0.1:5432/postgres python -m pytest tests -p no:cacheprovider -rfE
cd tests/e2e_jsdom && npm ci && cd ../.. && python tests/e2e_jsdom/run_e2e.py
cd tests/browser_e2e && npm ci && cd ../.. && python tests/browser_e2e/run_browser_e2e.py                      # Chromium
BROWSER=firefox FIREFOX_PATH=/path/to/firefox python tests/browser_e2e/run_browser_e2e.py                      # Firefox 129+
```
Kotlin core tests without Gradle (JUnit 4 and Kotlin 2.0.21 on a JVM):
```sh
cd android/app/src
kotlinc main/java/com/example/exammonitor/core/*.kt test/java/com/example/exammonitor/CoreLogicTest.kt \
  -cp junit-4.13.2.jar:hamcrest-core.jar -d out
java -cp out:junit-4.13.2.jar:hamcrest-core.jar:kotlin-stdlib.jar org.junit.runner.JUnitCore \
  com.example.exammonitor.TimetableAndNotificationTest com.example.exammonitor.ErrorAndValidationTest \
  com.example.exammonitor.RoleNavigationTest com.example.exammonitor.DataIsolationAndMappingTest
```
The full Android build needs the Android SDK and Gradle: see `android/README.md` and `android/build_debug.bat`.

## Operator-data tests (authorised machine only)
Place the operator's private files as described in `backend/data/original_portal/README.md`, then run
`python -m pytest tests/test_original_import.py tests/test_vsb_verification_enforcement.py tests/test_original_import_real_data.py`
from `backend`. Never add that data to a shared package or repository.

## Docker verification on substitute images (when registries are unreachable)
See `scripts/verification/docker_substitute/README.md`. This verifies the compose wiring only; it does not verify the official images.
