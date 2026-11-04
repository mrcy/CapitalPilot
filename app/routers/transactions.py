from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from .. import models as m
from ..database import get_db
from ..errors import NotFoundError
from ..schemas import TransactionIn
from ..services import transactions as svc
from ..services.repository import get_settings_row

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


@router.get("")
def list_transactions(
    tx_type: str | None = None, platform_id: int | None = None, asset_id: int | None = None,
    date_from: date | None = None, date_to: date | None = None, q: str | None = Query(None, max_length=100),
    limit: int = Query(200, ge=1, le=2000), offset: int = Query(0, ge=0), db: Session = Depends(get_db),
):
    cond = []
    if tx_type:
        cond.append(m.Transaction.tx_type == tx_type)
    if platform_id:
        cond.append(m.Transaction.platform_id == platform_id)
    if asset_id:
        cond.append(m.Transaction.asset_id == asset_id)
    if date_from:
        cond.append(m.Transaction.tx_date >= date_from)
    if date_to:
        cond.append(m.Transaction.tx_date <= date_to)
    if q:
        like = f"%{q}%"
        cond.append(or_(m.Transaction.note.like(like), m.Transaction.asset.has(m.Asset.name.like(like))))
    total = db.scalar(select(func.count()).select_from(m.Transaction).where(*cond))
    rows = db.scalars(select(m.Transaction).where(*cond).options(joinedload(m.Transaction.asset), joinedload(m.Transaction.platform))
                      .order_by(m.Transaction.tx_date.desc(), m.Transaction.id.desc()).limit(limit).offset(offset)).all()
    cal = get_settings_row(db).calendar
    return {"total": total, "items": [svc.tx_to_dict(t, cal) for t in rows]}


@router.post("", status_code=201)
def create(payload: TransactionIn, db: Session = Depends(get_db)):
    t, warnings = svc.create_transaction(db, payload.model_dump())
    return {"transaction": svc.tx_to_dict(t), "warnings": warnings}


@router.get("/{tx_id}")
def get_one(tx_id: int, db: Session = Depends(get_db)):
    t = db.get(m.Transaction, tx_id)
    if t is None:
        raise NotFoundError("تراکنش یافت نشد.")
    return svc.tx_to_dict(t)


@router.put("/{tx_id}")
def update(tx_id: int, payload: TransactionIn, db: Session = Depends(get_db)):
    t, warnings = svc.update_transaction(db, tx_id, payload.model_dump())
    return {"transaction": svc.tx_to_dict(t), "warnings": warnings}


@router.delete("/{tx_id}")
def delete(tx_id: int, db: Session = Depends(get_db)):
    return {"ok": True, "warnings": svc.delete_transaction(db, tx_id)}
