"""قرارداد مشترک منابع قیمت (Provider Contract).

هر Provider باید این موارد را فراهم کند: قیمت فعلی، اطلاعات نماد، تاریخچهٔ قیمت، بررسی سلامت،
گزارش خطا، زمان آخرین دریافت و واحد قیمت. وضعیت آخرین دریافت/خطا توسط Engine در دیتابیس ثبت می‌شود
و در ``status()`` نیز در دسترس است.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .http import HttpClient

_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٫٬،", "01234567890123456789.,,")


class ProviderError(Exception):
    """خطای منبع قیمت. code برای دسته‌بندی در لاگ و UI؛ retriable برای تصمیم retry."""

    def __init__(self, message: str, code: str = "error", retriable: bool = False, http_status: int | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.retriable = retriable
        self.http_status = http_status


@dataclass
class Quote:
    price: Decimal
    unit: str  # IRR | IRT | USD | USDT | ... (واحد قیمت در منبع)
    source_time: datetime | None  # زمان قیمت در منبع (وقت محلی، بدون tz)؛ None اگر منبع زمان نمی‌دهد
    kind: str = ""  # last | close | nav
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class SymbolInfo:
    external_id: str
    symbol: str
    name: str = ""
    market: str = ""
    active: bool | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class HistoryPoint:
    time: datetime
    price: Decimal
    kind: str = "close"


@dataclass
class Health:
    ok: bool
    message: str
    latency_ms: int | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderConfig:
    id: int | None
    name: str
    kind: str
    base_url: str = ""
    auth_type: str = "none"
    auth_param_name: str = ""
    api_key: str = ""
    request_params: dict[str, str] = field(default_factory=dict)
    field_map: dict[str, str] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)  # PriceProvider.config
    input_currency: str = ""
    timeout: float = 8.0


def to_decimal(v: Any, what: str = "قیمت") -> Decimal:
    if isinstance(v, bool) or v is None:
        raise ProviderError(f"مقدار {what} در پاسخ منبع معتبر نیست.", "parse")
    if isinstance(v, (int, float, Decimal)):
        s = str(v)
    else:
        s = str(v).strip().translate(_FA_DIGITS).replace(",", "").replace(" ", "")
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise ProviderError(f"مقدار {what} عددی نیست: {str(v)[:40]!r}", "parse")
    if not d.is_finite():
        raise ProviderError(f"مقدار {what} نامحدود/نامعتبر است.", "parse")
    return d


def normalize_fa(text: str) -> str:
    """یکسان‌سازی ي/ك عربی با ی/ک فارسی و حذف نیم‌فاصله‌های اضافی برای جستجو."""
    return (text or "").replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ").strip()


class PriceProvider(ABC):
    kind: str = ""
    label: str = ""
    default_unit: str = "IRT"
    supports_history: bool = False
    supports_search: bool = False

    def __init__(self, cfg: ProviderConfig, http: HttpClient):
        self.cfg = cfg
        self.http = http
        self.last_fetch_at: datetime | None = None
        self.last_error: str | None = None

    @property
    def price_unit(self) -> str:
        return (self.cfg.input_currency or self.default_unit).upper()

    def status(self) -> dict:
        return {"kind": self.kind, "price_unit": self.price_unit, "last_fetch_at": self.last_fetch_at,
                "last_error": self.last_error}

    @abstractmethod
    def get_quote(self, external_id: str, price_field: str = "") -> Quote:
        """قیمت فعلی نماد/بازار."""

    def symbol_info(self, external_id: str) -> SymbolInfo:
        raise ProviderError("این منبع اطلاعات نماد را پشتیبانی نمی‌کند.", "unsupported")

    def search_symbols(self, query: str) -> list[SymbolInfo]:
        raise ProviderError("این منبع جستجوی نماد را پشتیبانی نمی‌کند.", "unsupported")

    def get_history(self, external_id: str, start: date, end: date) -> list[HistoryPoint]:
        raise ProviderError("این منبع تاریخچهٔ قیمت را پشتیبانی نمی‌کند.", "unsupported")

    @abstractmethod
    def health(self) -> Health:
        """بررسی سلامت اتصال (بدون ثبت قیمت)."""


_ID_RE = re.compile(r"^[\w\-.:/ ]{1,120}$", re.UNICODE)


def safe_external_id(v: str) -> str:
    v = (v or "").strip()
    if not v or not _ID_RE.match(v):
        raise ProviderError("شناسهٔ دارایی در منبع خالی یا نامعتبر است.", "config")
    return v
