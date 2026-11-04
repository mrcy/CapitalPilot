"""مرکز هوشمندی قیمت‌ها: سلامت منابع، پایش قیمت دارایی‌ها، هشدارهای هوشمند و گزارش عملکرد.

همهٔ خروجی‌ها از داده‌های واقعی ثبت‌شده (قیمت‌ها، لاگ دریافت، وضعیت منابع) محاسبه می‌شود؛ هیچ مقدار نمایشی یا فرضی وجود ندارد.
هشدارها ذخیره نمی‌شوند و در هر درخواست از وضعیت جاری محاسبه می‌شوند تا هیچ‌گاه با دادهٔ واقعی ناهمخوان نباشند.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ... import models as m
from ...config import get_settings
from ..clock import now_local
from . import quality, service

STATUS_TEXT = {"valid": "معتبر", "stale": "قدیمی", "invalid": "نامعتبر", "manual": "دستی", "missing": "ناموجود",
               "conflict": "اختلاف منابع", "pending": "در انتظار تأیید"}
SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


def _max_age(db: Session) -> int:
    row = db.get(m.AppSettings, 1)
    return row.max_price_age_days if row else 3


def _window(days: int, date_from: date | None, date_to: date | None, now: datetime) -> tuple[datetime, datetime]:
    end = datetime.combine(date_to, time(23, 59, 59)) if date_to else now
    start = datetime.combine(date_from, time(0, 0)) if date_from else end - timedelta(days=max(1, days))
    return start, end


# ---------------------------------------------------------------- منابع
def _logs(db: Session, start: datetime, end: datetime, provider_id: int | None = None, asset_id: int | None = None) -> list:
    q = select(m.PriceFetchLog.ts, m.PriceFetchLog.provider_id, m.PriceFetchLog.ok, m.PriceFetchLog.latency_ms,
               m.PriceFetchLog.status).where(m.PriceFetchLog.ts >= start, m.PriceFetchLog.ts <= end,
                                             m.PriceFetchLog.provider_id.is_not(None))
    if provider_id:
        q = q.where(m.PriceFetchLog.provider_id == provider_id)
    if asset_id:
        q = q.where(m.PriceFetchLog.asset_id == asset_id)
    return list(db.execute(q))


def _agg(rows) -> dict:
    n = len(rows)
    ok = sum(1 for r in rows if r.ok)
    lat = [r.latency_ms for r in rows if r.ok and r.latency_ms is not None]
    return {"requests": n, "ok": ok, "errors": n - ok, "success_rate": (round(ok / n * 100, 1) if n else None),
            "avg_latency_ms": (round(sum(lat) / len(lat)) if lat else None)}


def provider_rows(db: Session, start: datetime, end: datetime, asset_id: int | None = None) -> list[dict]:
    logs = _logs(db, start, end, asset_id=asset_id)
    by_p: dict[int, list] = defaultdict(list)
    for r in logs:
        by_p[r.provider_id].append(r)
    out = []
    for p in db.scalars(select(m.PriceProvider).where(m.PriceProvider.is_archived.is_(False)).order_by(m.PriceProvider.id)):
        d = service.provider_dict(db, p)
        stats = _agg(by_p.get(p.id, []))
        out.append({"id": p.id, "name": p.name, "kind": p.kind, "kind_label": d["kind_label"], "is_enabled": p.is_enabled,
                    "status": d["status"], "last_success_at": p.last_success_at, "last_attempt_at": p.last_attempt_at,
                    "last_error": p.last_error, "last_latency_ms": p.last_latency_ms, "consecutive_failures": p.consecutive_failures,
                    "source_count": d["source_count"], **stats})
    return out


def overview(db: Session, days: int = 7, date_from: date | None = None, date_to: date | None = None, now: datetime | None = None) -> dict:
    now = now or now_local()
    start, end = _window(days, date_from, date_to, now)
    rows = provider_rows(db, start, end)
    live = [r for r in rows if r["kind"] != "manual"]
    all_logs = _agg(_logs(db, start, end))
    return {
        "window": {"from": start, "to": end},
        "summary": {"total": len(rows), "enabled": sum(1 for r in rows if r["is_enabled"]), "disabled": sum(1 for r in rows if not r["is_enabled"]),
                    "error": sum(1 for r in rows if r["status"] == "error"), "ok": sum(1 for r in rows if r["status"] == "ok"),
                    "last_success_at": max((r["last_success_at"] for r in live if r["last_success_at"]), default=None),
                    "requests": all_logs["requests"], "errors": all_logs["errors"], "success_rate": all_logs["success_rate"],
                    "avg_latency_ms": all_logs["avg_latency_ms"]},
        "providers": rows, "thresholds": thresholds(),
    }


def thresholds() -> dict:
    s = get_settings()
    return {"conflict_pct": s.quality_conflict_pct, "jump_pct": s.quality_jump_pct, "max_lag_minutes": s.quality_max_lag_minutes,
            "provider_down_failures": s.quality_provider_down_failures, "compare_window_hours": s.quality_compare_window_hours}


def performance(db: Session, days: int = 14, provider_id: int | None = None, asset_id: int | None = None,
                date_from: date | None = None, date_to: date | None = None, now: datetime | None = None) -> dict:
    """سری روزانهٔ درخواست، موفقیت، خطا و میانگین زمان پاسخ هر منبع."""
    now = now or now_local()
    start, end = _window(days, date_from, date_to, now)
    logs = _logs(db, start, end, provider_id, asset_id)
    names = {p.id: p.name for p in db.scalars(select(m.PriceProvider))}
    per: dict[tuple[int, date], list] = defaultdict(list)
    for r in logs:
        per[(r.provider_id, r.ts.date())].append(r)
    days_list = []
    d = start.date()
    while d <= end.date():
        days_list.append(d)
        d += timedelta(days=1)
    pids = sorted({k[0] for k in per})
    series = []
    for pid in pids:
        pts = []
        for day in days_list:
            a = _agg(per.get((pid, day), []))
            pts.append({"date": day, **a})
        series.append({"provider_id": pid, "name": names.get(pid, f"#{pid}"), "points": pts, "total": _agg([r for k, v in per.items() if k[0] == pid for r in v])})
    return {"days": days_list, "series": series}


# ---------------------------------------------------------------- دارایی‌ها
def _load_prices(db: Session, asset_ids: list[int], now: datetime) -> dict[int, list]:
    if not asset_ids:
        return {}
    rows = db.scalars(select(m.Price).where(m.Price.asset_id.in_(asset_ids), m.Price.recorded_at >= now - timedelta(days=400))
                      .order_by(m.Price.recorded_at, m.Price.id))
    out: dict[int, list] = defaultdict(list)
    for p in rows:
        out[p.asset_id].append(p)
    return out


def _rec(p, include_trace: bool = False) -> dict | None:
    if p is None:
        return None
    d = {"price_id": p.id, "price": p.price, "currency": p.currency, "source": p.source, "provider_id": p.provider_id, "origin": p.origin,
         "recorded_at": p.recorded_at, "fetched_at": p.fetched_at, "source_time": p.source_time, "price_kind": p.price_kind,
         "is_approved": p.is_approved, "is_valid": p.is_valid, "validity_note": p.validity_note, "user_confirmed": p.user_confirmed}
    if include_trace:
        d.update(raw_price=p.raw_price, raw_unit=p.raw_unit, conversion_note=p.conversion_note, flags=quality.flags_of(p),
                 via=_loads(p.via))
    return d


def _loads(t):
    try:
        return json.loads(t or "[]")
    except ValueError:
        return []


def _fx_info(db: Session, currency: str, now: datetime) -> dict | None:
    if currency == "IRT":
        return None
    r = db.scalar(select(m.FxRate).where(m.FxRate.currency == currency, m.FxRate.is_approved.is_(True)).order_by(m.FxRate.recorded_at.desc(), m.FxRate.id.desc()).limit(1))
    if r is None:
        return {"currency": currency, "rate": None, "note": "نرخ ارز ثبت نشده است؛ تبدیل به تومان ممکن نیست."}
    return {"currency": currency, "rate": r.rate, "recorded_at": r.recorded_at, "source": r.source, "note": "نرخ ارز دستی (جدول نرخ ارز)"}


def asset_rows(db: Session, now: datetime | None = None, *, q: str = "", status: str = "", provider_id: int | None = None,
               asset_id: int | None = None, include_inactive: bool = False) -> list[dict]:
    now = now or now_local()
    s = get_settings()
    max_age = _max_age(db)
    stmt = select(m.Asset).where(m.Asset.is_archived.is_(False)).order_by(m.Asset.sort_order, m.Asset.id)
    if not include_inactive:
        stmt = stmt.where(m.Asset.is_active.is_(True))
    if asset_id:
        stmt = stmt.where(m.Asset.id == asset_id)
    assets = list(db.scalars(stmt))
    if q:
        qq = q.strip().lower()
        assets = [a for a in assets if qq in a.name.lower() or qq in (a.symbol or "").lower() or qq in (a.name_en or "").lower()]
    prices = _load_prices(db, [a.id for a in assets], now)
    srcs: dict[int, list] = defaultdict(list)
    for sr in db.scalars(select(m.AssetPriceSource).where(m.AssetPriceSource.asset_id.in_([a.id for a in assets]) if assets else False).order_by(m.AssetPriceSource.priority, m.AssetPriceSource.id)):
        srcs[sr.asset_id].append(sr)
    plat = {p.id: p.name for p in db.scalars(select(m.Platform))}
    out = []
    for a in assets:
        rows = prices.get(a.id, [])
        st = quality.price_state(rows, now, max_age)
        good = st["last_good"]
        chain = srcs.get(a.id, [])
        enabled = [x for x in chain if x.is_enabled]
        if provider_id and not any(x.provider_id == provider_id for x in chain) and not (good and good.provider_id == provider_id):
            continue
        sources = []
        for i, x in enumerate(chain):
            pv = x.provider
            latest = max((p for p in rows if p.provider_id == pv.id and p.is_valid), key=lambda p: (p.recorded_at, p.id), default=None)
            sources.append({"source_id": x.id, "priority": x.priority, "role": "primary" if (enabled and x is enabled[0]) else "fallback",
                            "provider_id": pv.id, "provider": pv.name, "kind": pv.kind, "external_id": x.external_id, "price_field": x.price_field,
                            "is_enabled": x.is_enabled, "provider_enabled": pv.is_enabled and not pv.is_archived,
                            "provider_status": service.provider_status(pv), "last_attempt_at": x.last_attempt_at, "last_success_at": x.last_success_at,
                            "last_status": x.last_status, "last_error": x.last_error, "consecutive_failures": pv.consecutive_failures,
                            "latest": _rec(latest)})
        primary = next((x for x in sources if x["role"] == "primary"), None)
        primary_down = bool(primary and primary["kind"] != "manual" and (
            not primary["provider_enabled"] or primary["last_status"] == "error" or primary["consecutive_failures"] >= s.quality_provider_down_failures))
        using_fallback = bool(good and primary and (
            (good.origin == "manual" and primary["kind"] != "manual") or (good.origin == "online" and good.provider_id != primary["provider_id"])))
        attempts = [x for x in chain if x.last_attempt_at]
        last_att = max(attempts, key=lambda x: x.last_attempt_at, default=None)
        cmp = quality.compare_sources(rows, now, max_age, include_manual=True)
        newest_invalid = max((p for p in rows if not p.is_valid), key=lambda p: (p.recorded_at, p.id), default=None)
        shown = good if st["status"] in ("valid", "stale", "manual", "conflict") else None
        delay = None
        if good is not None and good.origin == "online" and good.fetched_at and good.source_time:
            delay = int((good.fetched_at - good.source_time).total_seconds())
        row = {
            "asset_id": a.id, "name": a.name, "name_en": a.name_en, "symbol": a.symbol, "asset_type": a.asset_type, "platform": plat.get(a.platform_id, ""),
            "currency": a.price_currency, "is_active": a.is_active,
            "status": st["status"], "status_text": STATUS_TEXT[st["status"]], "reason": st["reason"],
            "price": shown.price if shown else None, "source": shown.source if shown else None, "origin": shown.origin if shown else None,
            "recorded_at": shown.recorded_at if shown else None, "fetched_at": shown.fetched_at if shown else None,
            "age_minutes": int((now - shown.recorded_at).total_seconds() // 60) if shown else None,
            "age_days": st.get("age_days"), "delay_seconds": delay,
            "last_good": _rec(good, True),
            "latest_attempt": ({"provider": last_att.provider.name, "provider_id": last_att.provider_id, "at": last_att.last_attempt_at,
                                "status": last_att.last_status, "error": last_att.last_error} if last_att else None),
            "last_invalid": _rec(newest_invalid, True) if newest_invalid and (good is None or (newest_invalid.recorded_at, newest_invalid.id) > (good.recorded_at, good.id)) else None,
            "primary_down": primary_down, "using_fallback": using_fallback,
            "has_sources": bool(chain), "sources": sources,
            "comparison": cmp, "fx": _fx_info(db, a.price_currency, now) if good is not None else None,
        }
        out.append(row)
    if status:
        out = [r for r in out if r["status"] == status]
    return out


# ---------------------------------------------------------------- هشدارها
def _alert(kind: str, severity: str, title: str, message: str, *, asset_id=None, asset=None, provider_id=None, provider=None, at=None, value=None) -> dict:
    return {"id": f"{kind}:{asset_id or 0}:{provider_id or 0}", "type": kind, "severity": severity, "title": title, "message": message,
            "asset_id": asset_id, "asset": asset, "provider_id": provider_id, "provider": provider, "at": at, "value": value}


ALERT_TYPES = {
    "stale_price": "قدیمی‌شدن قیمت", "source_disagreement": "اختلاف غیرعادی منابع", "sharp_change": "تغییر شدید قیمت",
    "provider_down": "قطع ارتباط منبع", "wrong_currency": "واحد پول اشتباه", "invalid_price": "قیمت نامعتبر",
    "time_mismatch": "عدم تطابق زمان",
}


def alerts(db: Session, now: datetime | None = None, rows: list[dict] | None = None, providers: list[dict] | None = None) -> list[dict]:
    now = now or now_local()
    s = get_settings()
    rows = rows if rows is not None else asset_rows(db, now)
    out: list[dict] = []
    # ۱) قیمت قدیمی و اختلاف منابع
    for r in rows:
        base = dict(asset_id=r["asset_id"], asset=r["name"])
        if r["status"] == "stale":
            out.append(_alert("stale_price", "warning", "قیمت قدیمی", f"آخرین قیمت معتبر {r['name']} {r['age_days']} روز پیش بوده و در ارزش‌گذاری استفاده نمی‌شود.",
                              at=r["recorded_at"], value=r["age_days"], **base))
        if r["status"] == "conflict":
            c = r["comparison"]
            names = "، ".join(f"{x['source']}" for x in c["rows"] if x["origin"] != "manual")
            out.append(_alert("source_disagreement", "critical", "اختلاف غیرعادی بین منابع",
                              f"قیمت {r['name']} در منابع ({names}) تا {c['spread_pct']:.1f}٪ اختلاف دارد (آستانه {s.quality_conflict_pct:g}٪). "
                              "سیستم قیمتی انتخاب نمی‌کند؛ قیمت دستی ثبت کنید یا یکی از قیمت‌ها را صریحاً تأیید کنید.", value=float(c["spread_pct"]), **base))
    # ۲) تغییر شدید: دو قیمت معتبر پیاپی از یک منبع در ۷۲ ساعت اخیر
    ids = [r["asset_id"] for r in rows]
    prices = _load_prices(db, ids, now)
    for r in rows:
        by_src: dict[tuple, list] = defaultdict(list)
        for p in prices.get(r["asset_id"], []):
            if p.is_valid and now - p.recorded_at <= timedelta(hours=72):
                by_src[quality.source_key(p)].append(p)
        for key, lst in by_src.items():
            if len(lst) < 2:
                continue
            new, old = lst[-1], lst[-2]
            ch = quality.pct_change(new.price, old.price)
            if ch is not None and ch > Decimal(str(s.quality_jump_pct)):
                out.append(_alert("sharp_change", "warning", "تغییر شدید قیمت", f"قیمت {r['name']} از «{new.source}» {ch:.1f}٪ نسبت به قیمت قبلی تغییر کرده است (آستانه {s.quality_jump_pct:g}٪). مقدار را بررسی کنید.",
                                  asset_id=r["asset_id"], asset=r["name"], provider_id=new.provider_id, provider=new.source, at=new.recorded_at, value=float(ch)))
    # ۳) قطع ارتباط منبع
    provs = providers if providers is not None else provider_rows(db, now - timedelta(days=1), now)
    for p in provs:
        if p["kind"] == "manual" or not p["is_enabled"]:
            continue
        if p["status"] == "error" and p["consecutive_failures"] >= s.quality_provider_down_failures:
            out.append(_alert("provider_down", "critical", "قطع ارتباط منبع",
                              f"منبع «{p['name']}» {p['consecutive_failures']} بار پیاپی خطا داده است: {p['last_error']}",
                              provider_id=p["id"], provider=p["name"], at=p["last_attempt_at"], value=p["consecutive_failures"]))
    for r in rows:
        if r["primary_down"] and r["has_sources"]:
            pr = next(x for x in r["sources"] if x["role"] == "primary")
            fb = "از منبع جایگزین/دستی استفاده می‌شود." if r["using_fallback"] else "منبع جایگزین معتبری در دسترس نیست."
            out.append(_alert("provider_down", "warning", "منبع اصلی دارایی قطع است", f"منبع اصلی {r['name']} («{pr['provider']}») پاسخ نمی‌دهد؛ {fb}",
                              asset_id=r["asset_id"], asset=r["name"], provider_id=pr["provider_id"], provider=pr["provider"], at=pr["last_attempt_at"]))
    # ۴) واحد پول اشتباه (۲۴ ساعت اخیر)
    since = now - timedelta(hours=24)
    names = {p.id: p.name for p in db.scalars(select(m.PriceProvider))}
    anames = {a.id: a.name for a in db.scalars(select(m.Asset))}
    seen = set()
    for l in db.scalars(select(m.PriceFetchLog).where(m.PriceFetchLog.ts >= since, m.PriceFetchLog.code == "currency_mismatch").order_by(m.PriceFetchLog.ts.desc())):
        key = (l.asset_id, l.provider_id)
        if key in seen:
            continue
        seen.add(key)
        out.append(_alert("wrong_currency", "critical", "دریافت داده با واحد پول اشتباه", f"{names.get(l.provider_id, 'منبع')} برای {anames.get(l.asset_id, 'دارایی')} قیمتی با واحد ناسازگار داد و ذخیره نشد: {l.message}",
                          asset_id=l.asset_id, asset=anames.get(l.asset_id), provider_id=l.provider_id, provider=names.get(l.provider_id), at=l.ts))
    # ۵) قیمت نامعتبر و عدم تطابق زمان (۲۴ ساعت اخیر)
    seen_inv, seen_time = set(), set()
    recent = db.scalars(select(m.Price).where(m.Price.fetched_at >= since, m.Price.origin == "online").order_by(m.Price.fetched_at.desc(), m.Price.id.desc()))
    for p in recent:
        flags = quality.flags_of(p)
        key = (p.asset_id, p.provider_id)
        if not p.is_valid and ("non_positive" in flags or "future_time" in flags) and key not in seen_inv:
            seen_inv.add(key)
            kind = "time_mismatch" if "future_time" in flags else "invalid_price"
            out.append(_alert(kind, "warning", "زمان قیمت در آینده" if kind == "time_mismatch" else "قیمت صفر، منفی یا نامعتبر",
                              f"«{p.source}» برای {anames.get(p.asset_id, 'دارایی')}: {p.validity_note}", asset_id=p.asset_id, asset=anames.get(p.asset_id),
                              provider_id=p.provider_id, provider=p.source, at=p.fetched_at))
        if p.is_valid and "time_lag" in flags and key not in seen_time:
            seen_time.add(key)
            out.append(_alert("time_mismatch", "warning", "عدم تطابق زمان داده با زمان دریافت", f"«{p.source}» برای {anames.get(p.asset_id, 'دارایی')}: {p.validity_note or ''}".strip()
                              + (f" زمان منبع {p.source_time:%Y-%m-%d %H:%M}، زمان دریافت {p.fetched_at:%Y-%m-%d %H:%M}." if p.source_time and p.fetched_at else ""),
                              asset_id=p.asset_id, asset=anames.get(p.asset_id), provider_id=p.provider_id, provider=p.source, at=p.fetched_at))
    out.sort(key=lambda a: (SEVERITY_ORDER[a["severity"]], -(a["at"].timestamp() if a["at"] else 0)))
    return out


# ---------------------------------------------------------------- لاگ‌ها
def search_logs(db: Session, *, date_from: date | None = None, date_to: date | None = None, provider_id: int | None = None,
                asset_id: int | None = None, status: str = "", only_errors: bool = False, page: int = 1, page_size: int = 25) -> dict:
    conds = []
    if date_from:
        conds.append(m.PriceFetchLog.ts >= datetime.combine(date_from, time(0, 0)))
    if date_to:
        conds.append(m.PriceFetchLog.ts <= datetime.combine(date_to, time(23, 59, 59)))
    if provider_id:
        conds.append(m.PriceFetchLog.provider_id == provider_id)
    if asset_id:
        conds.append(m.PriceFetchLog.asset_id == asset_id)
    if status:
        conds.append(m.PriceFetchLog.status == status)
    if only_errors:
        conds.append(m.PriceFetchLog.ok.is_(False))
    total = db.scalar(select(func.count()).select_from(m.PriceFetchLog).where(*conds)) or 0
    stmt = select(m.PriceFetchLog).where(*conds).order_by(m.PriceFetchLog.ts.desc(), m.PriceFetchLog.id.desc()).offset((page - 1) * page_size).limit(page_size)
    names = {p.id: p.name for p in db.scalars(select(m.PriceProvider))}
    assets = {a.id: a.name for a in db.scalars(select(m.Asset))}
    items = [{**service.log_dict(l, names, assets), "code": l.code} for l in db.scalars(stmt)]
    return {"items": items, "total": total, "page": page, "page_size": page_size}
