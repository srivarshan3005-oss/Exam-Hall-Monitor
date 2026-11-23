"""Audit trail helper. record() only adds the row; the caller commits it in the same
transaction as the change it describes, so a change can never exist without its log line."""
import json, re
from fastapi import Request
from sqlalchemy.orm import Session
from . import models
from .deps_ip import client_ip


_SECRET_KEY = re.compile(r"pass(word)?|token|secret|authorization|cookie", re.I)


def _scrub(value):
    """Audit details must never carry credentials, even by accident."""
    if isinstance(value, dict):
        return {k: ("[redacted]" if _SECRET_KEY.search(str(k)) else _scrub(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def record(db: Session, actor: str, action: str, target: str, details: dict | str | None = None,
           request: Request | None = None, role: str | None = None) -> None:
    if isinstance(details, (dict, list)):
        details = json.dumps(_scrub(details), sort_keys=True, default=str)
    if details and len(details) > 1000:
        details = details[:997] + "..."
    db.add(models.AuditLog(actor=actor[:80], action=action, target=str(target)[:150], details=details,
                           actor_role=role, ip_address=client_ip(request) if request else None))
