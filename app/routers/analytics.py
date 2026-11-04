"""داشبورد، سبد، واریزی‌های ماهانه، پیشنهاد خرید و مرکز ریسک."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models as m
from ..database import get_db
from ..errors import NotFoundError, ValidationFailure
from ..schemas import ContributionRecordIn, PlanPeriodPatch
from ..services import clock, summary
from ..services.finance.plan import plan_status
from ..services.finance.rebalance import suggest_allocation
from ..services.finance.types import ZERO
from ..services.finance.valuation import value_portfolio
from ..services.marketdata.status import market_status
from ..services.repository import load_dataset, resolve_portfolio
from ..services.transactions import create_many

router = APIRouter(prefix="/api", tags=["analytics"])


def management_overview(db: Session, ds, pf: m.Portfolio) -> dict:
    """آمار مدیریتی داشبورد: دارایی‌ها، پلتفرم‌ها و وضعیت منابع قیمت."""
    total_assets = db.scalar(select(func.count()).select_from(m.Asset)) or 0
    archived = db.scalar(select(func.count()).select_from(m.Asset).where(m.Asset.is_archived.is_(True))) or 0
    active = db.scalar(select(func.count()).select_from(m.Asset).where(m.Asset.is_archived.is_(False), m.Asset.is_active.is_(True))) or 0
    platforms = db.scalar(select(func.count()).select_from(m.Platform).where(m.Platform.is_archived.is_(False), m.Platform.is_active.is_(True))) or 0
    portfolios = db.scalar(select(func.count()).select_from(m.Portfolio).where(m.Portfolio.is_archived.is_(False))) or 0
    return {"total_assets": total_assets, "active_assets": active, "archived_assets": archived, "platform_count": platforms,
            "portfolio_count": portfolios, "market": market_status(db, ds)}


@router.get("/dashboard")
def dashboard(portfolio_id: int | None = None, db: Session = Depends(get_db)):
    ds = load_dataset(db, portfolio_id)
    d = summary.dashboard(ds, clock.now_local())
    pf = resolve_portfolio(db, portfolio_id)
    d["portfolio"] = {"id": pf.id, "name": pf.name, "is_default": pf.is_default}
    d["management"] = management_overview(db, ds, pf)
    return d


@router.get("/portfolio")
def portfolio(portfolio_id: int | None = None, db: Session = Depends(get_db)):
    return summary.portfolio(load_dataset(db, portfolio_id), clock.now_local())


@router.get("/risk")
def risk(portfolio_id: int | None = None, db: Session = Depends(get_db)):
    return summary.risk_overview(load_dataset(db, portfolio_id), clock.now_local())


@router.get("/rebalance")
def rebalance(amount: Decimal | None = Query(None, gt=0, max_digits=30, decimal_places=4),
              source: str = Query("monthly", pattern="^(monthly|cash|custom)$"), portfolio_id: int | None = None,
              db: Session = Depends(get_db)):
    ds = load_dataset(db, portfolio_id)
    now = clock.now_local()
    val = value_portfolio(ds, now)
    cash = max(val.cash, ZERO)
    if source == "monthly":
        amount = ds.config.monthly_contribution
    elif source == "cash":
        amount = cash
    elif amount is None:
        raise ValidationFailure("برای حالت دلخواه، مبلغ را وارد کنید.")
    res = suggest_allocation(ds, val, amount) if amount and amount > 0 else {
        "available": False, "reason": "مبلغ قابل تخصیص صفر است (نقدینگی ثبت‌شده‌ای وجود ندارد)."}
    res["source"] = source
    res["defaults"] = {"monthly": ds.config.monthly_contribution, "cash": cash}
    res["weights"] = [r for r in summary.asset_rows(ds, val) if r["active"]]
    res["as_of"] = now
    return res


# ---------------------------------------------------------------- واریزی‌های ماهانه
def _platform_targets(ds):
    w: dict[int, Decimal] = {}
    for a in ds.assets:
        if a.active:
            w[a.platform_id] = w.get(a.platform_id, ZERO) + a.target_weight
    return [{"platform_id": p.id, "platform": p.name, "weight": w.get(p.id, ZERO)} for p in ds.platforms if w.get(p.id)]


@router.get("/contributions")
def contributions(portfolio_id: int | None = None, db: Session = Depends(get_db)):
    pf = resolve_portfolio(db, portfolio_id)
    ds = load_dataset(db, pf.id)
    st = plan_status(ds, clock.today_local())
    st["platform_targets"] = _platform_targets(ds)
    st["today"] = clock.today_local()
    st["monthly_contribution"] = ds.config.monthly_contribution
    st["initial_capital"] = ds.config.initial_capital
    deposits = [t for t in db.scalars(select(m.Transaction).where(m.Transaction.tx_type == "deposit", m.Transaction.portfolio_id == pf.id).order_by(m.Transaction.tx_date))]
    st["deposits"] = [{"id": t.id, "date": t.tx_date, "platform_id": t.platform_id, "amount": t.total_amount,
                       "plan_period_id": t.plan_period_id} for t in deposits]
    return st


def _split(amount: Decimal, targets: list[dict]) -> dict[int, Decimal]:
    total_w = sum((t["weight"] for t in targets), ZERO)
    if total_w <= 0:
        raise ValidationFailure("وزن هدف هیچ پلتفرمی مشخص نیست؛ تخصیص هر پلتفرم را دستی وارد کنید.")
    out = {t["platform_id"]: (amount * t["weight"] / total_w).quantize(Decimal("1"), rounding=ROUND_HALF_UP) for t in targets}
    diff = amount - sum(out.values(), ZERO)
    biggest = max(targets, key=lambda t: t["weight"])["platform_id"]
    out[biggest] += diff
    return out


@router.post("/contributions/{seq}/record", status_code=201)
def record_contribution(seq: int, payload: ContributionRecordIn, portfolio_id: int | None = None, db: Session = Depends(get_db)):
    """ثبت واریزی واقعی یک دوره: برای هر پلتفرم یک تراکنش «واریز سرمایه» ثبت می‌شود."""
    pf = resolve_portfolio(db, portfolio_id)
    period = db.scalar(select(m.PlanPeriod).where(m.PlanPeriod.seq == seq, m.PlanPeriod.portfolio_id == pf.id))
    if period is None:
        raise NotFoundError("دوره برنامه یافت نشد.")
    ds = load_dataset(db, pf.id)
    if payload.allocations:
        alloc = payload.allocations
    else:
        alloc = _split(payload.amount, _platform_targets(ds))
    items = [(pid, amt) for pid, amt in alloc.items() if amt and amt > 0]
    if not items:
        raise ValidationFailure("مبلغ واریزی باید بزرگ‌تر از صفر باشد.")
    note = payload.note or ("سرمایه اولیه" if seq == 0 else f"واریزی ماهانه شماره {seq}")
    rows, warnings = create_many(db, [
        {"tx_date": payload.date, "tx_type": "deposit", "platform_id": pid, "amount": amt, "plan_period_id": period.id, "portfolio_id": pf.id, "note": note}
        for pid, amt in items])
    return {"created": [r.id for r in rows], "warnings": warnings}


@router.patch("/contributions/{seq}")
def patch_period(seq: int, payload: PlanPeriodPatch, portfolio_id: int | None = None, db: Session = Depends(get_db)):
    pf = resolve_portfolio(db, portfolio_id)
    period = db.scalar(select(m.PlanPeriod).where(m.PlanPeriod.seq == seq, m.PlanPeriod.portfolio_id == pf.id))
    if period is None:
        raise NotFoundError("دوره برنامه یافت نشد.")
    if payload.planned_amount is not None:
        period.planned_amount = payload.planned_amount
    if payload.due_date is not None:
        period.due_date = payload.due_date
    if payload.note is not None:
        period.note = payload.note
    db.commit()
    return {"ok": True}
