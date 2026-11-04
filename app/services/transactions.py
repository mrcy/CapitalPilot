"""ثبت، ویرایش و حذف تراکنش‌ها با اعتبارسنجی کامل دفتر کل (بازپخش همه تراکنش‌ها)."""
from __future__ import annotations

from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models as m
from ..errors import NotFoundError, ValidationFailure
from .calendar_utils import fmt_date
from .clock import now_local, today_local
from .finance.ledger import LedgerError, replay
from .finance.types import BASE_CURRENCY, TxRec, ZERO
from .repository import get_settings_row, resolve_portfolio, tx_rec

Q4 = Decimal("0.0001")


def q4(x: Decimal) -> Decimal:
    return x.quantize(Q4, rounding=ROUND_HALF_UP)


def _decimals_of(x: Decimal) -> int:
    exp = x.normalize().as_tuple().exponent
    return -exp if isinstance(exp, int) and exp < 0 else 0


def normalize(db: Session, p: dict, existing: m.Transaction | None = None) -> dict:
    """بررسی قوانین هر نوع تراکنش و محاسبه «مبلغ نهایی» در Backend.

    existing: هنگام ویرایش، تراکنش فعلی (سبد آن تغییر نمی‌کند و محدودیت‌های «خرید جدید» برای دارایی
    قبلاً ثبت‌شده اعمال نمی‌شود تا تاریخچه قابل ویرایش بماند).
    """
    ty = p["tx_type"]
    d: date = p["tx_date"]
    if d > today_local():
        raise ValidationFailure("تاریخ تراکنش نمی‌تواند در آینده باشد.")
    fee = p.get("fee") or ZERO
    qty, price, amount = p.get("quantity"), p.get("unit_price"), p.get("amount")
    asset = db.get(m.Asset, p["asset_id"]) if p.get("asset_id") else None
    if p.get("asset_id") and asset is None:
        raise NotFoundError("دارایی انتخاب‌شده یافت نشد.")
    platform_id = p.get("platform_id")
    if asset is not None:
        if platform_id and platform_id != asset.platform_id:
            raise ValidationFailure("پلتفرم انتخاب‌شده با پلتفرم دارایی هم‌خوان نیست.")
        platform_id = asset.platform_id
    if not platform_id:
        raise ValidationFailure("پلتفرم یا دارایی باید مشخص شود.")
    if db.get(m.Platform, platform_id) is None:
        raise NotFoundError("پلتفرم یافت نشد.")
    if existing is not None:
        portfolio = resolve_portfolio(db, existing.portfolio_id)
    else:
        portfolio = resolve_portfolio(db, p.get("portfolio_id"))
        if portfolio.is_archived:
            raise ValidationFailure("این سبد بایگانی شده است؛ ابتدا آن را بازیابی کنید.")
    if ty == "buy" and asset is not None and not (existing is not None and existing.asset_id == asset.id):
        if asset.is_archived:
            raise ValidationFailure(f"دارایی «{asset.name}» بایگانی شده است و خرید جدید برای آن ثبت نمی‌شود؛ ابتدا آن را بازیابی کنید.")
        member = db.scalar(select(m.PortfolioAsset).where(m.PortfolioAsset.portfolio_id == portfolio.id,
                                                          m.PortfolioAsset.asset_id == asset.id))
        if member is None:
            raise ValidationFailure(f"دارایی «{asset.name}» عضو سبد «{portfolio.name}» نیست؛ ابتدا آن را به سبد اضافه کنید.")
    out = dict(portfolio_id=portfolio.id, tx_date=d, platform_id=platform_id, asset_id=asset.id if asset else None, tx_type=ty,
               quantity=None, unit_price=None, fee=fee, fx_rate=p.get("fx_rate"), plan_period_id=None,
               note=(p.get("note") or "").strip())

    if ty in ("buy", "sell"):
        if asset is None:
            raise ValidationFailure("برای خرید/فروش انتخاب دارایی الزامی است.")
        if qty is None or qty <= 0:
            raise ValidationFailure("تعداد واحد باید بزرگ‌تر از صفر باشد.")
        if price is None or price <= 0:
            raise ValidationFailure("قیمت هر واحد باید بزرگ‌تر از صفر باشد.")
        if asset.decimals >= 0 and _decimals_of(qty) > (asset.decimals or (6 if asset.fractional_units else 0)):
            raise ValidationFailure(f"تعداد اعشار مجاز برای «{asset.name}» حداکثر {asset.decimals} رقم است.")
        if ty == "buy" and asset.min_quantity and qty < asset.min_quantity and existing is None:
            raise ValidationFailure(f"حداقل تعداد خرید «{asset.name}» برابر {asset.min_quantity.normalize():f} است.")
        gross = qty * price
        total = gross + fee if ty == "buy" else gross - fee
        if total < 0:
            raise ValidationFailure("کارمزد بیشتر از مبلغ فروش است.")
        out.update(quantity=qty, unit_price=price, total_amount=q4(total))
    elif ty in ("deposit", "withdrawal"):
        if asset is not None:
            raise ValidationFailure("واریز/برداشت سرمایه به دارایی مرتبط نیست؛ فقط پلتفرم را انتخاب کنید.")
        if amount is None or amount <= 0:
            raise ValidationFailure("مبلغ باید بزرگ‌تر از صفر باشد.")
        if fee:
            raise ValidationFailure("برای واریز/برداشت کارمزد جداگانه ثبت نکنید؛ از تراکنش «کارمزد» استفاده کنید.")
        out.update(total_amount=q4(amount), fx_rate=None)
        if ty == "deposit" and p.get("plan_period_id"):
            period = db.get(m.PlanPeriod, p["plan_period_id"])
            if period is None:
                raise NotFoundError("دوره برنامه واریزی یافت نشد.")
            if period.portfolio_id != portfolio.id:
                raise ValidationFailure("دورهٔ انتخاب‌شده متعلق به این سبد نیست.")
            out["plan_period_id"] = p["plan_period_id"]
    elif ty == "dividend":
        if amount is None or amount <= 0:
            raise ValidationFailure("مبلغ سود نقدی باید بزرگ‌تر از صفر باشد.")
        if fee > amount:
            raise ValidationFailure("کارمزد/مالیات بیشتر از سود نقدی است.")
        out.update(total_amount=q4(amount - fee), fx_rate=None)
    elif ty == "fee":
        if amount is None or amount <= 0:
            raise ValidationFailure("مبلغ کارمزد باید بزرگ‌تر از صفر باشد.")
        if fee:
            raise ValidationFailure("برای تراکنش کارمزد، مبلغ را در فیلد «مبلغ» وارد کنید.")
        out.update(total_amount=q4(amount), fx_rate=None)
    elif ty == "adjustment":
        if asset is not None:
            if qty is None or qty == 0:
                raise ValidationFailure("برای اصلاح موجودی دارایی، تعداد (مثبت یا منفی) الزامی است.")
            if fee:
                raise ValidationFailure("برای اصلاح موجودی کارمزد ثبت نمی‌شود.")
            if qty > 0:
                if price is None or price < 0:
                    raise ValidationFailure("برای افزودن واحد، قیمت (بهای هر واحد) الزامی است؛ برای واحد بدون بها صفر وارد کنید.")
                out.update(quantity=qty, unit_price=price, total_amount=q4(qty * price))
            else:
                out.update(quantity=qty, unit_price=None, total_amount=ZERO, fx_rate=None)
        else:
            if amount is None or amount == 0:
                raise ValidationFailure("مبلغ اصلاح نقدینگی (مثبت یا منفی) الزامی است.")
            if fee:
                raise ValidationFailure("برای اصلاح نقدینگی کارمزد ثبت نمی‌شود.")
            out.update(total_amount=q4(amount), fx_rate=None)
    else:
        raise ValidationFailure("نوع تراکنش نامعتبر است.")
    return out


