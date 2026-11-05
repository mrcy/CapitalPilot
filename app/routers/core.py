"""اطلاعات پایه: متادیتا، تنظیمات، واحدهای پول و پلتفرم‌ها."""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import __version__, models as m
from ..config import get_settings
from ..database import get_db
from ..errors import ConflictError, NotFoundError, ValidationFailure
from ..schemas import CurrencyIn, SettingsIn
from ..services import clock
from ..services import catalog
from ..services.repository import effective_weights, get_default_portfolio, get_settings_row, sync_plan

router = APIRouter(prefix="/api", tags=["core"])


def settings_dict(db: Session) -> dict:
    """تنظیمات عمومی + پارامترهای برنامهٔ سبد پیش‌فرض (سازگار با نسخهٔ ۱)."""
    r = get_settings_row(db)
    pf = get_default_portfolio(db)
    members = list(db.scalars(select(m.PortfolioAsset).where(m.PortfolioAsset.portfolio_id == pf.id, m.PortfolioAsset.is_active.is_(True))))
    live = [pa for pa in members if pa.asset.is_active and not pa.asset.is_archived]
    eff = effective_weights(pf, live)
    total_w = sum(eff.values(), Decimal(0))
    return {
        "portfolio_id": pf.id, "portfolio_name": pf.name,
        "initial_capital": pf.initial_capital, "monthly_contribution": pf.monthly_contribution,
        "horizon_months": pf.horizon_months, "plan_start_date": pf.plan_start_date, "max_drawdown_pct": pf.max_drawdown_pct,
        "concentration_limit_pct": r.concentration_limit_pct, "deviation_warning_pp": r.deviation_warning_pp,
        "max_price_age_days": r.max_price_age_days, "calendar": r.calendar, "currency_label": r.currency_label,
        "plan_target_total": pf.initial_capital + pf.monthly_contribution * pf.horizon_months,
        "allocation_sum": total_w, "allocation_ok": round(total_w, 6) == Decimal(100),
        "plan_by_asset": [{"asset_id": pa.asset_id, "name": pa.asset.name, "weight": eff.get(pa.asset_id, Decimal(0)),
                           "initial": pf.initial_capital * eff.get(pa.asset_id, Decimal(0)) / 100,
                           "monthly": pf.monthly_contribution * eff.get(pa.asset_id, Decimal(0)) / 100} for pa in live],
        "scheduler_enabled": r.scheduler_enabled,
    }


@router.get("/meta")
def meta(db: Session = Depends(get_db)):
    s = get_settings()
    now = clock.now_local()
    return {
        "name": s.app_name, "tagline": s.app_tagline, "version": __version__, "now": now, "today": now.date(),
        "timezone": s.app_timezone, "settings": settings_dict(db),
        "currencies": [_cur(c) for c in db.scalars(select(m.Currency).order_by(m.Currency.is_base.desc(), m.Currency.code))],
        "platforms": [catalog.platform_dict(db, p) for p in db.scalars(select(m.Platform).order_by(m.Platform.sort_order, m.Platform.id))],
        "asset_types": [catalog.type_dict(db, t) for t in db.scalars(select(m.AssetType).order_by(m.AssetType.sort_order, m.AssetType.key))],
        "portfolios": [{"id": pf.id, "name": pf.name, "is_default": pf.is_default, "is_archived": pf.is_archived}
                       for pf in db.scalars(select(m.Portfolio).order_by(m.Portfolio.sort_order, m.Portfolio.id))],
    }


@router.get("/settings")
def get_app_settings(db: Session = Depends(get_db)):
    return settings_dict(db)


@router.put("/settings")
def update_settings(payload: SettingsIn, db: Session = Depends(get_db)):
    r = get_settings_row(db)
    pf = get_default_portfolio(db)
    data = payload.model_dump()
    apply_past = data.pop("apply_to_past_unpaid")
    for k in ("initial_capital", "monthly_contribution", "horizon_months", "max_drawdown_pct"):
        setattr(pf, k, data.pop(k))
    pf.plan_start_date = data.pop("plan_start_date")
    for k, v in data.items():
        setattr(r, k, v)
    db.flush()
    sync_plan(db, clock.today_local(), apply_to_past_unpaid=apply_past, portfolio=pf)
    db.commit()
    return settings_dict(db)


def _cur(c: m.Currency) -> dict:
    return {"code": c.code, "name": c.name, "symbol": c.symbol, "is_base": c.is_base, "is_active": c.is_active}


@router.get("/currencies")
def list_currencies(db: Session = Depends(get_db)):
    return [_cur(c) for c in db.scalars(select(m.Currency).order_by(m.Currency.is_base.desc(), m.Currency.code))]


@router.post("/currencies", status_code=201)
def create_currency(payload: CurrencyIn, db: Session = Depends(get_db)):
    if db.get(m.Currency, payload.code):
        raise ConflictError("این کد واحد پول قبلاً ثبت شده است.")
    c = m.Currency(code=payload.code, name=payload.name, symbol=payload.symbol, is_active=payload.is_active)
    db.add(c)
    db.commit()
    return _cur(c)


@router.put("/currencies/{code}")
def update_currency(code: str, payload: CurrencyIn, db: Session = Depends(get_db)):
    c = db.get(m.Currency, code.upper())
    if c is None:
        raise NotFoundError("واحد پول یافت نشد.")
    if c.is_base and not payload.is_active:
        raise ValidationFailure("واحد پایه را نمی‌توان غیرفعال کرد.")
    c.name, c.symbol, c.is_active = payload.name, payload.symbol, payload.is_active
    db.commit()
    return _cur(c)


@router.delete("/currencies/{code}")
def delete_currency(code: str, db: Session = Depends(get_db)):
    c = db.get(m.Currency, code.upper())
    if c is None:
        raise NotFoundError("واحد پول یافت نشد.")
    if c.is_base:
        raise ValidationFailure("واحد پایه قابل حذف نیست.")
    used = (db.scalar(select(func.count()).select_from(m.Asset).where(m.Asset.price_currency == c.code))
            or db.scalar(select(func.count()).select_from(m.Price).where(m.Price.currency == c.code))
            or db.scalar(select(func.count()).select_from(m.FxRate).where(m.FxRate.currency == c.code)))
    if used:
        raise ConflictError("این واحد پول در دارایی‌ها یا قیمت‌ها استفاده شده و قابل حذف نیست؛ می‌توانید آن را غیرفعال کنید.")
    db.delete(c)
    db.commit()
    return {"ok": True}
