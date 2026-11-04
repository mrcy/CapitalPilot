"""موتور داده‌های بازار: منابع قیمت، تست اتصال، لاگ، زمان‌بند، تاریخچهٔ قیمت و مقایسهٔ منابع.

این API هیچ سفارشی ارسال نمی‌کند و کلید API هرگز در پاسخ‌ها برنمی‌گردد (فقط has_api_key).
"""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..database import get_db
from ..errors import NotFoundError, ValidationFailure
from ..schemas import ConfirmIn, ProviderIn, SchedulerSettingsIn
from ..services import clock
from ..services.marketdata import service
from ..services.marketdata.base import ProviderError
from ..services.marketdata.engine import get_engine
from ..services.marketdata.scheduler import get_scheduler
from ..services.marketdata.status import market_status, scheduler_state
from ..services.purge import check_purge, request_purge
from ..services.repository import load_dataset

router = APIRouter(prefix="/api/market-data", tags=["market-data"])


class TestIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    external_id: str = Field(default="", max_length=120)
    price_field: str = Field(default="", max_length=16)


class RefreshIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_ids: list[int] | None = None


class HistoryImportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: int
    provider_id: int
    days: int = Field(default=90, ge=1, le=3650)


def _pv(db: Session, pid: int) -> m.PriceProvider:
    pv = db.get(m.PriceProvider, pid)
    if pv is None:
        raise NotFoundError("منبع قیمت یافت نشد.")
    return pv


@router.get("/kinds")
def kinds():
    return [{"kind": k, **{x: v for x, v in info.items()}} for k, info in service.KIND_INFO.items()]


@router.get("/status")
def status(portfolio_id: int | None = None, db: Session = Depends(get_db)):
    return market_status(db, load_dataset(db, portfolio_id))


# ---------------- منابع ----------------
@router.get("/providers")
def list_providers(include_archived: bool = True, db: Session = Depends(get_db)):
    q = select(m.PriceProvider).order_by(m.PriceProvider.id)
    if not include_archived:
        q = q.where(m.PriceProvider.is_archived.is_(False))
    return [service.provider_dict(db, p) for p in db.scalars(q)]


@router.post("/providers", status_code=201)
def create_provider(payload: ProviderIn, db: Session = Depends(get_db)):
    return service.provider_dict(db, service.save_provider(db, payload))


@router.get("/providers/{pid}")
def get_provider(pid: int, db: Session = Depends(get_db)):
    return service.provider_dict(db, _pv(db, pid))


@router.put("/providers/{pid}")
def update_provider(pid: int, payload: ProviderIn, db: Session = Depends(get_db)):
    return service.provider_dict(db, service.save_provider(db, payload, pid))


@router.post("/providers/{pid}/enable")
def enable_provider(pid: int, enabled: bool = True, db: Session = Depends(get_db)):
    return service.provider_dict(db, service.set_enabled(db, _pv(db, pid), enabled))


@router.post("/providers/{pid}/archive")
def archive_provider(pid: int, db: Session = Depends(get_db)):
    return service.provider_dict(db, service.archive_provider(db, _pv(db, pid), True))


@router.post("/providers/{pid}/restore")
def restore_provider(pid: int, db: Session = Depends(get_db)):
    return service.provider_dict(db, service.archive_provider(db, _pv(db, pid), False))


@router.delete("/providers/{pid}")
def delete_provider(pid: int, db: Session = Depends(get_db)):
    service.delete_provider(db, _pv(db, pid))
    return {"ok": True}


@router.post("/providers/{pid}/purge/request")
def purge_request(pid: int, db: Session = Depends(get_db)):
    pv = _pv(db, pid)
    return request_purge("provider", pv.id, service.dependencies(db, pv))


@router.post("/providers/{pid}/purge/confirm")
def purge_confirm(pid: int, payload: ConfirmIn, db: Session = Depends(get_db)):
    from ..services.backup import save_db_backup
    pv = _pv(db, pid)
    check_purge("provider", pv.id, payload.token, payload.phrase)
    backup = save_db_backup(db, "pre-purge")
    return {"ok": True, "removed": service.purge_provider(db, pv), "backup": backup}


@router.post("/providers/{pid}/test")
def test_provider(pid: int, payload: TestIn | None = None, db: Session = Depends(get_db)):
    payload = payload or TestIn()
    return get_engine().test_provider(db, _pv(db, pid), payload.external_id, payload.price_field)


@router.get("/providers/{pid}/search")
def search_symbols(pid: int, q: str = Query("", max_length=60), db: Session = Depends(get_db)):
    pv = _pv(db, pid)
    try:
        prov = get_engine().build(pv)
        return {"items": [{"external_id": s.external_id, "symbol": s.symbol, "name": s.name, "market": s.market,
                           "active": s.active, "extra": s.extra} for s in prov.search_symbols(q)]}
    except ProviderError as e:
        raise ValidationFailure(e.message, code=f"provider_{e.code}")


