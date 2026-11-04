"""انواع دارایی و پلتفرم‌ها."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import models as m
from ..database import get_db
from ..schemas import AssetTypeIn, PlatformIn
from ..services import catalog

router = APIRouter(prefix="/api", tags=["catalog"])


@router.get("/asset-types")
def list_types(db: Session = Depends(get_db)):
    return [catalog.type_dict(db, t) for t in db.scalars(select(m.AssetType).order_by(m.AssetType.sort_order, m.AssetType.key))]


@router.post("/asset-types", status_code=201)
def create_type(payload: AssetTypeIn, db: Session = Depends(get_db)):
    return catalog.type_dict(db, catalog.save_type(db, payload))


@router.put("/asset-types/{key}")
def update_type(key: str, payload: AssetTypeIn, db: Session = Depends(get_db)):
    if payload.key != key:
        from ..errors import ValidationFailure
        raise ValidationFailure("کلید نوع دارایی قابل تغییر نیست.")
    return catalog.type_dict(db, catalog.save_type(db, payload, key))


@router.delete("/asset-types/{key}")
def delete_type(key: str, db: Session = Depends(get_db)):
    catalog.delete_type(db, key)
    return {"ok": True}


@router.get("/platforms")
def list_platforms(q: str | None = Query(None, max_length=80), status: str = Query("all", pattern="^(all|live|archived)$"),
                   db: Session = Depends(get_db)):
    stmt = select(m.Platform).order_by(m.Platform.sort_order, m.Platform.id)
    if q:
        stmt = stmt.where(or_(m.Platform.name.like(f"%{q}%"), m.Platform.note.like(f"%{q}%")))
    if status == "live":
        stmt = stmt.where(m.Platform.is_archived.is_(False))
    elif status == "archived":
        stmt = stmt.where(m.Platform.is_archived.is_(True))
    return [catalog.platform_dict(db, p) for p in db.scalars(stmt)]


@router.post("/platforms", status_code=201)
def create_platform(payload: PlatformIn, db: Session = Depends(get_db)):
    return catalog.platform_dict(db, catalog.save_platform(db, payload))


@router.put("/platforms/{pid}")
def update_platform(pid: int, payload: PlatformIn, db: Session = Depends(get_db)):
    return catalog.platform_dict(db, catalog.save_platform(db, payload, pid))


@router.post("/platforms/{pid}/archive")
def archive_platform(pid: int, db: Session = Depends(get_db)):
    return catalog.platform_dict(db, catalog.archive_platform(db, pid, True))


@router.post("/platforms/{pid}/restore")
def restore_platform(pid: int, db: Session = Depends(get_db)):
    return catalog.platform_dict(db, catalog.archive_platform(db, pid, False))


@router.delete("/platforms/{pid}")
def delete_platform(pid: int, db: Session = Depends(get_db)):
    catalog.delete_platform(db, pid)
    return {"ok": True}
