from __future__ import annotations

import json
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..database import get_db
from ..errors import NotFoundError, ValidationFailure
from ..schemas import AssetIn, TargetWeightsIn
from ..services import clock, summary
from ..services.finance.valuation import value_portfolio
from ..services.repository import load_dataset
from ..services.transactions import tx_to_dict

router = APIRouter(prefix="/api/assets", tags=["assets"])


def asset_dict(a: m.Asset) -> dict:
    try:
        params = json.loads(a.price_provider_params) if a.price_provider_params else None
    except json.JSONDecodeError:
        params = None
    return {"id": a.id, "platform_id": a.platform_id, "name": a.name, "symbol": a.symbol, "asset_type": a.asset_type,
            "target_weight": a.target_weight, "price_currency": a.price_currency, "buy_fee_rate": a.buy_fee_rate,
            "fractional_units": a.fractional_units, "is_active": a.is_active, "price_provider": a.price_provider,
            "price_provider_params": params, "note": a.note, "sort_order": a.sort_order}


def _apply(db: Session, a: m.Asset, p: AssetIn) -> None:
    if db.get(m.Platform, p.platform_id) is None:
        raise NotFoundError("پلتفرم یافت نشد.")
    cur = db.get(m.Currency, p.price_currency.upper())
    if cur is None or not cur.is_active:
        raise ValidationFailure("واحد پول انتخاب‌شده معتبر/فعال نیست.")
    if p.price_provider:
        from ..services.price_providers import REGISTRY
        if p.price_provider not in REGISTRY:
            raise ValidationFailure("ارائه‌دهنده قیمت ناشناخته است.")
    a.platform_id, a.name, a.symbol, a.asset_type = p.platform_id, p.name, p.symbol, p.asset_type
    a.target_weight, a.price_currency, a.buy_fee_rate = p.target_weight, cur.code, p.buy_fee_rate
    a.fractional_units, a.is_active, a.note = p.fractional_units, p.is_active, p.note
    a.price_provider = p.price_provider
    a.price_provider_params = json.dumps(p.price_provider_params, ensure_ascii=False) if p.price_provider_params else ""


@router.get("")
def list_assets(db: Session = Depends(get_db)):
    ds = load_dataset(db)
    val = value_portfolio(ds, clock.now_local())
    rows = {r["id"]: r for r in summary.asset_rows(ds, val)}
    plat = {p.id: p.name for p in ds.platforms}
    out = []
    for a in db.scalars(select(m.Asset).order_by(m.Asset.sort_order, m.Asset.id)):
        d = asset_dict(a)
        d["platform"] = plat.get(a.platform_id, "")
        d["position"] = rows.get(a.id)
        out.append(d)
    return {"assets": out, "valuation_complete": val.complete}


@router.post("", status_code=201)
def create_asset(payload: AssetIn, db: Session = Depends(get_db)):
    a = m.Asset(sort_order=(db.scalar(select(m.Asset.sort_order).order_by(m.Asset.sort_order.desc())) or 0) + 1)
    _apply(db, a, payload)
    db.add(a)
    db.commit()
    return asset_dict(a)


@router.put("/target-weights")
def set_target_weights(payload: TargetWeightsIn, db: Session = Depends(get_db)):
    assets = {a.id: a for a in db.scalars(select(m.Asset))}
    for aid in payload.weights:
        if aid not in assets:
            raise NotFoundError(f"دارایی {aid} یافت نشد.")
    merged = {aid: payload.weights.get(aid, a.target_weight) for aid, a in assets.items() if a.is_active or aid in payload.weights}
    total = sum((w for aid, w in merged.items() if assets[aid].is_active), Decimal(0))
    if total != 100:
        raise ValidationFailure(f"مجموع وزن‌های هدف دارایی‌های فعال باید دقیقاً ۱۰۰٪ باشد (اکنون {total.normalize():f}٪).")
    for aid, w in payload.weights.items():
        assets[aid].target_weight = w
    db.commit()
    return {"ok": True, "sum": total}


@router.get("/{asset_id}")
def asset_detail(asset_id: int, db: Session = Depends(get_db)):
    a = db.get(m.Asset, asset_id)
    if a is None:
        raise NotFoundError("دارایی یافت نشد.")
    ds = load_dataset(db)
    now = clock.now_local()
    val = value_portfolio(ds, now)
    rows = {r["id"]: r for r in summary.asset_rows(ds, val)}
    d = asset_dict(a)
    d["platform"] = a.platform.name
    d["position"] = rows.get(a.id) or {"units": 0, "value": 0, "quote": None}
    fx = next((v.fx_effect for v in val.assets if v.asset.id == a.id), None)
    d["fx_effect"] = fx
    cal = ds.config.calendar
    d["transactions"] = [tx_to_dict(t, cal) for t in db.scalars(
        select(m.Transaction).where(m.Transaction.asset_id == a.id).order_by(m.Transaction.tx_date.desc(), m.Transaction.id.desc()))]
    d["prices"] = [{"id": p.id, "price": p.price, "currency": p.currency, "recorded_at": p.recorded_at, "source": p.source,
                    "is_approved": p.is_approved} for p in db.scalars(
        select(m.Price).where(m.Price.asset_id == a.id).order_by(m.Price.recorded_at.desc()).limit(120))]
    d["valuation_complete"] = val.complete
    return d


@router.put("/{asset_id}")
def update_asset(asset_id: int, payload: AssetIn, db: Session = Depends(get_db)):
    a = db.get(m.Asset, asset_id)
    if a is None:
        raise NotFoundError("دارایی یافت نشد.")
    if a.platform_id != payload.platform_id:
        has_tx = db.scalar(select(m.Transaction.id).where(m.Transaction.asset_id == a.id).limit(1))
        if has_tx:
            raise ValidationFailure("پلتفرم دارایی دارای تراکنش قابل تغییر نیست.")
    _apply(db, a, payload)
    db.commit()
    return asset_dict(a)


@router.post("/{asset_id}/active")
def set_active(asset_id: int, active: bool, db: Session = Depends(get_db)):
    a = db.get(m.Asset, asset_id)
    if a is None:
        raise NotFoundError("دارایی یافت نشد.")
    a.is_active = active
    db.commit()
    return asset_dict(a)
