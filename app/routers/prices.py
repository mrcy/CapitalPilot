from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .. import models as m
from ..database import get_db
from ..errors import NotFoundError, ValidationFailure
from ..schemas import FxIn, PriceIn
from ..services import clock, prices as svc
from ..services.finance.valuation import make_book
from ..services.marketdata import quality
from ..services.repository import load_dataset

router = APIRouter(prefix="/api", tags=["prices"])


def _json(t):
    import json
    try:
        return json.loads(t or "[]")
    except ValueError:
        return []


def price_dict(p: m.Price) -> dict:
    return {"id": p.id, "asset_id": p.asset_id, "asset": p.asset.name if p.asset else None, "price": p.price,
            "currency": p.currency, "recorded_at": p.recorded_at, "source": p.source, "is_approved": p.is_approved,
            "is_valid": p.is_valid, "validity_note": p.validity_note, "provider_id": p.provider_id,
            "fetched_at": p.fetched_at, "source_time": p.source_time, "price_kind": p.price_kind, "note": p.note,
            "origin": p.origin, "raw_price": p.raw_price, "raw_unit": p.raw_unit, "conversion_note": p.conversion_note,
            "quality_flags": quality.flags_of(p), "via": _json(p.via), "user_confirmed": p.user_confirmed,
            "upstream_source": p.upstream_source, "upstream_checked_at": p.upstream_checked_at, "snapshot_id": p.snapshot_id}


def fx_dict(r: m.FxRate) -> dict:
    return {"id": r.id, "currency": r.currency, "rate": r.rate, "recorded_at": r.recorded_at, "source": r.source,
            "is_approved": r.is_approved, "note": r.note}


@router.get("/prices")
def list_prices(asset_id: int | None = None, approved: bool | None = None, provider_id: int | None = None,
                valid: bool | None = None, limit: int = Query(300, ge=1, le=3000),
                db: Session = Depends(get_db)):
    q = select(m.Price).options(joinedload(m.Price.asset)).order_by(m.Price.recorded_at.desc(), m.Price.id.desc()).limit(limit)
    if asset_id:
        q = q.where(m.Price.asset_id == asset_id)
    if approved is not None:
        q = q.where(m.Price.is_approved.is_(approved))
    if provider_id:
        q = q.where(m.Price.provider_id == provider_id)
    if valid is not None:
        q = q.where(m.Price.is_valid.is_(valid))
    return [price_dict(p) for p in db.scalars(q)]


@router.get("/prices/current")
def current_prices(db: Session = Depends(get_db)):
    """وضعیت «قیمت روز» هر دارایی؛ قیمت قدیمی/نامعتبر به‌عنوان قیمت روز برنگردانده می‌شود."""
    ds = load_dataset(db)
    book = make_book(ds)
    now = clock.now_local()
    out = []
    for a in ds.assets:
        q = book.quote(a, now)
        latest = db.scalar(select(m.Price).where(m.Price.asset_id == a.id, m.Price.is_approved.is_(True), m.Price.is_valid.is_(True))
                           .order_by(m.Price.recorded_at.desc(), m.Price.id.desc()).limit(1))
        out.append({"source": latest.source if latest else None, "origin": latest.origin if latest else None, "asset_id": a.id, "asset": a.name, "active": a.active, "currency": a.price_currency, "ok": q.ok,
                    "price": q.price_irt, "native_price": q.native_price, "fx_rate": q.fx_rate, "recorded_at": q.recorded_at,
                    "age_days": q.age_days, "reason": q.reason, "reason_text": q.reason_text,
                    "last_price": q.last_price, "last_recorded_at": q.last_recorded_at})
    pending = db.scalar(select(m.Price.id).where(m.Price.is_approved.is_(False)).limit(1)) is not None
    return {"items": out, "max_age_days": ds.config.max_price_age_days, "has_pending": pending}


@router.post("/prices", status_code=201)
def create_price(payload: PriceIn, db: Session = Depends(get_db)):
    return price_dict(svc.create_price(db, payload.model_dump()))


@router.put("/prices/{price_id}")
def update_price(price_id: int, payload: PriceIn, db: Session = Depends(get_db)):
    return price_dict(svc.update_price(db, price_id, payload.model_dump()))


@router.post("/prices/{price_id}/approve")
def approve_price(price_id: int, approved: bool = True, db: Session = Depends(get_db)):
    p = db.get(m.Price, price_id)
    if p is None:
        raise NotFoundError("قیمت یافت نشد.")
    if approved and not p.is_valid:
        raise ValidationFailure("قیمت نامعتبر قابل تأیید نیست (" + (p.validity_note or "نامعتبر") + ").")
    p.is_approved = approved
    p.user_confirmed = bool(approved)  # تأیید صریح کاربر؛ در اختلاف منابع تصمیم کاربر ارجح است
    db.commit()
    return price_dict(p)


@router.delete("/prices/{price_id}")
def delete_price(price_id: int, db: Session = Depends(get_db)):
    p = db.get(m.Price, price_id)
    if p is None:
        raise NotFoundError("قیمت یافت نشد.")
    db.delete(p)
    db.commit()
    return {"ok": True}


@router.post("/prices/fetch")
def fetch_prices(asset_id: int | None = None, db: Session = Depends(get_db)):
    """دریافت قیمت از منابع پیکربندی‌شدهٔ هر دارایی (اصلی ← جایگزین). نتیجهٔ هر دارایی جداگانه گزارش می‌شود."""
    from ..services.marketdata.engine import get_engine
    return {"results": get_engine().refresh_all(db, [asset_id] if asset_id else None, force=True)}


@router.get("/fx")
def list_fx(currency: str | None = None, limit: int = Query(300, ge=1, le=3000), db: Session = Depends(get_db)):
    q = select(m.FxRate).order_by(m.FxRate.recorded_at.desc(), m.FxRate.id.desc()).limit(limit)
    if currency:
        q = q.where(m.FxRate.currency == currency.upper())
    return [fx_dict(r) for r in db.scalars(q)]


@router.post("/fx", status_code=201)
def create_fx(payload: FxIn, db: Session = Depends(get_db)):
    return fx_dict(svc.create_fx(db, payload.model_dump()))


@router.post("/fx/{fx_id}/approve")
def approve_fx(fx_id: int, approved: bool = True, db: Session = Depends(get_db)):
    r = db.get(m.FxRate, fx_id)
    if r is None:
        raise NotFoundError("نرخ یافت نشد.")
    r.is_approved = approved
    db.commit()
    return fx_dict(r)


@router.delete("/fx/{fx_id}")
def delete_fx(fx_id: int, db: Session = Depends(get_db)):
    r = db.get(m.FxRate, fx_id)
    if r is None:
        raise NotFoundError("نرخ یافت نشد.")
    db.delete(r)
    db.commit()
    return {"ok": True}
