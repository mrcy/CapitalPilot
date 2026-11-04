"""Iran Market Data (نسخهٔ ۲٫۳): دریافت، پردازش، ذخیره و جستجوی نمادهای فایل ``latest-toman.json``.

اصول:
* دریافت فقط در Backend انجام می‌شود؛ یک‌بار برای کل فایل (نه برای هر نماد/کاربر) و با کش، ETag، حداقل فاصله و retry.
* ساختار واقعی فایل پردازش می‌شود: ``{"data": {"generated_at", "categories": {<دسته>: [رکورد…]}}, "meta": {…}}``.
  دسته‌ها و نمادها فقط از خود فایل استخراج می‌شوند؛ هیچ فهرست ثابتی در کد نیست.
* هر نماد وضعیت مستقل دارد: valid | warning | stale | invalid | no_price. دریافت موفق فایل یعنی «معتبر بودن» قیمت‌ها نیست.
* ``timestamp`` (زمان قیمت)، ``checked_at`` (زمان بررسی منبع) و ``generated_at`` (زمان تولید فایل) و زمان دریافت CapitalPilot
  چهار مفهوم جدا هستند و جدا ذخیره می‌شوند.
* قیمت‌ها با ارز و واحد واقعی خودشان ذخیره می‌شوند؛ هیچ ضرب/تقسیم ضمنی (مثلاً ÷۱۰) انجام نمی‌شود.
* در قطع API آخرین داده‌ها حفظ می‌شود اما پس از ``stale_after`` همه «قدیمی» اعلام می‌شوند و در ارزش‌گذاری نمی‌آیند.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, time as dtime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, delete, false, func, or_, select, true
from sqlalchemy.orm import Session

from ... import models as m
from ...config import get_settings
from ...errors import NotFoundError, ValidationFailure
from ..clock import now_local
from .base import ProviderError, normalize_fa
from .http import HttpClient
from .quality import FUTURE_TOLERANCE, norm_unit

log = logging.getLogger("capitalpilot.iranmarket")

KIND = "iranmarket"
STATUSES = ("valid", "warning", "stale", "invalid", "no_price")
MIN_GAP_SECONDS = 10  # حداقل فاصلهٔ دو دریافت واقعی (حتی دستی)؛ جلوگیری از درخواست‌های پشت‌سرهم
FAIL_RETRY_MINUTES = 5  # پس از خطا، زمان‌بند زودتر از بازهٔ عادی دوباره تلاش می‌کند
_sleep = time.sleep
_fetch_lock = threading.Lock()
_hist_lock = threading.Lock()
_hist_cache: dict[tuple, tuple[float, Any]] = {}

INVALID_TEXT = {
    "non_positive": "قیمت صفر یا منفی است.",
    "bad_price": "مقدار قیمت عددی/معتبر نیست.",
    "bad_timestamp": "زمان قیمت (timestamp) قابل خواندن نیست.",
    "no_timestamp": "زمان قیمت (timestamp) در داده نیست.",
    "currency_missing": "واحد پول نماد مشخص نیست.",
    "unit_size_invalid": "اندازهٔ واحد (unit_size) نامعتبر است.",
}


# ---------------------------------------------------------------- پردازش فایل
@dataclass
class ParsedFile:
    generated_at: datetime | None = None
    published_at: datetime | None = None
    generated_at_jalali: str = ""
    upstream_sources: str = ""
    rows: list[dict] = field(default_factory=list)
    skipped: int = 0
    duplicates: int = 0
    categories: list[str] = field(default_factory=list)


def _tz() -> ZoneInfo:
    return ZoneInfo(get_settings().app_timezone)


def parse_time(v: Any) -> datetime | None:
    """ISO 8601 (با Z یا آفست) → وقت محلی برنامه بدون tz. بدون آفست = UTC. نامعتبر → None."""
    if not isinstance(v, str) or not v.strip():
        return None
    s = v.strip()
    try:
        dt = datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith(("Z", "z")) else s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(_tz()).replace(tzinfo=None, microsecond=0)


def _dec(v: Any) -> tuple[Decimal | None, bool]:
    """(مقدار، معتبر؟). None → (None, True)؛ غیرعددی → (None, False). bool عدد نیست."""
    if v is None:
        return None, True
    if isinstance(v, bool):
        return None, False
    try:
        d = Decimal(str(v).strip().replace(",", "")) if not isinstance(v, (int, float, Decimal)) else Decimal(str(v))
    except InvalidOperation:
        return None, False
    return (d, True) if d.is_finite() else (None, False)


def _s(v: Any, n: int) -> str:
    return v.strip()[:n] if isinstance(v, str) else ""


_SYMBOL_RE = re.compile(r"^[\w\-.:/ ]{1,120}$", re.UNICODE)


def norm_search(text: str) -> str:
    t = normalize_fa(text or "").lower().replace("_", " ").replace("-", " ").replace("/", " ")
    t = t.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    return re.sub(r"\s+", " ", t).strip()


def normalize_row(r: dict, category_hint: str = "") -> dict | None:
    """یک رکورد خام → ستون‌های market_symbols. رکورد بدون symbol معتبر None می‌شود. ایراد ذاتی در invalid_reason."""
    sym = r.get("symbol")
    if not isinstance(sym, str) or not _SYMBOL_RE.match(sym.strip()):
        return None
    sym = sym.strip()
    reasons: list[str] = []
    price, ok = _dec(r.get("price"))
    if not ok:
        reasons.append("bad_price")
    elif price is not None and price <= 0:
        reasons.append("non_positive")
    ts = parse_time(r.get("timestamp"))
    ts_raw = _s(r.get("timestamp"), 40)
    if ts is None and not ts_raw:
        ts = parse_time(r.get("timestamp_tehran"))  # فقط وقتی timestamp اصلاً نیست؛ مقدار خراب پنهان نمی‌شود
    if ts is None and (price is not None or not ok):
        reasons.append("bad_timestamp" if (ts_raw or r.get("timestamp_tehran")) else "no_timestamp")
    currency = _s(r.get("currency"), 16).upper()
    if not currency:
        reasons.append("currency_missing")
    unit_size, ok_u = _dec(r.get("unit_size"))
    if r.get("unit_size") is None:
        unit_size = Decimal(1)  # فایل‌های بدون unit_size = یک واحد؛ مقدار null فرض ضمنی نیست و در جزئیات دیده می‌شود
    elif not ok_u or unit_size is None or unit_size <= 0:
        reasons.append("unit_size_invalid")
        unit_size = None
    quality = [q.strip() for q in (r.get("quality") or []) if isinstance(q, str) and q.strip()] if isinstance(r.get("quality"), list) else []
    row = {
        "symbol": sym, "name_fa": _s(r.get("name_fa"), 200), "name_en": _s(r.get("name_en"), 200),
        "category": _s(r.get("category"), 60) or category_hint, "market": _s(r.get("market"), 60), "currency": currency,
        "unit": _s(r.get("unit"), 32), "unit_size": unit_size, "price": price,
        "market_status": _s(r.get("market_status"), 40),
        "price_time": ts, "timestamp_raw": ts_raw, "timestamp_tehran": _s(r.get("timestamp_tehran"), 40),
        "timestamp_jalali": _s(r.get("timestamp_jalali"), 24), "checked_at": parse_time(r.get("checked_at")),
        "upstream_source": _s(r.get("source"), 40), "api_stale": r.get("stale") is True,
        "quality": json.dumps(quality, ensure_ascii=False), "has_warning": any(q != "stale" for q in quality),
        "invalid_reason": reasons[0] if reasons else "",
    }
    for k in ("bid", "ask", "open", "high", "low", "prev_close", "change", "change_pct", "volume"):
        d, good = _dec(r.get(k))
        row[k] = d if good else None
    row["price_f"] = float(price) if price is not None else None
    row["change_pct_f"] = float(row["change_pct"]) if row["change_pct"] is not None else None
    row["search_text"] = norm_search(f"{sym} {row['name_fa']} {row['name_en']}")
    return row


def parse_payload(payload: Any) -> ParsedFile:
    """ساختار واقعی فایل را می‌خواند (data.categories → دسته‌ها) و با ساختارهای ساده‌تر هم کنار می‌آید. ایراد ساختاری → ProviderError(parse)."""
    if not isinstance(payload, (dict, list)):
        raise ProviderError("ساختار فایل Iran Market Data غیرمنتظره است (نه شیء و نه آرایه).", "parse")
    meta = payload.get("meta") if isinstance(payload, dict) and isinstance(payload.get("meta"), dict) else {}
    body = payload.get("data") if isinstance(payload, dict) else payload
    out = ParsedFile()
    out.published_at = parse_time(meta.get("published_at"))
    out.upstream_sources = _s(meta.get("source"), 200)
    cats: dict[str, list] = {}
    if isinstance(body, dict):
        out.generated_at = parse_time(body.get("generated_at"))
        out.generated_at_jalali = _s(body.get("generated_at_jalali"), 24)
        c = body.get("categories")
        if isinstance(c, dict):
            cats = {str(k): v for k, v in c.items() if isinstance(v, list)}
        elif isinstance(c, list):  # دسته‌ها به‌صورت آرایهٔ {key/name, items/symbols}
            for it in c:
                if isinstance(it, dict):
                    key = str(it.get("key") or it.get("category") or it.get("name") or "")
                    lst = it.get("items") or it.get("symbols") or it.get("data")
                    if key and isinstance(lst, list):
                        cats[key] = lst
        elif isinstance(body.get("items"), list):
            cats[""] = body["items"]
    elif isinstance(body, list):
        cats[""] = body
    if not cats:
        raise ProviderError("در فایل Iran Market Data فهرست دسته‌ها/نمادها پیدا نشد (data.categories).", "parse")
    seen: set[str] = set()
    cat_names: list[str] = []
    for cat, items in cats.items():
        for it in items:
            if not isinstance(it, dict):
                out.skipped += 1
                continue
            row = normalize_row(it, cat)
            if row is None:
                out.skipped += 1
                continue
            if row["symbol"] in seen:
                out.duplicates += 1
                continue
            seen.add(row["symbol"])
            out.rows.append(row)
            if row["category"] and row["category"] not in cat_names:
                cat_names.append(row["category"])
    if not out.rows:
        raise ProviderError("هیچ نماد معتبری در فایل Iran Market Data پیدا نشد.", "parse")
    out.categories = cat_names
    return out


# ---------------------------------------------------------------- ذخیره
_COLS = [c.name for c in m.MarketSymbol.__table__.columns if c.name not in ("first_seen_at", "last_seen_at", "snapshot_id", "in_latest")]


def apply_parsed(db: Session, parsed: ParsedFile, snapshot_id: int, now: datetime) -> int:
    """upsert نمادها؛ فقط ردیف‌های تغییرکرده نوشته می‌شوند. نمادهایی که در فایل نیستند in_latest=False می‌شوند (حذف نمی‌شوند)."""
    existing = {r.symbol: r for r in db.scalars(select(m.MarketSymbol))}
    changed = 0
    seen = set()
    for row in parsed.rows:
        seen.add(row["symbol"])
        cur = existing.get(row["symbol"])
        if cur is None:
            db.add(m.MarketSymbol(**row, in_latest=True, first_seen_at=now, last_seen_at=now, snapshot_id=snapshot_id))
            changed += 1
            continue
        diff = any(getattr(cur, k) != v for k, v in row.items())
        if diff:
            for k, v in row.items():
                setattr(cur, k, v)
            changed += 1
        cur.in_latest, cur.last_seen_at, cur.snapshot_id = True, now, snapshot_id
    for sym, cur in existing.items():
        if sym not in seen and cur.in_latest:
            cur.in_latest = False
            changed += 1
    return changed


def _raw_dir() -> Path:
    d = get_settings().data_dir / "raw" / "iranmarket"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_raw(body: bytes, when: datetime, prefix: str = "latest-toman") -> str:
    name = f"{prefix}-{when:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.json.gz"
    d = _raw_dir()
    (d / name).write_bytes(gzip.compress(body, 6))
    keep = max(1, get_settings().iranmarket_raw_keep)
    files = sorted((f for f in d.iterdir() if f.name.endswith(".json.gz")), key=lambda f: f.stat().st_mtime_ns, reverse=True)
    for f in files[keep:]:
        try:
            f.unlink()
        except OSError:  # pragma: no cover
            pass
    return name


def forget_missing_raw(db: Session) -> None:
    """مرجع پاسخ خامِ فایل‌هایی که پاک شده‌اند از دریافت‌ها برداشته می‌شود (نمای «پاسخ خام» فقط چند دریافت آخر را دارد)."""
    have = {f.name for f in _raw_dir().iterdir()}
    for s in db.scalars(select(m.MarketSnapshot).where(m.MarketSnapshot.raw_path != "")):
        if s.raw_path not in have:
            s.raw_path = ""


def read_raw(name: str) -> bytes | None:
    if not re.match(r"^[\w\-.]+\.json\.gz$", name or ""):
        return None
    p = _raw_dir() / name
    return gzip.decompress(p.read_bytes()) if p.exists() else None


# ---------------------------------------------------------------- وضعیت
def get_provider(db: Session) -> m.PriceProvider | None:
    return db.scalar(select(m.PriceProvider).where(m.PriceProvider.kind == KIND, m.PriceProvider.is_archived.is_(False)).order_by(m.PriceProvider.id).limit(1))


def source_url(pv: m.PriceProvider | None) -> str:
    return ((pv.base_url if pv is not None else "") or get_settings().iranmarket_url).strip()


def stale_after(pv: m.PriceProvider | None) -> timedelta:
    s = get_settings().iranmarket_stale_after_minutes
    if s > 0:
        return timedelta(minutes=s)
    interval = int(pv.refresh_interval_minutes) if pv is not None and pv.refresh_interval_minutes else 30
    return timedelta(minutes=max(90, 3 * interval))


def last_ok(db: Session) -> m.MarketSnapshot | None:
    return db.scalar(select(m.MarketSnapshot).where(m.MarketSnapshot.status.in_(("ok", "unchanged"))).order_by(m.MarketSnapshot.fetched_at.desc(), m.MarketSnapshot.id.desc()).limit(1))


def last_any(db: Session) -> m.MarketSnapshot | None:
    return db.scalar(select(m.MarketSnapshot).order_by(m.MarketSnapshot.fetched_at.desc(), m.MarketSnapshot.id.desc()).limit(1))


def snapshot_state(db: Session, pv: m.PriceProvider | None, now: datetime | None = None) -> dict:
    """تازگی کل داده: آخرین دریافت موفق و زمان تولید فایل. اگر هرکدام از آستانه قدیمی‌تر باشد، همهٔ قیمت‌ها «قدیمی» حساب می‌شوند."""
    now = now or now_local()
    ok = last_ok(db)
    lim = stale_after(pv)
    st = {"has_data": ok is not None, "last_ok_at": ok.fetched_at if ok else None, "generated_at": None, "published_at": None,
          "fetch_age_minutes": None, "file_age_minutes": None, "stale_after_minutes": int(lim.total_seconds() // 60), "stale": True, "reason": ""}
    if ok is None:
        st["reason"] = "هنوز دادهٔ Iran Market Data دریافت نشده است."
        return st
    gen = db.scalar(select(m.MarketSnapshot.generated_at).where(m.MarketSnapshot.generated_at.is_not(None)).order_by(m.MarketSnapshot.fetched_at.desc(), m.MarketSnapshot.id.desc()).limit(1))
    pub = db.scalar(select(m.MarketSnapshot.published_at).where(m.MarketSnapshot.published_at.is_not(None)).order_by(m.MarketSnapshot.fetched_at.desc(), m.MarketSnapshot.id.desc()).limit(1))
    st.update(generated_at=gen, published_at=pub, fetch_age_minutes=int((now - ok.fetched_at).total_seconds() // 60))
    reasons = []
    if now - ok.fetched_at > lim:
        reasons.append(f"آخرین دریافت موفق {st['fetch_age_minutes']} دقیقه پیش بوده است.")
    ref = gen or pub
    if ref is not None:
        st["file_age_minutes"] = int((now - ref).total_seconds() // 60)
        if now - ref > lim:
            reasons.append(f"فایل منبع {st['file_age_minutes']} دقیقه پیش تولید شده و به‌روز نشده است.")
    st["stale"] = bool(reasons)
    st["reason"] = " ".join(reasons)
    return st


def max_age_days(db: Session) -> int:
    row = db.get(m.AppSettings, 1)
    return int(row.max_price_age_days) if row else 3


def status_case(now: datetime, max_age: int, snap_stale: bool):
    """وضعیت هر نماد در SQL (برای فیلتر/شمارش بدون بارگذاری همهٔ ردیف‌ها). باید با classify() یکسان باشد."""
    S = m.MarketSymbol
    cutoff = datetime.combine(now.date() - timedelta(days=max_age), dtime.min)
    return case(
        (and_(S.price.is_(None), S.invalid_reason == ""), "no_price"),
        (or_(S.invalid_reason != "", S.price_time.is_(None), S.price_time > now + FUTURE_TOLERANCE), "invalid"),
        (or_(S.api_stale.is_(True), S.in_latest.is_(False), S.price_time < cutoff, true() if snap_stale else false()), "stale"),
        (S.has_warning.is_(True), "warning"),
        else_="valid",
    )


def classify(r: m.MarketSymbol, now: datetime, max_age: int, snap_stale: bool, snap_reason: str = "") -> tuple[str, str]:
    """(وضعیت، دلیل فارسی) یک نماد."""
    if r.price is None and not r.invalid_reason:
        return "no_price", "منبع قیمتی برای این نماد اعلام نکرده است (null)."
    if r.invalid_reason or r.price_time is None:
        return "invalid", INVALID_TEXT.get(r.invalid_reason, "داده نامعتبر است.")
    if r.price_time > now + FUTURE_TOLERANCE:
        return "invalid", "زمان قیمت در آینده است."
    cutoff = datetime.combine(now.date() - timedelta(days=max_age), dtime.min)
    if r.api_stale:
        return "stale", "منبع بالادستی قیمت را قدیمی (stale) اعلام کرده است."
    if not r.in_latest:
        return "stale", "این نماد دیگر در آخرین فایل نیست."
    if r.price_time < cutoff:
        return "stale", f"قیمت بیش از {max_age} روز قدیمی است."
    if snap_stale:
        return "stale", snap_reason or "داده‌های Iran Market Data به‌روز نیستند."
    if r.has_warning:
        return "warning", "هشدار کیفیت از منبع: " + "، ".join(_json_list(r.quality))
    return "valid", ""


def _json_list(t: str) -> list[str]:
    try:
        v = json.loads(t or "[]")
        return [x for x in v if isinstance(x, str)]
    except ValueError:
        return []


# ---------------------------------------------------------------- دریافت
def _http(pv: m.PriceProvider | None) -> HttpClient:
    timeout = float(pv.timeout_seconds) if pv is not None and pv.timeout_seconds else 8.0
    return HttpClient(max(timeout, 15.0), max_bytes=get_settings().iranmarket_max_bytes)  # فایل حدود ۱ مگابایت است


def _prune_snapshots(db: Session) -> None:
    cutoff = now_local() - timedelta(days=60)
    db.execute(delete(m.MarketSnapshot).where(m.MarketSnapshot.fetched_at < cutoff))


def fetch_snapshot(db: Session, pv: m.PriceProvider | None, *, now: datetime | None = None, record: bool = True,
                   raise_errors: bool = False) -> dict:
    """یک‌بار فایل را از اینترنت می‌گیرد، می‌خواند و ذخیره می‌کند. هم‌زمانی دوگانه ندارد (single-flight).

    بازهٔ کش را بررسی نمی‌کند (آن کار ``ensure_fresh`` است)؛ حداقل فاصلهٔ ``MIN_GAP_SECONDS`` همچنان اعمال می‌شود.
    record=False: لاگ/وضعیت سلامت منبع را ثبت نمی‌کند (برای «تست اتصال» که خودش ثبت می‌کند).
    خروجی: {ok, status: ok|unchanged|error|skipped, ...}
    """
    now = now or now_local()
    if not _fetch_lock.acquire(blocking=False):
        return {"ok": True, "status": "skipped", "reason": "in_progress", "message": "دریافت دیگری در حال انجام است."}
    try:
        prev_any = last_any(db)
        if prev_any is not None and (now - prev_any.fetched_at).total_seconds() < MIN_GAP_SECONDS and prev_any.status != "error":
            return {"ok": True, "status": "skipped", "reason": "recent", "message": "دریافت بسیار اخیر انجام شده است."}
        prev = last_ok(db)
        url = source_url(pv)
        retries = max(0, int(pv.retry_count)) if pv is not None else 1
        delay = float(pv.retry_delay_seconds) if pv is not None else 1.0
        has_rows = db.scalar(select(func.count()).select_from(m.MarketSymbol)) or 0
        headers = {"If-None-Match": prev.etag} if prev is not None and prev.etag and has_rows else None
        http = _http(pv)
        t0 = time.monotonic()
        resp = None
        err: ProviderError | None = None
        for i in range(retries + 1):
            try:
                resp = http.get(url, headers=headers, allow_not_modified=True)
                err = None
                break
            except ProviderError as e:
                err = e
                if not e.retriable or i == retries:
                    break
                _sleep(delay * (2 ** i))
        latency = int((time.monotonic() - t0) * 1000)
        snap = m.MarketSnapshot(provider_id=pv.id if pv is not None else None, fetched_at=now, source_url=url[:300], latency_ms=latency)
        parsed: ParsedFile | None = None
        body = b""
        if err is None and resp is not None:
            snap.http_status = resp.status_code
            snap.etag = (resp.headers.get("etag") or "")[:120]
            body = resp.content
            snap.size_bytes = len(body)
            if resp.status_code == 304 and prev is not None:
                snap.status, snap.sha256, snap.etag = "unchanged", prev.sha256, prev.etag
            else:
                snap.sha256 = hashlib.sha256(body).hexdigest()
                if prev is not None and prev.sha256 == snap.sha256 and has_rows:
                    snap.status = "unchanged"
                else:
                    try:
                        parsed = parse_payload(json.loads(body.decode("utf-8-sig")))
                        snap.status = "ok"
                    except (ValueError, UnicodeDecodeError):
                        err = ProviderError("پاسخ Iran Market Data JSON معتبر نیست.", "parse")
                    except ProviderError as e:
                        err = e
        if err is not None:
            snap.status, snap.error = "error", err.message[:1000]
            snap.http_status = snap.http_status or err.http_status
            if body:  # پاسخ خراب برای عیب‌یابی
                try:
                    snap.raw_path = save_raw(body[:1_000_000], now, "error")
                except OSError:  # pragma: no cover
                    pass
        elif snap.status == "unchanged":
            snap.symbol_count, snap.category_count = (prev.symbol_count, prev.category_count) if prev else (0, 0)
            snap.generated_at, snap.published_at, snap.upstream_sources = (prev.generated_at, prev.published_at, prev.upstream_sources) if prev else (None, None, "")
            snap.raw_path = prev.raw_path if prev else ""
        else:
            assert parsed is not None
            snap.generated_at, snap.published_at, snap.upstream_sources = parsed.generated_at, parsed.published_at, parsed.upstream_sources
            snap.symbol_count, snap.category_count, snap.skipped_count = len(parsed.rows), len(parsed.categories), parsed.skipped + parsed.duplicates
            try:
                snap.raw_path = save_raw(body, now)
                forget_missing_raw(db)
            except OSError as e:  # pragma: no cover
                log.warning("raw save failed: %s", e)
        db.add(snap)
        db.flush()
        if parsed is not None:
            snap.changed_count = apply_parsed(db, parsed, snap.id, now)
            db.flush()
        if err is None:
            c = counts(db, pv, now, snap_stale=False)
            snap.valid_count, snap.stale_count, snap.invalid_count, snap.no_price_count = c["valid"] + c["warning"], c["stale"], c["invalid"], c["no_price"]
        _prune_snapshots(db)
        if record and pv is not None:
            _record_health(db, pv, snap, now)
        db.commit()
        out = {"ok": err is None, "status": snap.status, "snapshot_id": snap.id, "latency_ms": latency, "symbols": snap.symbol_count,
               "changed": snap.changed_count, "valid": snap.valid_count, "stale": snap.stale_count, "invalid": snap.invalid_count,
               "no_price": snap.no_price_count, "generated_at": snap.generated_at, "message": snap.error or _ok_message(snap)}
        if err is not None:
            out["error"] = {"code": err.code, "message": err.message}
            if raise_errors:
                raise err
        return out
    finally:
        _fetch_lock.release()


def _ok_message(s: m.MarketSnapshot) -> str:
    if s.status == "unchanged":
        return "فایل از دریافت قبلی تغییری نکرده است (دادهٔ تکراری ثبت نشد)."
    return f"{s.symbol_count} نماد در {s.category_count} دسته دریافت شد ({s.changed_count} نماد جدید/تغییرکرده)."


def _record_health(db: Session, pv: m.PriceProvider, snap: m.MarketSnapshot, now: datetime) -> None:
    ok = snap.status != "error"
    pv.last_attempt_at, pv.last_latency_ms = now, snap.latency_ms
    if ok:
        pv.last_success_at, pv.last_status, pv.last_error, pv.consecutive_failures = now, "ok", "", 0
    else:
        pv.last_status, pv.last_error = "error", snap.error[:500]
        pv.consecutive_failures = (pv.consecutive_failures or 0) + 1
    db.add(m.PriceFetchLog(ts=now, provider_id=pv.id, asset_id=None, ok=ok, status="ok" if snap.status == "ok" else ("duplicate" if snap.status == "unchanged" else "error"),
                           message=(snap.error or _ok_message(snap))[:1000], latency_ms=snap.latency_ms, code=("" if ok else "fetch")))


def ensure_fresh(db: Session, pv: m.PriceProvider | None, now: datetime | None = None) -> None:
    """اگر دادهٔ ذخیره‌شده از بازهٔ دریافت قدیمی‌تر است، یک‌بار فایل را می‌گیرد. خطا پرتاب نمی‌شود؛ آخرین داده حفظ می‌شود."""
    now = now or now_local()
    ok, prev = last_ok(db), last_any(db)
    interval = timedelta(minutes=int(pv.refresh_interval_minutes) if pv is not None and pv.refresh_interval_minutes else 30)
    if ok is not None and now - ok.fetched_at < interval:
        return
    if prev is not None and prev.status == "error" and (now - prev.fetched_at) < timedelta(seconds=60):
        return  # خطای اخیر؛ درخواست‌های پشت‌سرهم نزن
    fetch_snapshot(db, pv, now=now)


def scheduler_due(db: Session, pv: m.PriceProvider, now: datetime) -> bool:
    prev = last_any(db)
    if prev is None:
        return True
    interval = timedelta(minutes=max(1, int(pv.refresh_interval_minutes or 30)))
    gap = min(interval, timedelta(minutes=FAIL_RETRY_MINUTES)) if prev.status == "error" else interval
    return now - prev.fetched_at >= gap


# ---------------------------------------------------------------- پرس‌وجو
def counts(db: Session, pv: m.PriceProvider | None, now: datetime | None = None, *, snap_stale: bool | None = None) -> dict:
    now = now or now_local()
    if snap_stale is None:
        snap_stale = snapshot_state(db, pv, now)["stale"]
    expr = status_case(now, max_age_days(db), snap_stale)
    rows = db.execute(select(expr, func.count()).select_from(m.MarketSymbol).group_by(expr)).all()
    out = {s: 0 for s in STATUSES}
    for st, n in rows:
        out[st] = n
    out["total"] = sum(out[s] for s in STATUSES)
    return out


def _linked_counts(db: Session) -> dict[str, int]:
    rows = db.execute(select(m.AssetPriceSource.external_id, func.count()).join(m.PriceProvider, m.PriceProvider.id == m.AssetPriceSource.provider_id)
                      .where(m.PriceProvider.kind == KIND).group_by(m.AssetPriceSource.external_id)).all()
    return {k: n for k, n in rows}


def overview(db: Session, now: datetime | None = None) -> dict:
    now = now or now_local()
    pv = get_provider(db)
    st = snapshot_state(db, pv, now)
    c = counts(db, pv, now, snap_stale=st["stale"])
    expr = status_case(now, max_age_days(db), st["stale"])
    cats = []
    for key, tot in db.execute(select(m.MarketSymbol.category, func.count()).group_by(m.MarketSymbol.category).order_by(func.count().desc())).all():
        by = dict(db.execute(select(expr, func.count()).where(m.MarketSymbol.category == key).group_by(expr)).all())
        cats.append({"key": key, "count": tot, "valid": by.get("valid", 0) + by.get("warning", 0), "stale": by.get("stale", 0),
                     "invalid": by.get("invalid", 0), "no_price": by.get("no_price", 0)})
    facets = {
        "markets": [{"key": k, "count": n} for k, n in db.execute(select(m.MarketSymbol.market, func.count()).group_by(m.MarketSymbol.market).order_by(func.count().desc())).all()],
        "currencies": [{"key": k, "count": n} for k, n in db.execute(select(m.MarketSymbol.currency, func.count()).group_by(m.MarketSymbol.currency).order_by(func.count().desc())).all()],
    }
    snap = last_any(db)
    ok = last_ok(db)
    errs_24h = db.scalar(select(func.count()).select_from(m.MarketSnapshot).where(m.MarketSnapshot.status == "error", m.MarketSnapshot.fetched_at >= now - timedelta(hours=24))) or 0
    reqs_24h = db.scalar(select(func.count()).select_from(m.MarketSnapshot).where(m.MarketSnapshot.fetched_at >= now - timedelta(hours=24))) or 0
    avg_ms = db.scalar(select(func.avg(m.MarketSnapshot.latency_ms)).where(m.MarketSnapshot.fetched_at >= now - timedelta(hours=24), m.MarketSnapshot.latency_ms.is_not(None)))
    linked = db.scalar(select(func.count(func.distinct(m.AssetPriceSource.asset_id))).join(m.PriceProvider, m.PriceProvider.id == m.AssetPriceSource.provider_id).where(m.PriceProvider.kind == KIND)) or 0
    provider = None
    if pv is not None:
        provider = {"id": pv.id, "name": pv.name, "is_enabled": pv.is_enabled, "interval_minutes": pv.refresh_interval_minutes, "base_url": source_url(pv),
                    "last_attempt_at": pv.last_attempt_at, "last_success_at": pv.last_success_at, "last_status": pv.last_status,
                    "last_error": pv.last_error, "last_latency_ms": pv.last_latency_ms, "consecutive_failures": pv.consecutive_failures,
                    "auto_approve": pv.auto_approve}
    if pv is None or not pv.is_enabled:
        conn = "disabled"
    elif snap is None:
        conn = "unknown"
    elif snap.status == "error":
        conn = "error"
    elif st["stale"]:
        conn = "stale"
    else:
        conn = "ok"
    return {"provider": provider, "connection": conn, "snapshot": {**st, "last_attempt_at": snap.fetched_at if snap else None,
            "last_status": snap.status if snap else None, "last_error": snap.error if snap else "", "latency_ms": ok.latency_ms if ok else None,
            "upstream_sources": ok.upstream_sources if ok else "", "snapshot_id": ok.id if ok else None, "size_bytes": ok.size_bytes if ok else 0},
            "totals": {"total": c["total"], "valid": c["valid"] + c["warning"], "warning": c["warning"], "stale": c["stale"], "invalid": c["invalid"],
                       "no_price": c["no_price"], "categories": len(cats), "linked_assets": linked},
            "categories": cats, "facets": facets,
            "requests": {"last_24h": reqs_24h, "errors_24h": errs_24h, "avg_latency_ms": int(avg_ms) if avg_ms is not None else None}}


SORTS = {"symbol": m.MarketSymbol.symbol, "name": m.MarketSymbol.name_fa, "category": m.MarketSymbol.category, "price": m.MarketSymbol.price_f,
         "change_pct": m.MarketSymbol.change_pct_f, "time": m.MarketSymbol.price_time}


def symbol_dict(r: m.MarketSymbol, now: datetime, max_age: int, snap_stale: bool, snap_reason: str = "", linked: dict | None = None) -> dict:
    status, reason = classify(r, now, max_age, snap_stale, snap_reason)
    age = int((now - r.price_time).total_seconds() // 60) if r.price_time else None
    return {"symbol": r.symbol, "name_fa": r.name_fa, "name_en": r.name_en, "category": r.category, "market": r.market, "currency": r.currency,
            "unit": r.unit, "unit_size": r.unit_size, "price": r.price, "bid": r.bid, "ask": r.ask, "open": r.open, "high": r.high, "low": r.low,
            "prev_close": r.prev_close, "change": r.change, "change_pct": r.change_pct, "volume": r.volume, "market_status": r.market_status,
            "price_time": r.price_time, "timestamp": r.timestamp_raw, "timestamp_tehran": r.timestamp_tehran, "timestamp_jalali": r.timestamp_jalali,
            "checked_at": r.checked_at, "source": r.upstream_source, "api_stale": r.api_stale, "quality": _json_list(r.quality),
            "status": status, "status_reason": reason, "age_minutes": age, "in_latest": r.in_latest, "invalid_reason": r.invalid_reason,
            "last_seen_at": r.last_seen_at, "snapshot_id": r.snapshot_id, "linked_count": (linked or {}).get(r.symbol, 0)}


def list_symbols(db: Session, *, q: str = "", category: str = "", market: str = "", currency: str = "", status: str = "", linked: bool | None = None,
                 sort: str = "category", order: str = "asc", page: int = 1, page_size: int = 50, now: datetime | None = None) -> dict:
    now = now or now_local()
    pv = get_provider(db)
    st = snapshot_state(db, pv, now)
    ma = max_age_days(db)
    expr = status_case(now, ma, st["stale"])
    S = m.MarketSymbol
    conds = []
    for tok in norm_search(q).split():
        conds.append(S.search_text.contains(tok, autoescape=True))
    if category:
        conds.append(S.category == category)
    if market:
        conds.append(S.market == market)
    if currency:
        conds.append(S.currency == currency.upper())
    if status:
        if status == "valid_only":
            conds.append(expr.in_(("valid", "warning")))
        elif status in STATUSES:
            conds.append(expr == status)
        else:
            raise ValidationFailure("وضعیت فیلتر نامعتبر است.")
    linked_syms = _linked_counts(db)
    if linked is True:
        conds.append(S.symbol.in_(list(linked_syms) or [""]))
    elif linked is False:
        conds.append(S.symbol.not_in(list(linked_syms) or [""]))
    total = db.scalar(select(func.count()).select_from(S).where(*conds)) or 0
    col = SORTS.get(sort)
    if col is None:
        raise ValidationFailure("مرتب‌سازی نامعتبر است.")
    primary = col.desc() if order == "desc" else col.asc()
    qy = select(S).where(*conds)
    if sort in ("price", "change_pct", "time"):
        qy = qy.order_by(col.is_(None), primary, S.symbol)
    elif sort == "category":
        qy = qy.order_by(S.category, S.name_fa, S.symbol) if order != "desc" else qy.order_by(S.category.desc(), S.name_fa, S.symbol)
    else:
        qy = qy.order_by(primary, S.symbol)
    rows = db.scalars(qy.limit(page_size).offset((page - 1) * page_size)).all()
    return {"items": [symbol_dict(r, now, ma, st["stale"], st["reason"], linked_syms) for r in rows], "total": total, "page": page, "page_size": page_size}


def get_symbol(db: Session, symbol: str, now: datetime | None = None) -> dict:
    now = now or now_local()
    r = db.get(m.MarketSymbol, symbol)
    if r is None:
        raise NotFoundError("نماد در داده‌های Iran Market Data پیدا نشد.")
    pv = get_provider(db)
    st = snapshot_state(db, pv, now)
    d = symbol_dict(r, now, max_age_days(db), st["stale"], st["reason"], _linked_counts(db))
    d["unit_size_note"] = None if r.unit_size == 1 else "قیمت برای اندازهٔ واحد بیش از ۱ است؛ اتصال به دارایی پشتیبانی نمی‌شود."
    d["linked_assets"] = linked_assets(db, symbol, now)
    d["link_blockers"] = link_blockers(r)
    return d


def linked_assets(db: Session, symbol: str, now: datetime | None = None) -> list[dict]:
    from .quality import price_state
    now = now or now_local()
    ma = max_age_days(db)
    out = []
    for s in db.scalars(select(m.AssetPriceSource).join(m.PriceProvider, m.PriceProvider.id == m.AssetPriceSource.provider_id)
                        .where(m.PriceProvider.kind == KIND, m.AssetPriceSource.external_id == symbol).order_by(m.AssetPriceSource.asset_id)):
        a = s.asset
        rows = db.scalars(select(m.Price).where(m.Price.asset_id == a.id)).all()
        ps = price_state(rows, now, ma)
        out.append({"asset_id": a.id, "name": a.name, "symbol": a.symbol, "is_archived": a.is_archived, "price_currency": a.price_currency, "unit": a.unit,
                    "priority": s.priority, "is_enabled": s.is_enabled, "price_status": ps["status"],
                    "price": ps["record"].price if ps.get("record") is not None else None,
                    "price_time": ps["record"].recorded_at if ps.get("record") is not None else None,
                    "last_status": s.last_status, "last_error": s.last_error, "link": _link_meta(s.link_meta)})
    return out


def _link_meta(t: str) -> dict:
    try:
        v = json.loads(t or "{}")
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}


# ---------------------------------------------------------------- اتصال به دارایی
def link_blockers(r: m.MarketSymbol, asset: m.Asset | None = None) -> list[str]:
    """موانع ساختاری اتصال. وضعیت قیمت (قدیمی/ناموجود) مانع اتصال نیست ولی در ارزش‌گذاری استفاده نمی‌شود."""
    out = []
    if not r.currency:
        out.append("واحد پول نماد مشخص نیست؛ برای جلوگیری از حدس، اتصال ممکن نیست.")
    if r.unit_size is None or r.unit_size != 1:
        out.append(f"قیمت این نماد برای اندازهٔ واحد {r.unit_size if r.unit_size is not None else '؟'} است؛ تبدیل ضمنی انجام نمی‌شود و اتصال پشتیبانی نمی‌شود.")
    if asset is not None and r.currency:
        a, b = norm_unit(asset.price_currency), norm_unit(r.currency)
        if a != b and {a, b} != {"IRT", "IRR"}:
            out.append(f"واحد نماد ({r.currency}) با واحد قیمت دارایی ({asset.price_currency}) سازگار نیست. "
                       f"برای دارایی‌های جهانی، واحد قیمت دارایی را همان ارز نماد بگذارید تا با نرخ ارز ثبت‌شده ارزش‌گذاری شود.")
    return out


def make_link_meta(db: Session, asset: m.Asset, symbol: str, now: datetime | None = None) -> str:
    r = db.get(m.MarketSymbol, symbol)
    if r is None:
        raise ValidationFailure(f"نماد «{symbol}» در داده‌های Iran Market Data نیست؛ ابتدا داده‌ها را دریافت کنید یا نماد را از فهرست انتخاب کنید.", code="symbol_not_found")
    bl = link_blockers(r, asset)
    if bl:
        raise ValidationFailure(bl[0], code="link_blocked", details={"blockers": bl})
    return json.dumps({"symbol": r.symbol, "name_fa": r.name_fa, "name_en": r.name_en, "category": r.category, "market": r.market,
                       "currency": r.currency, "unit": r.unit, "unit_size": str(r.unit_size), "confirmed_at": (now or now_local()).isoformat(timespec="seconds")},
                      ensure_ascii=False)


def link_symbol(db: Session, asset: m.Asset, symbol: str, *, confirm: bool, priority: int | None = None) -> m.AssetPriceSource:
    if not confirm:
        raise ValidationFailure("اتصال نماد باید صریحاً تأیید شود؛ تطبیق خودکار انجام نمی‌شود.", code="link_not_confirmed")
    pv = get_provider(db)
    if pv is None:
        raise NotFoundError("منبع Iran Market Data تعریف نشده یا بایگانی شده است.")
    meta = make_link_meta(db, asset, symbol.strip())
    row = db.scalar(select(m.AssetPriceSource).where(m.AssetPriceSource.asset_id == asset.id, m.AssetPriceSource.provider_id == pv.id))
    others = [s for s in db.scalars(select(m.AssetPriceSource).where(m.AssetPriceSource.asset_id == asset.id).order_by(m.AssetPriceSource.priority)) if s is not row]
    if row is None:
        row = m.AssetPriceSource(asset_id=asset.id, provider_id=pv.id, is_enabled=True)
        db.add(row)
    row.external_id, row.link_meta, row.price_field = symbol.strip(), meta, ""
    pos = len(others) + 1 if priority is None else max(1, min(priority, len(others) + 1))
    seq = others[: pos - 1] + [row] + others[pos - 1:]
    for i, s in enumerate(seq, start=1):
        s.priority = i
    db.commit()
    return row


def unlink_symbol(db: Session, asset: m.Asset) -> bool:
    pv = get_provider(db)
    if pv is None:
        return False
    row = db.scalar(select(m.AssetPriceSource).where(m.AssetPriceSource.asset_id == asset.id, m.AssetPriceSource.provider_id == pv.id))
    if row is None:
        return False
    db.delete(row)
    db.flush()
    for i, s in enumerate(db.scalars(select(m.AssetPriceSource).where(m.AssetPriceSource.asset_id == asset.id).order_by(m.AssetPriceSource.priority)), start=1):
        s.priority = i
    db.commit()
    return True


def suggest(db: Session, asset: m.Asset, limit: int = 8, now: datetime | None = None) -> list[dict]:
    """پیشنهاد تطبیق (فقط پیشنهاد؛ هرگز اتصال خودکار نمی‌سازد)."""
    toks = {t for t in norm_search(f"{asset.name} {asset.name_en} {asset.symbol}").split() if len(t) >= 2}
    if not toks:
        return []
    now = now or now_local()
    ma = max_age_days(db)
    st = snapshot_state(db, get_provider(db), now)
    scored = []
    for r in db.scalars(select(m.MarketSymbol)):
        hay = set(r.search_text.split())
        hit = toks & hay
        if not hit:
            continue
        if link_blockers(r, asset):
            continue
        score = len(hit) / len(toks) + (0.3 if norm_search(asset.symbol) and norm_search(asset.symbol) == norm_search(r.symbol) else 0)
        scored.append((score, r))
    scored.sort(key=lambda t: (-t[0], t[1].symbol))
    return [{**symbol_dict(r, now, ma, st["stale"], st["reason"]), "score": round(s, 2)} for s, r in scored[:limit]]


# ---------------------------------------------------------------- قیمت برای Provider/Engine
def quote_for(db: Session, pv: m.PriceProvider | None, symbol: str, now: datetime | None = None):
    """(Quote) از دادهٔ ذخیره‌شده. اگر دادهٔ کل قدیمی یا نماد معیوب باشد ProviderError. شبکه فقط در ensure_fresh."""
    from .base import Quote
    now = now or now_local()
    ensure_fresh(db, pv, now)
    st = snapshot_state(db, pv, now)
    if not st["has_data"]:
        raise ProviderError("هنوز دادهٔ Iran Market Data دریافت نشده است؛ ابتدا اتصال را تست یا دریافت دستی کنید.", "no_data")
    r = db.get(m.MarketSymbol, symbol)
    if r is None:
        raise ProviderError(f"نماد «{symbol}» در فایل Iran Market Data پیدا نشد.", "no_data")
    if st["stale"]:
        raise ProviderError(f"داده‌های Iran Market Data قدیمی‌اند و استفاده نمی‌شوند: {st['reason']}", "stale_snapshot")
    if not r.in_latest:
        raise ProviderError(f"نماد «{symbol}» دیگر در آخرین فایل نیست.", "no_data")
    if r.price is None and not r.invalid_reason:
        raise ProviderError(f"برای «{symbol}» قیمتی اعلام نشده است.", "no_data")
    if r.invalid_reason in ("bad_price", "bad_timestamp", "no_timestamp", "currency_missing", "unit_size_invalid"):
        raise ProviderError(f"دادهٔ «{symbol}» نامعتبر است: {INVALID_TEXT[r.invalid_reason]}", "invalid_data")
    if r.unit_size is None or r.unit_size != 1:
        raise ProviderError(f"قیمت «{symbol}» برای اندازهٔ واحد {r.unit_size} است و بدون تبدیل واحد استفاده نمی‌شود.", "unit_size")
    extra = {"identity": {"currency": r.currency, "unit": r.unit, "unit_size": str(r.unit_size)}, "upstream_source": r.upstream_source,
             "checked_at": r.checked_at, "snapshot_id": r.snapshot_id, "upstream_stale": r.api_stale, "quality": _json_list(r.quality),
             "unit": r.unit, "symbol": r.symbol, "name_fa": r.name_fa, "from_snapshot": True}
    return Quote(r.price if r.price is not None else Decimal(0), r.currency, r.price_time, "last", extra)


# ---------------------------------------------------------------- تاریخچه (مسیر مستند API)
def _base_dir(pv: m.PriceProvider | None) -> str:
    return source_url(pv).rsplit("/", 1)[0]


def history(db: Session, symbol: str, days: int = 90, pv: m.PriceProvider | None = None) -> dict:
    """تاریخچهٔ روزانهٔ OHLC از ``history/index.json`` و ``history/{SYMBOL}.json`` (مستند در README پروژهٔ Iran Market Data).

    فقط برای نمایش نمودار است و در جدول قیمت‌ها ذخیره نمی‌شود؛ کش حافظه‌ای دارد (فایل‌های تاریخچه روزی یک‌بار ساخته می‌شوند).
    """
    pv = pv or get_provider(db)
    base = _base_dir(pv)
    ttl = max(1, get_settings().iranmarket_history_ttl_minutes) * 60
    http = _http(pv)

    def cached(key: tuple, loader):
        with _hist_lock:
            hit = _hist_cache.get(key)
            if hit and time.monotonic() - hit[0] < ttl:
                return hit[1]
        val = loader()
        with _hist_lock:
            _hist_cache[key] = (time.monotonic(), val)
        return val

    try:
        index = cached((base, "index"), lambda: http.get_json(f"{base}/history/index.json"))
        items = index.get("data") if isinstance(index, dict) else None
        item = next((i for i in (items or []) if isinstance(i, dict) and i.get("symbol") == symbol), None)
        if item is None:
            return {"available": False, "symbol": symbol, "message": "منبع برای این نماد فایل تاریخچه منتشر نکرده است.", "points": []}
        file = str(item.get("file") or f"history/{symbol}.json")
        if not re.match(r"^history/[\w\-.]+\.json$", file):
            return {"available": False, "symbol": symbol, "message": "مسیر تاریخچهٔ اعلام‌شده معتبر نیست.", "points": []}
        data = cached((base, file), lambda: http.get_json(f"{base}/{file}"))
    except ProviderError as e:
        return {"available": False, "symbol": symbol, "message": f"دریافت تاریخچه ناموفق بود: {e.message}", "points": [], "error": e.code}
    candles = data.get("data") if isinstance(data, dict) else None
    if not isinstance(candles, list):
        return {"available": False, "symbol": symbol, "message": "ساختار فایل تاریخچه غیرمنتظره است.", "points": []}
    pts = []
    for c in candles[-max(1, days):]:
        if not isinstance(c, dict) or c.get("close") is None:
            continue
        pts.append({"t": c.get("t"), "date_jalali": c.get("date_jalali"), "open": c.get("open"), "high": c.get("high"), "low": c.get("low"),
                    "close": c.get("close"), "quality": c.get("quality") or []})
    meta = data.get("meta") if isinstance(data, dict) and isinstance(data.get("meta"), dict) else {}
    return {"available": True, "symbol": symbol, "currency": meta.get("currency") or item.get("currency"), "interval": meta.get("interval", "1d"),
            "published_at": meta.get("published_at"), "total_records": len(candles), "points": pts}


def clear_history_cache() -> None:
    with _hist_lock:
        _hist_cache.clear()
