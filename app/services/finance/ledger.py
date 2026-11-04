"""دفتر کل تراکنش‌ها: میانگین موزون، بهای تمام‌شده، سود و زیان تحقق‌یافته و نقدینگی.

قواعد:
* خرید: بهای تمام‌شده = تعداد × قیمت + کارمزد (کارمزد وارد بهای تمام‌شده می‌شود).
* فروش: درآمد خالص = تعداد × قیمت − کارمزد؛ سود تحقق‌یافته = درآمد خالص − (میانگین موزون × تعداد).
* سود نقدی: نقدینگی را افزایش می‌دهد و جزو سود تحقق‌یافته است (پس از کسر کارمزد/مالیات).
* کارمزد مستقل: هزینه است و نقدینگی را کم می‌کند (وارد بهای تمام‌شده نمی‌شود).
* واریز/برداشت: جریان نقدی بیرونی هستند؛ هرگز سود محسوب نمی‌شوند.
* اصلاح موجودی با دارایی: تعداد مثبت = افزودن واحد با بهای (تعداد × قیمت) بدون اثر نقدی؛
  تعداد منفی = کسر واحد به میانگین موزون بدون سود/زیان و بدون اثر نقدی.
* اصلاح موجودی بدون دارایی: مبلغ علامت‌دار روی نقدینگی پلتفرم (درآمد/هزینه اصلاحی).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .types import TxRec, ZERO

TYPE_PRIORITY = {"deposit": 0, "adjustment": 1, "buy": 2, "dividend": 3, "sell": 4, "fee": 5, "withdrawal": 6}


class LedgerError(Exception):
    """خطای منطقی در دفتر کل (مثلاً فروش بیش از موجودی)."""

    def __init__(self, message: str, tx_id: int | None = None, asset_id: int | None = None):
        super().__init__(message)
        self.message = message
        self.tx_id = tx_id
        self.asset_id = asset_id


def tx_sort_key(t: TxRec):
    return (t.date, TYPE_PRIORITY.get(t.type, 9), t.id)


@dataclass
class Position:
    asset_id: int
    units: Decimal = ZERO
    cost: Decimal = ZERO  # بهای تمام‌شده باقیمانده (شامل کارمزد خرید)
    foreign_cost: Decimal | None = ZERO  # بهای تمام‌شده به ارز (فقط اگر نرخ ارز همه خریدها ثبت شده)
    realized: Decimal = ZERO  # سود/زیان تحقق‌یافته از فروش
    dividends: Decimal = ZERO
    fees: Decimal = ZERO  # کارمزدهای مستقل منتسب به دارایی
    adjustments: Decimal = ZERO  # اثر خالص اصلاحات موجودی (بهای افزوده − بهای کسرشده)
    bought_cost: Decimal = ZERO  # مجموع مبلغ خرید (شامل کارمزد)
    bought_units: Decimal = ZERO
    sold_units: Decimal = ZERO
    sold_proceeds: Decimal = ZERO
    first_date: date | None = None

    @property
    def avg_cost(self) -> Decimal | None:
        return self.cost / self.units if self.units > 0 else None

    @property
    def fx_complete(self) -> bool:
        return self.foreign_cost is not None


@dataclass
class LedgerState:
    positions: dict[int, Position] = field(default_factory=dict)
    cash: dict[int, Decimal] = field(default_factory=lambda: defaultdict(lambda: ZERO))
    deposits: Decimal = ZERO
    withdrawals: Decimal = ZERO
    deposits_by_platform: dict[int, Decimal] = field(default_factory=lambda: defaultdict(lambda: ZERO))
    withdrawals_by_platform: dict[int, Decimal] = field(default_factory=lambda: defaultdict(lambda: ZERO))
    standalone_fees: Decimal = ZERO  # کارمزدهای مستقل (بدون دارایی)
    cash_adjustments: Decimal = ZERO

    def position(self, asset_id: int) -> Position:
        if asset_id not in self.positions:
            self.positions[asset_id] = Position(asset_id)
        return self.positions[asset_id]

    # ---- جمع‌های تجمیعی ----
    @property
    def total_cash(self) -> Decimal:
        return sum(self.cash.values(), ZERO)

    @property
    def realized_sales(self) -> Decimal:
        return sum((p.realized for p in self.positions.values()), ZERO)

    @property
    def dividends(self) -> Decimal:
        return sum((p.dividends for p in self.positions.values()), ZERO)

    @property
    def asset_fees(self) -> Decimal:
        return sum((p.fees for p in self.positions.values()), ZERO)

    @property
    def asset_adjustments(self) -> Decimal:
        return sum((p.adjustments for p in self.positions.values()), ZERO)

    @property
    def total_fees(self) -> Decimal:
        return self.standalone_fees + self.asset_fees


def apply_tx(state: LedgerState, t: TxRec) -> None:
    """اعمال یک تراکنش روی وضعیت. در صورت ناسازگاری LedgerError می‌دهد."""
    ty = t.type
    if ty == "deposit":
        state.cash[t.platform_id] += t.total
        state.deposits += t.total
        state.deposits_by_platform[t.platform_id] += t.total
    elif ty == "withdrawal":
        state.cash[t.platform_id] -= t.total
        state.withdrawals += t.total
        state.withdrawals_by_platform[t.platform_id] += t.total
    elif ty == "buy":
        _need_asset(t)
        pos = state.position(t.asset_id)
        pos.units += t.quantity
        pos.cost += t.total
        pos.bought_cost += t.total
        pos.bought_units += t.quantity
        _add_foreign(pos, t, t.total)
        pos.first_date = pos.first_date or t.date
        state.cash[t.platform_id] -= t.total
    elif ty == "sell":
        _need_asset(t)
        pos = state.position(t.asset_id)
        if pos.units < t.quantity:
            raise LedgerError(
                f"موجودی کافی برای فروش وجود ندارد (موجودی {pos.units.normalize():f}، فروش {t.quantity.normalize():f}).",
                t.id, t.asset_id,
            )
        cost_removed = _remove_units(pos, t.quantity)
        pos.realized += t.total - cost_removed
        pos.sold_units += t.quantity
        pos.sold_proceeds += t.total
        state.cash[t.platform_id] += t.total
    elif ty == "dividend":
        if t.asset_id is not None:
            state.position(t.asset_id).dividends += t.total
        else:
            state.cash_adjustments += t.total
        state.cash[t.platform_id] += t.total
    elif ty == "fee":
        if t.asset_id is not None:
            state.position(t.asset_id).fees += t.total
        else:
            state.standalone_fees += t.total
        state.cash[t.platform_id] -= t.total
    elif ty == "adjustment":
        if t.asset_id is None:
            state.cash[t.platform_id] += t.total
            state.cash_adjustments += t.total
        else:
            pos = state.position(t.asset_id)
            if t.quantity > 0:
                added = t.quantity * (t.unit_price or ZERO)
                pos.units += t.quantity
                pos.cost += added
                pos.adjustments += added
                _add_foreign(pos, t, added)
                pos.first_date = pos.first_date or t.date
            elif t.quantity < 0:
                q = -t.quantity
                if pos.units < q:
                    raise LedgerError("اصلاح موجودی بیش از موجودی فعلی دارایی است.", t.id, t.asset_id)
                removed = _remove_units(pos, q)
                pos.adjustments -= removed
    else:  # pragma: no cover
        raise LedgerError(f"نوع تراکنش ناشناخته: {ty}", t.id)


def _need_asset(t: TxRec) -> None:
    if t.asset_id is None or t.quantity is None or t.quantity <= 0:
        raise LedgerError("تراکنش خرید/فروش به دارایی و تعداد مثبت نیاز دارد.", t.id)


def _add_foreign(pos: Position, t: TxRec, cost_added: Decimal) -> None:
    if pos.foreign_cost is None:
        return
    if t.fx_rate and t.fx_rate > 0:
        pos.foreign_cost += cost_added / t.fx_rate
    else:
        # نرخ ارز ثبت نشده است: تفکیک اثر نرخ ارز ممکن نیست
        pos.foreign_cost = None


def _remove_units(pos: Position, q: Decimal) -> Decimal:
    """کسر q واحد با میانگین موزون؛ بهای کسرشده را برمی‌گرداند."""
    if q == pos.units:
        removed = pos.cost
        pos.units = ZERO
        pos.cost = ZERO
        pos.foreign_cost = ZERO  # بستن کامل موقعیت: ردیابی بهای ارزی از نو آغاز می‌شود
        return removed
    removed = pos.cost * q / pos.units
    if pos.foreign_cost is not None:
        pos.foreign_cost -= pos.foreign_cost * q / pos.units
    pos.units -= q
    pos.cost -= removed
    return removed


def replay(txs: list[TxRec], upto: date | None = None) -> LedgerState:
    """بازپخش تمام تراکنش‌ها به ترتیب (تاریخ، اولویت نوع، شناسه)."""
    state = LedgerState()
    for t in sorted(txs, key=tx_sort_key):
        if upto is not None and t.date > upto:
            break
        apply_tx(state, t)
    return state


def validate(txs: list[TxRec]) -> LedgerState:
    """اعتبارسنجی کامل: هیچ دارایی نباید در هیچ نقطه‌ای موجودی منفی شود."""
    return replay(txs)
