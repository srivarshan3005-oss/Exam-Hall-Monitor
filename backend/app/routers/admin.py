from fastapi import APIRouter, Depends, HTTPException, Request, Query, Response
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .. import models, schemas, audit
from ..database import get_db
from datetime import datetime, timedelta, timezone
from ..deps import require_roles, as_utc
from ..deps_ip import client_ip
from ..permissions import ROLES, ROLE_LABELS, ADMIN_ROLES, can_assign, can_manage
from ..ratelimit import limiter
from ..schemas_auth import AdminResetInput, StatusInput
from ..security import hash_password, validate_password_strength, generate_temporary_password
from ..security_events import log_event
from .auth import revoke_all_sessions

router = APIRouter(prefix="/api", tags=["Administration"])


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), user: models.User = Depends(require_roles("admin", "staff"))):
    count = lambda stmt: db.scalar(stmt) or 0  # noqa: E731
    return {
        "students": count(select(func.count()).select_from(models.Student)),
        "exams": count(select(func.count()).select_from(models.Exam)),
        "allotments": count(select(func.count()).select_from(models.Allotment)),
        "published_results": count(select(func.count()).select_from(models.Result)
                                   .where(models.Result.published == True)),  # noqa: E712
    }


@router.get("/admin/audit")
def audit_logs(response: Response, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
               action: str = Query("", max_length=60), actor: str = Query("", max_length=80),
               q: str = Query("", max_length=80), since: str = Query("", pattern=r"^(\d{4}-\d{2}-\d{2})?$"),
               until: str = Query("", pattern=r"^(\d{4}-\d{2}-\d{2})?$"),
               db: Session = Depends(get_db), user: models.User = Depends(require_roles("admin"))):
    """Administrative action history (search by action prefix, actor, free text, date range). Total in X-Total-Count."""
    cond = []
    if action:
        cond.append(models.AuditLog.action.startswith(action, autoescape=True))
    if actor:
        cond.append(models.AuditLog.actor == actor)
    if q:
        cond.append(models.AuditLog.target.icontains(q, autoescape=True) | models.AuditLog.details.icontains(q, autoescape=True)
                    | models.AuditLog.action.icontains(q, autoescape=True))
    if since:
        cond.append(models.AuditLog.created_at >= datetime.fromisoformat(since).replace(tzinfo=timezone.utc))
    if until:
        cond.append(models.AuditLog.created_at < datetime.fromisoformat(until).replace(tzinfo=timezone.utc) + timedelta(days=1))
    response.headers["X-Total-Count"] = str(db.scalar(select(func.count()).select_from(models.AuditLog).where(*cond)) or 0)
    stmt = select(models.AuditLog).where(*cond).order_by(models.AuditLog.id.desc()).limit(limit).offset(offset)
    return [{"id": r.id, "actor": r.actor, "action": r.action, "target": r.target, "details": r.details,
             "role": r.actor_role, "ip": r.ip_address, "created_at": r.created_at.isoformat()}
            for r in db.scalars(stmt).all()]


def _user_dict(u: models.User) -> dict:
    now = datetime.now(timezone.utc)
    return {"id": u.id, "username": u.username, "role": u.role, "role_label": ROLE_LABELS.get(u.role, u.role),
            "active": u.active, "status": u.status, "status_reason": u.status_reason, "email": u.email,
            "department": u.department, "pw_change_required": bool(u.must_change_password),
            "locked": bool(u.locked_until and as_utc(u.locked_until) > now),
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "student_linked": u.student_id is not None}


def _get_user(db: Session, username: str) -> models.User:
    u = db.scalar(select(models.User).where(models.User.username == username.strip().lower()))
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    return u


def _legacy(db: Session) -> bool:
    """True until the first active super administrator exists (see permissions.can_assign)."""
    return _admin_count(db, roles=("super_admin",)) == 0


def _guard_manage(actor: models.User, target: models.User, db: Session, request: Request):
    if not can_manage(actor.role, target.role, _legacy(db)):
        log_event(db, "authz.denied", request, username=actor.username, role=actor.role, severity="warning",
                  detail=f"tried to manage {target.role} account {target.username}")
        db.commit()
        raise HTTPException(status_code=403, detail=f"Only a Super administrator can manage "
                                                    f"{ROLE_LABELS.get(target.role, target.role)} accounts")


