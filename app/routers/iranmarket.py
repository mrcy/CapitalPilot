"""بازار جامع ایران (Iran Market Data): نمادها، دسته‌ها، دریافت دستی، تاریخچه و اتصال نماد به دارایی.

فقط‌خواندنی نسبت به بازار؛ هیچ سفارش خرید/فروشی ارسال نمی‌شود و نمادها هرگز خودکار به دارایی‌ها اضافه نمی‌شوند.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..database import get_db
from ..errors import ConflictError, NotFoundError, ValidationFailure
from ..services.marketdata import iranmarket as im
from ..services.marketdata.base import ProviderError

router = APIRouter(prefix="/api/iran-market", tags=["iran-market"])


class LinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    asset_id: int
    symbol: str = Field(min_length=1, max_length=120)
    confirm: bool = False
    priority: int | None = Field(default=None, ge=1, le=20)


def _asset(db: Session, aid: int) -> m.Asset:
    a = db.get(m.Asset, aid)
    if a is None:
        raise NotFoundError("دارایی یافت نشد.")
    return a


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    return im.overview(db)


@router.get("/symbols")
def symbols(q: str = Query("", max_length=80), category: str = Query("", max_length=60), market: str = Query("", max_length=60),
            currency: str = Query("", max_length=16), status: str = Query("", max_length=16), linked: bool | None = None,
            sort: str = "category", order: str = Query("asc", pattern="^(asc|desc)$"), page: int = Query(1, ge=1),
            page_size: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    return im.list_symbols(db, q=q, category=category, market=market, currency=currency, status=status, linked=linked,
                           sort=sort, order=order, page=page, page_size=page_size)


@router.get("/symbols/{symbol:path}/history")
def symbol_history(symbol: str, days: int = Query(90, ge=7, le=3650), db: Session = Depends(get_db)):
    if db.get(m.MarketSymbol, symbol) is None:
        raise NotFoundError("نماد در داده‌های Iran Market Data پیدا نشد.")
    return im.history(db, symbol, days)


@router.get("/symbols/{symbol:path}/stored-prices")
def stored_prices(symbol: str, limit: int = Query(200, ge=1, le=1000), db: Session = Depends(get_db)):
    """قیمت‌هایی که خود CapitalPilot با زمان و منبع برای دارایی‌های متصل به این نماد ذخیره کرده است."""
    rows = db.scalars(select(m.Price).join(m.AssetPriceSource, m.AssetPriceSource.asset_id == m.Price.asset_id)
                      .join(m.PriceProvider, m.PriceProvider.id == m.AssetPriceSource.provider_id)
                      .where(m.PriceProvider.kind == im.KIND, m.AssetPriceSource.external_id == symbol, m.Price.provider_id == m.PriceProvider.id)
                      .order_by(m.Price.recorded_at.desc(), m.Price.id.desc()).limit(limit)).all()
    return {"items": [{"id": p.id, "asset_id": p.asset_id, "asset": p.asset.name, "price": p.price, "currency": p.currency, "recorded_at": p.recorded_at,
                       "fetched_at": p.fetched_at, "checked_at": p.upstream_checked_at, "source": p.upstream_source, "is_valid": p.is_valid,
                       "validity_note": p.validity_note} for p in rows]}


@router.get("/symbols/{symbol:path}")
def symbol_detail(symbol: str, db: Session = Depends(get_db)):
    return im.get_symbol(db, symbol)


@router.post("/refresh")
def refresh(db: Session = Depends(get_db)):
    """دریافت دستی فایل (یک درخواست برای همهٔ نمادها). نیازمند فعال بودن منبع در «منابع قیمت» است."""
    pv = im.get_provider(db)
    if pv is None:
        raise NotFoundError("منبع Iran Market Data تعریف نشده یا بایگانی شده است؛ در «منابع قیمت» بازیابی کنید.")
    if not pv.is_enabled:
        raise ConflictError("منبع Iran Market Data غیرفعال است؛ ابتدا آن را فعال کنید.", code="provider_disabled")
    r = im.fetch_snapshot(db, pv)
    if r["status"] == "skipped":
        r["message"] = r["message"] + " چند ثانیه بعد دوباره تلاش کنید."
    im.clear_history_cache() if r["status"] == "ok" else None
    return r


@router.get("/snapshots")
def snapshots(limit: int = Query(40, ge=1, le=200), db: Session = Depends(get_db)):
    rows = db.scalars(select(m.MarketSnapshot).order_by(m.MarketSnapshot.fetched_at.desc(), m.MarketSnapshot.id.desc()).limit(limit)).all()
    return {"items": [{"id": s.id, "fetched_at": s.fetched_at, "status": s.status, "generated_at": s.generated_at, "published_at": s.published_at,
                       "http_status": s.http_status, "latency_ms": s.latency_ms, "size_bytes": s.size_bytes, "symbol_count": s.symbol_count,
                       "category_count": s.category_count, "valid_count": s.valid_count, "stale_count": s.stale_count, "invalid_count": s.invalid_count,
                       "no_price_count": s.no_price_count, "changed_count": s.changed_count, "skipped_count": s.skipped_count, "error": s.error,
                       "has_raw": bool(s.raw_path), "sha256": s.sha256[:12]} for s in rows]}


@router.get("/snapshots/{sid}/raw")
def snapshot_raw(sid: int, db: Session = Depends(get_db)):
    """پاسخ خام دریافت‌شده برای عیب‌یابی (فقط چند دریافت آخر نگه داشته می‌شود)."""
    s = db.get(m.MarketSnapshot, sid)
    if s is None:
        raise NotFoundError("دریافت یافت نشد.")
    body = im.read_raw(s.raw_path) if s.raw_path else None
    if body is None:
        raise NotFoundError("پاسخ خام این دریافت دیگر نگه‌داری نمی‌شود.")
    return Response(body, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="iranmarket-{sid}.json"'})


@router.get("/suggest")
def suggest(asset_id: int, limit: int = Query(8, ge=1, le=20), db: Session = Depends(get_db)):
    """پیشنهاد تطبیق نماد برای یک دارایی؛ فقط پیشنهاد است و اتصال نمی‌سازد."""
    return {"items": im.suggest(db, _asset(db, asset_id), limit), "auto_link": False}


@router.get("/links")
def links(asset_id: int, db: Session = Depends(get_db)):
    pv = im.get_provider(db)
    a = _asset(db, asset_id)
    s = db.scalar(select(m.AssetPriceSource).where(m.AssetPriceSource.asset_id == a.id, m.AssetPriceSource.provider_id == (pv.id if pv else 0)))
    return {"linked": s is not None, "symbol": s.external_id if s else None, "priority": s.priority if s else None, "link": im._link_meta(s.link_meta) if s else None}


@router.post("/link")
def link(payload: LinkIn, db: Session = Depends(get_db)):
    a = _asset(db, payload.asset_id)
    row = im.link_symbol(db, a, payload.symbol, confirm=payload.confirm, priority=payload.priority)
    return {"ok": True, "asset_id": a.id, "symbol": row.external_id, "priority": row.priority, "link": im._link_meta(row.link_meta)}


@router.delete("/link")
def unlink(asset_id: int, db: Session = Depends(get_db)):
    """قطع اتصال: فقط تنظیم منبع برداشته می‌شود؛ قیمت‌های ثبت‌شده و تراکنش‌ها دست‌نخورده می‌مانند."""
    a = _asset(db, asset_id)
    return {"ok": im.unlink_symbol(db, a), "asset_id": a.id}
