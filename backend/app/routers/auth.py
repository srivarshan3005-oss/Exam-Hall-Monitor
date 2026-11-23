import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from .. import models, schemas, audit
from ..config import settings
from ..database import get_db
from ..deps import current_user, as_utc
from ..deps_ip import client_ip
from ..mailer import send_mail
from .. import notifications as notify
from ..permissions import ROLE_LABELS
from ..ratelimit import limiter
from ..schemas_auth import RegisterInput, ActivateInput, ForgotInput, ResetInput
from ..security import (verify_password, hash_password, burn_password_check, create_access_token,
                        validate_password_strength, new_one_time_token, hash_one_time_token)
from ..security_events import log_event

router = APIRouter(prefix="/api/auth", tags=["Authentication"])
_WINDOW = 15 * 60
_HOUR = 3600


def _too_many(retry_after: int):
    raise HTTPException(status_code=429, detail="Too many sign-in attempts. Try again later.",
                        headers={"Retry-After": str(max(1, retry_after))})


def _limit(key: str, limit: int, window: int, what: str = "requests"):
    ok, retry = limiter.check_and_record(key, limit, window)
    if not ok:
        raise HTTPException(status_code=429, detail=f"Too many {what}. Try again later.",
                            headers={"Retry-After": str(max(1, retry))})


def open_session(db: Session, user: models.User, request: Request) -> str:
    """Create a server-side session, keep at most MAX_SESSIONS_PER_USER, return the signed token."""
    now = datetime.now(timezone.utc)
    sid = secrets.token_hex(16)
    db.add(models.AuthSession(id=sid, user_id=user.id, created_at=now, last_seen_at=now,
                              expires_at=now + timedelta(minutes=settings.access_token_minutes),
                              ip_address=client_ip(request), user_agent=(request.headers.get("user-agent") or "")[:200] or None))
    db.flush()
    live = db.scalars(select(models.AuthSession).where(
        models.AuthSession.user_id == user.id, models.AuthSession.revoked_at.is_(None),
        models.AuthSession.expires_at > now).order_by(models.AuthSession.created_at.desc())).all()
    for old in live[settings.max_sessions_per_user:]:
        old.revoked_at = now
    return create_access_token(user.username, user.role, user.token_version, sid)


def revoke_all_sessions(db: Session, user_id: int) -> None:
    db.execute(update(models.AuthSession).where(models.AuthSession.user_id == user_id,
                                                models.AuthSession.revoked_at.is_(None))
               .values(revoked_at=datetime.now(timezone.utc)))


def _fail_login(db, request, user, name):
    limiter.record(f"login-fail:{name}")
    now = datetime.now(timezone.utc)
    event = "auth.login_failed"
    if user:
        user.failed_attempts = (user.failed_attempts or 0) + 1
        action = "auth.login_failed"
        if user.failed_attempts >= settings.login_max_failures:
            user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
            user.failed_attempts = 0
            action = event = "auth.account_locked"
        audit.record(db, user.username, action, user.username, request=request, role=user.role)
    log_event(db, event, request, username=name, role=user.role if user else None,
              severity="critical" if event == "auth.account_locked" else "warning",
              detail="known account" if user else "unknown account")
    db.commit()
    raise HTTPException(status_code=401, detail="Incorrect username or password")


