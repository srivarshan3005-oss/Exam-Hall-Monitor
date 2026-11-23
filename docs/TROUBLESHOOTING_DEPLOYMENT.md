# Deployment troubleshooting — Phase 9

| Symptom | Check / remedy |
|---|---|
| Windows `py` missing | Install Python 3.12+ and the Python Launcher. |
| Windows pip install fails | Check DNS, proxy, firewall and rerun `install.bat`; inspect pip's first error. |
| Windows start health timeout | Read `backend/logs/server.err.log`; verify port 8000 and `.env`. |
| `SECRET_KEY` invalid | Generate a new key; preserve it across restarts or existing sessions become invalid. |
| Production CORS/startup refusal | Use explicit HTTPS origins and matching HTTPS `PUBLIC_BASE_URL`. |
| Docker Compose says password unset | Supply `--env-file backend/.env.production`; ensure `POSTGRES_PASSWORD` is set there. |
| Database connection refused | Check `db` health, service logs and compose network; do not expose port 5432 publicly. |
| PostgreSQL auth failure | Confirm `POSTGRES_PASSWORD` is consistent in the app env and Postgres initialisation. Changing the env value does not rotate an already-created database user's password automatically. |
| Nginx certificate error | Verify `deploy/certs/fullchain.pem` and `privkey.pem`, permissions, hostname and certificate chain. |
| HTTP redirect loop / wrong scheme | Confirm Nginx sets `X-Forwarded-Proto https` and `TRUST_PROXY=true` only behind this proxy. |
| Upload returns 413 | Align Nginx `client_max_body_size` with `MAX_UPLOAD_MB`. |
| Migration fails | Stop rollout, preserve the database, inspect migration output and follow `docs/MIGRATIONS.md`. |
| Backup fails for PostgreSQL | Confirm PostgreSQL client utilities are available to the backup process and storage is writable. |
| Container exits on read-only filesystem | Check mounted writable volumes and `/tmp`; do not remove the non-root/read-only hardening as a first response. |

Never delete a database, named volume or backup to clear an error. Capture logs and a verified backup before attempting repair.
