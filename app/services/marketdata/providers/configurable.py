"""آداپتور JSON قابل‌پیکربندی: Custom API، StreamData و Servix.

برای StreamData (سهام/شاخص خارجی) و Servix (طلا، ارز و ...) مستندات عمومی تأییدشده‌ای در دسترس نیست، بنابراین
هیچ نشانی یا ساختار پاسخ فرضی در برنامه ثابت نشده است: آدرس، احراز هویت و مسیر فیلدها را از مستندات
سرویس‌دهندهٔ خودتان در پنل «منابع قیمت» (یا متغیرهای محیطی) وارد کنید.

تنظیمات:
- base_url: آدرس کامل (می‌تواند ``{symbol}`` داشته باشد) یا آدرس پایه به‌همراه ``config.path``.
- request_params: پارامترهای ثابت query (مقادیر می‌توانند ``{symbol}`` داشته باشند).
- field_map: ``price`` (الزامی)، ``time``، ``currency``، ``change`` با JSONPath.
- config: ``path``، ``multiplier``، ``time_format`` (iso | unix | unix_ms | الگوی strptime)،
  ``health_path``، ``history_path`` + ``history_time`` + ``history_price`` (آرایهٔ تاریخچه).
"""
from __future__ import annotations

import time
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from ....config import get_settings
from ...clock import now_local
from ..base import Health, HistoryPoint, PriceProvider, ProviderError, Quote, safe_external_id, to_decimal
from ..jsonpath import extract


def parse_time(v, fmt: str) -> datetime | None:
    if v is None or v == "":
        return None
    tz = ZoneInfo(get_settings().app_timezone)
    try:
        if fmt in ("unix", "unix_ms") or (not fmt and isinstance(v, (int, float))):
            n = float(v)
            if fmt == "unix_ms" or n > 10**11:
                n /= 1000
            return datetime.fromtimestamp(n, tz).replace(tzinfo=None)
        s = str(v).strip()
        if not fmt or fmt == "iso":
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(s, fmt)
        if dt.tzinfo is not None:
            dt = dt.astimezone(tz).replace(tzinfo=None)
        return dt
    except (ValueError, OverflowError, OSError):
        raise ProviderError(f"قالب زمان پاسخ منبع قابل خواندن نیست: {str(v)[:40]!r}", "parse")


