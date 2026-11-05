"""قیمت‌گذاری: انتخاب «قیمت روز» معتبر و ارزش‌گذاری سبد.

قاعده مهم: قیمت تأییدنشده، قدیمی (بیش از max_price_age_days) یا بدون نرخ ارز لازم،
هرگز به‌عنوان قیمت روز استفاده نمی‌شود؛ به‌جای آن دلیل نامعتبر بودن برگردانده می‌شود.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal

from .ledger import LedgerState, Position, replay
from .types import AssetRec, BASE_CURRENCY, DataSet, FxRec, PriceRec, ZERO, HUNDRED

REASONS = {
    "no_price": "قیمت تأییدشده‌ای ثبت نشده است",
    "stale": "قیمت ثبت‌شده قدیمی است",
    "currency_mismatch": "واحد پول قیمت‌های ثبت‌شده با واحد پول دارایی هم‌خوان نیست",
    "no_fx": "نرخ ارز تأییدشده‌ای ثبت نشده است",
    "stale_fx": "نرخ ارز ثبت‌شده قدیمی است",
    "conflict": "اختلاف غیرعادی بین منابع قیمت؛ تا تصمیم شما (قیمت دستی یا تأیید یک قیمت) استفاده نمی‌شود",
}


@dataclass(frozen=True)
class Quote:
    ok: bool
    price_irt: Decimal | None = None
    native_price: Decimal | None = None
    currency: str = BASE_CURRENCY
    fx_rate: Decimal | None = None
    recorded_at: datetime | None = None
    fx_recorded_at: datetime | None = None
    age_days: int | None = None
    reason: str | None = None  # کد دلیل در صورت نامعتبر بودن
    last_price: Decimal | None = None  # آخرین قیمت (فقط برای اطلاع؛ به‌عنوان قیمت روز استفاده نمی‌شود)
    last_recorded_at: datetime | None = None

    @property
    def reason_text(self) -> str | None:
        return REASONS.get(self.reason) if self.reason else None


class PriceBook:
    def __init__(self, prices: list[PriceRec], fx: list[FxRec], max_age_days: int):
        self.max_age = max_age_days
        self._p: dict[int, list[PriceRec]] = {}
        self._pk: dict[int, list[datetime]] = {}
        for p in sorted((p for p in prices if p.approved), key=lambda p: (p.recorded_at, p.id)):
            self._p.setdefault(p.asset_id, []).append(p)
        for k, v in self._p.items():
            self._pk[k] = [x.recorded_at for x in v]
        self._f: dict[str, list[FxRec]] = {}
        self._fk: dict[str, list[datetime]] = {}
        for r in sorted((r for r in fx if r.approved), key=lambda r: (r.recorded_at, r.id)):
            self._f.setdefault(r.currency, []).append(r)
        for k, v in self._f.items():
            self._fk[k] = [x.recorded_at for x in v]

    def price_dates(self) -> set[date]:
        return {p.recorded_at.date() for v in self._p.values() for p in v} | {
            r.recorded_at.date() for v in self._f.values() for r in v
        }

    def _latest(self, store, keys, key, as_of):
        arr = store.get(key)
        if not arr:
            return None
        i = bisect_right(keys[key], as_of)
        return arr[i - 1] if i else None

    def quote(self, asset: AssetRec, as_of: datetime) -> Quote:
        rec = self._latest(self._p, self._pk, asset.id, as_of)
        if rec is None:
            return Quote(False, currency=asset.price_currency, reason="no_price")
        age = (as_of.date() - rec.recorded_at.date()).days
        base = dict(currency=asset.price_currency, recorded_at=rec.recorded_at, age_days=age,
                    last_price=rec.price, last_recorded_at=rec.recorded_at)
        if rec.flag == "conflict":
            return Quote(False, reason="conflict", **base)
        if rec.currency != asset.price_currency:
            return Quote(False, reason="currency_mismatch", **base)
        if age > self.max_age:
            return Quote(False, reason="stale", **base)
        if asset.price_currency == BASE_CURRENCY:
            return Quote(True, price_irt=rec.price, native_price=rec.price, **base)
        fx = self._latest(self._f, self._fk, asset.price_currency, as_of)
        if fx is None:
            return Quote(False, reason="no_fx", **base)
        if (as_of.date() - fx.recorded_at.date()).days > self.max_age:
            return Quote(False, reason="stale_fx", fx_rate=fx.rate, fx_recorded_at=fx.recorded_at, **base)
        return Quote(True, price_irt=rec.price * fx.rate, native_price=rec.price, fx_rate=fx.rate,
                     fx_recorded_at=fx.recorded_at, **base)


def end_of_day(d: date) -> datetime:
    return datetime.combine(d, time(23, 59, 59))


@dataclass
class AssetValuation:
    asset: AssetRec
    pos: Position
    quote: Quote
    value: Decimal | None  # ارزش روز (None اگر قیمت معتبر نیست)
    unrealized: Decimal | None
    unrealized_pct: Decimal | None
    total_pnl: Decimal | None
    return_pct: Decimal | None
    fx_effect: dict | None = None


def fx_decomposition(asset: AssetRec, pos: Position, q: Quote) -> dict | None:
    """تفکیک سود/زیان تحقق‌نیافته به اثر قیمت دارایی (به ارز) و اثر تغییر نرخ ارز.

    unrealized = (ارزش ارزی − بهای ارزی) × نرخ فعلی  +  بهای ارزی × (نرخ فعلی − نرخ میانگین خرید)
    """
    if asset.price_currency == BASE_CURRENCY or pos.units <= 0:
        return None
    if not q.ok or q.fx_rate is None:
        return {"available": False, "reason": "قیمت یا نرخ ارز معتبر موجود نیست."}
    if not pos.fx_complete or not pos.foreign_cost or pos.foreign_cost <= 0:
        return {"available": False, "reason": "نرخ ارز در همه خریدها ثبت نشده است؛ تفکیک اثر نرخ ارز ممکن نیست."}
    value_fx = pos.units * q.native_price
    fx_avg = pos.cost / pos.foreign_cost
    asset_effect = (value_fx - pos.foreign_cost) * q.fx_rate
    fx_effect = pos.foreign_cost * (q.fx_rate - fx_avg)
    return {
        "available": True, "currency": asset.price_currency, "fx_rate_now": q.fx_rate, "fx_rate_avg_cost": fx_avg,
        "foreign_cost": pos.foreign_cost, "asset_price_effect": asset_effect, "fx_rate_effect": fx_effect,
        "total_unrealized": asset_effect + fx_effect,
    }


def value_asset(asset: AssetRec, pos: Position, quote: Quote) -> AssetValuation:
    value = pos.units * quote.price_irt if (quote.ok and pos.units > 0) else (ZERO if pos.units == 0 else None)
    unreal = None
    unreal_pct = None
    if value is not None:
        unreal = value - pos.cost
        unreal_pct = unreal / pos.cost * HUNDRED if pos.cost > 0 else None
    total = None
    ret = None
    if unreal is not None:
        total = pos.realized + pos.dividends - pos.fees + pos.adjustments + unreal
        basis = pos.bought_cost
        ret = total / basis * HUNDRED if basis > 0 else None
    return AssetValuation(asset, pos, quote, value, unreal, unreal_pct, total, ret, fx_decomposition(asset, pos, quote))


@dataclass
class PortfolioValuation:
    as_of: datetime
    state: LedgerState
    assets: list[AssetValuation]
    assets_value: Decimal  # فقط دارایی‌های دارای قیمت معتبر
    cash: Decimal
    total_value: Decimal
    cost_basis: Decimal
    unrealized: Decimal
    unpriced: list[AssetValuation]
    complete: bool

    @property
    def invested_value(self) -> Decimal:
        return self.assets_value


def make_book(ds: DataSet) -> PriceBook:
    return PriceBook(ds.prices, ds.fx, ds.config.max_price_age_days)


def value_portfolio(ds: DataSet, as_of: datetime, book: PriceBook | None = None,
                    state: LedgerState | None = None) -> PortfolioValuation:
    book = book or make_book(ds)
    state = state or replay(ds.txs, upto=as_of.date())
    rows: list[AssetValuation] = []
    for a in ds.assets:
        pos = state.positions.get(a.id)
        if pos is None:
            if not a.active:
                continue
            pos = Position(a.id)
        if not a.active and pos.units == 0 and pos.bought_cost == 0 and pos.dividends == 0:
            continue
        rows.append(value_asset(a, pos, book.quote(a, as_of)))
    priced = [r for r in rows if r.value is not None]
    unpriced = [r for r in rows if r.value is None]
    assets_value = sum((r.value for r in priced), ZERO)
    cost = sum((r.pos.cost for r in priced), ZERO)
    cash = state.total_cash
    return PortfolioValuation(
        as_of=as_of, state=state, assets=rows, assets_value=assets_value, cash=cash,
        total_value=assets_value + cash, cost_basis=cost,
        unrealized=sum((r.unrealized for r in priced), ZERO), unpriced=unpriced, complete=not unpriced,
    )