def _admin_count(db: Session, exclude_id: int | None = None, roles=ADMIN_ROLES) -> int:
    stmt = select(func.count()).select_from(models.User).where(
        models.User.role.in_(roles), models.User.status == "active", models.User.active == True)  # noqa: E712
    if exclude_id:
        stmt = stmt.where(models.User.id != exclude_id)
    return db.scalar(stmt) or 0


def _guard_last_admin(db: Session, actor: models.User, u: models.User, what: str):
    """Never allow the system to end up without an active administrator / super administrator."""
    if u.id == actor.id:
        raise HTTPException(status_code=409, detail=f"You cannot {what} your own account")
    if u.role in ADMIN_ROLES and u.status == "active" and _admin_count(db, u.id) == 0:
        raise HTTPException(status_code=409, detail="At least one active administrator must remain")
    if u.role == "super_admin" and u.status == "active" and _admin_count(db, u.id, ("super_admin",)) == 0:
        raise HTTPException(status_code=409, detail="At least one active super administrator must remain")


@router.get("/admin/roles")
def role_catalogue(db: Session = Depends(get_db), user: models.User = Depends(require_roles("admin", "staff", "invigilator"))):
    """Roles this deployment knows, and which ones the caller may assign."""
    return {"roles": [{"role": r, "label": ROLE_LABELS[r], "assignable": can_assign(user.role, r, legacy=_legacy(db))} for r in ROLES]}


@router.get("/admin/users")
def list_users(response: Response, q: str = Query("", max_length=60), role: str = Query("", max_length=20),
               status: str = Query("", pattern="^(active|pending|suspended)?$"),
               department: str = Query("", max_length=100), locked: bool | None = None,
               limit: int = Query(200, ge=1, le=500), offset: int = Query(0, ge=0),
               db: Session = Depends(get_db), user: models.User = Depends(require_roles("admin"))):
    cond = []
    if q:
        cond.append(models.User.username.icontains(q.lower(), autoescape=True) | models.User.email.icontains(q.lower(), autoescape=True))
    if role:
        if role not in ROLES:
            raise HTTPException(status_code=422, detail="Unknown role")
        cond.append(models.User.role == role)
    if status:
        cond.append(models.User.status == status)
    if department:
        cond.append(func.lower(models.User.department) == department.strip().lower())
    rows = db.scalars(select(models.User).where(*cond).order_by(models.User.username)).all()
    out = [_user_dict(u) for u in rows]
    if locked is not None:
        out = [u for u in out if u["locked"] == locked]
    response.headers["X-Total-Count"] = str(len(out))
    return out[offset:offset + limit]


@router.post("/admin/users", status_code=201)
def create_user(data: schemas.UserCreate, request: Request, db: Session = Depends(get_db),
                admin: models.User = Depends(require_roles("admin"))):
    if not can_assign(admin.role, data.role, legacy=_legacy(db)):
        log_event(db, "authz.denied", request, username=admin.username, role=admin.role, severity="warning",
                  detail=f"tried to create role {data.role}")
        db.commit()
        raise HTTPException(status_code=403, detail="Only a Super administrator can create administrator accounts")
    problems = validate_password_strength(data.password, data.username)
    student = None
    if data.role == "student":
        if not data.student_register_number:
            problems.append("student_register_number is required for student accounts")
        else:
            student = db.scalar(select(models.Student).where(
                models.Student.register_number == data.student_register_number))
            if not student:
                raise HTTPException(status_code=404, detail="No matching student record")
    elif data.student_register_number:
        problems.append("student_register_number is only valid for student accounts")
    if problems:
        raise HTTPException(status_code=422, detail="; ".join(problems))
    if db.scalar(select(models.User).where(models.User.username == data.username)):
        raise HTTPException(status_code=409, detail="Username already exists")
    if student and db.scalar(select(models.User.id).where(models.User.student_id == student.id)):
        raise HTTPException(status_code=409, detail="This student record already has a login account")
    u = models.User(username=data.username, password_hash=hash_password(data.password), role=data.role,
                    student_id=student.id if student else None, email=data.email, department=data.department,
                    must_change_password=data.require_password_change,
                    password_changed_at=datetime.now(timezone.utc))
    db.add(u)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Username already exists, or this student already has an account")
    audit.record(db, admin.username, "user.created", u.username, {"role": u.role}, request, admin.role)
    log_event(db, "account.created", request, username=admin.username, role=admin.role, detail=f"{u.username} as {u.role}")
    db.commit()
    return _user_dict(u)


