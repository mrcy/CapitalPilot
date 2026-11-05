"""سبدهای سرمایه‌گذاری: ایجاد، ویرایش، عضویت دارایی‌ها و وزن‌های هدف، بایگانی و حذف ایمن."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import models as m
from ..errors import ConflictError, NotFoundError, ValidationFailure
from .clock import now_local, today_local
from .repository import effective_weights, sync_plan

HUNDRED = Decimal(100)


def member_dict(pa: m.PortfolioAsset, eff: dict[int, Decimal]) -> dict:
    a = pa.asset
    return {"asset_id": a.id, "name": a.name, "symbol": a.symbol, "asset_type": a.asset_type, "platform_id": a.platform_id,
            "platform": a.platform.name if a.platform else None, "target_weight": pa.target_weight,
            "target_amount": pa.target_amount, "effective_weight": eff.get(a.id, Decimal(0)), "is_active": pa.is_active,
            "asset_active": a.is_active and not a.is_archived, "asset_archived": a.is_archived}


def portfolio_dict(db: Session, pf: m.Portfolio, with_members: bool = False) -> dict:
    members = list(db.scalars(select(m.PortfolioAsset).where(m.PortfolioAsset.portfolio_id == pf.id)))
    eff = effective_weights(pf, members)
    n_tx = db.scalar(select(func.count()).select_from(m.Transaction).where(m.Transaction.portfolio_id == pf.id)) or 0
    if pf.target_mode == "amount":
        total = sum((pa.target_amount for pa in members if pa.is_active), Decimal(0))
        ok = total > 0
    else:
        total = sum((pa.target_weight for pa in members if pa.is_active), Decimal(0))
        ok = total == HUNDRED
    d = {"id": pf.id, "name": pf.name, "description": pf.description, "initial_capital": pf.initial_capital,
         "monthly_contribution": pf.monthly_contribution, "horizon_months": pf.horizon_months,
         "max_drawdown_pct": pf.max_drawdown_pct, "plan_start_date": pf.plan_start_date, "target_mode": pf.target_mode,
         "is_default": pf.is_default, "is_archived": pf.is_archived, "archived_at": pf.archived_at,
         "plan_target_total": pf.initial_capital + pf.monthly_contribution * pf.horizon_months,
         "member_count": len(members), "active_member_count": sum(1 for x in members if x.is_active),
         "transaction_count": n_tx, "target_total": total, "targets_ok": ok}
    if with_members:
        d["members"] = [member_dict(pa, eff) for pa in sorted(members, key=lambda x: (x.asset.sort_order, x.asset_id))]
    return d


def get_portfolio(db: Session, pid: int) -> m.Portfolio:
    pf = db.get(m.Portfolio, pid)
    if pf is None:
        raise NotFoundError("سبد یافت نشد.")
    return pf


def save_portfolio(db: Session, p, pid: int | None = None) -> m.Portfolio:
    pf = get_portfolio(db, pid) if pid else None
    dup = db.scalar(select(m.Portfolio.id).where(m.Portfolio.name == p.name, m.Portfolio.id != (pid or 0)))
    if dup:
        raise ConflictError("سبدی با این نام وجود دارد.")
    if pf is None:
        pf = m.Portfolio(sort_order=(db.scalar(select(func.max(m.Portfolio.sort_order))) or 0) + 1)
        db.add(pf)
    elif pf.is_archived:
        raise ValidationFailure("سبد بایگانی‌شده را ابتدا بازیابی کنید.")
    pf.name, pf.description, pf.initial_capital = p.name, p.description, p.initial_capital
    pf.monthly_contribution, pf.horizon_months, pf.max_drawdown_pct = p.monthly_contribution, p.horizon_months, p.max_drawdown_pct
    pf.plan_start_date = p.plan_start_date or pf.plan_start_date or today_local()
    pf.target_mode = p.target_mode
    db.flush()
    sync_plan(db, today_local(), apply_to_past_unpaid=p.apply_to_past_unpaid, portfolio=pf)
    db.commit()
    return pf


def set_targets(db: Session, pf: m.Portfolio, members) -> list[str]:
    """جایگزینی کامل فهرست اعضا و وزن‌های هدف. عضوهای حذف‌شده تراکنش‌هایشان را حفظ می‌کنند."""
    if pf.is_archived:
        raise ValidationFailure("سبد بایگانی‌شده را ابتدا بازیابی کنید.")
    ids = [x.asset_id for x in members]
    if len(set(ids)) != len(ids):
        raise ValidationFailure("یک دارایی نباید بیش از یک بار در سبد تکرار شود.")
    assets = {a.id: a for a in db.scalars(select(m.Asset).where(m.Asset.id.in_(ids)))} if ids else {}
    for x in members:
        if x.asset_id not in assets:
            raise NotFoundError(f"دارایی {x.asset_id} یافت نشد.")
    existing = {pa.asset_id: pa for pa in db.scalars(select(m.PortfolioAsset).where(m.PortfolioAsset.portfolio_id == pf.id))}
    for x in members:
        if assets[x.asset_id].is_archived and x.asset_id not in existing:
            raise ValidationFailure(f"دارایی «{assets[x.asset_id].name}» بایگانی شده و به سبد اضافه نمی‌شود.")
    active = [x for x in members if x.is_active]
    if pf.target_mode == "percent":
        total = sum((x.target_weight for x in active), Decimal(0))
        if active and total != HUNDRED:
            raise ValidationFailure(f"مجموع وزن‌های هدف اعضای فعال باید دقیقاً ۱۰۰٪ باشد (اکنون {total.normalize():f}٪).")
    elif active and sum((x.target_amount for x in active), Decimal(0)) <= 0:
        raise ValidationFailure("حداقل برای یک دارایی فعال مبلغ هدف مثبت وارد کنید.")
    warnings = []
    for aid, pa in list(existing.items()):
        if aid not in ids:
            held = db.scalar(select(func.count()).select_from(m.Transaction).where(
                m.Transaction.portfolio_id == pf.id, m.Transaction.asset_id == aid))
            if held:
                warnings.append(f"«{pa.asset.name}» از سبد خارج شد؛ تراکنش‌هایش حفظ شده و در گزارش‌ها دیده می‌شود، "
                                "ولی دیگر در پیشنهاد خرید نمی‌آید.")
            db.delete(pa)
    for x in members:
        pa = existing.get(x.asset_id)
        if pa is None:
            pa = m.PortfolioAsset(portfolio_id=pf.id, asset_id=x.asset_id)
            db.add(pa)
        pa.target_weight, pa.target_amount, pa.is_active = x.target_weight, x.target_amount, x.is_active
    db.commit()
    return warnings


def add_member(db: Session, pf: m.Portfolio, asset_id: int, target_weight: Decimal = Decimal(0),
               target_amount: Decimal = Decimal(0)) -> m.PortfolioAsset:
    a = db.get(m.Asset, asset_id)
    if a is None:
        raise NotFoundError("دارایی یافت نشد.")
    if a.is_archived:
        raise ValidationFailure("دارایی بایگانی‌شده به سبد اضافه نمی‌شود؛ ابتدا آن را بازیابی کنید.")
    if pf.is_archived:
        raise ValidationFailure("سبد بایگانی شده است.")
    pa = db.scalar(select(m.PortfolioAsset).where(m.PortfolioAsset.portfolio_id == pf.id, m.PortfolioAsset.asset_id == asset_id))
    if pa is not None:
        raise ConflictError("این دارایی از قبل عضو سبد است.")
    pa = m.PortfolioAsset(portfolio_id=pf.id, asset_id=asset_id, target_weight=target_weight, target_amount=target_amount)
    db.add(pa)
    db.commit()
    return pa


def remove_member(db: Session, pf: m.Portfolio, asset_id: int) -> dict:
    pa = db.scalar(select(m.PortfolioAsset).where(m.PortfolioAsset.portfolio_id == pf.id, m.PortfolioAsset.asset_id == asset_id))
    if pa is None:
        raise NotFoundError("این دارایی عضو سبد نیست.")
    n_tx = db.scalar(select(func.count()).select_from(m.Transaction).where(
        m.Transaction.portfolio_id == pf.id, m.Transaction.asset_id == asset_id)) or 0
    db.delete(pa)
    db.commit()
    return {"ok": True, "kept_transactions": n_tx}


def archive_portfolio(db: Session, pf: m.Portfolio, archive: bool) -> m.Portfolio:
    if archive and pf.is_default:
        raise ValidationFailure("سبد پیش‌فرض را نمی‌توان بایگانی کرد؛ ابتدا سبد دیگری را پیش‌فرض کنید.")
    pf.is_archived = archive
    pf.archived_at = now_local() if archive else None
    db.commit()
    return pf


def make_default(db: Session, pf: m.Portfolio) -> m.Portfolio:
    if pf.is_archived:
        raise ValidationFailure("سبد بایگانی‌شده پیش‌فرض نمی‌شود.")
    for other in db.scalars(select(m.Portfolio).where(m.Portfolio.is_default.is_(True))):
        other.is_default = False
    pf.is_default = True
    db.commit()
    return pf


def delete_portfolio(db: Session, pf: m.Portfolio) -> None:
    if pf.is_default:
        raise ValidationFailure("سبد پیش‌فرض قابل حذف نیست.")
    n_tx = db.scalar(select(func.count()).select_from(m.Transaction).where(m.Transaction.portfolio_id == pf.id)) or 0
    if n_tx:
        raise ConflictError(f"این سبد {n_tx} تراکنش دارد و فقط قابل بایگانی است.", code="has_transactions",
                            details={"transactions": n_tx})
    db.execute(delete(m.PortfolioAsset).where(m.PortfolioAsset.portfolio_id == pf.id))
    db.execute(delete(m.PlanPeriod).where(m.PlanPeriod.portfolio_id == pf.id))
    db.delete(pf)
    db.commit()
