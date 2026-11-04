"""لایهٔ مستقل کنترل کیفیت قیمت (Price Quality Engine).

اصول:
* هیچ قیمت نامعتبر (صفر/منفی/غیرعددی/آینده/کهنه/واحد ناسازگار) وارد ارزش‌گذاری نمی‌شود.
* هر قیمت دریافتی همراه با منبع، زمان دریافت، قیمت خام و ردپای تبدیل واحد ذخیره می‌شود.
* در اختلاف غیرعادی بین منابع، سیستم خودسرانه یکی را انتخاب نمی‌کند: قیمت دارایی «در اختلاف» اعلام می‌شود تا کاربر
  خودش قیمت دستی ثبت کند یا قیمت مشخصی را صریحاً تأیید کند.
* قیمت دستی (origin=manual) همیشه از قیمت آنلاین (origin=online) قابل تشخیص است.
* آخرین قیمت معتبر (last_good) و وضعیت آخرین تلاش دریافت (latest_attempt) جدا از هم گزارش می‌شوند.

این ماژول به شبکه و پایگاه‌داده وابسته نیست؛ توابع روی رکوردهای قیمت (هر شیء با ویژگی‌های مدل Price) کار می‌کنند.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Iterable, Sequence

from ...config import get_settings
from .base import ProviderError
from .calendar import is_market_open

FUTURE_TOLERANCE = timedelta(minutes=10)
UNIT_ALIASES = {"TOMAN": "IRT", "TMN": "IRT", "RIAL": "IRR", "RLS": "IRR", "تومان": "IRT", "ریال": "IRR"}

# برچسب‌های کیفیت ذخیره‌شده روی هر رکورد
FLAG_LABELS = {
    "jump": "تغییر شدید نسبت به قیمت قبلی",
    "time_lag": "فاصلهٔ زیاد زمان منبع با زمان دریافت",
    "no_source_time": "منبع زمان قیمت را اعلام نکرده (زمان دریافت جایگزین شد)",
    "future_time": "زمان قیمت در آینده است",
    "stale": "قیمت قدیمی",
    "non_positive": "قیمت صفر، منفی یا نامعتبر",
    "unit_converted": "واحد قیمت تبدیل شد",
}


def norm_unit(u: str) -> str:
    u = (u or "").strip().upper()
    return UNIT_ALIASES.get(u, UNIT_ALIASES.get(u.lower(), u))


def convert_unit(price: Decimal, unit: str, target: str) -> Decimal:
    """تبدیل واحد قیمت (ریال↔تومان، ضریب ۱۰). ارز خارجی اینجا تبدیل نمی‌شود: قیمت به ارز خودش ذخیره و با نرخ ارز ثبت‌شده ارزش‌گذاری می‌شود."""
    u, t = norm_unit(unit), norm_unit(target)
    if u == t:
        return price
    if u == "IRR" and t == "IRT":
        return price / 10
    if u == "IRT" and t == "IRR":
        return price * 10
    raise ProviderError(f"واحد قیمت منبع ({u}) با واحد دارایی ({t}) سازگار نیست؛ «واحد ورودی» منبع یا واحد دارایی را اصلاح کنید.", "currency_mismatch")


def _fmt(d: Decimal) -> str:
    s = format(d.normalize(), "f")
    return s


def conversion_trace(raw: Decimal, unit: str, target: str, converted: Decimal) -> str:
    """توضیح شفاف و قابل ردیابی از تبدیل واحد."""
    u, t = norm_unit(unit), norm_unit(target)
    if u == t:
        return f"بدون تبدیل ({_fmt(raw)} {t})"
    if u == "IRR" and t == "IRT":
        return f"{_fmt(raw)} IRR ÷ 10 = {_fmt(converted)} IRT"
    if u == "IRT" and t == "IRR":
        return f"{_fmt(raw)} IRT × 10 = {_fmt(converted)} IRR"
    return f"{_fmt(raw)} {u} → {_fmt(converted)} {t}"


@dataclass
class Assessment:
    valid: bool
    price: Decimal
    note: str = ""
    flags: list[str] = field(default_factory=list)
    conversion_note: str = ""
    raw_price: Decimal | None = None
    raw_unit: str = ""

    @property
    def flags_json(self) -> str:
        return json.dumps(self.flags, ensure_ascii=False)


def pct_change(new: Decimal, old: Decimal) -> Decimal | None:
    if old is None or old == 0:
        return None
    return abs(new - old) / abs(old) * 100


def assess_quote(*, raw_price: Decimal | None, unit: str, source_time: datetime | None, now: datetime, asset_currency: str,
                 max_age_days: int, market: str = "none", prev_price: Decimal | None = None) -> Assessment:
    """اعتبارسنجی یک قیمت دریافتی. در ناسازگاری واحد ProviderError(currency_mismatch) پرتاب می‌شود."""
    s = get_settings()
    if raw_price is None or not raw_price.is_finite() or raw_price <= 0:
        return Assessment(False, Decimal(0), "قیمت دریافتی صفر، منفی یا نامعتبر است.", ["non_positive"],
                          raw_price=raw_price if raw_price is not None and raw_price.is_finite() else None, raw_unit=unit or "")
    price = convert_unit(raw_price, unit, asset_currency)  # ProviderError(currency_mismatch)
    flags: list[str] = []
    trace = conversion_trace(raw_price, unit, asset_currency, price)
    if norm_unit(unit) != norm_unit(asset_currency):
        flags.append("unit_converted")
    a = Assessment(True, price, "", flags, trace, raw_price, norm_unit(unit))
    if source_time is None:
        flags.append("no_source_time")
    else:
        if source_time > now + FUTURE_TOLERANCE:
            flags.append("future_time")
            a.valid, a.note = False, "زمان قیمت در آینده است."
            return a
        age = (now.date() - source_time.date()).days
        if age > max_age_days:
            flags.append("stale")
            a.valid, a.note = False, f"قیمت قدیمی است ({age} روز پیش؛ حداکثر مجاز {max_age_days} روز)."
            return a
        lag = now - source_time
        if market in ("24h", "tse") and is_market_open(market, now) and lag > timedelta(minutes=s.quality_max_lag_minutes):
            flags.append("time_lag")
            a.note = f"زمان قیمت در منبع {int(lag.total_seconds() // 60)} دقیقه با زمان دریافت فاصله دارد."
    if prev_price is not None:
        ch = pct_change(price, prev_price)
        if ch is not None and ch > Decimal(str(s.quality_jump_pct)):
            flags.append("jump")
            a.note = (a.note + " " if a.note else "") + f"تغییر {ch:.1f}٪ نسبت به قیمت قبلی."
    return a


# ---------------------------------------------------------------- مقایسهٔ منابع و وضعیت قیمت دارایی
def source_key(p) -> tuple:
    return ("manual", "") if p.origin == "manual" else ("online", p.provider_id if p.provider_id else p.source)


def _age_days(p, now: datetime) -> int:
    return (now.date() - p.recorded_at.date()).days


def _sort_key(p):
    return (p.recorded_at, p.id)


def compare_sources(rows: Sequence, now: datetime, max_age_days: int, *, include_manual: bool = False) -> dict:
    """آخرین قیمت معتبر و تازهٔ هر منبع را مقایسه می‌کند. قیمت‌های تأییدنشده هم شمرده می‌شوند (مشاهدهٔ واقعی منبع‌اند)."""
    s = get_settings()
    fresh = [p for p in rows if p.is_valid and _age_days(p, now) <= max_age_days
             and (include_manual or p.origin != "manual")]
    if not fresh:
        return {"rows": [], "spread_pct": None, "conflict": False, "threshold_pct": s.quality_conflict_pct}
    newest = max(fresh, key=_sort_key)
    window = timedelta(hours=s.quality_compare_window_hours)
    latest: dict[tuple, object] = {}
    for p in sorted(fresh, key=_sort_key):
        if newest.recorded_at - p.recorded_at <= window:
            latest[source_key(p)] = p
    items = sorted(latest.values(), key=_sort_key, reverse=True)
    out = [{"price_id": p.id, "source": p.source, "provider_id": p.provider_id, "origin": p.origin, "price": p.price,
            "recorded_at": p.recorded_at, "fetched_at": p.fetched_at, "is_approved": p.is_approved} for p in items]
    online = [p for p in items if p.origin != "manual"]
    spread = None
    conflict = False
    if len(online) >= 2:
        lo, hi = min(p.price for p in online), max(p.price for p in online)
        spread = pct_change(hi, lo)
        conflict = spread is not None and spread > Decimal(str(s.quality_conflict_pct))
        med = median([p.price for p in online])
        for o in out:
            if o["origin"] != "manual" and med:
                o["diff_pct"] = (o["price"] - med) / med * 100
    return {"rows": out, "spread_pct": spread, "conflict": conflict, "threshold_pct": s.quality_conflict_pct}


def detect_conflict(rows: Sequence, now: datetime, max_age_days: int) -> dict | None:
    """اختلاف غیرعادی منابع آنلاین؛ مگر آنکه جدیدترین قیمت دستی یا تأییدشدهٔ صریح کاربر باشد (تصمیم کاربر ارجح است)."""
    valid = [p for p in rows if p.is_valid]
    if not valid:
        return None
    latest = max(valid, key=_sort_key)
    if latest.origin == "manual" or latest.user_confirmed:
        return None
    cmp = compare_sources(rows, now, max_age_days)
    return cmp if cmp["conflict"] else None


def price_state(rows: Sequence, now: datetime, max_age_days: int) -> dict:
    """وضعیت قیمت روز یک دارایی از روی رکوردهای قیمت.

    status: valid | manual | stale | invalid | pending | conflict | missing
    همان قاعدهٔ ارزش‌گذاری: فقط تأییدشده و معتبر؛ سن بر حسب روز تقویمی.
    """
    rows = list(rows)
    if not rows:
        return {"status": "missing", "reason": "قیمتی ثبت نشده است.", "record": None, "last_good": None, "conflict": None}
    usable = [p for p in rows if p.is_approved and p.is_valid]
    last_good = max(usable, key=_sort_key) if usable else None
    if last_good is None:
        newest = max(rows, key=_sort_key)
        if not newest.is_valid:
            return {"status": "invalid", "reason": newest.validity_note or "قیمت نامعتبر است.", "record": newest, "last_good": None, "conflict": None}
        return {"status": "pending", "reason": "قیمت دریافت‌شده هنوز تأیید نشده و در ارزش‌گذاری استفاده نمی‌شود.", "record": newest, "last_good": None, "conflict": None}
    age = _age_days(last_good, now)
    conflict = detect_conflict(rows, now, max_age_days)
    base = {"record": last_good, "last_good": last_good, "conflict": conflict, "age_days": age}
    if conflict is not None:
        return {**base, "status": "conflict", "reason": f"اختلاف غیرعادی بین منابع ({conflict['spread_pct']:.1f}٪)؛ تا تصمیم شما قیمتی استفاده نمی‌شود."}
    if age > max_age_days:
        return {**base, "status": "stale", "reason": f"قیمت قدیمی است ({age} روز پیش)."}
    if last_good.origin == "manual":
        return {**base, "status": "manual", "reason": "قیمت دستی."}
    return {**base, "status": "valid", "reason": ""}


def flags_of(p) -> list[str]:
    try:
        v = json.loads(p.quality_flags or "[]")
        return [x for x in v if isinstance(x, str)]
    except ValueError:
        return []


def conflict_asset_ids(rows_by_asset: dict[int, Sequence], now: datetime, max_age_days: int) -> dict[int, dict]:
    out = {}
    for aid, rows in rows_by_asset.items():
        c = detect_conflict(rows, now, max_age_days)
        if c:
            out[aid] = c
    return out