@router.patch("/admin/users/{username}")
def update_user(username: str, data: schemas.UserUpdate, request: Request, db: Session = Depends(get_db),
                admin: models.User = Depends(require_roles("admin"))):
    u = _get_user(db, username)
    changes = data.model_dump(exclude_unset=True)
    if u.id != admin.id:
        _guard_manage(admin, u, db, request)
    if "role" in changes and changes["role"] != u.role:
        if not can_assign(admin.role, changes["role"], u.role, _legacy(db)):
            log_event(db, "authz.denied", request, username=admin.username, role=admin.role, severity="warning",
                      detail=f"tried to change {u.username}: {u.role} -> {changes['role']}")
            db.commit()
            raise HTTPException(status_code=403, detail="Only a Super administrator can grant or remove administrator roles")
        if u.role in ADMIN_ROLES and changes["role"] not in ADMIN_ROLES or (u.role == "super_admin" and changes["role"] != "super_admin"):
            _guard_last_admin(db, admin, u, "demote")
    if changes.get("active") is False and u.status == "active":
        if u.role in ADMIN_ROLES:
            _guard_last_admin(db, admin, u, "deactivate")
        elif u.id == admin.id:
            raise HTTPException(status_code=409, detail="You cannot deactivate your own account")
    bump, old_role = False, u.role
    if "role" in changes and changes["role"] != u.role:
        if changes["role"] == "student" and not u.student_id:
            raise HTTPException(status_code=422, detail="Link the account to a student before using the student role")
        u.role = changes["role"]
        bump = True
    if "active" in changes and changes["active"] != u.active:
        u.active = changes["active"]
        u.status = "active" if u.active else "suspended"
        u.status_reason = None if u.active else "deactivated by an administrator"
        bump = True
    if changes.get("unlock"):
        u.locked_until = None
        u.failed_attempts = 0
    if "email" in changes:
        u.email = changes["email"] or None
    if "department" in changes:
        u.department = (changes["department"] or "").strip() or None
    if changes.get("new_password"):
        problems = validate_password_strength(changes["new_password"], u.username)
        if problems:
            raise HTTPException(status_code=422, detail="; ".join(problems))
        u.password_hash = hash_password(changes["new_password"])
        u.password_changed_at = datetime.now(timezone.utc)
        bump = True
    if bump:
        u.token_version += 1
        revoke_all_sessions(db, u.id)
    shown = sorted(k for k in changes if k not in ("new_password",)) + (["password"] if "new_password" in changes else [])
    audit.record(db, admin.username, "user.updated", u.username, {"fields": shown, **({"role_from": old_role, "role_to": u.role} if old_role != u.role else {})}, request, admin.role)
    if old_role != u.role:
        log_event(db, "account.role_changed", request, username=admin.username, role=admin.role, severity="warning",
                  detail=f"{u.username}: {old_role} -> {u.role}")
    db.commit()
    return _user_dict(u)


def _set_status(db, request, admin, u, new_status: str, reason: str | None, action: str, ev: str):
    u.status, u.active = new_status, new_status == "active"
    u.status_reason = (reason or None) if new_status != "active" else None
    u.token_version += 1
    revoke_all_sessions(db, u.id)
    if new_status == "active":
        u.locked_until, u.failed_attempts = None, 0
    audit.record(db, admin.username, action, u.username, {"reason": reason}, request, admin.role)
    log_event(db, ev, request, username=admin.username, role=admin.role, severity="warning", detail=f"{u.username}")
    db.commit()
    return _user_dict(u)


@router.post("/admin/users/{username}/suspend")
def suspend_user(username: str, data: StatusInput, request: Request, db: Session = Depends(get_db),
                 admin: models.User = Depends(require_roles("admin"))):
    u = _get_user(db, username)
    _guard_manage(admin, u, db, request)
    _guard_last_admin(db, admin, u, "suspend")
    return _set_status(db, request, admin, u, "suspended", data.reason, "user.suspended", "account.suspended")


