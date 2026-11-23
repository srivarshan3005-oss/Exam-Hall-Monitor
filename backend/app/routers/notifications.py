"""Per-user notification centre. Every query is filtered by the signed-in user's id, so one user can never
read, change or delete another user's notification (a foreign id answers 404, exactly like a missing one)."""
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, func, update, or_
from sqlalchemy.orm import Session
from .. import models
from ..database import get_db
from ..deps import current_user
from ..notifications import ALWAYS_IN_APP, prefs_for
from ..notify_templates import CATEGORIES, PRIORITIES
from ..ratelimit import limiter

router = APIRouter(prefix="/api/notifications", tags=["Notifications"])


def _view(n: models.Notification) -> dict:
    return {"id": n.id, "category": n.category, "category_label": CATEGORIES.get(n.category, n.category),
            "priority": n.priority, "title": n.title, "body": n.body, "link": n.link,
            "created_at": n.created_at.isoformat(), "read": n.read_at is not None,
            "read_at": n.read_at.isoformat() if n.read_at else None, "archived": n.archived_at is not None}


def _own(db: Session, user: models.User, nid: int) -> models.Notification:
    n = db.scalar(select(models.Notification).where(models.Notification.id == nid, models.Notification.user_id == user.id,
                                                     models.Notification.deleted_at.is_(None)))
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    return n


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.get("")
def list_notifications(response: Response, status: Literal["unread", "read", "archived", "all", "inbox"] = "inbox",
                       category: str = Query("", max_length=20), priority: str = Query("", max_length=10),
                       q: str = Query("", max_length=80), limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0),
                       db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    """status: inbox (default: not archived) | unread | read | archived | all. Newest first."""
    if category and category not in CATEGORIES:
        raise HTTPException(status_code=422, detail="Unknown category")
    if priority and priority not in PRIORITIES:
        raise HTTPException(status_code=422, detail="Unknown priority")
    N = models.Notification
    cond = [N.user_id == user.id, N.deleted_at.is_(None)]
    if status == "unread":
        cond += [N.read_at.is_(None), N.archived_at.is_(None)]
    elif status == "read":
        cond += [N.read_at.is_not(None), N.archived_at.is_(None)]
    elif status == "archived":
        cond.append(N.archived_at.is_not(None))
    elif status == "inbox":
        cond.append(N.archived_at.is_(None))
    if category:
        cond.append(N.category == category)
    if priority:
        cond.append(N.priority == priority)
    if q.strip():
        like = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        cond.append(or_(N.title.ilike(like, escape="\\"), N.body.ilike(like, escape="\\")))
    total = db.scalar(select(func.count()).select_from(N).where(*cond)) or 0
    rows = db.scalars(select(N).where(*cond).order_by(N.created_at.desc(), N.id.desc()).limit(limit).offset(offset)).all()
    response.headers["X-Total-Count"] = str(total)
    return [_view(n) for n in rows]


def _unread(db: Session, user: models.User) -> int:
    N = models.Notification
    return db.scalar(select(func.count()).select_from(N).where(N.user_id == user.id, N.deleted_at.is_(None),
                                                            N.read_at.is_(None), N.archived_at.is_(None))) or 0


@router.get("/unread-count")
def unread_count(db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    return {"unread": _unread(db, user)}


@router.post("/read-all")
def read_all(category: str = Query("", max_length=20), db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    if category and category not in CATEGORIES:
        raise HTTPException(status_code=422, detail="Unknown category")
    N = models.Notification
    cond = [N.user_id == user.id, N.deleted_at.is_(None), N.read_at.is_(None), N.archived_at.is_(None)] + ([N.category == category] if category else [])
    r = db.execute(update(N).where(*cond).values(read_at=_now()))
    db.commit()
    return {"marked_read": r.rowcount, "unread": _unread(db, user)}


class PrefItem(BaseModel):
    category: str = Field(max_length=20)
    in_app: bool = True
    email: bool = True


class PrefInput(BaseModel):
    preferences: list[PrefItem] = Field(max_length=20)


def _prefs_view(db: Session, user: models.User) -> list[dict]:
    cur = prefs_for(db, user.id)
    return [{"category": c, "label": label, "in_app": cur[c][0], "email": cur[c][1],
             "in_app_locked": c in ALWAYS_IN_APP} for c, label in CATEGORIES.items()]


@router.get("/preferences")
def get_preferences(db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    return {"preferences": _prefs_view(db, user), "has_email": bool(user.email or user.student_id)}


@router.put("/preferences")
def put_preferences(data: PrefInput, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    ok, retry = limiter.check_and_record(f"prefs:{user.id}", 60, 3600)
    if not ok:
        raise HTTPException(status_code=429, detail="Too many changes. Try again later.", headers={"Retry-After": str(retry)})
    for item in data.preferences:
        if item.category not in CATEGORIES:
            raise HTTPException(status_code=422, detail=f"Unknown category: {item.category}")
        if item.category in ALWAYS_IN_APP and not item.in_app:
            raise HTTPException(status_code=422, detail="Account and security notices cannot be switched off in the application")
    for item in data.preferences:
        p = db.scalar(select(models.NotificationPreference).where(models.NotificationPreference.user_id == user.id,
                                                                  models.NotificationPreference.category == item.category))
        if p:
            p.in_app, p.email = item.in_app, item.email
        else:
            db.add(models.NotificationPreference(user_id=user.id, category=item.category, in_app=item.in_app, email=item.email))
    db.commit()
    return {"preferences": _prefs_view(db, user)}


@router.get("/{notification_id}")
def get_one(notification_id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    return _view(_own(db, user, notification_id))


@router.post("/{notification_id}/read")
def mark_read(notification_id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    n = _own(db, user, notification_id)
    if n.read_at is None:
        n.read_at = _now()
        db.commit()
    return {**_view(n), "unread": _unread(db, user)}


@router.post("/{notification_id}/unread")
def mark_unread(notification_id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    n = _own(db, user, notification_id)
    n.read_at = None
    db.commit()
    return {**_view(n), "unread": _unread(db, user)}


@router.post("/{notification_id}/archive")
def archive(notification_id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    n = _own(db, user, notification_id)
    n.archived_at = n.archived_at or _now()
    db.commit()
    return {**_view(n), "unread": _unread(db, user)}


@router.post("/{notification_id}/unarchive")
def unarchive(notification_id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    n = _own(db, user, notification_id)
    n.archived_at = None
    db.commit()
    return {**_view(n), "unread": _unread(db, user)}


@router.delete("/{notification_id}")
def delete_one(notification_id: int, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    n = _own(db, user, notification_id)
    n.deleted_at = _now()    # soft delete: the event key stays, so a repeated action / scheduler run cannot bring it back
    db.commit()
    return {"deleted": notification_id, "unread": _unread(db, user)}
