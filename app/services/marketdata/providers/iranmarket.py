"""IranMarketDataProvider: قیمت نمادهای فایل عمومی Iran Market Data (``latest-toman.json``).

* فایل فقط در Backend و فقط یک‌بار برای همهٔ نمادها دریافت می‌شود؛ قیمت هر دارایی از دادهٔ ذخیره‌شدهٔ دیتابیس خوانده می‌شود.
* مرجع ساختار و واحدها: https://github.com/iran-market/iran-market.github.io (README و SYMBOLS.md).
* قیمت‌ها با ارز و واحد خودِ فایل برگردانده می‌شوند (IRT برای دارایی‌های ریالی، USD برای جهانی)؛ این Provider هیچ تبدیل ضمنی ندارد.
* این منبع «مکمل» است و جایگزین اجباری TSETMC یا بیت‌پین نیست؛ فقط برای دارایی‌هایی که نمادشان صریحاً به آن‌ها وصل شده استفاده می‌شود.
"""
from __future__ import annotations

import time
from datetime import date

from sqlalchemy.orm import Session

from ....config import get_settings
from ... import clock
from .. import iranmarket as im
from ..base import Health, HistoryPoint, PriceProvider, ProviderError, Quote, SymbolInfo


def _session() -> Session:
    from ....database import SessionLocal
    return SessionLocal()


class IranMarketDataProvider(PriceProvider):
    kind = "iranmarket"
    label = "Iran Market Data (بازار جامع ایران)"
    default_unit = "IRT"
    supports_history = False  # تاریخچهٔ API فقط برای نمودار نمایش داده می‌شود و به جدول قیمت‌ها وارد نمی‌شود
    supports_search = True

    @property
    def url(self) -> str:
        return (self.cfg.base_url or get_settings().iranmarket_url).strip()

    def _pv(self, db: Session):
        from ....models import PriceProvider as PV
        return db.get(PV, self.cfg.id) if self.cfg.id else im.get_provider(db)

    def get_quote(self, external_id: str, price_field: str = "") -> Quote:
        sym = (external_id or "").strip()
        if not sym:
            raise ProviderError("نماد Iran Market Data انتخاب نشده است.", "config")
        with _session() as db:
            q = im.quote_for(db, self._pv(db), sym, im.now_local())
        self.last_fetch_at = clock.now_local()
        return q

    def search_symbols(self, query: str) -> list[SymbolInfo]:
        with _session() as db:
            res = im.list_symbols(db, q=query, page_size=100, sort="name")
        return [SymbolInfo(external_id=i["symbol"], symbol=i["symbol"], name=i["name_fa"] or i["name_en"] or i["symbol"], market=i["category"],
                           active=i["status"] in ("valid", "warning"),
                           extra={"price": str(i["price"]) if i["price"] is not None else None, "currency": i["currency"], "unit": i["unit"],
                                  "status": i["status"], "name_en": i["name_en"]}) for i in res["items"]]

    def symbol_info(self, external_id: str) -> SymbolInfo:
        with _session() as db:
            d = im.get_symbol(db, external_id.strip())
        return SymbolInfo(d["symbol"], d["symbol"], d["name_fa"] or d["name_en"], d["category"], d["status"] in ("valid", "warning"),
                          {"price": str(d["price"]) if d["price"] is not None else None, "currency": d["currency"], "unit": d["unit"], "status": d["status"]})

    def get_history(self, external_id: str, start: date, end: date) -> list[HistoryPoint]:
        raise ProviderError("تاریخچهٔ Iran Market Data فقط برای نمودار نمایش داده می‌شود و در قیمت‌ها ذخیره نمی‌شود.", "unsupported")

    def health(self) -> Health:
        """تست اتصال: فایل را واقعاً از شبکه می‌گیرد و می‌خواند و ذخیره می‌کند (بدون ثبت لاگ مضاعف)."""
        t0 = time.monotonic()
        with _session() as db:
            r = im.fetch_snapshot(db, self._pv(db), record=False, raise_errors=True)
            if r["status"] == "skipped":
                st = im.snapshot_state(db, self._pv(db))
                if not st["has_data"]:
                    raise ProviderError(r["message"], "busy", True)
                return Health(True, f"{r['message']} آخرین دادهٔ ذخیره‌شده استفاده می‌شود.", int((time.monotonic() - t0) * 1000), {})
        self.last_fetch_at = clock.now_local()
        return Health(True, r["message"], r.get("latency_ms"), {"symbols": r["symbols"], "valid": r["valid"], "stale": r["stale"], "invalid": r["invalid"],
                                                               "no_price": r["no_price"], "generated_at": str(r["generated_at"] or "")})
