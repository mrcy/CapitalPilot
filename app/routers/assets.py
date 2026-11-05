from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..database import get_db
from ..errors import NotFoundError, ValidationFailure
from ..schemas import AssetIn, ConfirmIn, PriceSourceIn, TargetWeightsIn
from ..services import assets as svc
from ..services import clock, summary
from ..services.finance.valuation import value_portfolio
from ..services.purge import check_purge, request_purge
from ..services.repository import get_settings_row, load_dataset, resolve_portfolio
from ..services.transactions import tx_to_dict
from ..services.backup import save_db_backup

router = APIRouter(prefix="/api/assets", tags=["assets"])


def _get(db: Session, asset_id: int) -> m.Asset:
    a = db.get(m.Asset, asset_id)
    if a is None:
        raise NotFoundError("دارایی یافت نشد.")
    return a


def latest_price_info(db: Session, asset_id: int, max_age_days: int) -> dict | None:
    """آخرین قیمت تأییدشدهٔ معتبر؛ اگر قدیمی باشد با stale=True علامت می‌خورد (هرگز به‌عنوان قیمت روز نمایش داده نمی‌شود)."""
    p = db.scalar(select(m.Price).where(m.Price.asset_id == asset_id, m.Price.is_approved.is_(True), m.Price.is_valid.is_(True))
                  .order_by(m.Price.recorded_at.desc(), m.Price.id.desc()).limit(1))
    if p is None:
        return None
    age = (clock.now_local().date() - p.recorded_at.date()).days
    return {"price": p.price, "currency": p.currency, "recorded_at": p.recorded_at, "source": p.source, "origin": p.origin,
            "age_days": age, "stale": age > max_age_days}


@router.get("")
def list_assets(
    q: str | None = Query(None, max_length=100), asset_type: str | None = None, platform_id: int | None = None,
    status: str = Query("all", pattern="^(all|live|active|inactive|archived)$"),
    sort: str = Query("order", pattern="^(name|symbol|type|created|weight|order)$"), desc: bool = False,
    page: int = Query(1, ge=1), page_size: int = Query(200, ge=1, le=500), portfolio_id: int | None = None,
    db: Session = Depends(get_db),
):
    ds = load_dataset(db, portfolio_id)
    val = value_portfolio(ds, clock.now_local())
    rows = {r["id"]: r for r in summary.asset_rows(ds, val)}
    weights = {a.id: a for a in ds.assets}
    total, items = svc.list_assets(db, q=q, asset_type=asset_type, platform_id=platform_id, status=status, sort=sort,
                                   desc=desc, page=page, page_size=page_size)
    max_age = ds.config.max_price_age_days
    out = []
    for a in items:
        d = svc.asset_dict(db, a)
        d["position"] = rows.get(a.id)
        rec = weights.get(a.id)
        d["in_portfolio"] = rec is not None
        d["portfolio_target_weight"] = rec.target_weight if rec else None
        d["latest_price"] = latest_price_info(db, a.id, max_age)
        out.append(d)
    return {"assets": out, "total": total, "page": page, "page_size": page_size, "valuation_complete": val.complete}


@router.post("", status_code=201)
def create_asset(payload: AssetIn, db: Session = Depends(get_db)):
    a = svc.create_asset(db, payload)
    return svc.asset_dict(db, a)


@router.put("/target-weights")
def set_target_weights(payload: TargetWeightsIn, portfolio_id: int | None = None, db: Session = Depends(get_db)):
    """سازگاری با نسخهٔ ۱: به‌روزرسانی وزن هدف اعضای یک سبد (پیش‌فرض: سبد اصلی). مجموع فعال‌ها باید ۱۰۰٪ باشد."""
    pf = resolve_portfolio(db, portfolio_id)
    if pf.target_mode != "percent":
        raise ValidationFailure("این سبد با مبلغ ثابت تنظیم شده است؛ از صفحهٔ سبد استفاده کنید.")
    members = {pa.asset_id: pa for pa in db.scalars(select(m.PortfolioAsset).where(m.PortfolioAsset.portfolio_id == pf.id))}
    for aid in payload.weights:
        if aid not in members:
            raise NotFoundError(f"دارایی {aid} عضو این سبد نیست.")
    merged = {aid: payload.weights.get(aid, pa.target_weight) for aid, pa in members.items() if pa.is_active}
    total = sum(merged.values(), Decimal(0))
    if total != 100:
        raise ValidationFailure(f"مجموع وزن‌های هدف دارایی‌های فعال باید دقیقاً ۱۰۰٪ باشد (اکنون {total.normalize():f}٪).")
    for aid, w in payload.weights.items():
        members[aid].target_weight = w
        if pf.is_default:
            members[aid].asset.target_weight = w
    db.commit()
    return {"ok": True, "sum": total}


