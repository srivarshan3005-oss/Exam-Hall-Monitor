"""Column types shared by every model.

UTCDateTime: every timestamp in the database is UTC.
* PostgreSQL stores it as TIMESTAMPTZ and returns an aware datetime (converted to UTC here).
* SQLite has no time-zone type: it stores the text 'YYYY-MM-DD HH:MM:SS.ffffff' and SQLAlchemy returns a *naive*
  datetime. This type stores the UTC wall time and re-attaches tzinfo=UTC when reading, so application code always
  receives an aware UTC datetime on both databases (no more naive/aware comparison errors).
* A naive datetime handed to the database is interpreted as UTC (the application always creates UTC values).
No schema change: the column is still DateTime(timezone=True), so existing databases are read exactly as before.
"""
from datetime import datetime, timezone
from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
