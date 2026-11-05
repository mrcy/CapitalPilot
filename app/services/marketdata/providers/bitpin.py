"""بیت‌پین: لیست بازارها، قیمت لحظه‌ای، آخرین قیمت معامله، تغییر ۲۴ساعته و تاریخچه (در صورت پشتیبانی).

نشانی‌ها (API عمومی بیت‌پین، مستندات: https://docs.bitpin.ir/ و کلاینت‌های متن‌باز):
- بازارها و قیمت‌ها: GET {base}/api/v1/mkt/tickers/   (آرایه‌ای از {symbol, price, high, low, daily_change_price, ...})
- تاریخچه (TradingView UDF): GET {base}/v1/mkt/tv/get_bars/?symbol=BTC_IRT&res=1D&from=&to=

توجه: «سبدهای آمادهٔ سرمایه‌گذاری» بیت‌پین (مانند «سرمایه پایدار») بازار تکی نیستند و در این API عمومی
ارزش/قیمتی ندارند. برای آن‌ها از منبع دستی یا Custom API استفاده کنید؛ شناسهٔ سبد در این Provider پذیرفته نمی‌شود.
"""
from __future__ import annotations

import re
import threading
import time
from datetime import date, datetime, time as dtime
from decimal import Decimal
from zoneinfo import ZoneInfo

from ....config import get_settings
from ...clock import now_local
from ..base import Health, HistoryPoint, PriceProvider, ProviderError, Quote, SymbolInfo, to_decimal

SYMBOL_RE = re.compile(r"^[A-Z0-9]{1,15}_(IRT|USDT)$")
_cache: dict[str, tuple[float, list]] = {}
_cache_lock = threading.Lock()
TICKER_TTL = 8.0  # ثانیه؛ یک درخواست tickers برای همهٔ دارایی‌ها استفاده می‌شود (جلوگیری از درخواست تکراری)


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


class BitpinProvider(PriceProvider):
    kind = "bitpin"
    label = "بیت‌پین (بازارهای تکی)"
    default_unit = "IRT"
    supports_history = True
    supports_search = True

    @property
    def base(self) -> str:
        return (self.cfg.base_url or get_settings().bitpin_base_url).rstrip("/")

    def _tickers(self) -> list[dict]:
        key = self.base
        with _cache_lock:
            hit = _cache.get(key)
            if hit and time.monotonic() - hit[0] < TICKER_TTL:
                return hit[1]
        data = self.http.get_json(f"{self.base}/api/v1/mkt/tickers/")
        if isinstance(data, dict):
            data = data.get("results") or data.get("data") or []
        if not isinstance(data, list):
            raise ProviderError("ساختار پاسخ tickers بیت‌پین غیرمنتظره است.", "parse")
        self.last_fetch_at = now_local()
        with _cache_lock:
            _cache[key] = (time.monotonic(), data)
        return data

    @staticmethod
    def check_symbol(external_id: str) -> str:
        s = (external_id or "").strip().upper()
        if not SYMBOL_RE.match(s):
            raise ProviderError("شناسهٔ بیت‌پین باید نماد یک بازار تکی مثل BTC_IRT یا ETH_USDT باشد. "
                                "سبدهای آمادهٔ بیت‌پین قیمت عمومی ندارند؛ از منبع دستی یا Custom API استفاده کنید.", "config")
        return s

    def get_quote(self, external_id: str, price_field: str = "") -> Quote:
        sym = self.check_symbol(external_id)
        row = next((t for t in self._tickers() if isinstance(t, dict) and t.get("symbol") == sym), None)
        if row is None:
            raise ProviderError(f"بازار {sym} در فهرست بیت‌پین پیدا نشد.", "no_data")
        price = to_decimal(row.get("price"))
        unit = sym.split("_", 1)[1]
        extra = {k: row[k] for k in ("high", "low") if row.get(k) is not None}
        if row.get("daily_change_price") is not None:
            extra["change_24h_pct"] = str(row["daily_change_price"])
        # tickers زمان معامله ندارد؛ این مقدار قیمت لحظهٔ دریافت است.
        return Quote(price, unit, None, "last", extra)

    def search_symbols(self, query: str) -> list[SymbolInfo]:
        q = (query or "").strip().upper()
        out = []
        for t in self._tickers():
            sym = t.get("symbol", "") if isinstance(t, dict) else ""
            if SYMBOL_RE.match(sym) and (not q or q in sym):
                out.append(SymbolInfo(external_id=sym, symbol=sym, name=sym.replace("_", "/"), market="Bitpin", active=True,
                                      extra={"price": str(t.get("price")), "change_24h_pct": t.get("daily_change_price")}))
        return out[:100]

    def symbol_info(self, external_id: str) -> SymbolInfo:
        sym = self.check_symbol(external_id)
        q = self.get_quote(sym)
        return SymbolInfo(sym, sym, sym.replace("_", "/"), "Bitpin", True, {"price": str(q.price), **q.extra})

    def get_history(self, external_id: str, start: date, end: date) -> list[HistoryPoint]:
        sym = self.check_symbol(external_id)
        tz = ZoneInfo(get_settings().app_timezone)
        frm = int(datetime.combine(start, dtime.min, tz).timestamp())
        to = int(datetime.combine(end, dtime.max, tz).timestamp())
        rows = self.http.get_json(f"{self.base}/v1/mkt/tv/get_bars/", params={"symbol": sym, "res": "1D", "from": frm, "to": to})
        if not isinstance(rows, list):
            raise ProviderError("ساختار پاسخ تاریخچهٔ بیت‌پین غیرمنتظره است.", "parse")
        out = []
        for r in rows:
            try:
                ts = int(r["ts"])
                ts = ts // 1000 if ts > 10**11 else ts
                out.append(HistoryPoint(datetime.fromtimestamp(ts, tz).replace(tzinfo=None), to_decimal(r["close"]), "close"))
            except (KeyError, TypeError, ValueError, ProviderError):
                continue
        return sorted(out, key=lambda p: p.time)

    def health(self) -> Health:
        t0 = time.monotonic()
        with _cache_lock:
            _cache.pop(self.base, None)
        n = len(self._tickers())
        return Health(True, f"اتصال برقرار است؛ {n} بازار دریافت شد.", int((time.monotonic() - t0) * 1000), {"markets": n})
