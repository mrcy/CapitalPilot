from __future__ import annotations

from ..base import Health, PriceProvider, ProviderError, Quote


class ManualPriceProvider(PriceProvider):
    """قیمت دستی: دریافت خودکار ندارد؛ Engine آخرین قیمت دستی تأییدشده را به‌عنوان آخرین گزینه بررسی می‌کند."""

    kind = "manual"
    label = "قیمت دستی"
    default_unit = "IRT"

    def get_quote(self, external_id: str, price_field: str = "") -> Quote:
        raise ProviderError("قیمت دستی دریافت خودکار ندارد؛ آن را در صفحهٔ قیمت‌ها ثبت کنید.", "manual")

    def health(self) -> Health:
        return Health(True, "قیمت دستی همیشه در دسترس است (ثبت توسط کاربر).")
