"""Security event log (separate from the administrative audit log). Never receives secrets."""
import re
from fastapi import Request
from sqlalchemy.orm import Session
from . import models
from .deps_ip import client_ip

_NAME = re.compile(r"^[a-z0-9._-]{3,40}$")


def safe_username(raw: str | None) -> str | None:
    """A mistyped password in the username box must never reach the log: keep only username-shaped input."""
    if not raw:
        return None
    n = raw.strip().lower()
    return n if _NAME.match(n) else "(invalid-format)"


def log_event(db: Session, event_type: str, request: Request | None = None, *, username: str | None = None,
              role: str | None = None, severity: str = "info", detail: str | None = None) -> None:
    ua = (request.headers.get("user-agent") if request else None)
    db.add(models.SecurityEvent(
        event_type=event_type, severity=severity, username=safe_username(username), role=role,
        ip_address=client_ip(request) if request else None, user_agent=(ua or "")[:200] or None,
        path=(request.url.path[:200] if request else None), detail=(detail or "")[:500] or None))
