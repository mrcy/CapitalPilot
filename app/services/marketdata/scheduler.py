"""زمان‌بند مستقل دریافت قیمت (thread پس‌زمینه) با فاصلهٔ هر دارایی، ساعات بازار و ثبت لاگ."""
from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ... import models as m
from ...config import get_settings
from ..clock import now_local
from .base import ProviderError
from .calendar import is_market_open
from .engine import MarketDataEngine, get_engine

log = logging.getLogger("capitalpilot.scheduler")


class PriceScheduler:
    def __init__(self, session_factory: sessionmaker, engine: MarketDataEngine | None = None):
        self.session_factory = session_factory
        self.engine = engine or get_engine()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._run_lock = threading.Lock()
        self._tse_day: tuple[date, date | None] | None = None
        self.state: dict = {"running": False, "last_run_at": None, "last_result": None, "last_error": None}

    # ---------------------------------------------------------------- منطق
    def _last_trading_day(self, db: Session, now: datetime) -> date | None:
        """آخرین روز معاملاتی از TSETMC (در صورت فعال بودن)؛ روزی یک‌بار. best-effort."""
        if self._tse_day and self._tse_day[0] == now.date():
            return self._tse_day[1]
        pv = db.scalar(select(m.PriceProvider).where(m.PriceProvider.kind == "tsetmc", m.PriceProvider.is_enabled.is_(True)))
        day = None
        if pv is not None:
            try:
                prov = self.engine.build(pv)
                day = prov.last_trading_day()  # type: ignore[attr-defined]
            except (ProviderError, AttributeError) as e:
                log.info("trading-day detection unavailable: %s", e)
        self._tse_day = (now.date(), day)
        return day

    @staticmethod
    def _interval_minutes(asset: m.Asset, srcs: list[m.AssetPriceSource], default: int) -> int:
        if asset.fetch_interval_minutes:
            return asset.fetch_interval_minutes
        first = srcs[0]
        return first.interval_minutes or first.provider.refresh_interval_minutes or default

    def due_assets(self, db: Session, now: datetime) -> tuple[list[m.Asset], int]:
        row = db.get(m.AppSettings, 1)
        default = row.scheduler_default_interval_minutes if row else 30
        hours_only = row.scheduler_market_hours_only if row else True
        due, skipped_closed = [], 0
        for a in self.engine.assets_with_sources(db):
            srcs = sorted((s for s in db.scalars(select(m.AssetPriceSource).where(m.AssetPriceSource.asset_id == a.id))
                           if s.is_enabled and s.provider.is_enabled and not s.provider.is_archived and s.provider.kind != "manual"),
                          key=lambda s: s.priority)
            if not srcs:
                continue
            last = max((s.last_attempt_at for s in srcs if s.last_attempt_at), default=None)
            if last is not None and now - last < timedelta(minutes=self._interval_minutes(a, srcs, default)):
                continue
            if hours_only:
                market = srcs[0].provider.market
                ltd = self._last_trading_day(db, now) if market == "tse" else None
                if not is_market_open(market, now, ltd):
                    skipped_closed += 1
                    continue
            due.append(a)
        return due, skipped_closed

    def run_once(self, now: datetime | None = None) -> dict:
        """یک دور اجرا؛ هم‌زمانی دوگانه جلوگیری می‌شود (درخواست تکراری ندارد)."""
        if not self._run_lock.acquire(blocking=False):
            return {"skipped": "already_running"}
        try:
            now = now or now_local()
            with self.session_factory() as db:
                row = db.get(m.AppSettings, 1)
                if row is not None and not row.scheduler_enabled:
                    return {"skipped": "disabled"}
                due, closed = self.due_assets(db, now)
                results = [self.engine.refresh_asset(db, a, now=now) for a in due]
            summary = {"at": now, "due": len(due), "ok": sum(1 for r in results if r["ok"]),
                       "failed": sum(1 for r in results if not r["ok"]), "skipped_market_closed": closed}
            self.state.update(last_run_at=now, last_result=summary, last_error=None)
            return summary
        except Exception as e:
            log.exception("scheduler run failed")
            self.state.update(last_run_at=now_local(), last_error=f"{type(e).__name__}: {e}")
            return {"error": str(e)}
        finally:
            self._run_lock.release()

    # ---------------------------------------------------------------- چرخهٔ عمر
    def _loop(self) -> None:
        tick = max(5, get_settings().scheduler_tick_seconds)
        while not self._stop.wait(tick):
            self.run_once()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="price-scheduler", daemon=True)
        self._thread.start()
        self.state["running"] = True
        log.info("price scheduler started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self.state["running"] = False


_scheduler: PriceScheduler | None = None


def get_scheduler() -> PriceScheduler:
    global _scheduler
    if _scheduler is None:
        from ...database import SessionLocal
        _scheduler = PriceScheduler(SessionLocal)
    return _scheduler
