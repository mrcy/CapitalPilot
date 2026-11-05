"""بارگذاری داده‌ها از دیتابیس به ساختارهای خالص مالی و همگام‌سازی برنامه واریزی."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..errors import NotFoundError
from .clock import now_local
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


def config_from_row(r: m.AppSettings, pf: m.Portfolio | None = None) -> Config:
    """تنظیمات محاسباتی: پارامترهای برنامه از سبد و پارامترهای عمومی از تنظیمات برنامه می‌آیند."""
    return Config(
        initial_capital=pf.initial_capital if pf else r.initial_capital,
        monthly_contribution=pf.monthly_contribution if pf else r.monthly_contribution,
        horizon_months=pf.horizon_months if pf else r.horizon_months,
        start_date=pf.plan_start_date if pf else r.plan_start_date,
        max_drawdown_pct=pf.max_drawdown_pct if pf else r.max_drawdown_pct,
        concentration_limit_pct=r.concentration_limit_pct, deviation_warning_pp=r.deviation_warning_pp,
        max_price_age_days=r.max_price_age_days, calendar=r.calendar,
    )


def tx_rec(t: m.Transaction) -> TxRec:
    return TxRec(t.id, t.tx_date, t.tx_type, t.platform_id, t.asset_id, t.quantity, t.unit_price, t.fee,
                 t.total_amount, t.fx_rate, t.plan_period_id)


def asset_rec(a: m.Asset, target_weight: Decimal | None = None, active: bool | None = None) -> AssetRec:
    return AssetRec(
        a.id, a.platform_id, a.name, a.symbol, a.asset_type,
        a.target_weight if target_weight is None else target_weight, a.price_currency, a.buy_fee_rate,
        a.fractional_units or a.decimals > 0, a.is_active and not a.is_archived if active is None else active,
        a.decimals or (6 if a.fractional_units else 0), a.min_quantity or Decimal(0),
    )


# ---------------- سبدها ----------------
def get_default_portfolio(db: Session) -> m.Portfolio:
    pf = db.scalar(select(m.Portfolio).where(m.Portfolio.is_default.is_(True)))
    if pf is None:
        pf = db.scalar(select(m.Portfolio).order_by(m.Portfolio.id))
    if pf is None:
        r = get_settings_row(db)
        pf = m.Portfolio(name="سبد اصلی", initial_capital=r.initial_capital, monthly_contribution=r.monthly_contribution,
                         horizon_months=r.horizon_months, max_drawdown_pct=r.max_drawdown_pct,
                         plan_start_date=r.plan_start_date, is_default=True)
        db.add(pf)
        db.flush()
    return pf


def resolve_portfolio(db: Session, portfolio_id: int | None) -> m.Portfolio:
    if portfolio_id is None:
        return get_default_portfolio(db)
    pf = db.get(m.Portfolio, portfolio_id)
    if pf is None:
        raise NotFoundError("سبد یافت نشد.")
    return pf


def effective_weights(pf: m.Portfolio, members: list[m.PortfolioAsset]) -> dict[int, Decimal]:
    """وزن هدف مؤثر (درصد) هر عضو فعال؛ در حالت مبلغ ثابت از نسبت مبلغ‌ها محاسبه می‌شود."""
    active = [pa for pa in members if pa.is_active]
    if pf.target_mode == "amount":
        total = sum((pa.target_amount for pa in active), Decimal(0))
        return {pa.asset_id: (pa.target_amount / total * 100 if total > 0 else Decimal(0)) for pa in active}
    return {pa.asset_id: pa.target_weight for pa in active}


def _price_recs(db: Session, asset_ids: set[int], max_age_days: int) -> list[PriceRec]:
    """قیمت‌های قابل‌استفاده در ارزش‌گذاری (تأییدشده و معتبر). اگر جدیدترین قیمت یک دارایی در «اختلاف غیرعادی منابع» باشد،
    همان رکورد با flag=conflict علامت می‌خورد تا قیمتی خودسرانه انتخاب نشود (لایهٔ کیفیت)."""
    if not asset_ids:
        return []
    from .marketdata import quality
    now = now_local()
    rows = list(db.scalars(select(m.Price).where(m.Price.asset_id.in_(asset_ids), m.Price.is_valid.is_(True))))
    recent: dict[int, list] = {}
    for p in rows:
        if (now.date() - p.recorded_at.date()).days <= max_age_days:
            recent.setdefault(p.asset_id, []).append(p)
    conflicts = quality.conflict_asset_ids(recent, now, max_age_days)
    flagged: set[int] = set()
    for aid in conflicts:
        approved = [p for p in recent[aid] if p.is_approved]
        if approved:
            flagged.add(max(approved, key=lambda p: (p.recorded_at, p.id)).id)
    return [PriceRec(p.id, p.asset_id, p.price, p.currency, p.recorded_at, p.is_approved, p.source, "conflict" if p.id in flagged else "")
            for p in rows if p.is_approved]


def load_dataset(db: Session, portfolio_id: int | None = None) -> DataSet:
    pf = resolve_portfolio(db, portfolio_id)
    cfg = config_from_row(get_settings_row(db), pf)
    members = list(db.scalars(select(m.PortfolioAsset).where(m.PortfolioAsset.portfolio_id == pf.id)))
    member_by_asset = {pa.asset_id: pa for pa in members}
    weights = effective_weights(pf, members)
    txs = list(db.scalars(select(m.Transaction).where(m.Transaction.portfolio_id == pf.id)))
    held_ids = {t.asset_id for t in txs if t.asset_id}
    platforms = list(db.scalars(select(m.Platform).order_by(m.Platform.id)))
    plat_ok = {p.id: p.is_active and not p.is_archived for p in platforms}
    assets = []
    for a in db.scalars(select(m.Asset).order_by(m.Asset.sort_order, m.Asset.id)):
        pa = member_by_asset.get(a.id)
        if pa is None and a.id not in held_ids:
            continue
        active = bool(pa and pa.is_active and a.is_active and not a.is_archived and plat_ok.get(a.platform_id, True))
        assets.append(asset_rec(a, weights.get(a.id, Decimal(0)) if active or pa else Decimal(0), active))
    asset_ids = {a.id for a in assets}
    used_platforms = {a.platform_id for a in assets} | {t.platform_id for t in txs}
    prices = _price_recs(db, asset_ids, cfg.max_price_age_days)
    periods = db.scalars(select(m.PlanPeriod).where(m.PlanPeriod.portfolio_id == pf.id))
    return DataSet(
        config=cfg,
        platforms=[PlatformRec(p.id, p.name, p.kind, p.is_active and not p.is_archived) for p in platforms
                   if p.id in used_platforms],
        assets=assets, txs=[tx_rec(t) for t in txs], prices=prices,
        fx=[FxRec(r.id, r.currency, r.rate, r.recorded_at, r.is_approved, r.source) for r in db.scalars(select(m.FxRate))],
        periods=[PlanRec(p.id, p.seq, p.due_date, p.planned_amount) for p in periods],
    )


def sync_plan(db: Session, today: date, apply_to_past_unpaid: bool = False, portfolio: m.Portfolio | None = None) -> None:
    """ایجاد/به‌روزرسانی دوره‌های برنامه واریزی هر سبد بر اساس تنظیمات آن.

    دوره‌های دارای واریزی ثبت‌شده هرگز تغییر نمی‌کنند. دوره‌های پرداخت‌نشده گذشته فقط با گزینه
    apply_to_past_unpaid به‌روزرسانی می‌شوند. بدون مشخص‌کردن سبد، همهٔ سبدهای بایگانی‌نشده همگام می‌شوند.
    """
    if portfolio is None:
        get_default_portfolio(db)
        for pf in db.scalars(select(m.Portfolio).where(m.Portfolio.is_archived.is_(False))).all():
            sync_plan(db, today, apply_to_past_unpaid, pf)
        return
    cfg = config_from_row(get_settings_row(db), portfolio)
    schedule = generate_schedule(cfg)
    periods = {p.seq: p for p in db.scalars(select(m.PlanPeriod).where(m.PlanPeriod.portfolio_id == portfolio.id))}
    linked = {pid for pid in db.scalars(select(m.Transaction.plan_period_id).where(m.Transaction.plan_period_id.is_not(None)))}
    wanted = set()
    for seq, due, amt in schedule:
        wanted.add(seq)
        p = periods.get(seq)
        if p is None:
            db.add(m.PlanPeriod(portfolio_id=portfolio.id, seq=seq, due_date=due, planned_amount=amt))
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
