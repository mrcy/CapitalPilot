"""ابزارهای تقویم شمسی/میلادی (ذخیره‌سازی همیشه میلادی است)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import jdatetime

JALALI_MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
GREG_MONTHS = ["ژانویه", "فوریه", "مارس", "آوریل", "مه", "ژوئن", "ژوئیه", "اوت", "سپتامبر", "اکتبر", "نوامبر", "دسامبر"]
QUARTERS_JALALI = ["بهار", "تابستان", "پاییز", "زمستان"]


def to_jalali(d: date) -> tuple[int, int, int]:
    j = jdatetime.date.fromgregorian(date=d)
    return j.year, j.month, j.day


def from_jalali(y: int, m: int, d: int) -> date:
    return jdatetime.date(y, m, d).togregorian()


def fmt_date(d: date | datetime | None, calendar: str = "jalali") -> str:
    if d is None:
        return ""
    if isinstance(d, datetime):
        d = d.date()
    if calendar == "jalali":
        y, m, dd = to_jalali(d)
        return f"{y:04d}/{m:02d}/{dd:02d}"
    return d.isoformat()


def fmt_datetime(d: datetime | None, calendar: str = "jalali") -> str:
    if d is None:
        return ""
    return f"{fmt_date(d, calendar)} {d:%H:%M}"


def add_months(d: date, months: int) -> date:
    """افزودن ماه میلادی با حفظ روز ماه (در صورت نبودن روز، آخرین روز ماه)."""
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    day = d.day
    while True:
        try:
            return date(y, m, day)
        except ValueError:
            day -= 1


def add_months_calendar(d: date, months: int, calendar: str) -> date:
    if calendar != "jalali":
        return add_months(d, months)
    y, m, day = to_jalali(d)
    total = y * 12 + (m - 1) + months
    ny, nm = divmod(total, 12)
    nm += 1
    while True:
        try:
            return from_jalali(ny, nm, day)
        except ValueError:
            day -= 1


def month_key(d: date, calendar: str) -> tuple[int, int]:
    if calendar == "jalali":
        y, m, _ = to_jalali(d)
        return y, m
    return d.year, d.month


def month_label(key: tuple[int, int], calendar: str) -> str:
    y, m = key
    names = JALALI_MONTHS if calendar == "jalali" else GREG_MONTHS
    return f"{names[m - 1]} {y}"


def month_bounds(y: int, m: int, calendar: str) -> tuple[date, date]:
    if calendar == "jalali":
        start = from_jalali(y, m, 1)
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        end = from_jalali(ny, nm, 1) - timedelta(days=1)
    else:
        start = date(y, m, 1)
        end = (date(y + (m == 12), (m % 12) + 1, 1)) - timedelta(days=1)
    return start, end


def period_bounds(kind: str, year: int, index: int, calendar: str) -> tuple[date, date, str]:
    """kind: month|quarter|year ؛ index: شماره ماه/فصل (۱..)؛ خروجی: (شروع، پایان، عنوان)."""
    if kind == "month":
        s, e = month_bounds(year, index, calendar)
        return s, e, month_label((year, index), calendar)
    if kind == "quarter":
        if not 1 <= index <= 4:
            raise ValueError("شماره فصل باید ۱ تا ۴ باشد")
        s, _ = month_bounds(year, (index - 1) * 3 + 1, calendar)
        _, e = month_bounds(year, index * 3, calendar)
        name = QUARTERS_JALALI[index - 1] if calendar == "jalali" else f"Q{index}"
        return s, e, f"فصل {name} {year}"
    if kind == "year":
        s, _ = month_bounds(year, 1, calendar)
        _, e = month_bounds(year, 12, calendar)
        return s, e, f"سال {year}"
    raise ValueError("نوع بازه نامعتبر است")


def current_year_month(d: date, calendar: str) -> tuple[int, int]:
    return month_key(d, calendar)
