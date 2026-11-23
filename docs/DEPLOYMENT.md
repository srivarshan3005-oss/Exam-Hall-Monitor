# Deployment (V7)

**Two different things, hosted separately:**

| Part | Needs | Where it can run |
|---|---|---|
| **Backend** (FastAPI: monitoring, PDF parsing, database, page images, API, student portal, dashboard) | Python 3.12, writable disk, outbound https to vsbec.edu.in | Windows PC, Linux VPS, Docker |
| **Static frontend** (`backend/app/static/portal/*`) | any static host | the backend serves it itself; a separate static host (e.g. GitHub Pages) would still need `/api/*` from a backend |

**GitHub Pages cannot run the Python backend.** A static host alone cannot search, render page images or monitor anything. The
GitHub *Actions* workflow (`.github/workflows/vsb-monitor.yml`) can run the monitoring cycle on a schedule, keep state, send
e-mail and mirror to Supabase, but it does not serve students. For students you need the backend running somewhere.

## A. Windows (simplest) - see `docs/WINDOWS_INSTALLATION.md`
`install.bat` -> `start.bat` -> `http://127.0.0.1:8000/portal/`. `stop.bat`, `health_check.bat`, `test.bat`.
Reachable from other devices only if you deliberately bind/forward the port; put TLS in front for anything public.

## B. Docker, single container (SQLite)
```
docker compose -f docker-compose.local.yml up --build -d
docker compose -f docker-compose.local.yml exec app python -m app.cli create-admin --username admin
```
Data lives in the `exam_data` volume (database, PDFs, backups, logs).

## C. Docker, production (PostgreSQL + nginx + TLS)
`docker-compose.yml` + `backend/.env.production` + certificates in `deploy/certs/`; see `docs/DOCKER.md` and `docs/PRODUCTION_DEPLOYMENT.md`.

## D. Linux without Docker
```
sudo apt install python3.12 python3.12-venv tesseract-ocr
cd backend && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m app.cli init-env && .venv/bin/python -m app.cli migrate
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers   # behind nginx/Caddy with TLS
```
Run it under systemd (`Restart=always`). The scheduler runs inside this process.

## E. GitHub Actions monitor (optional)
Repository secrets: `SECRET_KEY` (required), optionally `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SMTP_*`. Workflow: cron every
15 min + manual dispatch, Python 3.12 with pip cache, Tesseract install, state restored/saved with `actions/cache`, failure ->
log artifact + one open issue. Not verified by running on GitHub from this environment (see Known limitations).

## Backups
`backup.bat` / `python -m app.cli backup` (database + documents), `restore_backup.bat` / `python -m app.cli restore-backup <zip>`; details in `docs/BACKUP_RECOVERY.md`. PostgreSQL: `pg_dump`.
