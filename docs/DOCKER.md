# Docker and Compose guide — Phase 9

## Files
- `backend/Dockerfile`: Python 3.12 slim image, PostgreSQL driver, Tesseract OCR binary, non-root runtime, health check.
- `docker-compose.yml`: PostgreSQL 16, API, Nginx TLS proxy and persistent named volumes.
- `deploy/nginx.conf.template`: HTTP-to-HTTPS redirect, TLS 1.2/1.3, HSTS and security headers, upload size limit. The `${DOMAIN_NAME}` variable is rendered by the nginx image (`NGINX_ENVSUBST_FILTER=DOMAIN_NAME` so nginx's own `$variables` are untouched).
- `backend/.env.production.example`: production configuration template.

## First start (new deployment)
The application refuses to start on an un-migrated database (`assert_database_current`), so run the schema step **before** `up -d`:
```sh
docker compose --env-file backend/.env.production config
docker compose --env-file backend/.env.production build
docker compose --env-file backend/.env.production run --rm app python -m app.cli check-config
docker compose --env-file backend/.env.production run --rm app python -m app.cli migrate
docker compose --env-file backend/.env.production up -d
docker compose --env-file backend/.env.production exec app python -m app.cli create-admin --username <admin-name> --role super_admin
```
The full walk-through (secrets, TLS, updates) is in [production deployment](PRODUCTION_DEPLOYMENT.md).

## Commands
Always pass the production env file explicitly:
```sh
docker compose --env-file backend/.env.production config
docker compose --env-file backend/.env.production up -d --build   # only after the migrate step above has succeeded
docker compose --env-file backend/.env.production ps
docker compose --env-file backend/.env.production logs -f app
docker compose --env-file backend/.env.production down
```
`down` preserves named volumes. Never use `down -v` unless intentionally destroying all persistent database, upload and backup data.

## Health and logs
Docker health check calls `/api/ready`. The `proxy` service starts only after `app` reports healthy (`depends_on` with `condition: service_healthy`), so Nginx is not up before the application is ready. Logs go to stdout/stderr and Docker's bounded `json-file` log driver (10 MB × 5 files per service). Inspect with `docker compose ... logs`.

## TLS
Nginx will not start until `deploy/certs/fullchain.pem` and `deploy/certs/privkey.pem` exist. The `.gitkeep` placeholder is the only file shipped there.
The host name comes from `DOMAIN_NAME` in `backend/.env.production`; Compose refuses to start without it. Do not publish the service before the certificate for that name is installed and tested (`openssl s_client -connect <domain>:443 -servername <domain>`).

## Scheduled backups are off by default in Compose
`BACKUP_SCHEDULE_ENABLED` defaults to `false` in `docker-compose.yml`. PostgreSQL backups call `pg_dump`, which is **not** installed in the
application image (the image carries only the Python driver), so an enabled schedule would fail on every cycle. Take backups with a
`pg_dump` of matching major version 16 from the host or a maintenance container, or add a matching client to your own image and then set
`BACKUP_SCHEDULE_ENABLED=true` in `backend/.env.production`. Until then, the application-level `backup` CLI is not a working PostgreSQL backup
in this image; see [backup and recovery](BACKUP_RECOVERY.md).

## PostgreSQL backup and restore (documented procedure, NOT yet executed in Docker)
> **Status:** these commands have not been run against the official `postgres:16-alpine` image or any Docker stack by the maintainers.
> Treat them as the procedure to verify, then record the result: take a backup, restore it into a **scratch** deployment, and
> confirm `db-audit` and a login before relying on it. The application-level `backup` CLI is not a working PostgreSQL backup in this image (see above).

Run from the repository root with the stack up. The `db` container already has the matching PostgreSQL 16 client tools, so no image change is needed.
The dump is written inside the container and copied out with `docker compose cp`, which avoids shell redirection (PowerShell 5.1 corrupts binary output sent through `>`).
```sh
# Backup (custom format; the file contains student data, so store it encrypted and access-controlled, never in the repository)
docker compose --env-file backend/.env.production exec -T db pg_dump -U exam_monitor -d exam_monitor --format=custom --file=/tmp/exam_monitor.dump
docker compose --env-file backend/.env.production cp db:/tmp/exam_monitor.dump ./exam_monitor-YYYYMMDD.dump
docker compose --env-file backend/.env.production exec -T db rm /tmp/exam_monitor.dump
```
```sh
# Check that the dump is readable (lists its contents; does not change anything)
docker compose --env-file backend/.env.production cp ./exam_monitor-YYYYMMDD.dump db:/tmp/check.dump
docker compose --env-file backend/.env.production exec -T db pg_restore --list /tmp/check.dump
docker compose --env-file backend/.env.production exec -T db rm /tmp/check.dump
```
```sh
# Restore (replaces the current database contents: take a fresh backup first, and keep the previous dump)
docker compose --env-file backend/.env.production stop proxy app
docker compose --env-file backend/.env.production cp ./exam_monitor-YYYYMMDD.dump db:/tmp/restore.dump
docker compose --env-file backend/.env.production exec -T db pg_restore -U exam_monitor -d exam_monitor --clean --if-exists --no-owner /tmp/restore.dump
docker compose --env-file backend/.env.production exec -T db rm /tmp/restore.dump
docker compose --env-file backend/.env.production run --rm app python -m app.cli migrate
docker compose --env-file backend/.env.production run --rm app python -m app.cli db-audit
docker compose --env-file backend/.env.production up -d
```
Expected result: `pg_dump` and `pg_restore` exit 0, `migrate` reports the database is current, `db-audit` reports no issues, and an administrator can sign in
with the previously created data present. `pg_restore --clean` may print warnings about objects that did not exist; any **error** means the restore is not trustworthy.
The `app_uploads` volume (private uploaded documents) is **not** part of the database dump and must be backed up separately (see the volume inventory below).

## Volume inventory
- `postgres_data`: PostgreSQL database files.
- `app_uploads`: private uploaded documents.
- `app_backups`: application backup archives.

Back up volumes independently as part of host-level disaster recovery. Application backup archives are stored at `/app/backups`.

## Environment-driven settings (nothing is hard-coded)
| Variable (in `backend/.env.production`) | Used for |
|---|---|
| `DOMAIN_NAME` | Nginx `server_name`, `PUBLIC_BASE_URL`, `CORS_ORIGINS` (Compose builds them) |
| `POSTGRES_PASSWORD` | PostgreSQL password and the application `DATABASE_URL` (letters/digits only) |
| `SECRET_KEY` | Token signing; `check-config` rejects short, low-variety or placeholder keys |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Activation / reset / notification e-mail (warning only if empty) |

`python -m app.cli check-config` in production also fails if `PUBLIC_BASE_URL`, `CORS_ORIGINS` or `DATABASE_URL` still contain example placeholders.
Status (see `docs/archive/VALIDATION_REPORT_v6.md`): `docker compose config`, `build`, `run ... check-config`, `run ... migrate`, `up -d`, `exec ... create-admin`, the health checks, the TLS proxy, login, create/read/update/delete, restart and `down`/`up` with volumes kept were all run end to end, **but on local substitute base images** (Ubuntu-based stand-ins for `python:3.12-slim`, `postgres:16-alpine` and `nginx:1.27-alpine`), because the container registries were unreachable. The pinned official images themselves were **not** pulled or run, so this is partial verification. Reproduce it with `scripts/verification/docker_substitute/README.md`; the production procedure above is unchanged and still pins the official images.
