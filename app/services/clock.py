from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from ..config import get_settings


def now_local() -> datetime:
    """زمان فعلی به‌صورت naive در منطقه زمانی برنامه."""
    return datetime.now(ZoneInfo(get_settings().app_timezone)).replace(tzinfo=None, microsecond=0)


def today_local() -> date:
    return now_local().date()
