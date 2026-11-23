"""Administrative hall directory, announcements and student-facing timetable."""
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .. import models, doc_models, audit, notifications as notify
from ..database import get_db
from ..deps import require_roles, department_scope
from ..permissions import ROLES

router = APIRouter(prefix="/api", tags=["Campus and announcements"])

class HallInput(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    display_name: str | None = Field(default=None, max_length=150)
    building: str | None = Field(default=None, max_length=100)
    block: str | None = Field(default=None, max_length=50)
    floor: str | None = Field(default=None, max_length=20)
    room: str | None = Field(default=None, max_length=50)
    capacity: int | None = Field(default=None, ge=1, le=10000)
    notes: str | None = Field(default=None, max_length=2000)
    building_id: int | None = None
    block_id: int | None = None
    floor_id: int | None = None

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value):
        return value.strip().upper()

class AnnouncementInput(BaseModel):
    title: str = Field(min_length=3, max_length=180)
    body: str = Field(min_length=1, max_length=10000)
    published: bool = False
    publish_at: datetime | None = None
    expires_at: datetime | None = None
    # Phase 6: targeting and delivery (all optional; omitted = old behaviour, public, no notification)
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    audience_roles: list[str] | None = Field(default=None, max_length=5)
    audience_department: str | None = Field(default=None, max_length=100)
    audience_year: int | None = Field(default=None, ge=1, le=8)
    notify: bool = False
    remind_at: datetime | None = None

    @field_validator("audience_roles")
    @classmethod
    def roles_valid(cls, value):
        if value is None:
            return None
        bad = [r for r in value if r not in ROLES]
        if bad:
            raise ValueError("Unknown role: " + ", ".join(bad))
        return sorted(set(value)) or None

    @field_validator("title", "body")
    @classmethod
    def strip_text(cls, value):
        return value.strip()

    @field_validator("publish_at", "expires_at", "remind_at")
    @classmethod
    def normalize_utc(cls, value):
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Publication and expiry timestamps must include a timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def dates_valid(self):
        if self.publish_at and self.expires_at and self.expires_at <= self.publish_at:
            raise ValueError("Expiry must be later than publication")
        if self.remind_at and ((self.publish_at and self.remind_at < self.publish_at) or (self.expires_at and self.remind_at >= self.expires_at)):
            raise ValueError("The reminder must fall between publication and expiry")
        if self.audience_department is not None:
            self.audience_department = self.audience_department.strip() or None
        return self

def _validate_hierarchy(db, data):
    if data.building_id and not db.get(models.Building, data.building_id):
        raise HTTPException(422,"Unknown building")
    if data.block_id:
        block=db.get(models.Block,data.block_id)
        if not block or not data.building_id or block.building_id != data.building_id:
            raise HTTPException(422,"Block must belong to the selected building")
    if data.floor_id:
        floor=db.get(models.Floor,data.floor_id)
        if not floor or not data.block_id or floor.block_id != data.block_id:
            raise HTTPException(422,"Floor must belong to the selected block")
    if data.block_id and data.building_id:
        block=db.get(models.Block,data.block_id)
        if block and block.building_id != data.building_id:
            raise HTTPException(422,"Block does not belong to the selected building")

@router.get("/admin/buildings")
def list_buildings(db:Session=Depends(get_db),user:models.User=Depends(require_roles("admin","staff"))):
    return [{"id":b.id,"code":b.code,"name":b.name,"address":b.address,"active":b.active} for b in db.scalars(select(models.Building).order_by(models.Building.code)).all()]

@router.post("/admin/buildings",status_code=201)
def create_building(data:dict,request:Request,db:Session=Depends(get_db),user:models.User=Depends(require_roles("admin"))):
    code=str(data.get("code","")).strip().upper(); name=str(data.get("name","")).strip(); address=data.get("address")
    if not code or len(code)>40 or not name or len(name)>150: raise HTTPException(422,"Building code and name are required")
    if db.scalar(select(models.Building).where(models.Building.code==code)): raise HTTPException(409,"Building code already exists")
    b=models.Building(code=code,name=name,address=str(address)[:300] if address else None); db.add(b); db.flush()
    audit.record(db,user.username,"building.created",b.code,request=request,role=user.role); db.commit(); return {"id":b.id,"code":b.code,"name":b.name}

