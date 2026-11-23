#!/bin/bash
# Minimal re-implementation of the official postgres image's first-start behaviour (role + database from env). Does not echo secrets.
set -e
PGBIN=/usr/lib/postgresql/16/bin
: "${PGDATA:=/var/lib/postgresql/data}"
mkdir -p "$PGDATA"; chown -R postgres:postgres "$PGDATA"; chmod 700 "$PGDATA"
if [ ! -s "$PGDATA/PG_VERSION" ]; then
  : "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"; : "${POSTGRES_USER:=postgres}"; : "${POSTGRES_DB:=$POSTGRES_USER}"
  pwfile=$(mktemp); printf '%s' "$POSTGRES_PASSWORD" > "$pwfile"; chown postgres "$pwfile"
  runuser -u postgres -- $PGBIN/initdb -D "$PGDATA" --username="$POSTGRES_USER" --pwfile="$pwfile" --encoding=UTF8 --locale=C.UTF-8 --auth-local=trust --auth-host=scram-sha-256 >/dev/null
  rm -f "$pwfile"
  echo "host all all all scram-sha-256" >> "$PGDATA/pg_hba.conf"
  runuser -u postgres -- $PGBIN/pg_ctl -D "$PGDATA" -o "-c listen_addresses=''" -w -s start
  if [ "$POSTGRES_DB" != "postgres" ]; then
    runuser -u postgres -- $PGBIN/psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres -qc "CREATE DATABASE \"$POSTGRES_DB\""
  fi
  runuser -u postgres -- $PGBIN/pg_ctl -D "$PGDATA" -m fast -w -s stop
  echo "substitute-postgres: initialised database '$POSTGRES_DB' for role '$POSTGRES_USER'"
fi
exec runuser -u postgres -- $PGBIN/postgres -D "$PGDATA" -c listen_addresses='*'
