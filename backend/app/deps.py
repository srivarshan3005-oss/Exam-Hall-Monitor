from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session
from . import models
from .config import settings
from .database import get_db
from .permissions import expand, ROLE_LABELS
from .deps_ip import client_ip
from .ratelimit import limiter
from .security import decode_token
from .security_events import log_event

bearer = HTTPBearer(auto_error=False)
# A user who must change the password may only use these endpoints until they do.
PASSWORD_CHANGE_ALLOWED = ("/api/auth/me", "/api/auth/profile", "/api/auth/change-password", "/api/auth/logout")


def as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _deny(db: Session, request: Request, detail: str, event: str, username: str | None = None):
    # Cap how many rows one client can make us write with junk tokens.
    if limiter.check_and_record(f"evt-deny:{client_ip(request)}", 30, 60)[0]:
        log_event(db, event, request, username=username, severity="warning", detail=detail)
        db.commit()
    raise HTTPException(status_code=401, detail=detail)


def _user_from_credentials(creds, db: Session, request: Request) -> models.User:
    payload = decode_token(creds.credentials)
    if not payload:
        _deny(db, request, "Invalid or expired token", "auth.token_rejected")
    user = db.scalar(select(models.User).where(models.User.username == payload.get("sub")))
    if (not user or not user.active or user.status != "active" or payload.get("ver") != user.token_version
            or payload.get("role") != user.role):
        _deny(db, request, "Account unavailable", "auth.token_rejected", payload.get("sub"))
    sid = payload.get("sid")
    sess = db.get(models.AuthSession, sid) if sid else None
    now = datetime.now(timezone.utc)
    if (not sess or sess.user_id != user.id or sess.revoked_at is not None or as_utc(sess.expires_at) <= now):
        _deny(db, request, "Session ended. Sign in again.", "auth.session_rejected", user.username)
    if as_utc(sess.last_seen_at) < now - timedelta(minutes=settings.session_idle_minutes):
        sess.revoked_at = now
        log_event(db, "auth.session_idle_timeout", request, username=user.username, role=user.role)
        db.commit()
        raise HTTPException(status_code=401, detail="Session timed out. Sign in again.")
    if now - as_utc(sess.last_seen_at) > timedelta(seconds=60):   # keep write load low
        sess.last_seen_at = now
        db.commit()
    if user.must_change_password and request.url.path not in PASSWORD_CHANGE_ALLOWED:
        raise HTTPException(status_code=403, detail="Password change required before continuing")
    request.state.session_id = sid
    return user


def current_user(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer),
                 db: Session = Depends(get_db)) -> models.User:
    if not creds:
        raise HTTPException(status_code=401, detail="Authentication required")
    return _user_from_credentials(creds, db, request)


def optional_user(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer),
                  db: Session = Depends(get_db)) -> models.User | None:
    return _user_from_credentials(creds, db, request) if creds else None


def require_roles(*roles: str):
    """Backend permission check. 'admin' also admits 'super_admin'. A refusal is logged as a security
    event and the 403 tells the caller which role level is needed (permission-denied feedback)."""
    allowed = expand(roles)

    def checker(request: Request, user: models.User = Depends(current_user),
                db: Session = Depends(get_db)) -> models.User:
        if user.role not in allowed:
            log_event(db, "authz.denied", request, username=user.username, role=user.role, severity="warning",
                      detail=f"{request.method} needs one of: {', '.join(sorted(allowed))}")
            db.commit()
            needed = " or ".join(ROLE_LABELS.get(r, r) for r in roles)
            raise HTTPException(status_code=403, detail=f"Insufficient permission. This action needs: {needed}.")
        return user
    return checker


def department_scope(user: models.User) -> str | None:
    """Department staff with an assigned department only see that department's students."""
    return (user.department or "").strip() or None if user.role == "staff" else None
