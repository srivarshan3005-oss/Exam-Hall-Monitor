from logging.config import fileConfig
from alembic import context
from sqlalchemy import create_engine, pool, event, inspect
from app.config import settings
from app.database import Base, normalize_database_url
from app import models, doc_models  # noqa: F401  (register all tables on Base.metadata)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)
target_metadata = Base.metadata


def _url() -> str:
    return normalize_database_url(
        (config.get_main_option("sqlalchemy.url") or settings.database_url).replace("%%", "%"))


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = _url()
    is_sqlite = url.startswith("sqlite")
    engine = create_engine(url, poolclass=pool.NullPool,
                           connect_args={"timeout": max(settings.sqlite_busy_timeout_ms, 0) / 1000} if is_sqlite else {})
    if is_sqlite:
        @event.listens_for(engine, "connect")
        def _sqlite_setup(dbapi_conn, _rec):
            dbapi_conn.isolation_level = None        # we emit BEGIN ourselves => SQLite DDL becomes transactional
            dbapi_conn.execute("PRAGMA foreign_keys=OFF")   # batch table rebuilds need FK checks off
            dbapi_conn.execute(f"PRAGMA busy_timeout={int(settings.sqlite_busy_timeout_ms)}")

        @event.listens_for(engine, "begin")
        def _sqlite_begin(conn):
            conn.exec_driver_sql("BEGIN")
    with engine.connect() as connection:
        if connection.dialect.name == "postgresql":
            has_history = "alembic_version" in inspect(connection).get_table_names()
            # inspect() autobegins a transaction; Alembic must own the transaction, otherwise it treats it as an
            # external one and never commits (the upgrade would silently roll back). End it before configuring.
            connection.rollback()
        else:
            has_history = True
        if not has_history:
            raise RuntimeError(
                "This PostgreSQL database has no migration history. The released SQLite-era revisions 0001-0009 "
                "cannot be replayed on PostgreSQL, so a new database must be created with:  python -m app.cli migrate  "
                "(it builds the current schema and stamps it; see docs/MIGRATIONS.md). Do not run 'alembic upgrade' "
                "directly on an empty PostgreSQL database.")
        # transaction_per_migration: each revision is atomic (its DDL and the alembic_version update commit
        # together or not at all), on PostgreSQL and on SQLite. A failure leaves the database at the last good revision.
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True,
                          compare_type=True, transactional_ddl=True, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
