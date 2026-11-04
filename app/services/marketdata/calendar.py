"""ساعات و تقویم بازار برای زمان‌بند.

بورس تهران: شنبه تا چهارشنبه در ساعات قابل تنظیم (TSE_OPEN_TIME/TSE_CLOSE_TIME). تعطیلات رسمی در برنامه ثابت نشده؛
وقتی «آخرین روز معاملاتی» از TSETMC (LastPossibleDeven) در دسترس باشد، روز تعطیل بر اساس آن تشخیص داده می‌شود
(best-effort). رمزارز ۲۴ساعته است. بازار «none» محدودیتی ندارد.
"""
from __future__ import annotations

from datetime import date, datetime, time

from ...config import get_settings

TSE_DAYS = {5, 6, 0, 1, 2}  # شنبه، یکشنبه، دوشنبه، سه‌شنبه، چهارشنبه (Python weekday)


def _t(s: str, default: time) -> time:
    try:
        h, mi = s.split(":")
        return time(int(h), int(mi))
    except (ValueError, AttributeError):
        return default


def is_market_open(market: str, now: datetime, last_trading_day: date | None = None) -> bool:
    if market in ("24h", "none", ""):
        return True
    if market != "tse":
        return True
    s = get_settings()
    if now.weekday() not in TSE_DAYS:
        return False
    opens, closes = _t(s.tse_open_time, time(8, 45)), _t(s.tse_close_time, time(12, 45))
    if not (opens <= now.time() <= closes):
        return False
    if last_trading_day is not None and last_trading_day < now.date() and now.time() >= time(10, 0):
        # تا ساعت ۱۰ معامله‌ای برای امروز ثبت نشده → احتمالاً تعطیل رسمی
        return False
    return True
