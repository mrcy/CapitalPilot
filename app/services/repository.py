"""بارگذاری داده‌ها از دیتابیس به ساختارهای خالص مالی و همگام‌سازی برنامه واریزی."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from .finance.plan import generate_schedule
from .finance.types import (
    AssetRec, Config, DataSet, FxRec, PlanRec, PlatformRec, PriceRec, TxRec,
)


def get_settings_row(db: Session) -> m.AppSettings:
    row = db.get(m.AppSettings, 1)
    if row is None:
        row = m.AppSettings(id=1, plan_start_date=date.today())
        db.add(row)
        db.flush()
    return row


def config_from_row(r: m.AppSettings) -> Config:
    return Config(
        initial_capital=r.initial_capital, monthly_contribution=r.monthly_contribution, horizon_months=r.horizon_months,
        start_date=r.plan_start_date, max_drawdown_pct=r.max_drawdown_pct,
        concentration_limit_pct=r.concentration_limit_pct, deviation_warning_pp=r.deviation_warning_pp,
        max_price_age_days=r.max_price_age_days, calendar=r.calendar,
    )


def tx_rec(t: m.Transaction) -> TxRec:
    return TxRec(t.id, t.tx_date, t.tx_type, t.platform_id, t.asset_id, t.quantity, t.unit_price, t.fee,
                 t.total_amount, t.fx_rate, t.plan_period_id)


def asset_rec(a: m.Asset) -> AssetRec:
    return AssetRec(a.id, a.platform_id, a.name, a.symbol, a.asset_type, a.target_weight, a.price_currency,
                    a.buy_fee_rate, a.fractional_units, a.is_active)


def load_dataset(db: Session) -> DataSet:
    cfg = config_from_row(get_settings_row(db))
    return DataSet(
        config=cfg,
        platforms=[PlatformRec(p.id, p.name, p.kind, p.is_active) for p in db.scalars(select(m.Platform).order_by(m.Platform.id))],
        assets=[asset_rec(a) for a in db.scalars(select(m.Asset).order_by(m.Asset.sort_order, m.Asset.id))],
        txs=[tx_rec(t) for t in db.scalars(select(m.Transaction))],
        prices=[PriceRec(p.id, p.asset_id, p.price, p.currency, p.recorded_at, p.is_approved, p.source)
                for p in db.scalars(select(m.Price))],
        fx=[FxRec(r.id, r.currency, r.rate, r.recorded_at, r.is_approved, r.source) for r in db.scalars(select(m.FxRate))],
        periods=[PlanRec(p.id, p.seq, p.due_date, p.planned_amount) for p in db.scalars(select(m.PlanPeriod))],
    )


def sync_plan(db: Session, today: date, apply_to_past_unpaid: bool = False) -> None:
    """ایجاد/به‌روزرسانی دوره‌های برنامه واریزی بر اساس تنظیمات.

    دوره‌های دارای واریزی ثبت‌شده هرگز تغییر نمی‌کنند. دوره‌های پرداخت‌نشده گذشته فقط با گزینه
    apply_to_past_unpaid به‌روزرسانی می‌شوند.
    """
    cfg = config_from_row(get_settings_row(db))
    schedule = generate_schedule(cfg)
    periods = {p.seq: p for p in db.scalars(select(m.PlanPeriod))}
    linked = {pid for pid in db.scalars(select(m.Transaction.plan_period_id).where(m.Transaction.plan_period_id.is_not(None)))}
    wanted = set()
    for seq, due, amt in schedule:
        wanted.add(seq)
        p = periods.get(seq)
        if p is None:
            db.add(m.PlanPeriod(seq=seq, due_date=due, planned_amount=amt))
            continue
        if p.id in linked:
            continue
        if p.due_date < today and not apply_to_past_unpaid:
            continue
        p.due_date, p.planned_amount = due, amt
    for seq, p in periods.items():
        if seq not in wanted and p.id not in linked:
            db.delete(p)
    db.flush()
