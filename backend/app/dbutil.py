"""Database helpers that must behave the same on SQLite and PostgreSQL."""
from sqlalchemy import text
from sqlalchemy.orm import Session

_ALLOCATION_LOCK_KEY = 8_100_001   # arbitrary constant, only used as a PostgreSQL advisory-lock id


def lock_allocation(db: Session) -> None:
    """Serialise every operation that decides where a student sits.

    Seat uniqueness is guaranteed by the unique constraints, but rules such as 'no clash with a simultaneous
    examination' and 'hall capacity' are checked by *reading* first and *writing* afterwards. Two requests could both
    pass the read and then both write. Call this at the start of the transaction, BEFORE those reads:
    * PostgreSQL: transaction-scoped advisory lock (released on commit/rollback; other requests wait).
    * SQLite: an UPDATE that matches no rows still takes the database write lock, waiting up to busy_timeout.
    The lock is released automatically when the session commits or rolls back.
    """
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _ALLOCATION_LOCK_KEY})
    else:
        db.execute(text("UPDATE allotments SET id = id WHERE 1 = 0"))
