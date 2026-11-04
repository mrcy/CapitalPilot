"""Market Data Engine: زنجیرهٔ منابع (اصلی ← جایگزین ← دستی)، اعتبارسنجی، ثبت تاریخچه و جلوگیری از تکرار.

اصول:
- هر خطا در ``price_fetch_logs`` ثبت می‌شود و منبع بعدی امتحان می‌شود.
- قیمت قدیمی، آیندهٔ دور، یا با واحد ناسازگار «نامعتبر» ثبت می‌شود (is_valid=False) و هرگز وارد ارزش‌گذاری نمی‌شود.
- هیچ قیمت قدیمی/نامعتبری جایگزین قیمت تازه نمی‌شود؛ اگر همهٔ منابع شکست بخورند نتیجه «در دسترس نیست یا قدیمی است» است.
- محدودیت نرخ درخواست، retry با backoff نمایی و کش کوتاه‌مدت (جلوگیری از درخواست تکراری) برای هر Provider.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ... import models as m
from ..clock import now_local
from . import service
from .base import PriceProvider, ProviderError, Quote
from .providers import build_provider
import json

log = logging.getLogger("capitalpilot.marketdata")
CACHE_TTL_SECONDS = 15.0
from .quality import FUTURE_TOLERANCE, Assessment, assess_quote, convert_unit, conversion_trace, norm_unit  # noqa: E402,F401


class MarketDataEngine:
    def __init__(self, sleep=time.sleep, monotonic=time.monotonic, cache_ttl: float = CACHE_TTL_SECONDS):
        self._sleep, self._mono, self.cache_ttl = sleep, monotonic, cache_ttl
        self._cache: dict[tuple, tuple[float, Quote]] = {}
        self._locks: dict[tuple, threading.Lock] = {}
        self._meta_lock = threading.Lock()
        self._rate_lock = threading.Lock()
        self._last_req: dict[int, float] = {}

    # ------------------------------------------------------------ پایین‌سطح
    def clear_cache(self) -> None:
        with self._meta_lock:
            self._cache.clear()

    def _lock_for(self, key: tuple) -> threading.Lock:
        with self._meta_lock:
            return self._locks.setdefault(key, threading.Lock())

    def _throttle(self, pv: m.PriceProvider) -> None:
        gap = float(pv.min_interval_seconds or 0)
        if gap <= 0:
            return
        with self._rate_lock:
            last = self._last_req.get(pv.id)
            if last is not None:
                wait = gap - (self._mono() - last)
                if wait > 5:
                    raise ProviderError("محدودیت نرخ درخواست منبع فعال است؛ کمی بعد دوباره تلاش کنید.", "rate_limited", True)
                if wait > 0:
                    self._sleep(wait)
            self._last_req[pv.id] = self._mono()

    def build(self, pv: m.PriceProvider) -> PriceProvider:
        return build_provider(service.to_config(pv))

    def fetch_quote(self, pv: m.PriceProvider, external_id: str, field: str = "", *, use_cache: bool = True,
                    provider: PriceProvider | None = None) -> tuple[Quote, bool, int]:
        """(Quote، از‌کش، تأخیر میلی‌ثانیه). خطا: ProviderError."""
        key = (pv.id, external_id, field)
        with self._lock_for(key):
            hit = self._cache.get(key)
            if use_cache and self.cache_ttl > 0 and hit and self._mono() - hit[0] < self.cache_ttl:
                return hit[1], True, 0
            prov = provider or self.build(pv)
            attempts = max(0, int(pv.retry_count)) + 1
            for i in range(attempts):
                self._throttle(pv)
                t0 = self._mono()
                try:
                    q = prov.get_quote(external_id, field)
                except ProviderError as e:
                    prov.last_error = e.message
                    if not e.retriable or i == attempts - 1:
                        raise
                    delay = float(pv.retry_delay_seconds or 0) * (2 ** i)
                    log.info("provider %s retry %d in %.1fs: %s", pv.name, i + 1, delay, e.message)
                    self._sleep(delay)
                    continue
                ms = int((self._mono() - t0) * 1000)
                with self._meta_lock:
                    self._cache[key] = (self._mono(), q)
                return q, False, ms
        raise ProviderError("دریافت قیمت ناموفق بود.", "error")  # pragma: no cover

    # ------------------------------------------------------------ ثبت وضعیت
    def _log(self, db: Session, pv: m.PriceProvider | None, asset: m.Asset | None, ok: bool, status: str, message: str,
             latency: int | None = None, price: Decimal | None = None, now: datetime | None = None, code: str = "") -> None:
        db.add(m.PriceFetchLog(ts=now or now_local(), provider_id=pv.id if pv else None, asset_id=asset.id if asset else None,
                               ok=ok, status=status, message=message[:1000], latency_ms=latency, price=price, code=code[:32]))

    def _touch(self, pv: m.PriceProvider, src: m.AssetPriceSource | None, ok: bool, err: str, latency: int | None, now: datetime) -> None:
        pv.last_attempt_at = now
        pv.last_latency_ms = latency
        if ok:
            pv.last_success_at, pv.last_status, pv.last_error, pv.consecutive_failures = now, "ok", "", 0
        else:
            pv.last_status, pv.last_error = "error", err[:500]
            pv.consecutive_failures = (pv.consecutive_failures or 0) + 1
        if src is not None:
            src.last_attempt_at = now
            src.last_status = "ok" if ok else "error"
            src.last_error = "" if ok else err[:500]
            if ok:
                src.last_success_at = now

    # ------------------------------------------------------------ ذخیرهٔ قیمت
    def _store(self, db: Session, asset: m.Asset, pv: m.PriceProvider, q: Quote, price: Decimal, valid: bool, note: str,
               now: datetime, assessed: Assessment | None = None) -> tuple[str, m.Price | None]:
        """ذخیرهٔ قیمت آنلاین. همیشه با منبع (نام و شناسه)، زمان دریافت، قیمت خام و ردپای تبدیل؛ بدون این‌ها ذخیره نمی‌شود."""
        if not pv.name:
            raise ValueError("قیمت آنلاین بدون نام منبع ذخیره نمی‌شود.")
        kind = q.kind or ""
        if q.source_time is not None:
            exists = db.scalar(select(m.Price).where(m.Price.asset_id == asset.id, m.Price.provider_id == pv.id,
                                                     m.Price.source_time == q.source_time, m.Price.price_kind == kind))
            if exists is not None:
                if valid and not exists.is_valid:
                    # منبع همان زمان را اصلاح کرده: رکورد نامعتبر قبلی با مقدار معتبر جدید جایگزین می‌شود (ردپا حفظ می‌شود)
                    exists.price, exists.is_valid, exists.validity_note, exists.fetched_at = price, True, note, now
                    exists.is_approved = bool(pv.auto_approve)
                    exists.note = "دریافت خودکار"
                    exists.raw_price = assessed.raw_price if assessed else q.price
                    exists.raw_unit = assessed.raw_unit if assessed else norm_unit(q.unit)
                    exists.conversion_note = assessed.conversion_note if assessed else ""
                    exists.quality_flags = assessed.flags_json if assessed else "[]"
                    db.flush()
                    return "stored", exists
                return "duplicate", None
        else:
            prev = db.scalar(select(m.Price).where(m.Price.asset_id == asset.id, m.Price.provider_id == pv.id,
                                                   m.Price.price_kind == kind).order_by(m.Price.fetched_at.desc()).limit(1))
            if prev is not None and prev.fetched_at and prev.price == price and (now - prev.fetched_at) < timedelta(seconds=60):
                return "duplicate", None
        row = m.Price(asset_id=asset.id, price=price, currency=asset.price_currency, recorded_at=q.source_time or now,
                      source=pv.name, is_approved=bool(pv.auto_approve and valid), note="دریافت خودکار" + ("" if valid else " — نامعتبر"),
                      provider_id=pv.id, fetched_at=now, source_time=q.source_time, price_kind=kind, is_valid=valid,
                      validity_note=note, origin="online",
                      raw_price=assessed.raw_price if assessed else q.price, raw_unit=assessed.raw_unit if assessed else norm_unit(q.unit),
                      conversion_note=assessed.conversion_note if assessed else "",
                      quality_flags=assessed.flags_json if assessed else "[]")
        try:
            with db.begin_nested():
                db.add(row)
                db.flush()
        except IntegrityError:
            return "duplicate", None
        return "stored", row

    # ------------------------------------------------------------ منبع به منبع
    def _validate(self, q: Quote, asset: m.Asset, max_age_days: int, now: datetime, market: str = "none",
                  prev_price: Decimal | None = None) -> Assessment:
        """اعتبارسنجی با لایهٔ کیفیت؛ ناسازگاری واحد → ProviderError(currency_mismatch)."""
        return assess_quote(raw_price=q.price, unit=q.unit, source_time=q.source_time, now=now, asset_currency=asset.price_currency,
                            max_age_days=max_age_days, market=market, prev_price=prev_price)

    @staticmethod
    def _prev_valid_price(db: Session, asset: m.Asset, pv: m.PriceProvider, now: datetime) -> Decimal | None:
        """آخرین قیمت معتبر همان منبع در ۷۲ ساعت اخیر (برای تشخیص تغییر شدید)."""
        p = db.scalar(select(m.Price).where(m.Price.asset_id == asset.id, m.Price.provider_id == pv.id, m.Price.is_valid.is_(True),
                                            m.Price.recorded_at >= now - timedelta(hours=72)).order_by(m.Price.recorded_at.desc(), m.Price.id.desc()).limit(1))
        return p.price if p else None

    def _latest_manual(self, db: Session, asset: m.Asset, max_age_days: int, now: datetime) -> m.Price | None:
        p = db.scalar(select(m.Price).where(m.Price.asset_id == asset.id, m.Price.origin == "manual", m.Price.is_approved.is_(True),
                                            m.Price.is_valid.is_(True)).order_by(m.Price.recorded_at.desc(), m.Price.id.desc()).limit(1))
        if p is None or (now.date() - p.recorded_at.date()).days > max_age_days:
            return None
        return p

    def refresh_asset(self, db: Session, asset: m.Asset, force: bool = False, now: datetime | None = None,
                      all_sources: bool = False) -> dict:
        """all_sources=True: پس از اولین موفقیت هم از بقیهٔ منابع می‌گیرد (فقط برای مقایسه؛ نتیجهٔ اصلی همان اولین منبع موفق است)."""
        now = now or now_local()
        max_age = db.get(m.AppSettings, 1).max_price_age_days if db.get(m.AppSettings, 1) else 3
        srcs = [s for s in db.scalars(select(m.AssetPriceSource).where(m.AssetPriceSource.asset_id == asset.id)) if s.is_enabled]
        srcs.sort(key=lambda s: s.priority)
        res = {"asset_id": asset.id, "asset": asset.name, "ok": False, "status": "no_source", "price": None,
               "currency": asset.price_currency, "provider": None, "provider_id": None, "source_time": None,
               "message": "برای این دارایی منبع قیمت تعریف نشده است؛ قیمت را دستی ثبت کنید یا منبعی اضافه کنید.",
               "attempts": [], "stale": False}
        if not srcs:
            return res
        res["message"] = ""
        for src in srcs:
            pv = src.provider
            att = {"provider": pv.name, "provider_id": pv.id, "ok": False, "status": "", "message": ""}
            res["attempts"].append(att)
            if pv.is_archived or not pv.is_enabled:
                att.update(status="disabled", message="منبع غیرفعال است.")
                continue
            if pv.kind == "manual":
                if res["ok"]:
                    att.update(status="skipped", message="قبلاً از منبع بالاتر قیمت معتبر گرفته شد.")
                    continue
                p = self._latest_manual(db, asset, max_age, now)
                if p is not None:
                    att.update(ok=True, status="manual", message="آخرین قیمت دستی تأییدشده استفاده می‌شود.")
                    res.update(ok=True, status="manual", price=p.price, provider=pv.name, provider_id=pv.id,
                               source_time=p.recorded_at, message=f"از آخرین قیمت دستی ({p.recorded_at:%Y-%m-%d %H:%M}) استفاده شد.")
                    db.commit()
                    if not all_sources:
                        return res
                    continue
                att.update(status="no_manual", message="قیمت دستی تازه‌ای ثبت نشده است.")
                continue
            t0 = self._mono()
            try:
                q, cached, ms = self.fetch_quote(pv, src.external_id, src.price_field, use_cache=True)
                asm = self._validate(q, asset, max_age, now, pv.market, self._prev_valid_price(db, asset, pv, now))
                price, valid, note = asm.price, asm.valid, asm.note
            except ProviderError as e:
                ms = int((self._mono() - t0) * 1000)
                att.update(status=e.code, message=e.message)
                self._log(db, pv, asset, False, "error" if e.code != "currency_mismatch" else "invalid",
                          f"[{e.code}] {e.message}", ms, None, now, code=e.code)
                self._touch(pv, src, False, e.message, ms, now)
                log.warning("price fetch failed asset=%s provider=%s: %s", asset.id, pv.name, e.message)
                db.commit()
                continue
            status, row = self._store(db, asset, pv, q, price, valid, note, now, asm)
            if not valid:
                code = "stale" if "stale" in asm.flags else ("future_time" if "future_time" in asm.flags else "non_positive" if "non_positive" in asm.flags else "invalid")
                att.update(status="stale" if "stale" in asm.flags else "invalid", message=note)
                self._log(db, pv, asset, False, att["status"], note, ms, price, now, code=code)
                self._touch(pv, src, False, note, ms, now)
                db.commit()
                continue
            msg = "قیمت دریافت و ثبت شد." if status == "stored" else "قیمت جدیدی نسبت به آخرین ثبت وجود ندارد (تکراری ثبت نشد)."
            if status == "stored" and not pv.auto_approve:
                msg += " در انتظار تأیید است و تا تأیید در ارزش‌گذاری استفاده نمی‌شود."
            att.update(ok=True, status="ok" if status == "stored" else "duplicate", message=msg)
            if row is not None:
                # ثبت کامل مسیر: کدام منابع قبل از این منبع شکست خوردند و نهایتاً قیمت از کجا آمد
                row.via = json.dumps([{"provider": x["provider"], "status": x["status"], "message": x["message"][:200]} for x in res["attempts"]], ensure_ascii=False)
                if asm.note:
                    msg += " " + asm.note
            self._log(db, pv, asset, True, "ok" if status == "stored" else "duplicate", msg + (" (از کش)" if cached else ""), ms, price, now)
            self._touch(pv, src, True, "", ms, now)
            if not res["ok"]:
                res.update(ok=True, status="ok" if status == "stored" else "duplicate", price=price, provider=pv.name, provider_id=pv.id,
                           source_time=q.source_time or now, message=msg, approved=bool(row.is_approved) if row else None,
                           cached=cached, extra=q.extra)
            db.commit()
            if not all_sources:
                return res
        if res["ok"]:
            return res
        # همهٔ منابع ناموفق
        latest = db.scalar(select(m.Price).where(m.Price.asset_id == asset.id, m.Price.is_approved.is_(True), m.Price.is_valid.is_(True))
                           .order_by(m.Price.recorded_at.desc()).limit(1))
        res["stale"] = latest is not None and (now.date() - latest.recorded_at.date()).days > max_age
        res["status"] = "unavailable"
        res["message"] = "قیمت در دسترس نیست یا قدیمی است؛ هیچ قیمتی به‌عنوان قیمت روز استفاده نمی‌شود. قیمت را دستی ثبت کنید."
        db.commit()
        return res

    def refresh_all(self, db: Session, asset_ids: list[int] | None = None, force: bool = False, now: datetime | None = None) -> list[dict]:
        out = []
        for a in self.assets_with_sources(db, asset_ids):
            try:
                out.append(self.refresh_asset(db, a, force=force, now=now))
            except Exception as e:  # یک دارایی نباید بقیه را متوقف کند
                db.rollback()
                log.exception("refresh failed for asset %s", a.id)
                out.append({"asset_id": a.id, "asset": a.name, "ok": False, "status": "error", "message": f"خطای داخلی: {type(e).__name__}",
                            "attempts": []})
        return out

    @staticmethod
    def assets_with_sources(db: Session, asset_ids: list[int] | None = None) -> list[m.Asset]:
        ids = select(m.AssetPriceSource.asset_id).where(m.AssetPriceSource.is_enabled.is_(True))
        q = select(m.Asset).where(m.Asset.id.in_(ids)).order_by(m.Asset.sort_order, m.Asset.id)
        if asset_ids:
            q = q.where(m.Asset.id.in_(asset_ids))
        has_tx = select(m.Transaction.asset_id).where(m.Transaction.asset_id.is_not(None))
        # دارایی بایگانی‌شدهٔ بدون سابقه نیازی به قیمت ندارد؛ اگر تراکنش دارد برای سود/زیان لازم است.
        return [a for a in db.scalars(q) if not a.is_archived or db.scalar(select(func.count()).select_from(m.Transaction).where(m.Transaction.asset_id == a.id))]

    # ------------------------------------------------------------ تاریخچه
    def import_history(self, db: Session, asset: m.Asset, src: m.AssetPriceSource, days: int = 90, today: date | None = None) -> dict:
        """دریافت تاریخچهٔ روزانه از منبع (در صورت پشتیبانی) و ثبت بدون تکرار؛ فقط قیمت‌های معتبر و غیرآینده."""
        pv = src.provider
        now = now_local()
        end = today or now.date()
        start = end - timedelta(days=days)
        prov = self.build(pv)
        if pv.kind == "manual":
            raise ProviderError("قیمت دستی تاریخچهٔ خودکار ندارد.", "unsupported")
        self._throttle(pv)
        points = prov.get_history(src.external_id, start, end)
        stored = dup = bad = 0
        for pt in points:
            q = Quote(pt.price, prov.price_unit, pt.time, pt.kind or "close")
            try:
                price, valid, note = Decimal(0), False, ""
                price = convert_unit(q.price, q.unit, asset.price_currency)
                valid = price > 0 and pt.time <= now + FUTURE_TOLERANCE
                note = "" if valid else "قیمت تاریخی نامعتبر است."
            except ProviderError as e:
                valid, note = False, e.message
            asm = Assessment(valid, price, note, [] if valid else ["non_positive"], conversion_trace(q.price, q.unit, asset.price_currency, price) if price > 0 else "",
                             q.price, norm_unit(q.unit))
            st, _ = self._store(db, asset, pv, q, price, valid, note, now, asm)
            if not valid:
                bad += 1
            elif st == "stored":
                stored += 1
            else:
                dup += 1
        self._log(db, pv, asset, True, "ok", f"تاریخچه: {stored} ثبت، {dup} تکراری، {bad} نامعتبر", None, None, now)
        db.commit()
        return {"fetched": len(points), "stored": stored, "duplicates": dup, "invalid": bad}

    # ------------------------------------------------------------ تست اتصال
    def test_provider(self, db: Session, pv: m.PriceProvider, external_id: str = "", price_field: str = "") -> dict:
        now = now_local()
        out = {"ok": False, "provider": pv.name, "kind": pv.kind, "health": None, "quote": None, "error": None, "tested_at": now}
        prov = self.build(pv)
        t0 = self._mono()
        try:
            h = prov.health()
            out["health"] = {"ok": h.ok, "message": h.message, "latency_ms": h.latency_ms, "details": h.details}
            if external_id and pv.kind != "manual":
                q, _, ms = self.fetch_quote(pv, external_id, price_field, use_cache=False, provider=prov)
                shown = None
                err = None
                try:
                    shown = str(convert_unit(q.price, q.unit, pv.input_currency or q.unit))
                except ProviderError as e:
                    err = e.message
                out["quote"] = {"price": str(q.price), "unit": q.unit, "converted_price": shown, "source_time": q.source_time,
                                "kind": q.kind, "extra": q.extra, "latency_ms": ms, "note": err}
            out["ok"] = True
            ms = int((self._mono() - t0) * 1000)
            self._log(db, pv, None, True, "ok", "تست اتصال موفق: " + h.message, ms, None, now)
            self._touch(pv, None, True, "", ms, now)
        except ProviderError as e:
            ms = int((self._mono() - t0) * 1000)
            out["error"] = {"code": e.code, "message": e.message}
            self._log(db, pv, None, False, "error", f"[{e.code}] تست اتصال: {e.message}", ms, None, now)
            self._touch(pv, None, False, e.message, ms, now)
        db.commit()
        return out


_engine: MarketDataEngine | None = None


def get_engine() -> MarketDataEngine:
    global _engine
    if _engine is None:
        _engine = MarketDataEngine()
    return _engine