@router.get("/providers/{pid}/history")
def provider_history(pid: int, external_id: str = Query(max_length=120), days: int = Query(30, ge=1, le=3650),
                     db: Session = Depends(get_db)):
    pv = _pv(db, pid)
    today = clock.today_local()
    try:
        pts = get_engine().build(pv).get_history(external_id, today - timedelta(days=days), today)
    except ProviderError as e:
        raise ValidationFailure(e.message, code=f"provider_{e.code}")
    return {"points": [{"time": p.time, "price": p.price, "kind": p.kind} for p in pts]}


@router.get("/providers/{pid}/logs")
def provider_logs(pid: int, only_errors: bool = False, limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)):
    _pv(db, pid)
    return service.list_logs(db, provider_id=pid, asset_id=None, only_errors=only_errors, limit=limit)


@router.get("/logs")
def logs(provider_id: int | None = None, asset_id: int | None = None, only_errors: bool = False,
         limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db)):
    return service.list_logs(db, provider_id=provider_id, asset_id=asset_id, only_errors=only_errors, limit=limit)


# ---------------- دریافت ----------------
@router.post("/refresh")
def refresh(payload: RefreshIn | None = None, db: Session = Depends(get_db)):
    ids = payload.asset_ids if payload else None
    return {"results": get_engine().refresh_all(db, ids, force=True)}


@router.post("/history/import")
def import_history(payload: HistoryImportIn, db: Session = Depends(get_db)):
    a = db.get(m.Asset, payload.asset_id)
    if a is None:
        raise NotFoundError("دارایی یافت نشد.")
    src = db.scalar(select(m.AssetPriceSource).where(m.AssetPriceSource.asset_id == a.id, m.AssetPriceSource.provider_id == payload.provider_id))
    if src is None:
        raise ValidationFailure("این منبع برای دارایی تعریف نشده است.")
    try:
        return get_engine().import_history(db, a, src, payload.days)
    except ProviderError as e:
        raise ValidationFailure(e.message, code=f"provider_{e.code}")


# ---------------- زمان‌بند ----------------
@router.get("/scheduler")
def get_scheduler_state(db: Session = Depends(get_db)):
    return scheduler_state(db)


@router.put("/scheduler")
def set_scheduler(payload: SchedulerSettingsIn, db: Session = Depends(get_db)):
    from ..services.repository import get_settings_row
    r = get_settings_row(db)
    r.scheduler_enabled = payload.scheduler_enabled
    r.scheduler_default_interval_minutes = payload.scheduler_default_interval_minutes
    r.scheduler_market_hours_only = payload.scheduler_market_hours_only
    db.commit()
    return scheduler_state(db)


@router.post("/scheduler/run")
def run_scheduler_now():
    return get_scheduler().run_once()


# ---------------- تاریخچه و مقایسهٔ منابع ----------------
@router.get("/history")
def price_history(asset_id: int, days: int = Query(90, ge=1, le=3650), valid_only: bool = False, db: Session = Depends(get_db)):
    a = db.get(m.Asset, asset_id)
    if a is None:
        raise NotFoundError("دارایی یافت نشد.")
    since = clock.now_local() - timedelta(days=days)
    q = select(m.Price).where(m.Price.asset_id == a.id, m.Price.recorded_at >= since).order_by(m.Price.recorded_at, m.Price.id)
    if valid_only:
        q = q.where(m.Price.is_valid.is_(True), m.Price.is_approved.is_(True))
    names = {p.id: p.name for p in db.scalars(select(m.PriceProvider))}
    series: dict[str, dict] = {}
    for p in db.scalars(q):
        key = str(p.provider_id) if p.provider_id else "manual"
        s = series.setdefault(key, {"provider_id": p.provider_id, "name": names.get(p.provider_id, "دستی"), "points": []})
        s["points"].append({"id": p.id, "t": p.recorded_at, "price": p.price, "kind": p.price_kind, "is_valid": p.is_valid,
                            "is_approved": p.is_approved, "source": p.source, "note": p.validity_note})
    comparison = []
    for key, s in series.items():
        valid = [x for x in s["points"] if x["is_valid"]]
        last = valid[-1] if valid else None
        comparison.append({"provider_id": s["provider_id"], "name": s["name"], "last_price": last["price"] if last else None,
                           "last_time": last["t"] if last else None, "approved": last["is_approved"] if last else None,
                           "count": len(s["points"]), "invalid_count": len(s["points"]) - len(valid)})
    base = next((c["last_price"] for c in comparison if c["last_price"]), None)
    for c in comparison:
        c["diff_pct"] = ((c["last_price"] - base) / base * 100) if (c["last_price"] and base) else None
    return {"asset_id": a.id, "currency": a.price_currency, "series": list(series.values()), "comparison": comparison}
