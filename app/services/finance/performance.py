"""سری زمانی ارزش سبد، بازده زمانی (TWR)، افت سرمایه (Drawdown) و XIRR.

اصل اساسی: واریز و برداشت جریان نقدی بیرونی است و سود/زیان محسوب نمی‌شود.
افت سرمایه روی «شاخص بازده تعدیل‌شده با جریان نقدی» محاسبه می‌شود:

    شاخص_t = شاخص_{t-1} × (V_t − F_t) / V_{t-1}

که V ارزش کل سبد (دارایی‌ها + نقدینگی) و F خالص واریز − برداشت بین دو نقطه است.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from ..calendar_utils import month_key, month_label
from .ledger import LedgerState, apply_tx, tx_sort_key
from .types import DataSet, ZERO, HUNDRED
from .valuation import PriceBook, end_of_day, make_book, value_asset, Quote


@dataclass
class Point:
    date: date
    value: Decimal  # ارزش کل (دارایی + نقدینگی)
    assets_value: Decimal
    cash: Decimal
    complete: bool
    missing: list[int]
    deposits_cum: Decimal
    withdrawals_cum: Decimal
    unrealized: Decimal = ZERO
    index: float | None = None
    drawdown_pct: float | None = None
    peak_index: float | None = None


def series_dates(ds: DataSet, book: PriceBook, as_of: date) -> list[date]:
    dates = {t.date for t in ds.txs} | book.price_dates() | {as_of}
    if not ds.txs:
        return []
    first = min(t.date for t in ds.txs)
    return sorted(d for d in dates if first <= d <= as_of)


def build_series(ds: DataSet, as_of: date, book: PriceBook | None = None) -> list[Point]:
    """ارزش سبد در هر تاریخ مهم (تراکنش یا ثبت قیمت). نقاطی که قیمت معتبر ندارند complete=False هستند."""
    book = book or make_book(ds)
    txs = sorted((t for t in ds.txs if t.date <= as_of), key=tx_sort_key)
    assets = {a.id: a for a in ds.assets}
    state = LedgerState()
    i = 0
    out: list[Point] = []
    for d in series_dates(ds, book, as_of):
        while i < len(txs) and txs[i].date <= d:
            apply_tx(state, txs[i])
            i += 1
        ts = end_of_day(d)
        total = ZERO
        unreal = ZERO
        missing: list[int] = []
        for aid, pos in state.positions.items():
            if pos.units <= 0 or aid not in assets:
                continue
            q: Quote = book.quote(assets[aid], ts)
            if not q.ok:
                missing.append(aid)
                continue
            v = pos.units * q.price_irt
            total += v
            unreal += v - pos.cost
        cash = state.total_cash
        out.append(Point(d, total + cash, total, cash, not missing, missing, state.deposits, state.withdrawals, unreal))
    _apply_index(out)
    return out


def _apply_index(points: list[Point]) -> None:
    """محاسبه شاخص TWR و افت سرمایه برای نقاط کامل."""
    index = 100.0
    peak = 100.0
    last: Point | None = None
    for p in points:
        if not p.complete:
            continue
        if last is None or last.value <= 0:
            if p.value > 0:
                # نقطه مبنا (بدون بازده)
                p.index = index
                peak = max(peak, index)
                p.peak_index = peak
                p.drawdown_pct = (index / peak - 1) * 100
                last = p
            continue
        flow = (p.deposits_cum - p.withdrawals_cum) - (last.deposits_cum - last.withdrawals_cum)
        r = float((p.value - flow) / last.value)
        index *= max(r, 0.0)
        peak = max(peak, index)
        p.index = index
        p.peak_index = peak
        p.drawdown_pct = (index / peak - 1) * 100
        last = p


def drawdown_summary(points: list[Point], as_of: date, max_dd_pct: Decimal) -> dict:
    valid = [p for p in points if p.index is not None]
    if len(valid) < 2:
        return {
            "available": False,
            "reason": "برای محاسبه افت سرمایه حداقل دو نقطه ارزش‌گذاری کامل (با قیمت معتبر همه دارایی‌ها) لازم است.",
            "series": [_pt(p) for p in points],
        }
    last = valid[-1]
    peak_pt = max(valid, key=lambda p: (p.index, -p.date.toordinal()))
    max_dd_pt = min(valid, key=lambda p: p.drawdown_pct)
    current_dd = -last.drawdown_pct
    peak_equiv = last.value * Decimal(str(peak_pt.index / last.index)) if last.index else None
    return {
        "available": True,
        "is_current": last.date == as_of,
        "last_point_date": last.date,
        "current_drawdown_pct": round(current_dd, 4),
        "max_drawdown_pct": round(-max_dd_pt.drawdown_pct, 4),
        "max_drawdown_date": max_dd_pt.date,
        "peak_date": peak_pt.date,
        "peak_index": round(peak_pt.index, 4),
        "current_index": round(last.index, 4),
        "peak_equivalent_value": peak_equiv,
        "loss_from_peak": (peak_equiv - last.value) if peak_equiv is not None else None,
        "risk_used_pct": round(current_dd / float(max_dd_pct) * 100, 2) if max_dd_pct else None,
        "cumulative_twr_pct": round(last.index - 100, 4),
        "series": [_pt(p) for p in points],
    }


def _pt(p: Point) -> dict:
    return {
        "date": p.date, "value": p.value, "assets_value": p.assets_value, "cash": p.cash, "complete": p.complete,
        "deposits_cum": p.deposits_cum, "withdrawals_cum": p.withdrawals_cum,
        "net_invested": p.deposits_cum - p.withdrawals_cum,
        "index": None if p.index is None else round(p.index, 4),
        "drawdown_pct": None if p.drawdown_pct is None else round(-p.drawdown_pct, 4),
    }


# ---------------------------------------------------------------- XIRR
def xirr(flows: list[tuple[date, float]]) -> float | None:
    """نرخ بازده داخلی سالانه با جریان‌های نقدی تاریخ‌دار (روز/۳۶۵). None اگر جواب نداشته باشد."""
    if len(flows) < 2:
        return None
    if not (any(a < 0 for _, a in flows) and any(a > 0 for _, a in flows)):
        return None
    d0 = min(d for d, _ in flows)

    def f(r: float) -> float:
        return sum(a / (1.0 + r) ** ((d - d0).days / 365.0) for d, a in flows)

    lo, hi = -0.999999, 1.0
    flo = f(lo)
    fhi = f(hi)
    n = 0
    while flo * fhi > 0 and n < 60:
        hi = hi * 2 + 1
        fhi = f(hi)
        n += 1
    if flo * fhi > 0:
        return None
    for _ in range(300):
        mid = (lo + hi) / 2
        fm = f(mid)
        if abs(fm) < 1e-9:
            return mid
        if flo * fm < 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2


def portfolio_xirr(ds: DataSet, current_value: Decimal, complete: bool, as_of: date) -> dict:
    deposits = [t for t in ds.txs if t.type == "deposit" and t.date <= as_of]
    if not deposits:
        return {"available": False, "reason": "هنوز واریزی ثبت نشده است؛ بازدهی زمانی (XIRR) قابل محاسبه نیست."}
    if not complete:
        return {"available": False, "reason": "برای برخی دارایی‌ها قیمت معتبر امروز ثبت نشده است؛ XIRR محاسبه نشد."}
    first = min(t.date for t in deposits)
    span = (as_of - first).days
    if span < 30:
        return {"available": False, "reason": "حداقل ۳۰ روز از اولین واریزی لازم است تا بازدهی سالانه (XIRR) معنادار باشد."}
    flows: list[tuple[date, float]] = []
    for t in ds.txs:
        if t.date > as_of:
            continue
        if t.type == "deposit":
            flows.append((t.date, -float(t.total)))
        elif t.type == "withdrawal":
            flows.append((t.date, float(t.total)))
    flows.append((as_of, float(current_value)))
    r = xirr(flows)
    if r is None:
        return {"available": False, "reason": "جریان‌های نقدی موجود جواب معتبر برای XIRR ندارند."}
    return {"available": True, "annual_pct": round(r * 100, 4), "days": span}


# -------------------------------------------------- عملکرد دوره‌ای
def monthly_performance(points: list[Point], calendar: str) -> list[dict]:
    """عملکرد ماهانه: بازده زمانی و سود/زیان ریالی هر ماه (واریزی‌ها سود حساب نمی‌شوند)."""
    valid = [p for p in points if p.index is not None]
    if not valid:
        return []
    by_month: dict[tuple[int, int], list[Point]] = {}
    for p in valid:
        by_month.setdefault(month_key(p.date, calendar), []).append(p)
    out = []
    prev: Point | None = None
    for key in sorted(by_month):
        last = by_month[key][-1]
        if prev is None:
            # ماه اول: مبنا اولین نقطه همان ماه
            base = by_month[key][0]
        else:
            base = prev
        if base is last:
            prev = last
            continue
        flow = (last.deposits_cum - last.withdrawals_cum) - (base.deposits_cum - base.withdrawals_cum)
        out.append({
            "key": f"{key[0]}-{key[1]:02d}", "label": month_label(key, calendar),
            "return_pct": round((last.index / base.index - 1) * 100, 4),
            "pnl": last.value - base.value - flow,
            "net_flow": flow, "end_value": last.value,
        })
        prev = last
    return out


def period_stats(points: list[Point], start: date, end: date) -> dict:
    """آمار یک بازه: ارزش ابتدا/انتها، جریان‌ها، سود/زیان و بازده زمانی (واریزی‌ها سود نیستند)."""
    valid = [p for p in points if p.index is not None]
    before = [p for p in valid if p.date < start]
    inside = [p for p in valid if start <= p.date <= end]
    if not inside:
        return {"available": False, "reason": "برای این بازه نقطه ارزش‌گذاری کامل (با قیمت معتبر) وجود ندارد."}
    last = inside[-1]
    base = before[-1] if before else None
    open_value = base.value if base else ZERO
    dep = last.deposits_cum - (base.deposits_cum if base else ZERO)
    wd = last.withdrawals_cum - (base.withdrawals_cum if base else ZERO)
    ref = base or inside[0]
    ret = 0.0 if ref is last else (last.index / ref.index - 1) * 100
    return {
        "available": True,
        "opening_value": open_value, "closing_value": last.value,
        "opening_date": base.date if base else None, "closing_date": last.date,
        "deposits": dep, "withdrawals": wd,
        "pnl": last.value - open_value - (dep - wd),
        "return_pct": round(ret, 4),
    }
