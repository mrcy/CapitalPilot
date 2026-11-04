"""وضعیت کلی منابع قیمت برای داشبورد و صفحهٔ منابع قیمت."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ... import models as m
from ..clock import now_local
from ..finance.types import DataSet
from ..finance.valuation import make_book
from . import service
from .scheduler import get_scheduler


def market_status(db: Session, ds: DataSet | None = None) -> dict:
    now = now_local()
    providers = list(db.scalars(select(m.PriceProvider).where(m.PriceProvider.is_archived.is_(False))))
    st = {"total": len(providers), "enabled": 0, "ok": 0, "error": 0, "unknown": 0, "disabled": 0}
    for p in providers:
        st[service.provider_status(p)] += 1
        st["enabled"] += 1 if p.is_enabled else 0
    since = now - timedelta(hours=24)
    errors = list(db.scalars(select(m.PriceFetchLog).where(m.PriceFetchLog.ok.is_(False), m.PriceFetchLog.ts >= since)
                             .order_by(m.PriceFetchLog.ts.desc()).limit(8)))
    n_err = db.scalar(select(func.count()).select_from(m.PriceFetchLog).where(m.PriceFetchLog.ok.is_(False), m.PriceFetchLog.ts >= since)) or 0
    names = {p.id: p.name for p in providers}
    assets = {a.id: a.name for a in db.scalars(select(m.Asset))}
    last_update = db.scalar(select(func.max(m.Price.fetched_at)).where(m.Price.provider_id.is_not(None), m.Price.is_valid.is_(True)))
    stale = missing = ok = 0
    stale_names: list[str] = []
    if ds is not None:
        book = make_book(ds)
        for a in ds.assets:
            if not a.active:
                continue
            q = book.quote(a, now)
            if q.ok:
                ok += 1
            elif q.reason == "no_price":
                missing += 1
            else:
                stale += 1
                stale_names.append(a.name)
    with_sources = db.scalar(select(func.count(func.distinct(m.AssetPriceSource.asset_id))).where(m.AssetPriceSource.is_enabled.is_(True))) or 0
    return {
        "providers": st, "stale_prices": stale, "missing_prices": missing, "fresh_prices": ok, "stale_assets": stale_names,
        "last_update_at": last_update, "errors_24h": n_err, "assets_with_sources": with_sources,
        "recent_errors": [service.log_dict(l, names, assets) for l in errors], "scheduler": scheduler_state(db),
    }


def scheduler_state(db: Session) -> dict:
    row = db.get(m.AppSettings, 1)
    from ...config import get_settings
    sch = get_scheduler()
    return {"enabled": bool(row and row.scheduler_enabled), "env_enabled": get_settings().scheduler_enabled,
            "default_interval_minutes": row.scheduler_default_interval_minutes if row else 30,
            "market_hours_only": row.scheduler_market_hours_only if row else True,
            "running": bool(sch._thread and sch._thread.is_alive()), "last_run_at": sch.state.get("last_run_at"),
            "last_result": sch.state.get("last_result"), "last_error": sch.state.get("last_error")}