class ConfigurableJSONProvider(PriceProvider):
    kind = "custom_api"
    label = "Custom API (JSON)"
    default_unit = "IRT"
    env_base = ""
    env_key = ""

    # ---- آدرس و احراز هویت ----
    def _key(self) -> str:
        if self.cfg.api_key:
            return self.cfg.api_key
        return getattr(get_settings(), self.env_key, "") if self.env_key else ""

    def _base(self) -> str:
        return self.cfg.base_url or (getattr(get_settings(), self.env_base, "") if self.env_base else "")

    def _build(self, symbol: str, path_key: str = "path") -> tuple[str, dict, dict]:
        base = self._base().strip()
        if not base:
            raise ProviderError("آدرس API تنظیم نشده است (در پنل منابع قیمت یا متغیر محیطی).", "config")
        path = str(self.cfg.options.get(path_key, "") or "")
        sym = symbol
        url = base.replace("{symbol}", sym) if "{symbol}" in base else base.rstrip("/") + ("/" + path.lstrip("/").replace("{symbol}", sym) if path else "")
        params = {k: str(v).replace("{symbol}", sym) for k, v in self.cfg.request_params.items()}
        headers: dict[str, str] = {}
        key = self._key()
        t = self.cfg.auth_type
        if t != "none":
            if not key:
                raise ProviderError("نوع احراز هویت انتخاب شده ولی کلید API ذخیره نشده است.", "auth")
            if t == "bearer":
                headers["Authorization"] = f"Bearer {key}"
            elif t == "header":
                if not self.cfg.auth_param_name:
                    raise ProviderError("نام هدر احراز هویت را وارد کنید.", "config")
                headers[self.cfg.auth_param_name] = key
            elif t == "query":
                if not self.cfg.auth_param_name:
                    raise ProviderError("نام پارامتر احراز هویت را وارد کنید.", "config")
                params[self.cfg.auth_param_name] = key
        return url, params, headers

    def _fetch(self, symbol: str, path_key: str = "path"):
        url, params, headers = self._build(symbol, path_key)
        data = self.http.get_json(url, params=params, headers=headers, has_credentials=self.cfg.auth_type != "none")
        self.last_fetch_at = now_local()
        return data

    # ---- قرارداد ----
    def get_quote(self, external_id: str, price_field: str = "") -> Quote:
        sym = external_id.strip() if external_id and external_id.strip() else ""
        if "{symbol}" in (self._base() + str(self.cfg.options.get("path", "")) + "".join(self.cfg.request_params.values())):
            sym = safe_external_id(sym)
        fm = self.cfg.field_map
        if not fm.get("price"):
            raise ProviderError("مسیر JSON قیمت (field_map.price) تنظیم نشده است.", "config")
        data = self._fetch(sym)
        price = to_decimal(extract(data, fm["price"]))
        mult = self.cfg.options.get("multiplier")
        if mult not in (None, "", 1, "1"):
            price *= to_decimal(mult, "ضریب")
        when = None
        if fm.get("time"):
            when = parse_time(extract(data, fm["time"]), str(self.cfg.options.get("time_format", "") or ""))
        unit = self.cfg.input_currency
        if fm.get("currency"):
            unit = str(extract(data, fm["currency"])).strip().upper() or unit
        if not unit:
            raise ProviderError("واحد پول قیمت مشخص نیست؛ «واحد ورودی» را در تنظیمات منبع تعیین کنید.", "config")
        extra = {}
        if fm.get("change"):
            try:
                extra["change"] = str(to_decimal(extract(data, fm["change"]), "تغییر"))
            except ProviderError:
                pass
        return Quote(price, unit.upper(), when, price_field or "last", extra)

    @property
    def supports_history(self) -> bool:  # type: ignore[override]
        return bool(self.cfg.options.get("history_path"))

    def get_history(self, external_id: str, start: date, end: date) -> list[HistoryPoint]:
        o = self.cfg.options
        if not o.get("history_path"):
            raise ProviderError("مسیر تاریخچه (config.history_path) تعریف نشده است.", "unsupported")
        url, params, headers = self._build(external_id.strip(), "history_path")
        params = {k: v.replace("{start}", start.isoformat()).replace("{end}", end.isoformat()) for k, v in params.items()}
        data = self.http.get_json(url, params=params, headers=headers, has_credentials=self.cfg.auth_type != "none")
        rows = extract(data, o.get("history_list", "$")) if o.get("history_list") else data
        if not isinstance(rows, list):
            raise ProviderError("پاسخ تاریخچه آرایه نیست (config.history_list را تنظیم کنید).", "parse")
        out = []
        for r in rows:
            try:
                t = parse_time(extract(r, o.get("history_time", "time")), str(o.get("time_format", "") or ""))
                p = to_decimal(extract(r, o.get("history_price", "close")))
            except ProviderError:
                continue
            if t and start <= t.date() <= end:
                out.append(HistoryPoint(t, p, "close"))
        return sorted(out, key=lambda x: x.time)

    def health(self) -> Health:
        t0 = time.monotonic()
        hp = self.cfg.options.get("health_path")
        sample = str(self.cfg.options.get("sample_symbol", "") or "")
        if hp:
            url, params, headers = self._build(sample, "health_path")
            self.http.get(url, params=params, headers=headers, has_credentials=self.cfg.auth_type != "none")
            msg = "اتصال به نشانی سلامت برقرار است."
        else:
            if not self.cfg.field_map.get("price"):
                raise ProviderError("برای تست اتصال، مسیر JSON قیمت را تنظیم و یک نماد نمونه بدهید.", "config")
            self.get_quote(sample)
            msg = "درخواست نمونه موفق بود و قیمت از مسیر JSON خوانده شد."
        return Health(True, msg, int((time.monotonic() - t0) * 1000))


class CustomAPIProvider(ConfigurableJSONProvider):
    kind = "custom_api"
    label = "Custom API (JSON)"


class StreamDataProvider(ConfigurableJSONProvider):
    kind = "streamdata"
    label = "StreamData (سهام و شاخص خارجی)"
    default_unit = "USD"
    env_base = "streamdata_base_url"
    env_key = "streamdata_api_key"


class ServixProvider(ConfigurableJSONProvider):
    kind = "servix"
    label = "Servix (طلا، ارز و ...)"
    default_unit = "IRT"
    env_base = "servix_base_url"
    env_key = "servix_api_key"
