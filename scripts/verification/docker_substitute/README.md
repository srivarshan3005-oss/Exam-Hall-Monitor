# Docker verification with local substitute images

**Read this first.** These files exist because the pinned base images in the production configuration
(`python:3.12-slim`, `postgres:16-alpine`, `nginx:1.27-alpine`) could not be pulled in the environment where this package
was verified (container registries were unreachable). To still exercise the project's **real** `docker-compose.yml` and
**real** `backend/Dockerfile`, the driver here builds clearly labelled *local substitute* images from an Ubuntu 24.04 root
filesystem and runs the real stack on them.

* The substitute images are **not** the official images, are labelled `substitute="true" official="false"`, and are named
  `local-substitute/...`. They must never be used in production.
* The production `docker-compose.yml` and `backend/Dockerfile` are **not modified**. The driver works on a scratch copy and
  changes only the `FROM` line of that copy (it prints the diff). Registry pinning stays exactly as shipped.
* A pass here verifies the project's compose wiring, Dockerfile steps, migrations, health checks, TLS proxy template,
  authentication and CRUD on **these** substitutes. It does **not** verify the official images. Run the production
  procedure in `docs/DOCKER.md` on a host with registry access before production use.

Known, declared differences from the official images: Ubuntu Python 3.12.3 (not Debian slim), Ubuntu PostgreSQL 16 (glibc,
not alpine), and Ubuntu nginx 1.24, which does not know `http2 on;` (needs 1.25.1+), so the substitute proxy entrypoint
comments that one line out. The substitute database image initialises UTF8, as the official image does.

## Prerequisites (one-time)
```sh
apt-get install -y debootstrap zstd
debootstrap --variant=minbase --components=main,universe \
  --include=python3,python3-venv,python3-pip,ca-certificates,curl,gettext-base,openssl \
  noble /tmp/noble http://archive.ubuntu.com/ubuntu
tar --numeric-owner -C /tmp/noble -c . | docker import - local-substitute/ubuntu-noble-minbase:test
```
If your network re-signs HTTPS with its own certificate authority, put that CA (PEM, `*.crt`) in
`scripts/verification/docker_substitute/base/extra-ca/` or point `EM_EXTRA_CA` at it. Do not do this for any other reason.

## Run
```sh
scripts/verification/docker_substitute/run_substitute_verification.sh
```
It generates throw-away random secrets and a self-signed certificate (kept only in the scratch copy), then runs, in order:
`compose config`, `build`, `check-config`, `migrate`, `up -d`, `create-admin`, an end-to-end check through the TLS proxy,
an application restart, `down` then `up` with volumes kept, a persistence check, and a scan of every log for the generated
secrets. It exits non-zero if any step fails. Set `EM_KEEP=1` to leave the stack running, `EM_VERIFY_WORKDIR` to change the
scratch folder.
