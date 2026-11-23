#!/bin/bash
# Runs the project's REAL docker-compose.yml and backend/Dockerfile, with the pinned official base images replaced by LOCAL
# SUBSTITUTES (see README.md). Work happens in a scratch copy; the package is never modified. Needs: docker + compose v2, python3,
# openssl, root (to edit /etc/hosts and talk to docker), and the base image $EM_BASE_IMAGE (see README for the debootstrap step).
set -u
HERE=$(cd "$(dirname "$0")" && pwd); ROOT=$(cd "$HERE/../../.." && pwd)
WORK=${EM_VERIFY_WORKDIR:-/tmp/em_docker_verify}; HOSTN=${EM_TEST_HOST:-exam.test.local}
BASE_IMG=local-substitute/ubuntu-noble-minbase:test
docker image inspect "$BASE_IMG" >/dev/null 2>&1 || { echo "Missing $BASE_IMG. See README.md (debootstrap prerequisite)."; exit 2; }
rm -rf "$WORK"; mkdir -p "$WORK"; cp -r "$ROOT/." "$WORK/stack"; S="$WORK/stack"; V="$S/scripts/verification/docker_substitute"; cd "$S" || exit 2
[ -n "${EM_EXTRA_CA:-}" ] && cp "$EM_EXTRA_CA" "$V/base/extra-ca/extra-ca.crt"
python3 - <<'PY'
import secrets, string, re
a = string.ascii_letters + string.digits
pg = "".join(secrets.choice(a) for _ in range(24)); sk = "".join(secrets.choice(a + "-_") for _ in range(64)); adm = "Adm" + "".join(secrets.choice(a) for _ in range(16)) + "9x"
s = open("backend/.env.production.example", encoding="utf-8").read()
def setv(k, v):
    global s
    s = re.sub(rf"^{k}=.*$", f"{k}={v}", s, flags=re.M) if re.search(rf"^{k}=.*$", s, re.M) else s + f"\n{k}={v}"
import os; h = os.environ.get("EM_TEST_HOST", "exam.test.local")
setv("SECRET_KEY", sk); setv("POSTGRES_PASSWORD", pg); setv("DOMAIN_NAME", h); setv("PUBLIC_BASE_URL", f"https://{h}"); setv("CORS_ORIGINS", f"https://{h}")
setv("DATABASE_URL", f"postgresql+psycopg://exam_monitor:{pg}@db:5432/exam_monitor")
open("backend/.env.production", "w", encoding="utf-8").write(s); os.chmod("backend/.env.production", 0o600)
open(".testcreds", "w").write(f"export EM_ADMIN_PASSWORD='{adm}'\nexport POSTGRES_PASSWORD='{pg}'\n"); os.chmod(".testcreds", 0o600)
PY
source ./.testcreds; export EM_TEST_HOST="$HOSTN" EM_TEST_CERT="$S/deploy/certs/fullchain.pem" EM_RESULT_JSON="$WORK/check_results.json"
openssl req -x509 -nodes -newkey rsa:2048 -days 2 -subj "/CN=$HOSTN" -keyout deploy/certs/privkey.pem -out deploy/certs/fullchain.pem >/dev/null 2>&1; chmod 600 deploy/certs/privkey.pem
grep -q "$HOSTN" /etc/hosts || echo "127.0.0.1 $HOSTN" >> /etc/hosts
sed 's|^FROM python:3.12-slim$|FROM local-substitute/python-ubuntu:3.12.3|' backend/Dockerfile > substitute.app.Dockerfile
echo "Dockerfile difference (must be the FROM line only):"; diff backend/Dockerfile substitute.app.Dockerfile
cp "$V/docker-compose.substitute.yml" .
FAILS=0; rc() { echo "RC $1 $2"; [ "$2" -eq 0 ] || FAILS=$((FAILS+1)); }
docker build -q -t local-substitute/python-ubuntu:3.12.3 "$V/base" >/dev/null; rc "build substitute python base" $?
docker build -q -t local-substitute/postgres-ubuntu:16 "$V/db" >/dev/null; rc "build substitute postgres" $?
docker build -q -t local-substitute/nginx-ubuntu:1.24 "$V/proxy" >/dev/null; rc "build substitute nginx" $?
C="docker compose --env-file backend/.env.production -f docker-compose.yml -f docker-compose.substitute.yml"
SK=$(grep -E '^SECRET_KEY=' backend/.env.production | cut -d= -f2-)
wait_healthy() { for i in $(seq 1 40); do $C ps --format '{{.Service}}={{.Health}}' 2>/dev/null | grep -q 'app=healthy' && return 0; sleep 3; done; return 1; }
$C down -v >/dev/null 2>&1
$C config -q; rc "compose config" $?
$C build app >"$WORK/build.log" 2>&1; rc "compose build app (real backend/Dockerfile)" $?
$C run --rm app python -m app.cli check-config >"$WORK/check.log" 2>&1; rc "run app check-config" $?; tail -1 "$WORK/check.log"
$C run --rm app python -m app.cli migrate >"$WORK/migrate.log" 2>&1; rc "run app migrate" $?; grep "Database is at" "$WORK/migrate.log"
$C up -d >"$WORK/up.log" 2>&1; rc "compose up -d" $?
wait_healthy; rc "app health check healthy" $?
$C exec -T -e EM_ADMIN_PASSWORD app python -m app.cli create-admin --username docker_admin --role super_admin >"$WORK/admin.log" 2>&1; rc "exec create-admin" $?
python3 "$V/check_stack.py" >"$WORK/e2e.log" 2>&1; rc "end-to-end stack check" $?; tail -2 "$WORK/e2e.log"; grep "^FAIL" "$WORK/e2e.log"
$C restart app >/dev/null 2>&1; wait_healthy; rc "app healthy after restart" $?
python3 "$V/check_persistence.py" "after app restart" >"$WORK/p1.log" 2>&1; rc "persistence after restart" $?; cat "$WORK/p1.log"
$C down >/dev/null 2>&1; rc "compose down (volumes kept)" $?; $C up -d >/dev/null 2>&1; rc "compose up -d again" $?; wait_healthy; rc "app healthy after down/up" $?
python3 "$V/check_persistence.py" "after down/up, volumes kept" >"$WORK/p2.log" 2>&1; rc "persistence after down/up" $?; cat "$WORK/p2.log"
echo "database:"; $C exec -T db psql -U exam_monitor -d exam_monitor -Atc "select 'alembic_version='||version_num from alembic_version; select 'server_encoding='||current_setting('server_encoding')" 2>&1
$C logs --no-color >"$WORK/alllogs.txt" 2>&1
for pair in "EM_ADMIN_PASSWORD:$EM_ADMIN_PASSWORD" "POSTGRES_PASSWORD:$POSTGRES_PASSWORD" "SECRET_KEY:$SK"; do n=${pair%%:*}; v=${pair#*:}; c=$(cat "$WORK/alllogs.txt" "$WORK"/*.log | grep -cF -- "$v"); echo "leak scan $n occurrences in all logs: $c"; [ "$c" -eq 0 ] || FAILS=$((FAILS+1)); done
[ "${EM_KEEP:-0}" = "1" ] || $C down -v >/dev/null 2>&1
echo "SUMMARY: failed steps = $FAILS"; [ "$FAILS" -eq 0 ] && echo "RESULT: ALL STEPS PASSED (substitute images; see README)" || echo "RESULT: FAILURES"; exit $FAILS
