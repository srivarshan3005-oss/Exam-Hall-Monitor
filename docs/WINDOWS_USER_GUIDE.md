# Windows operator guide — Phase 9

## Daily use
- Start: double-click `start.bat`.
- Browse: `http://127.0.0.1:8000`.
- Stop: double-click `stop.bat`.
- The app binds to loopback (`127.0.0.1`); it is not exposed to the LAN by the Windows launcher.
- Logs: `backend\logs\server.out.log` and `backend\logs\server.err.log`.

## Health checks
Open `http://127.0.0.1:8000/api/health` for process health and `/api/ready` for database readiness. The start script waits for readiness and stops a failed startup process.

## Backups
Run `backup.bat` or `cd backend && .venv\Scripts\python.exe -m app.cli backup`. Keep copies outside the computer and periodically verify restore procedures using a separate test environment. Never test restore against the only live copy.

## Safe shutdown and updates
Stop the application before replacing files or restoring a backup. Preserve `backend\.env`, database files, `backend\uploads`, and `backend\backups`. Extract updates over a separate staging copy first; do not overwrite runtime data. Run migrations after making a verified backup.