@router.post("/admin/users/{username}/restore")
def restore_user(username: str, data: StatusInput, request: Request, db: Session = Depends(get_db),
                 admin: models.User = Depends(require_roles("admin"))):
    """Restore a suspended account or approve a pending self-registration."""
    u = _get_user(db, username)
    _guard_manage(admin, u, db, request)
    if u.status == "active":
        raise HTTPException(status_code=409, detail="Account is already active")
    ev = "account.approved" if u.status == "pending" else "account.restored"
    return _set_status(db, request, admin, u, "active", data.reason, "user.restored" if ev == "account.restored" else "user.approved", ev)


@router.post("/admin/users/{username}/reset-password")
def admin_reset_password(username: str, data: AdminResetInput, request: Request, db: Session = Depends(get_db),
                         admin: models.User = Depends(require_roles("admin"))):
    """Issues a random temporary password (shown once). Safeguards: a written reason, no self-reset,
    administrator targets need a Super administrator, rate limit, all sessions end, change forced at next sign-in."""
    u = _get_user(db, username)
    if u.id == admin.id:
        raise HTTPException(status_code=409, detail="Use Change password for your own account")
    _guard_manage(admin, u, db, request)
    ok, retry = limiter.check_and_record(f"adminreset:{admin.username}", 10, 3600)
    if not ok:
        raise HTTPException(status_code=429, detail="Too many administrator resets; try later",
                            headers={"Retry-After": str(retry)})
    temp = generate_temporary_password()
    u.password_hash = hash_password(temp)
    u.must_change_password = True
    u.password_changed_at = datetime.now(timezone.utc)
    u.locked_until, u.failed_attempts = None, 0
    u.token_version += 1
    revoke_all_sessions(db, u.id)
    audit.record(db, admin.username, "user.password_reset_by_admin", u.username, {"reason": data.reason}, request, admin.role)
    log_event(db, "account.password_reset_by_admin", request, username=admin.username, role=admin.role,
              severity="critical", detail=f"target {u.username}")
    db.commit()
    return {"username": u.username, "temporary_password": temp, "pw_change_required": True,
            "detail": "Give this password to the user through a secure channel. It is shown only once "
                      "and must be changed at the next sign-in."}


@router.post("/admin/users/{username}/force-logout")
def force_logout(username: str, request: Request, db: Session = Depends(get_db),
                 admin: models.User = Depends(require_roles("admin"))):
    u = _get_user(db, username)
    if u.id != admin.id:
        _guard_manage(admin, u, db, request)
    u.token_version += 1
    revoke_all_sessions(db, u.id)
    audit.record(db, admin.username, "user.force_logout", u.username, None, request, admin.role)
    log_event(db, "account.force_logout", request, username=admin.username, role=admin.role, detail=u.username)
    db.commit()
    return {"detail": "All sessions ended"}


@router.get("/admin/users/{username}/activity")
def user_activity(username: str, limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db),
                  admin: models.User = Depends(require_roles("admin"))):
    """Login and account activity history for one account (sign-ins, failures, changes made to it)."""
    u = _get_user(db, username)
    ev = db.scalars(select(models.SecurityEvent).where(models.SecurityEvent.username == u.username)
                    .order_by(models.SecurityEvent.id.desc()).limit(limit)).all()
    au = db.scalars(select(models.AuditLog).where((models.AuditLog.actor == u.username) | (models.AuditLog.target == u.username))
                    .order_by(models.AuditLog.id.desc()).limit(limit)).all()
    return {"user": _user_dict(u),
            "security_events": [_event_dict(e) for e in ev],
            "audit": [{"id": r.id, "actor": r.actor, "action": r.action, "target": r.target, "details": r.details,
                       "created_at": r.created_at.isoformat()} for r in au]}


# ---------------------------------------------------------------- security dashboard
def _event_dict(e: models.SecurityEvent) -> dict:
    return {"id": e.id, "created_at": e.created_at.isoformat(), "event_type": e.event_type, "severity": e.severity,
            "username": e.username, "role": e.role, "ip": e.ip_address, "user_agent": e.user_agent,
            "path": e.path, "detail": e.detail}


