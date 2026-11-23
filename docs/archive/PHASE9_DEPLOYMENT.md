# Phase 9 — deployment, Windows installation and production configuration

**Delivery state: implementation packaged; no deployment was performed or claimed. Previous test suites were not rerun, per request.**

## Implemented
- Windows installer: Python 3.12+ launcher check, isolated venv, pip install, non-overwriting generated `.env`, institution-name wizard, config validation, additive migrations, read-only DB audit and first-admin prompt.
- Windows operations: managed start/stop scripts, environment and migration checks, readiness polling, separate stdout/stderr logs and actionable failure messages.
- Container build: Python 3.12 slim, PostgreSQL driver, unprivileged user, read-only root filesystem, dropped capabilities, no-new-privileges, healthcheck.
- Compose topology: PostgreSQL 16, private API, Nginx reverse proxy, named persistent volumes for database/uploads/backups, bounded container logs.
- Reverse proxy: HTTP-to-HTTPS redirect, TLS 1.2/1.3, HSTS and common security headers. Certificate/hostname provisioning remains an operator action.
- Production environment template: secure settings defaults, explicit HTTPS origin, disabled demo data and self-registration.
- Operations guides: Windows install/use, production rollout, Docker, troubleshooting, migrations and backup/recovery.

## Important deployment prerequisites / limitations
- The ZIP is source/configuration only. It has not been deployed to a production host.
- Replace the example domain and install valid TLS certificate/key files before exposing Nginx.
- Generate and protect unique production `SECRET_KEY` and PostgreSQL password values.
- Docker Compose command must use `--env-file backend/.env.production` so interpolation of `POSTGRES_PASSWORD` is available.
- PostgreSQL backups through the existing Phase 8.2 service require compatible PostgreSQL client tools (`pg_dump`/`pg_restore`) in the maintenance environment. The application image installs the Python driver, not PostgreSQL client binaries.
- Windows launcher binds only to `127.0.0.1`; it is intended for a local single-host installation, not LAN/public deployment.
- No previous test suite was rerun. New scripts/configuration were statically reviewed; Windows, Docker, TLS, PostgreSQL, and production deployment behavior still require validation in their target environments.

## Preservation
All Phase 1–8 source, migrations, database-management features, Android source and existing data-management scripts are retained. Runtime databases, secrets, virtual environments, caches, logs and backup contents are excluded from the archive. Phase 10 has not been started.
