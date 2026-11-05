"""TSETMC (بورس تهران): آخرین معامله، قیمت پایانی، NAV صندوق‌ها، تاریخچه و جستجوی نماد.

نشانی‌ها و ساختار پاسخ از کلاینت متن‌باز pytse-client (نسخهٔ 0.19.1) استخراج شده‌اند. TSETMC مستندات رسمی
API عمومی ندارد؛ این نشانی‌ها ممکن است بدون اطلاع تغییر کنند — در این صورت خطای «parse/http» ثبت می‌شود و
سیستم به منبع جایگزین یا قیمت دستی می‌رود. همهٔ قیمت‌ها به ریال هستند و Engine آن‌ها را به تومان تبدیل می‌کند.
"""
from __future__ import annotations

import csv
import io
import time
from datetime import date, datetime, time as dtime
from decimal import Decimal

from ....config import get_settings
from ...clock import now_local
from ..base import Health, HistoryPoint, PriceProvider, ProviderError, Quote, SymbolInfo, normalize_fa, safe_external_id, to_decimal

FIELD_INDEX = {"last": 2, "close": 3}  # اندیس در بخش اول instinfofast
FIELD_LABEL = {"last": "آخرین معامله", "close": "قیمت پایانی", "nav": "NAV"}


class TSETMCProvider(PriceProvider):
    kind = "tsetmc"
    label = "TSETMC (بورس تهران)"
    default_unit = "IRR"
    supports_history = True
    supports_search = True

    @property
    def base(self) -> str:
        return (self.cfg.base_url or get_settings().tsetmc_base_url).rstrip("/")

    def _text(self, url: str, params: dict | None = None) -> str:
        resp = self.http.get(url, params=params)
        txt = resp.content.decode("utf-8", errors="replace").strip()
        self.last_fetch_at = now_local()
        return txt

    # ---- قیمت فعلی ----
    def get_quote(self, external_id: str, price_field: str = "") -> Quote:
        ins = safe_external_id(external_id)
        if not ins.isdigit():
            raise ProviderError("شناسهٔ TSETMC (insCode) باید عددی باشد؛ از جستجوی نماد استفاده کنید.", "config")
        field = price_field or "last"
        if field not in ("last", "close", "nav"):
            raise ProviderError("نوع قیمت TSETMC باید last، close یا nav باشد.", "config")
        txt = self._text(f"{self.base}/instinfofast.aspx", {"i": ins, "c": "0", "e": "1"})
        if not txt:
            raise ProviderError("پاسخ خالی از TSETMC (نماد بسته یا شناسه نادرست است).", "no_data")
        sec = txt.split(";")[0].split(",")
        try:
            when = datetime.strptime(sec[12] + sec[13], "%Y%m%d%H%M%S")
        except (IndexError, ValueError):
            when = None
        if field == "nav":
            try:
                raw, nav_date = sec[15].strip(), sec[14].strip()
            except IndexError:
                raise ProviderError("NAV برای این نماد در پاسخ TSETMC موجود نیست.", "no_data")
            if not raw or not raw.lstrip("-").isdigit():
                raise ProviderError("NAV معتبر برای این نماد موجود نیست (صندوق نیست یا مقدار ندارد).", "no_data")
            nav_time = None
            if len(nav_date) == 8 and nav_date.isdigit():
                nav_time = datetime.strptime(nav_date, "%Y%m%d").replace(hour=12)
            if nav_time is None:
                raise ProviderError("تاریخ NAV در پاسخ مشخص نیست؛ اعتبار آن قابل تأیید نیست.", "no_data")
            return Quote(to_decimal(raw, "NAV"), "IRR", nav_time, "nav", {"nav_date": nav_date})
        idx = FIELD_INDEX[field]
        try:
            raw = sec[idx].strip()
        except IndexError:
            raise ProviderError("ساختار پاسخ TSETMC غیرمنتظره است.", "parse")
        if not raw or not raw.isdigit():
            raise ProviderError(f"{FIELD_LABEL[field]} برای این نماد در پاسخ TSETMC موجود/عددی نیست (مقدار: {raw[:10]!r}).", "no_data")
        extra = {}
        for key, i in (("last", 2), ("close", 3), ("yesterday", 5), ("high", 6), ("low", 7), ("volume", 9)):
            try:
                if sec[i].strip().isdigit():
                    extra[key] = sec[i].strip()
            except IndexError:
                pass
        extra["state"] = sec[1].strip() if len(sec) > 1 else ""
        return Quote(to_decimal(raw), "IRR", when, field, extra)

    # ---- جستجو و اطلاعات نماد ----
    def search_symbols(self, query: str) -> list[SymbolInfo]:
        q = normalize_fa(query)
        if len(q) < 2:
            raise ProviderError("حداقل ۲ نویسه برای جستجو وارد کنید.", "config")
        txt = self._text(f"{self.base}/search.aspx", {"skey": q})
        out = []
        for rec in txt.split(";"):
            f = rec.split(",")
            if len(f) < 3 or not f[2].strip().isdigit():
                continue
            out.append(SymbolInfo(external_id=f[2].strip(), symbol=normalize_fa(f[0]), name=normalize_fa(f[1]),
                                  market="TSETMC", active=(f[7].strip() == "1") if len(f) > 7 else None))
        return out[:50]

    def symbol_info(self, external_id: str) -> SymbolInfo:
        ins = safe_external_id(external_id)
        q = self.get_quote(ins, "last")
        return SymbolInfo(external_id=ins, symbol="", name="", market="TSETMC", active=True,
                          extra={"last_trade_time": q.source_time, **q.extra})

    # ---- تاریخچه ----
    def get_history(self, external_id: str, start: date, end: date) -> list[HistoryPoint]:
        ins = safe_external_id(external_id)
        txt = self._text(f"{self.base}/Export-txt.aspx", {"t": "i", "a": "1", "b": "0", "i": ins})
        out = []
        for row in csv.DictReader(io.StringIO(txt)):
            try:
                d = datetime.strptime(row["<DTYYYYMMDD>"], "%Y%m%d")
                close = row["<CLOSE>"]
            except (KeyError, ValueError):
                continue
            if not (start <= d.date() <= end) or not str(close).strip().isdigit():
                continue
            out.append(HistoryPoint(d.replace(hour=12, minute=30), to_decimal(close), "close"))
        if not out and txt and "<DTYYYYMMDD>" not in txt:
            raise ProviderError("ساختار پاسخ تاریخچهٔ TSETMC غیرمنتظره است.", "parse")
        return sorted(out, key=lambda p: p.time)

    # ---- سلامت و تقویم ----
    def last_trading_day(self) -> date:
        s = get_settings()
        base = (s.tsetmc_service_url if not self.cfg.base_url else self.base).rstrip("/")
        txt = self._text(f"{base}/TseClient2.aspx", {"t": "LastPossibleDeven"})
        head = txt.split(";")[0].strip()
        try:
            return datetime.strptime(head, "%Y%m%d").date()
        except ValueError:
            raise ProviderError("پاسخ «آخرین روز معاملاتی» TSETMC قابل خواندن نیست.", "parse")

    def health(self) -> Health:
        t0 = time.monotonic()
        d = self.last_trading_day()
        return Health(True, f"اتصال برقرار است؛ آخرین روز معاملاتی: {d.isoformat()}", int((time.monotonic() - t0) * 1000),
                      {"last_trading_day": d.isoformat()})
