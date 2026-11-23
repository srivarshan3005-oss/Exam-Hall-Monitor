# Installation guide

## Windows

Use Windows 10/11 with Python 3.12+ and the Python launcher (`py`). Run `install.bat` from the extracted project root. It creates `backend/.venv`, installs the pinned/ranged backend dependencies, creates local configuration if absent, applies migrations and interactively creates an administrator account. Start with `start.bat`. Details, process-safety rules and verification status: [WINDOWS_INSTALLATION.md](WINDOWS_INSTALLATION.md).

The app binds to `127.0.0.1:8000` by default. This is a local development/single-machine setup, not an internet-facing production deployment.

## Android source

The Android project is under `android/`. Open it in a compatible Android Studio/Gradle environment with Android SDK 35 and build tools. The Gradle wrapper (8.10.2) is included. See `android/README.md` for build, API configuration and testing. The app has not been compiled in the authoring environment.

## Optional OCR

See [OCR.md](OCR.md). Tesseract is a separate native dependency and is not installed by the standard installer.

## Linux / macOS
See the README "Install and start" section for the exact commands (venv, `pip install -r requirements.txt`, `.env` with a generated `SECRET_KEY`, `python -m app.cli migrate`, `python -m app.cli create-admin`, `uvicorn app.main:app`).

## Front-end tests (optional)
Backend/contract tests: `cd backend && python -m pytest`. DOM-level UI test: `cd backend/tests/e2e_jsdom && npm install`, then from `backend/` run `python tests/e2e_jsdom/run_e2e.py` (uses a temporary database and a temporary server on port 8765).

## V.S.B. Engineering College, Karur
After installation set `COLLEGE_NAME` in `backend/.env`, then follow the quick start in the README (VSB official notices → process PDFs → VSB allocation → approve → publish).
Docker deployments must always pass `--env-file backend/.env.production` to `docker compose` (see [DOCKER.md](DOCKER.md)).