@router.get("/admin/security/events")
def security_events(response: Response, type: str = Query("", max_length=50), severity: str = Query("", pattern="^(info|warning|critical)?$"),
                    username: str = Query("", max_length=80), ip: str = Query("", max_length=64),
                    q: str = Query("", max_length=80), since: str = Query("", pattern=r"^(\d{4}-\d{2}-\d{2})?$"),
                    until: str = Query("", pattern=r"^(\d{4}-\d{2}-\d{2})?$"),
                    limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
                    db: Session = Depends(get_db), admin: models.User = Depends(require_roles("admin"))):
    """Search/filter security events. `type` matches by prefix: auth.login, auth.login_failed, authz.denied, account."""
    cond = []
    E = models.SecurityEvent
    if type:
        cond.append(E.event_type.startswith(type, autoescape=True))
    if severity:
        cond.append(E.severity == severity)
    if username:
        cond.append(E.username == username.strip().lower())
    if ip:
        cond.append(E.ip_address == ip)
    if q:
        cond.append(E.detail.icontains(q, autoescape=True) | E.path.icontains(q, autoescape=True)
                    | E.event_type.icontains(q, autoescape=True))
    if since:
        cond.append(E.created_at >= datetime.fromisoformat(since).replace(tzinfo=timezone.utc))
    if until:
        cond.append(E.created_at < datetime.fromisoformat(until).replace(tzinfo=timezone.utc) + timedelta(days=1))
    response.headers["X-Total-Count"] = str(db.scalar(select(func.count()).select_from(E).where(*cond)) or 0)
    rows = db.scalars(select(E).where(*cond).order_by(E.id.desc()).limit(limit).offset(offset)).all()
    return [_event_dict(e) for e in rows]


@router.get("/admin/security/summary")
def security_summary(hours: int = Query(24, ge=1, le=720), db: Session = Depends(get_db),
                     admin: models.User = Depends(require_roles("admin"))):
    E = models.SecurityEvent
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    counts = dict(db.execute(select(E.event_type, func.count()).where(E.created_at >= since).group_by(E.event_type)).all())
    now = datetime.now(timezone.utc)
    users = db.scalars(select(models.User)).all()
    by_status, by_role = {}, {}
    for u in users:
        by_status[u.status] = by_status.get(u.status, 0) + 1
        by_role[u.role] = by_role.get(u.role, 0) + 1
    top_ips = db.execute(select(E.ip_address, func.count().label("n")).where(
        E.created_at >= since, E.event_type.in_(("auth.login_failed", "auth.account_locked", "auth.login_blocked")))
        .group_by(E.ip_address).order_by(func.count().desc()).limit(5)).all()
    active_sessions = db.scalar(select(func.count()).select_from(models.AuthSession).where(
        models.AuthSession.revoked_at.is_(None), models.AuthSession.expires_at > now)) or 0
    return {"window_hours": hours,
            "successful_logins": counts.get("auth.login", 0),
            "failed_logins": counts.get("auth.login_failed", 0) + counts.get("auth.account_locked", 0),
            "lockouts": counts.get("auth.account_locked", 0),
            "permission_denials": counts.get("authz.denied", 0),
            "rate_limited": counts.get("auth.rate_limited", 0),
            "password_resets": counts.get("auth.password_reset", 0) + counts.get("account.password_reset_by_admin", 0),
            "role_changes": counts.get("account.role_changed", 0),
            "accounts_by_status": by_status, "accounts_by_role": by_role,
            "locked_accounts": [u.username for u in users if u.locked_until and as_utc(u.locked_until) > now],
            "active_sessions": active_sessions,
            "top_failed_login_ips": [{"ip": ip, "count": n} for ip, n in top_ips],
            "critical_events": db.scalar(select(func.count()).select_from(E).where(E.created_at >= since, E.severity == "critical")) or 0}


@router.get("/admin/security/sessions")
def active_sessions(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db),
                    admin: models.User = Depends(require_roles("admin"))):
    now = datetime.now(timezone.utc)
    rows = db.execute(select(models.AuthSession, models.User.username, models.User.role).join(
        models.User, models.User.id == models.AuthSession.user_id).where(
        models.AuthSession.revoked_at.is_(None), models.AuthSession.expires_at > now)
        .order_by(models.AuthSession.last_seen_at.desc()).limit(limit)).all()
    return [{"username": n, "role": r, "created_at": s.created_at.isoformat(), "last_seen_at": s.last_seen_at.isoformat(),
             "ip": s.ip_address, "user_agent": s.user_agent} for s, n, r in rows]