@router.get("/{asset_id}")
def asset_detail(asset_id: int, portfolio_id: int | None = None, db: Session = Depends(get_db)):
    a = _get(db, asset_id)
    ds = load_dataset(db, portfolio_id)
    now = clock.now_local()
    val = value_portfolio(ds, now)
    rows = {r["id"]: r for r in summary.asset_rows(ds, val)}
    d = svc.asset_dict(db, a)
    d["position"] = rows.get(a.id) or {"units": 0, "value": 0, "quote": None}
    d["fx_effect"] = next((v.fx_effect for v in val.assets if v.asset.id == a.id), None)
    cal = ds.config.calendar
    pf = resolve_portfolio(db, portfolio_id)
    d["portfolio"] = {"id": pf.id, "name": pf.name}
    d["transactions"] = [tx_to_dict(t, cal) for t in db.scalars(
        select(m.Transaction).where(m.Transaction.asset_id == a.id, m.Transaction.portfolio_id == pf.id)
        .order_by(m.Transaction.tx_date.desc(), m.Transaction.id.desc()))]
    d["prices"] = [price_dict(p) for p in db.scalars(
        select(m.Price).where(m.Price.asset_id == a.id).order_by(m.Price.recorded_at.desc(), m.Price.id.desc()).limit(120))]
    d["latest_price"] = latest_price_info(db, a.id, ds.config.max_price_age_days)
    d["dependencies"] = svc.dependencies(db, a)
    d["valuation_complete"] = val.complete
    return d


def price_dict(p: m.Price) -> dict:
    return {"id": p.id, "price": p.price, "currency": p.currency, "recorded_at": p.recorded_at, "source": p.source,
            "is_approved": p.is_approved, "is_valid": p.is_valid, "validity_note": p.validity_note,
            "provider_id": p.provider_id, "fetched_at": p.fetched_at, "source_time": p.source_time,
            "price_kind": p.price_kind, "note": p.note}


@router.put("/{asset_id}")
def update_asset(asset_id: int, payload: AssetIn, db: Session = Depends(get_db)):
    a = _get(db, asset_id)
    svc.update_asset(db, a, payload)
    return svc.asset_dict(db, a)


@router.post("/{asset_id}/active")
def set_active(asset_id: int, active: bool, db: Session = Depends(get_db)):
    a = _get(db, asset_id)
    a.is_active = active
    db.commit()
    return svc.asset_dict(db, a)


@router.post("/{asset_id}/archive")
def archive(asset_id: int, db: Session = Depends(get_db)):
    return svc.asset_dict(db, svc.archive_asset(db, _get(db, asset_id), True))


@router.post("/{asset_id}/restore")
def restore(asset_id: int, db: Session = Depends(get_db)):
    return svc.asset_dict(db, svc.archive_asset(db, _get(db, asset_id), False))


@router.get("/{asset_id}/dependencies")
def dependencies(asset_id: int, db: Session = Depends(get_db)):
    a = _get(db, asset_id)
    dep = svc.dependencies(db, a)
    return {"asset_id": a.id, "name": a.name, "dependencies": dep, "can_delete": dep["transactions"] == 0 and dep["prices"] == 0,
            "can_purge": dep["transactions"] == 0, "archive_only": dep["transactions"] > 0}


@router.delete("/{asset_id}")
def delete_asset(asset_id: int, db: Session = Depends(get_db)):
    svc.delete_asset(db, _get(db, asset_id))
    return {"ok": True}


@router.post("/{asset_id}/purge/request")
def purge_request(asset_id: int, db: Session = Depends(get_db)):
    a = _get(db, asset_id)
    dep = svc.dependencies(db, a)
    if dep["transactions"]:
        raise ValidationFailure("دارایی دارای تراکنش هرگز حذف دائمی نمی‌شود؛ فقط بایگانی.", code="has_transactions", details=dep)
    return request_purge("asset", a.id, dep)


@router.post("/{asset_id}/purge/confirm")
def purge_confirm(asset_id: int, payload: ConfirmIn, db: Session = Depends(get_db)):
    a = _get(db, asset_id)
    check_purge("asset", a.id, payload.token, payload.phrase)
    backup = save_db_backup(db, "pre-purge")
    dep = svc.purge_asset(db, a)
    return {"ok": True, "removed": dep, "backup": backup}


@router.put("/{asset_id}/price-sources")
def set_price_sources(asset_id: int, sources: list[PriceSourceIn], db: Session = Depends(get_db)):
    a = _get(db, asset_id)
    svc._apply_sources(db, a, sources)
    db.commit()
    return svc.asset_dict(db, a)["sources"]


@router.post("/{asset_id}/refresh-price")
def refresh_price(asset_id: int, all_sources: bool = False, db: Session = Depends(get_db)):
    from ..services.marketdata.engine import get_engine
    a = _get(db, asset_id)
    return get_engine().refresh_asset(db, a, force=True, all_sources=all_sources)