@router.get("/admin/buildings/{building_id}/blocks")
def list_blocks(building_id:int,db:Session=Depends(get_db),user:models.User=Depends(require_roles("admin","staff"))):
    if not db.get(models.Building,building_id): raise HTTPException(404,"Building not found")
    return [{"id":b.id,"building_id":b.building_id,"code":b.code,"name":b.name,"active":b.active} for b in db.scalars(select(models.Block).where(models.Block.building_id==building_id).order_by(models.Block.code)).all()]

@router.get("/admin/blocks/{block_id}/floors")
def list_floors(block_id:int,db:Session=Depends(get_db),user:models.User=Depends(require_roles("admin","staff"))):
    if not db.get(models.Block,block_id): raise HTTPException(404,"Block not found")
    return [{"id":f.id,"block_id":f.block_id,"code":f.code,"name":f.name,"active":f.active} for f in db.scalars(select(models.Floor).where(models.Floor.block_id==block_id).order_by(models.Floor.code)).all()]

@router.post("/admin/buildings/{building_id}/blocks",status_code=201)
def create_block(building_id:int,data:dict,request:Request,db:Session=Depends(get_db),user:models.User=Depends(require_roles("admin"))):
    building=db.get(models.Building,building_id); code=str(data.get("code","")).strip().upper(); name=str(data.get("name","")).strip()
    if not building: raise HTTPException(404,"Building not found")
    if not code or not name: raise HTTPException(422,"Block code and name are required")
    if db.scalar(select(models.Block).where(models.Block.building_id==building_id,models.Block.code==code)): raise HTTPException(409,"Block already exists")
    b=models.Block(building_id=building_id,code=code,name=name); db.add(b); db.flush(); audit.record(db,user.username,"block.created",b.code,{"building_id":building_id},request,user.role); db.commit(); return {"id":b.id,"code":b.code,"name":b.name}

@router.post("/admin/blocks/{block_id}/floors",status_code=201)
def create_floor(block_id:int,data:dict,request:Request,db:Session=Depends(get_db),user:models.User=Depends(require_roles("admin"))):
    block=db.get(models.Block,block_id); code=str(data.get("code","")).strip().upper(); name=str(data.get("name","")).strip()
    if not block: raise HTTPException(404,"Block not found")
    if not code or not name: raise HTTPException(422,"Floor code and name are required")
    if db.scalar(select(models.Floor).where(models.Floor.block_id==block_id,models.Floor.code==code)): raise HTTPException(409,"Floor already exists")
    f=models.Floor(block_id=block_id,code=code,name=name); db.add(f); db.flush(); audit.record(db,user.username,"floor.created",f.code,{"block_id":block_id},request,user.role); db.commit(); return {"id":f.id,"code":f.code,"name":f.name}

def _hall(h, db=None):
    building=db.get(models.Building,h.building_id) if db and h.building_id else None
    block=db.get(models.Block,h.block_id) if db and h.block_id else None
    floor=db.get(models.Floor,h.floor_id) if db and h.floor_id else None
    return {"id":h.id,"code":h.code,"display_name":h.display_name,
            "building":building.name if building else h.building,"block":block.name if block else h.block,
            "floor":floor.name if floor else h.floor,"room":h.room,"capacity":h.capacity,"verified":h.verified,"notes":h.notes,
            "building_id":h.building_id,"block_id":h.block_id,"floor_id":h.floor_id}

@router.get("/halls")
def halls(db: Session=Depends(get_db)):
    return [_hall(h,db) for h in db.scalars(select(doc_models.Hall).order_by(doc_models.Hall.building, doc_models.Hall.code)).all() if h.verified]

@router.get("/admin/halls")
def admin_halls(db: Session=Depends(get_db), user: models.User=Depends(require_roles("admin","staff"))):
    return [_hall(h,db) for h in db.scalars(select(doc_models.Hall).order_by(doc_models.Hall.code)).all()]

