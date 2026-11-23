# Production deployment — Phase 9

This is a deployment recipe, not evidence that a production server has been provisioned. Adapt the hostname, SMTP, firewall, DNS, TLS certificate and operational retention policy to the institution.

## Architecture
Internet → Nginx TLS reverse proxy → private FastAPI container → PostgreSQL 16. PostgreSQL data, uploaded documents and verified backups use separate named Docker volumes. The API container runs as an unprivileged user, drops Linux capabilities, uses a read-only root filesystem, and is not published directly to the host.

## Prepare secrets and TLS
1. Install Docker Engine with the Compose plugin on a supported Linux host.
2. Point DNS `A`/`AAAA` records for your hostname to the server.
3. Create `backend/.env.production` from `backend/.env.production.example`.
4. Generate unique secrets (example: `openssl rand -hex 32` for the PostgreSQL password; use `python -c "import secrets; print(secrets.token_urlsafe(48))"` for `SECRET_KEY`). Set both values only in the untracked production env file. Avoid punctuation in the PostgreSQL password unless URL-encoding it in `DATABASE_URL`.
5. Set `COLLEGE_NAME` and `DOMAIN_NAME` (host name only, e.g. `exams.yourcollege.edu`; Compose derives `PUBLIC_BASE_URL`, `CORS_ORIGINS` and the Nginx host from it). Fill the `SMTP_*` values if e-mail is needed. Keep `SEED_DEMO=false`, `ENABLE_DOCS=false`, and `ALLOW_SELF_REGISTRATION=false` unless the institution explicitly approves otherwise.
6. Install a valid TLS certificate and private key as `deploy/certs/fullchain.pem` and `deploy/certs/privkey.pem` (restrict the key to root/administrators). `deploy/nginx.conf.template` is rendered by the Nginx image from `DOMAIN_NAME`; nothing in it is edited by hand.

## Launch
From the repository root:
```sh
docker compose --env-file backend/.env.production config
docker compose --env-file backend/.env.production build
docker compose --env-file backend/.env.production run --rm app python -m app.cli check-config   # must print 'Configuration OK'; it rejects placeholder values
docker compose --env-file backend/.env.production run --rm app python -m app.cli migrate
docker compose --env-file backend/.env.production up -d
docker compose --env-file backend/.env.production ps
docker compose --env-file backend/.env.production logs --tail=150 app proxy db
```
Create the first administrator interactively:
```sh
docker compose --env-file backend/.env.production exec app python -m app.cli create-admin --username <admin-name> --role super_admin
```
The CLI prompts for the password; do not place it in shell history or environment variables.

## HTTPS and network controls
Only Nginx publishes ports 80/443. Restrict SSH and management access at the host firewall. Do not expose PostgreSQL port 5432 or the application port 8000. The proxy sets forwarded headers and `TRUST_PROXY=true` is enabled only because the proxy is part of this deployment. Do not enable proxy trust behind an uncontrolled proxy.

## Persistent storage and backups
Named volumes: `postgres_data`, `app_uploads`, `app_backups`. Do not use `docker compose down -v` on a production installation; `-v` deletes persistent volumes. The application backup CLI needs `pg_dump` (PostgreSQL 16 client), which the supplied app image does **not** contain, and `BACKUP_SCHEDULE_ENABLED` is therefore `false` by default (see [Docker guide](DOCKER.md)). Once a matching `pg_dump` is available to the container, run a verified application backup:
```sh
docker compose --env-file backend/.env.production exec app python -m app.cli backup
docker compose --env-file backend/.env.production exec app python -m app.cli backup-list
```
Export backups off-host and encrypt them at rest. A backup on the same server is not a disaster-recovery copy.

## Updates
1. Take and copy off-host a verified backup.
2. Pull/copy the reviewed release and rebuild: `docker compose ... build app`.
3. Run `docker compose ... run --rm app python -m app.cli migrate`.
4. Recreate: `docker compose ... up -d`.
5. Check `ps`, `/api/ready`, logs and the administrator's key workflows.

## Recovery
Stop application and proxy containers; retain the PostgreSQL volume. Restore through the documented Phase 8.2 CLI workflow using a controlled maintenance procedure and a verified backup. For PostgreSQL, ensure compatible `pg_dump`/`pg_restore` client tools are available in the maintenance environment. Restore is intentionally not exposed as a live HTTP endpoint. Validate `db-audit` and `/api/ready` before reopening access.
