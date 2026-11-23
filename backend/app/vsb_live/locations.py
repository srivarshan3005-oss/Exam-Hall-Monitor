"""Verified building / block / floor / room / map data for a hall.

Nothing is invented: a hall's location is shown to students ONLY when an administrator marked the hall `verified`, and each
value is shown only if it is actually stored. Map coordinates and directions need a recorded source. Otherwise the portal says
"Building/floor location has not yet been verified." and draws no map.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import doc_models as dm, models

NOT_VERIFIED_TEXT = "Building/floor location has not yet been verified."


def _norm(code: str | None) -> str:
    return " ".join((code or "").upper().split())


def valid_coord(lat, lon) -> bool:
    try:
        return lat is not None and lon is not None and -90 <= float(lat) <= 90 and -180 <= float(lon) <= 180 \
            and not (math.isnan(float(lat)) or math.isnan(float(lon)))
    except (TypeError, ValueError):
        return False


def find_hall(db: Session, code: str | None) -> dm.Hall | None:
    if not code:
        return None
    return db.scalar(select(dm.Hall).where(func.upper(func.trim(dm.Hall.code)) == _norm(code)))


def public_location(db: Session, hall_code: str | None) -> dict:
    """What a student may see about where a hall is. {} when nothing verified exists."""
    hall = find_hall(db, hall_code)
    if not (hall and hall.verified):
        return {}
    building = db.get(models.Building, hall.building_id) if hall.building_id else None
    block = db.get(models.Block, hall.block_id) if hall.block_id else None
    floor = db.get(models.Floor, hall.floor_id) if hall.floor_id else None
    out: dict = {k: v for k, v in {
        "building": building.name if building else hall.building,
        "block": block.name if block else hall.block,
        "floor": floor.name if floor else hall.floor,
        "room": hall.room}.items() if v is not None and str(v).strip()}
    if hall.directions and hall.directions.strip() and hall.location_source:
        out["directions"] = hall.directions.strip()
    if valid_coord(hall.latitude, hall.longitude) and hall.location_source:
        m: dict = {"latitude": float(hall.latitude), "longitude": float(hall.longitude), "label": hall.display_name or hall.code,
                   "osm_url": f"https://www.openstreetmap.org/?mlat={float(hall.latitude):.6f}&mlon={float(hall.longitude):.6f}"
                              f"#map=19/{float(hall.latitude):.6f}/{float(hall.longitude):.6f}"}
        ent = db.get(dm.CampusPoint, hall.entrance_id) if hall.entrance_id else None
        if ent and ent.verified and valid_coord(ent.latitude, ent.longitude):
            m["entrance"] = {"name": ent.name, "latitude": float(ent.latitude), "longitude": float(ent.longitude)}
        out["map"] = m
    if out and hall.location_source:
        out["source"] = hall.location_source
    return out


def hall_dict(db: Session, h: dm.Hall) -> dict:
    iso = lambda d: d.isoformat() if d else None  # noqa: E731
    return {"id": h.id, "code": h.code, "display_name": h.display_name, "building": h.building, "block": h.block, "floor": h.floor,
            "room": h.room, "building_id": h.building_id, "block_id": h.block_id, "floor_id": h.floor_id, "capacity": h.capacity,
            "latitude": h.latitude, "longitude": h.longitude, "directions": h.directions, "location_source": h.location_source,
            "entrance_id": h.entrance_id, "verified": bool(h.verified), "verified_by": h.verified_by, "verified_at": iso(h.verified_at),
            "notes": h.notes}


LOCATION_FIELDS = ("display_name", "building", "block", "floor", "room", "latitude", "longitude", "directions",
                   "location_source", "entrance_id", "notes")


def record_change(db: Session, hall: dm.Hall, actor: str, action: str, before: dict | None, source: str | None) -> None:
    after = {k: getattr(hall, k) for k in LOCATION_FIELDS} | {"verified": bool(hall.verified)}
    db.add(dm.HallLocationHistory(hall_id=hall.id, actor=actor[:80], action=action[:20],
                                  before=json.dumps(before, default=str) if before is not None else None,
                                  after=json.dumps(after, default=str), source=(source or None) and source[:300],
                                  created_at=datetime.now(timezone.utc)))


def snapshot(hall: dm.Hall) -> dict:
    return {k: getattr(hall, k) for k in LOCATION_FIELDS} | {"verified": bool(hall.verified)}