def _check(db: Session, recs: list[TxRec]):
    try:
        return replay(recs)
    except LedgerError as e:
        asset = db.get(m.Asset, e.asset_id) if e.asset_id else None
        where = f" ({asset.name})" if asset else ""
        raise ValidationFailure(f"این تغییر باعث ناسازگاری حساب می‌شود{where}: {e.message}", code="ledger_inconsistent") from e


def _warnings(db: Session, state) -> list[str]:
    out = []
    for pid, cash in state.cash.items():
        if cash < 0:
            pl = db.get(m.Platform, pid)
            out.append(f"نقدینگی پلتفرم «{pl.name if pl else pid}» منفی شده است؛ احتمالاً واریزی ثبت نشده است.")
    return out


def _all_recs(db: Session, portfolio_id: int, exclude_id: int | None = None) -> list[TxRec]:
    """دفتر کل هر سبد مستقل است؛ سازگاری فقط درون همان سبد بررسی می‌شود."""
    return [tx_rec(t) for t in db.scalars(select(m.Transaction).where(m.Transaction.portfolio_id == portfolio_id))
            if t.id != exclude_id]


def _rec_from_cols(cols: dict, id_: int) -> TxRec:
    return TxRec(id_, cols["tx_date"], cols["tx_type"], cols["platform_id"], cols["asset_id"], cols["quantity"],
                 cols["unit_price"], cols["fee"], cols["total_amount"], cols["fx_rate"], cols["plan_period_id"])


