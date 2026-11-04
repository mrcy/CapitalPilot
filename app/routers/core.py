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
from ..schemas import CurrencyIn, PlatformIn, SettingsIn
from ..services import clock
from ..services.price_providers import available_providers
from ..services.repository import get_settings_row, sync_plan

router = APIRouter(prefix="/api", tags=["core"])


def settings_dict(db: Session) -> dict:
    r = get_settings_row(db)
    assets = list(db.scalars(select(m.Asset).where(m.Asset.is_active.is_(True)).order_by(m.Asset.sort_order, m.Asset.id)))
    total_w = sum((a.target_weight for a in assets), Decimal(0))
    return {
        "initial_capital": r.initial_capital, "monthly_contribution": r.monthly_contribution,
        "horizon_months": r.horizon_months, "plan_start_date": r.plan_start_date, "max_drawdown_pct": r.max_drawdown_pct,
        "concentration_limit_pct": r.concentration_limit_pct, "deviation_warning_pp": r.deviation_warning_pp,
        "max_price_age_days": r.max_price_age_days, "calendar": r.calendar, "currency_label": r.currency_label,
        "plan_target_total": r.initial_capital + r.monthly_contribution * r.horizon_months,
        "allocation_sum": total_w, "allocation_ok": total_w == Decimal(100),
        "plan_by_asset": [{"asset_id": a.id, "name": a.name, "weight": a.target_weight,
                           "initial": r.initial_capital * a.target_weight / 100,
                           "monthly": r.monthly_contribution * a.target_weight / 100} for a in assets],
    }


@router.get("/meta")
def meta(db: Session = Depends(get_db)):
    s = get_settings()
    now = clock.now_local()
    return {
        "name": s.app_name, "tagline": s.app_tagline, "version": __version__, "now": now, "today": now.date(),
        "timezone": s.app_timezone, "settings": settings_dict(db),
        "currencies": [_cur(c) for c in db.scalars(select(m.Currency).order_by(m.Currency.is_base.desc(), m.Currency.code))],
        "platforms": [_plat(p) for p in db.scalars(select(m.Platform).order_by(m.Platform.id))],
        "price_providers": available_providers(),
        "price_api_enabled": bool(s.allowed_price_hosts),
    }


@router.get("/settings")
def get_app_settings(db: Session = Depends(get_db)):
    return settings_dict(db)


@router.put("/settings")
def update_settings(payload: SettingsIn, db: Session = Depends(get_db)):
    r = get_settings_row(db)
    data = payload.model_dump()
    apply_past = data.pop("apply_to_past_unpaid")
    for k, v in data.items():
        setattr(r, k, v)
    db.flush()
    sync_plan(db, clock.today_local(), apply_to_past_unpaid=apply_past)
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


def _plat(p: m.Platform) -> dict:
    return {"id": p.id, "name": p.name, "kind": p.kind, "is_active": p.is_active, "note": p.note}


@router.get("/platforms")
def list_platforms(db: Session = Depends(get_db)):
    return [_plat(p) for p in db.scalars(select(m.Platform).order_by(m.Platform.id))]


@router.post("/platforms", status_code=201)
def create_platform(payload: PlatformIn, db: Session = Depends(get_db)):
    p = m.Platform(**payload.model_dump())
    db.add(p)
    db.commit()
    return _plat(p)


@router.put("/platforms/{pid}")
def update_platform(pid: int, payload: PlatformIn, db: Session = Depends(get_db)):
    p = db.get(m.Platform, pid)
    if p is None:
        raise NotFoundError("پلتفرم یافت نشد.")
    for k, v in payload.model_dump().items():
        setattr(p, k, v)
    db.commit()
    return _plat(p)