@router.post("/login")
def login(data: schemas.LoginInput, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    ok, retry = limiter.check_and_record(f"login-ip:{ip}", settings.login_ip_max_attempts, _WINDOW)
    if not ok:
        log_event(db, "auth.rate_limited", request, username=data.username, severity="warning", detail="login ip limit")
        db.commit()
        _too_many(retry)

    name = data.username.strip().lower()[:80]
    fail_key = f"login-fail:{name}"
    lock_window = settings.login_lockout_minutes * 60
    user = db.scalar(select(models.User).where(models.User.username == name))
    now = datetime.now(timezone.utc)

    # Lockout is identical for real and unknown usernames (no account enumeration).
    mem_blocked, mem_retry = limiter.is_blocked(fail_key, settings.login_max_failures, lock_window)
    db_locked = bool(user and user.locked_until and as_utc(user.locked_until) > now)
    if mem_blocked or db_locked:
        retry_after = mem_retry or int((as_utc(user.locked_until) - now).total_seconds()) + 1
        log_event(db, "auth.login_blocked", request, username=name, severity="warning", detail="locked out")
        db.commit()
        _too_many(retry_after)

    usable = bool(user and user.active and user.status == "active")
    if usable:
        valid = verify_password(data.password, user.password_hash)
    else:
        burn_password_check(data.password)
        valid = False
    if not valid:
        if user and not usable:   # same response as a wrong password; the reason is only in the log
            log_event(db, "auth.login_refused_inactive", request, username=name, role=user.role,
                      severity="warning", detail=f"status={user.status}")
        _fail_login(db, request, user, name)

    limiter.clear(fail_key)
    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    if (settings.password_max_age_days and user.password_changed_at
            and as_utc(user.password_changed_at) < now - timedelta(days=settings.password_max_age_days)):
        user.must_change_password = True
    token = open_session(db, user, request)
    audit.record(db, user.username, "auth.login", user.username, request=request, role=user.role)
    log_event(db, "auth.login", request, username=user.username, role=user.role)
    db.commit()
    return {"access_token": token, "token_type": "bearer", "role": user.role, "username": user.username,
            "role_label": ROLE_LABELS.get(user.role, user.role),
            "pw_change_required": bool(user.must_change_password),
            "expires_in": settings.access_token_minutes * 60}


@router.get("/me")
def me(user: models.User = Depends(current_user)):
    return {"username": user.username, "role": user.role}


@router.get("/profile")
def profile(user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    out = {"username": user.username, "role": user.role, "role_label": ROLE_LABELS.get(user.role, user.role),
           "department": user.department, "email": user.email, "pw_change_required": bool(user.must_change_password)}
    if user.role == "student" and user.student_id:      # lets a student's own page know which record is theirs
        own = db.get(models.Student, user.student_id)
        if own:
            out["register_number"] = own.register_number
            out["student_name"] = own.full_name
    return out


@router.post("/change-password")
def change_password(data: schemas.ChangePasswordInput, request: Request,
                    user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    _limit(f"chgpw:{user.username}", 10, _WINDOW, "password change attempts")
    if not verify_password(data.current_password, user.password_hash):
        audit.record(db, user.username, "auth.password_change_failed", user.username, request=request, role=user.role)
        log_event(db, "auth.password_change_failed", request, username=user.username, role=user.role, severity="warning")
        db.commit()
        raise HTTPException(status_code=403, detail="Current password is incorrect")
    problems = validate_password_strength(data.new_password, user.username)
    if data.new_password == data.current_password:
        problems.append("New password must differ from the current password")
    if problems:
        raise HTTPException(status_code=422, detail="; ".join(problems))
    user.password_hash = hash_password(data.new_password)
    user.must_change_password = False
    user.password_changed_at = datetime.now(timezone.utc)
    user.token_version += 1  # signs out every existing session
    revoke_all_sessions(db, user.id)
    audit.record(db, user.username, "auth.password_changed", user.username, request=request, role=user.role)
    log_event(db, "auth.password_changed", request, username=user.username, role=user.role)
    token = open_session(db, user, request)
    db.commit()
    notify.notify_account_event(db, user, "password_changed", f"account:{user.id}:pwchange:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}")
    return {"access_token": token, "token_type": "bearer", "detail": "Password changed. Other sessions were signed out."}


@router.post("/logout")
def logout(request: Request, user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    """Ends the current session (its token stops working immediately)."""
    sess = db.get(models.AuthSession, getattr(request.state, "session_id", None) or "")
    if sess:
        sess.revoked_at = datetime.now(timezone.utc)
    audit.record(db, user.username, "auth.logout", user.username, request=request, role=user.role)
    log_event(db, "auth.logout", request, username=user.username, role=user.role)
    db.commit()
    return {"detail": "Signed out"}


@router.post("/logout-all")
def logout_all(request: Request, user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    """Signs the account out everywhere."""
    user.token_version += 1
    revoke_all_sessions(db, user.id)
    audit.record(db, user.username, "auth.logout_all", user.username, request=request, role=user.role)
    log_event(db, "auth.logout_all", request, username=user.username, role=user.role)
    db.commit()
    return {"detail": "Signed out everywhere"}


@router.get("/sessions")
def my_sessions(request: Request, user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    rows = db.scalars(select(models.AuthSession).where(
        models.AuthSession.user_id == user.id, models.AuthSession.revoked_at.is_(None),
        models.AuthSession.expires_at > now).order_by(models.AuthSession.created_at.desc())).all()
    cur = getattr(request.state, "session_id", None)
    return [{"id": s.id[:8], "created_at": s.created_at.isoformat(), "last_seen_at": s.last_seen_at.isoformat(),
             "ip": s.ip_address, "user_agent": s.user_agent, "current": s.id == cur} for s in rows]


@router.delete("/sessions/{short_id}")
def end_session(short_id: str, request: Request, user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    if not (4 <= len(short_id) <= 8):
        raise HTTPException(status_code=404, detail="Session not found")
    s = db.scalar(select(models.AuthSession).where(
        models.AuthSession.user_id == user.id, models.AuthSession.id.startswith(short_id, autoescape=True),
        models.AuthSession.revoked_at.is_(None)))
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")   # also covers other users' sessions (IDOR)
    s.revoked_at = datetime.now(timezone.utc)
    log_event(db, "auth.session_revoked", request, username=user.username, role=user.role)
    db.commit()
    return {"detail": "Session ended"}


# ---------------------------------------------------------------- registration and activation
GENERIC_REGISTER = {"detail": "If the details match a student record with an e-mail address on file, an activation "
                              "link has been sent to that address. The account stays inactive until it is used."}


def _issue_token(db: Session, user: models.User, purpose: str, minutes: int) -> str:
    db.execute(update(models.PasswordToken).where(models.PasswordToken.user_id == user.id,
                                                  models.PasswordToken.purpose == purpose,
                                                  models.PasswordToken.used_at.is_(None))
               .values(used_at=datetime.now(timezone.utc)))      # older links stop working
    raw, digest = new_one_time_token()
    now = datetime.now(timezone.utc)
    db.add(models.PasswordToken(user_id=user.id, purpose=purpose, token_hash=digest, created_at=now,
                                expires_at=now + timedelta(minutes=minutes)))
    return raw


@router.post("/register", status_code=202)
def register(data: RegisterInput, request: Request, db: Session = Depends(get_db)):
    """Student self-registration. The response is identical whether or not the register number exists,
    is already registered, or the e-mail matches, so it cannot be used to discover who is a student."""
    ip = client_ip(request)
    _limit(f"register:{ip}", settings.register_per_hour, _HOUR, "registration attempts")
    problems = validate_password_strength(data.password, data.username)
    if problems:
        raise HTTPException(status_code=422, detail="; ".join(problems))
    student = db.scalar(select(models.Student).where(models.Student.register_number == data.register_number))
    taken = db.scalar(select(models.User).where(models.User.username == data.username))
    linked = student and db.scalar(select(models.User).where(models.User.student_id == student.id))
    ok = (settings.allow_self_registration and student and student.active and not taken and not linked
          and student.email and student.email.strip().lower() == data.email)
    if not ok:
        log_event(db, "auth.register_rejected", request, username=data.username, severity="warning")
        db.commit()
        return GENERIC_REGISTER
    u = models.User(username=data.username, password_hash=hash_password(data.password), role="student",
                    student_id=student.id, active=False, status="pending", email=data.email,
                    password_changed_at=datetime.now(timezone.utc))
    db.add(u)
    db.flush()
    raw = _issue_token(db, u, "activation", settings.activation_token_hours * 60)
    audit.record(db, u.username, "user.registered", u.username, {"role": "student"}, request, "student")
    log_event(db, "auth.registered", request, username=u.username, role="student")
    db.commit()
    send_mail(data.email, "Activate your Exam Monitor account",
              f"Open this link to activate your account (valid {settings.activation_token_hours} hours):\n"
              f"{settings.public_base_url}/?activate={raw}\n\nIf you did not register, ignore this message.")
    return GENERIC_REGISTER


@router.post("/activate")
def activate(data: ActivateInput, request: Request, db: Session = Depends(get_db)):
    _limit(f"activate:{client_ip(request)}", 20, _HOUR, "activation attempts")
    now = datetime.now(timezone.utc)
    t = db.scalar(select(models.PasswordToken).where(models.PasswordToken.token_hash == hash_one_time_token(data.token),
                                                     models.PasswordToken.purpose == "activation"))
    if not t or t.used_at is not None or as_utc(t.expires_at) <= now:
        log_event(db, "auth.activation_failed", request, severity="warning")
        db.commit()
        raise HTTPException(status_code=400, detail="This activation link is invalid or has expired")
    u = db.get(models.User, t.user_id)
    if u and u.status == "pending":
        u.status, u.active = "active", True
        audit.record(db, u.username, "user.activated", u.username, {"via": "e-mail link"}, request, u.role)
        log_event(db, "auth.activated", request, username=u.username, role=u.role)
    t.used_at = now
    db.commit()
    if u and u.status == "active":
        notify.notify_account_event(db, u, "account_activated", f"account:{u.id}:activated")
    return {"detail": "Account activated. You can now sign in."}


# ---------------------------------------------------------------- password recovery
GENERIC_FORGOT = {"detail": "If an active account matches, a password-reset link has been sent to its e-mail address."}


@router.post("/forgot-password", status_code=202)
def forgot_password(data: ForgotInput, request: Request, db: Session = Depends(get_db)):
    """Always answers the same way: nothing reveals whether the account exists."""
    ip = client_ip(request)
    _limit(f"forgot-ip:{ip}", settings.forgot_password_per_hour, _HOUR, "reset requests")
    ident = data.identifier.strip().lower()
    _limit(f"forgot-id:{ident}", 3, _HOUR, "reset requests")
    u = db.scalar(select(models.User).where(models.User.username == ident))
    if not u and "@" in ident:
        u = db.scalar(select(models.User).where(models.User.email == ident))
    email = None
    if u and u.active and u.status == "active":
        email = u.email or (db.get(models.Student, u.student_id).email if u.student_id else None)
    if u and email:
        raw = _issue_token(db, u, "reset", settings.reset_token_minutes)
        log_event(db, "auth.reset_requested", request, username=u.username, role=u.role)
        db.commit()
        send_mail(email, "Reset your Exam Monitor password",
                  f"Open this link to choose a new password (valid {settings.reset_token_minutes} minutes, one use):\n"
                  f"{settings.public_base_url}/?reset={raw}\n\nIf you did not ask for this, ignore this message.")
    else:
        log_event(db, "auth.reset_requested_unmatched", request, username=ident if "@" not in ident else None, severity="info")
        db.commit()
    return GENERIC_FORGOT


@router.post("/reset-password")
def reset_password(data: ResetInput, request: Request, db: Session = Depends(get_db)):
    _limit(f"reset-ip:{client_ip(request)}", 20, _HOUR, "reset attempts")
    now = datetime.now(timezone.utc)
    t = db.scalar(select(models.PasswordToken).where(models.PasswordToken.token_hash == hash_one_time_token(data.token),
                                                     models.PasswordToken.purpose == "reset"))
    if not t or t.used_at is not None or as_utc(t.expires_at) <= now:
        log_event(db, "auth.reset_failed", request, severity="warning")
        db.commit()
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired")
    u = db.get(models.User, t.user_id)
    if not u or not u.active or u.status != "active":
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired")
    problems = validate_password_strength(data.new_password, u.username)
    if problems:
        raise HTTPException(status_code=422, detail="; ".join(problems))     # token stays valid for a retry
    u.password_hash = hash_password(data.new_password)
    u.password_changed_at, u.must_change_password = now, False
    u.failed_attempts, u.locked_until = 0, None
    u.token_version += 1
    revoke_all_sessions(db, u.id)
    t.used_at = now
    audit.record(db, u.username, "auth.password_reset", u.username, {"via": "e-mail link"}, request, u.role)
    log_event(db, "auth.password_reset", request, username=u.username, role=u.role)
    db.commit()
    notify.notify_account_event(db, u, "password_changed", f"account:{u.id}:pwchange:{now.strftime('%Y%m%d%H%M%S%f')}")
    return {"detail": "Password updated. Sign in with the new password."}