@router.post("/admin/halls", status_code=201)
def create_hall(data: HallInput, request: Request, db: Session=Depends(get_db), user: models.User=Depends(require_roles("admin"))):
    _validate_hierarchy(db, data)
    h=doc_models.Hall(**data.model_dump(), verified=False)
    db.add(h)
    try: db.flush()
    except IntegrityError:
        db.rollback(); raise HTTPException(409,"Hall code already exists")
    audit.record(db,user.username,"hall.created",h.code,request=request,role=user.role); db.commit()
    return _hall(h,db)

@router.patch("/admin/halls/{hall_id}")
def update_hall(hall_id:int,data:HallInput,request:Request,db:Session=Depends(get_db),user:models.User=Depends(require_roles("admin"))):
    h=db.get(doc_models.Hall,hall_id)
    if not h: raise HTTPException(404,"Hall not found")
    _validate_hierarchy(db, data)
    old_identity=(h.code,h.building,h.block,h.floor,h.room,h.building_id,h.block_id,h.floor_id,h.capacity)
    for k,v in data.model_dump().items(): setattr(h,k,v)
    new_identity=(h.code,h.building,h.block,h.floor,h.room,h.building_id,h.block_id,h.floor_id,h.capacity)
    if old_identity != new_identity: h.verified=False; h.verified_by=None; h.verified_at=None
    audit.record(db,user.username,"hall.updated",str(h.id),{"fields":sorted(data.model_fields_set)},request,user.role); db.commit()
    return _hall(h,db)

@router.post("/admin/halls/{hall_id}/verify")
def verify_hall(hall_id:int,request:Request,db:Session=Depends(get_db),user:models.User=Depends(require_roles("admin"))):
    h=db.get(doc_models.Hall,hall_id)
    if not h: raise HTTPException(404,"Hall not found")
    h.verified=True; h.verified_by=user.username; h.verified_at=datetime.now(timezone.utc)
    audit.record(db,user.username,"hall.verified",h.code,request=request,role=user.role); db.commit()
    return _hall(h,db)

def _is_targeted(a: models.Announcement) -> bool:
    return bool(a.audience_roles or a.audience_department or a.audience_year)


@router.get("/announcements")
def public_announcements(db:Session=Depends(get_db)):
    """Public list. Targeted announcements (specific roles/department/year) are delivered to those users as
    notifications and are never shown on the public page."""
    now=datetime.now(timezone.utc)
    rows=db.scalars(select(models.Announcement).where(models.Announcement.published==True).order_by(models.Announcement.publish_at.desc().nullslast()).limit(100)).all()  # noqa: E712
    def active(a):
        pub=a.publish_at.replace(tzinfo=timezone.utc) if a.publish_at and a.publish_at.tzinfo is None else a.publish_at
        exp=a.expires_at.replace(tzinfo=timezone.utc) if a.expires_at and a.expires_at.tzinfo is None else a.expires_at
        return (not pub or pub<=now) and (not exp or exp>now)
    return [{"id":a.id,"title":a.title,"body":a.body,"published_at":a.publish_at.isoformat() if a.publish_at else a.created_at.isoformat()} for a in rows if active(a) and not _is_targeted(a)]

def _ann_view(a: models.Announcement) -> dict:
    iso=lambda d: d.isoformat() if d else None
    return {"id":a.id,"title":a.title,"body":a.body,"published":a.published,"publish_at":iso(a.publish_at),"expires_at":iso(a.expires_at),
            "priority":a.priority or "normal","audience_roles":[r for r in (a.audience_roles or "").split(",") if r],
            "audience_department":a.audience_department,"audience_year":a.audience_year,"notify":bool(a.notify),
            "notified_at":iso(a.notified_at),"remind_at":iso(a.remind_at),"reminded_at":iso(a.reminded_at),"created_by":a.created_by}

@router.get("/admin/announcements")
def admin_announcements(db:Session=Depends(get_db),user:models.User=Depends(require_roles("admin","staff"))):
    rows=db.scalars(select(models.Announcement).order_by(models.Announcement.created_at.desc()).limit(200)).all()
    return [_ann_view(a) for a in rows]

