from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

import httpx

from ...config import get_settings
from .base import PriceProvider, ProviderError, ProviderQuote

MAX_BYTES = 1_000_000


def _dig(data, path: str):
    cur = data
    for part in [p for p in path.split(".") if p != ""]:
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                raise ProviderError(f"مسیر JSON نامعتبر است: {part}")
        elif isinstance(cur, dict):
            if part not in cur:
                raise ProviderError(f"کلید «{part}» در پاسخ منبع پیدا نشد.")
            cur = cur[part]
        else:
            raise ProviderError("مسیر JSON در ساختار پاسخ وجود ندارد.")
    return cur


class GenericJsonProvider(PriceProvider):
    name = "generic_json"
    label = "JSON عمومی (آدرس شما)"
    param_help = {
        "url": "آدرس https منبع قیمت (میزبان باید در PRICE_API_ALLOWED_HOSTS باشد)",
        "json_path": "مسیر قیمت در پاسخ JSON، مثل data.price یا result.0.last",
        "currency": "واحد پول قیمت (پیش‌فرض: واحد پول دارایی)",
        "multiplier": "ضریب ضرب در مقدار دریافتی (مثلاً 0.1 برای تبدیل ریال به تومان)",
    }

    def fetch(self, params: dict) -> ProviderQuote:
        s = get_settings()
        url = (params or {}).get("url", "")
        path = (params or {}).get("json_path", "")
        if not url or not path:
            raise ProviderError("آدرس و مسیر JSON برای این دارایی تنظیم نشده است.")
        u = urlparse(url)
        if u.scheme not in ("http", "https") or not u.hostname:
            raise ProviderError("آدرس منبع قیمت نامعتبر است.")
        if u.hostname.lower() not in s.allowed_price_hosts:
            raise ProviderError("میزبان این آدرس در PRICE_API_ALLOWED_HOSTS مجاز نشده است (دریافت خودکار قیمت غیرفعال است).")
        headers = {"Accept": "application/json"}
        if s.price_api_key:
            headers[s.price_api_key_header] = s.price_api_key
        try:
            with httpx.Client(timeout=s.price_api_timeout_seconds, follow_redirects=False) as c:
                resp = c.get(url, headers=headers)
        except httpx.HTTPError as e:
            raise ProviderError(f"اتصال به منبع قیمت ناموفق بود: {type(e).__name__}")
        if resp.status_code != 200:
            raise ProviderError(f"منبع قیمت خطا برگرداند (HTTP {resp.status_code}).")
        if len(resp.content) > MAX_BYTES:
            raise ProviderError("پاسخ منبع بیش از حد بزرگ است.")
        try:
            raw = _dig(json.loads(resp.content), path)
            price = Decimal(str(raw).replace(",", "")) * Decimal(str(params.get("multiplier", "1")))
        except (json.JSONDecodeError, InvalidOperation):
            raise ProviderError("پاسخ منبع قابل تفسیر به‌عنوان قیمت عددی نیست.")
        if price <= 0:
            raise ProviderError("قیمت دریافتی معتبر نیست (صفر یا منفی).")
        return ProviderQuote(price=price, currency=params.get("currency") or "")