def create_transaction(db: Session, payload: dict) -> tuple[m.Transaction, list[str]]:
    cols = normalize(db, payload)
    recs = _all_recs(db, cols["portfolio_id"])
    nid = db.scalar(select(func.coalesce(func.max(m.Transaction.id), 0))) + 1
    state = _check(db, recs + [_rec_from_cols(cols, nid)])
    t = m.Transaction(**cols)
    db.add(t)
    db.flush()
    warnings = _warnings(db, state)
    if payload.get("record_price") and cols["tx_type"] in ("buy", "sell") and cols["asset_id"]:
        w = _record_price_from_tx(db, t)
        if w:
            warnings.append(w)
    db.commit()
    return t, warnings


def _record_price_from_tx(db: Session, t: m.Transaction) -> str | None:
    asset = db.get(m.Asset, t.asset_id)
    if asset.price_currency == BASE_CURRENCY:
        native = t.unit_price
    elif t.fx_rate:
        native = t.unit_price / t.fx_rate
    else:
        return "قیمت روز ثبت نشد: برای دارایی ارزی، نرخ ارز تراکنش لازم است."
    now = now_local()
    when = datetime.combine(t.tx_date, now.time() if t.tx_date == now.date() else time(12, 0))
    db.add(m.Price(asset_id=asset.id, price=native, currency=asset.price_currency, recorded_at=when,
                   source=f"تراکنش #{t.id}", is_approved=True, note="ثبت‌شده همراه تراکنش"))
    return None


def update_transaction(db: Session, tx_id: int, payload: dict) -> tuple[m.Transaction, list[str]]:
    t = db.get(m.Transaction, tx_id)
    if t is None:
        raise NotFoundError("تراکنش یافت نشد.")
    cols = normalize(db, payload, existing=t)
    recs = _all_recs(db, t.portfolio_id, exclude_id=tx_id) + [_rec_from_cols(cols, tx_id)]
    state = _check(db, recs)
    for k, v in cols.items():
        setattr(t, k, v)
    db.flush()
    warnings = _warnings(db, state)
    db.commit()
    return t, warnings


def delete_transaction(db: Session, tx_id: int) -> list[str]:
    t = db.get(m.Transaction, tx_id)
    if t is None:
        raise NotFoundError("تراکنش یافت نشد.")
    state = _check(db, _all_recs(db, t.portfolio_id, exclude_id=tx_id))
    db.delete(t)
    db.flush()
    warnings = _warnings(db, state)
    db.commit()
    return warnings


def tx_to_dict(t: m.Transaction, calendar: str = "jalali") -> dict:
    return {
        "id": t.id, "portfolio_id": t.portfolio_id, "tx_date": t.tx_date, "tx_date_fa": fmt_date(t.tx_date, calendar), "platform_id": t.platform_id,
        "platform": t.platform.name if t.platform else None, "asset_id": t.asset_id,
        "asset": t.asset.name if t.asset else None, "tx_type": t.tx_type, "quantity": t.quantity,
        "unit_price": t.unit_price, "fee": t.fee, "total_amount": t.total_amount, "fx_rate": t.fx_rate,
        "plan_period_id": t.plan_period_id, "note": t.note,
    }


def create_many(db: Session, payloads: list[dict]) -> tuple[list[m.Transaction], list[str]]:
    """ثبت اتمیک چند تراکنش (همه یا هیچ)."""
    cols_list = [normalize(db, p) for p in payloads]
    nid = db.scalar(select(func.coalesce(func.max(m.Transaction.id), 0)))
    pids = {c["portfolio_id"] for c in cols_list}
    state = None
    for pid in pids:
        extra = [_rec_from_cols(c, nid + i + 1) for i, c in enumerate(cols_list) if c["portfolio_id"] == pid]
        state = _check(db, _all_recs(db, pid) + extra)
    rows = [m.Transaction(**c) for c in cols_list]
    db.add_all(rows)
    db.flush()
    warnings = _warnings(db, state)
    db.commit()
    return rows, warnings