def _apply_targeting(data: AnnouncementInput, values: dict, user: models.User) -> dict:
    """Department staff may only notify their own department's students; institution-wide or role-wide
    notification is an administrator action."""
    values["audience_roles"]=",".join(values["audience_roles"]) if values.get("audience_roles") else None
    if user.role=="staff":
        dept=department_scope(user)
        if values.get("notify"):
            if not dept:
                raise HTTPException(403,"Only administrators can notify users. Department staff need an assigned department.")
            values.update(audience_roles="student",audience_department=dept)
        elif values.get("audience_roles") or values.get("audience_department") or values.get("audience_year"):
            raise HTTPException(403,"Only administrators can target an announcement. Staff announcements are public or notify their own department.")
    return values

@router.post("/admin/announcements",status_code=201)
def create_announcement(data:AnnouncementInput,request:Request,db:Session=Depends(get_db),user:models.User=Depends(require_roles("admin","staff"))):
    a=models.Announcement(**_apply_targeting(data,data.model_dump(),user),created_by=user.username); db.add(a); db.flush()
    audit.record(db,user.username,"announcement.created",str(a.id),{"published":a.published,"notify":a.notify,"targeted":_is_targeted(a)},request,user.role); db.commit()
    notify.notify_announcement(db,a)
    return {"id":a.id}

@router.patch("/admin/announcements/{announcement_id}")
def update_announcement(announcement_id:int,data:AnnouncementInput,request:Request,db:Session=Depends(get_db),user:models.User=Depends(require_roles("admin","staff"))):
    a=db.get(models.Announcement,announcement_id)
    if not a: raise HTTPException(404,"Announcement not found")
    values=data.model_dump()
    # fields an older client does not send keep their stored value
    for k in ("priority","audience_roles","audience_department","audience_year","notify","remind_at"):
        if k not in data.model_fields_set: values.pop(k)
    values=_apply_targeting(data,values,user) if any(k in values for k in ("audience_roles","notify")) else values
    if "audience_roles" in values and not isinstance(values["audience_roles"],(str,type(None))): values["audience_roles"]=",".join(values["audience_roles"])
    if "remind_at" in values and values["remind_at"]!=a.remind_at: a.reminded_at=None
    for k,v in values.items(): setattr(a,k,v)
    audit.record(db,user.username,"announcement.updated",str(a.id),{"fields":sorted(data.model_fields_set)},request,user.role); db.commit()
    notify.notify_announcement(db,a)      # sends at most once per announcement (notified_at)
    return {"id":a.id,"updated":True}

@router.delete("/admin/announcements/{announcement_id}")
def delete_announcement(announcement_id:int,request:Request,db:Session=Depends(get_db),user:models.User=Depends(require_roles("admin"))):
    a=db.get(models.Announcement,announcement_id)
    if not a: raise HTTPException(404,"Announcement not found")
    audit.record(db,user.username,"announcement.deleted",str(a.id),request=request,role=user.role); db.delete(a); db.commit(); return {"deleted":announcement_id}


@router.post("/admin/halls/{hall_id}/seats/generate")
def generate_hall_seats(hall_id:int,request:Request,db:Session=Depends(get_db),user:models.User=Depends(require_roles("admin"))):
    hall=db.get(doc_models.Hall,hall_id)
    if not hall: raise HTTPException(404,"Hall not found")
    if not hall.capacity or hall.capacity<1: raise HTTPException(422,"Set a valid hall capacity first")
    existing=db.scalar(select(models.HallSeat.id).where(models.HallSeat.hall_id==hall_id).limit(1))
    if existing: raise HTTPException(409,"Seat inventory already exists; it will not be overwritten")
    db.add_all([models.HallSeat(hall_id=hall_id,seat_label=str(n),active=True) for n in range(1,hall.capacity+1)])
    audit.record(db,user.username,"hall.seats_generated",hall.code,{"capacity":hall.capacity},request,user.role); db.commit()
    return {"hall_id":hall_id,"seats_created":hall.capacity}

@router.get("/admin/halls/{hall_id}/seats")
def list_hall_seats(hall_id:int,db:Session=Depends(get_db),user:models.User=Depends(require_roles("admin","staff"))):
    hall=db.get(doc_models.Hall,hall_id)
    if not hall: raise HTTPException(404,"Hall not found")
    rows=db.scalars(select(models.HallSeat).where(models.HallSeat.hall_id==hall_id).order_by(models.HallSeat.seat_label)).all()
    return [{"id":s.id,"seat_label":s.seat_label,"active":s.active} for s in rows]
