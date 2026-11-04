"""ماژول اتصال به منابع قیمت.

* هیچ آدرس یا API ساختگی برای بیت‌پین یا صندوق‌های مفید تعریف نشده است.
* ارائه‌دهنده عمومی `generic_json` فقط وقتی کار می‌کند که کاربر آدرس معتبر منبع خودش را
  در تنظیمات دارایی وارد کند و میزبان آن در PRICE_API_ALLOWED_HOSTS مجاز شده باشد.
* کلید API فقط از متغیر محیطی سرور خوانده می‌شود و هرگز به مرورگر ارسال نمی‌شود.
* برای افزودن منبع جدید، یک کلاس از PriceProvider بسازید و در REGISTRY ثبت کنید.
"""
from __future__ import annotations

from .base import PriceProvider, ProviderError, ProviderQuote
from .generic_json import GenericJsonProvider

REGISTRY: dict[str, type[PriceProvider]] = {GenericJsonProvider.name: GenericJsonProvider}


def get_provider(name: str) -> PriceProvider:
    cls = REGISTRY.get(name)
    if cls is None:
        raise ProviderError(f"ارائه‌دهنده قیمت «{name}» ناشناخته است.")
    return cls()


def available_providers() -> list[dict]:
    return [{"name": c.name, "label": c.label, "params": c.param_help} for c in REGISTRY.values()]
