# LOCAL SUBSTITUTE for postgres:16-alpine (Ubuntu PostgreSQL 16, glibc). NOT an official image.
FROM local-substitute/python-ubuntu:3.12.3
LABEL substitute="true" substitutes="postgres:16-alpine" official="false"
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-16 postgresql-client-16 \
 && rm -rf /var/lib/apt/lists/* && (pg_dropcluster --stop 16 main || true) \
 && ln -sf /usr/lib/postgresql/16/bin/pg_isready /usr/local/bin/pg_isready
ENV PGDATA=/var/lib/postgresql/data
COPY entrypoint.sh /usr/local/bin/substitute-entrypoint.sh
RUN chmod +x /usr/local/bin/substitute-entrypoint.sh
EXPOSE 5432
ENTRYPOINT ["/usr/local/bin/substitute-entrypoint.sh"]
