"""پشتیبان‌گیری JSON، بازیابی، نسخه پشتیبان فایل دیتابیس و پاک‌سازی چندمرحله‌ای."""
from __future__ import annotations

import json
import logging
import secrets
import shutil
import sqlite3
import time
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import delete, inspect, select
from sqlalchemy.orm import Session

from .. import __version__
from .. import models as m
from ..config import get_settings
from ..errors import AppError, ValidationFailure
from .clock import now_local, today_local
from .finance.ledger import LedgerError, replay
from .repository import sync_plan, tx_rec
from .seed import seed_defaults

log = logging.getLogger("capitalpilot.backup")
SCHEMA_VERSION = 2
SUPPORTED_VERSIONS = (1, 2)
# ستون‌های محرمانه که هرگز در پشتیبان JSON نوشته نمی‌شوند (کلید API پس از بازیابی باید دوباره وارد شود)
SECRET_COLUMNS = {"price_providers": {"api_key_enc"}}
# ترتیب درج (به‌خاطر کلیدهای خارجی)
TABLES = [
    ("currencies", m.Currency), ("app_settings", m.AppSettings), ("asset_types", m.AssetType), ("platforms", m.Platform),
    ("portfolios", m.Portfolio), ("price_providers", m.PriceProvider), ("assets", m.Asset), ("plan_periods", m.PlanPeriod),
    ("portfolio_assets", m.PortfolioAsset), ("transactions", m.Transaction), ("prices", m.Price), ("fx_rates", m.FxRate),
    ("asset_price_sources", m.AssetPriceSource), ("price_fetch_logs", m.PriceFetchLog),
]
V1_TABLES = {"currencies", "app_settings", "platforms", "assets", "plan_periods", "transactions", "prices", "fx_rates"}
RESET_PHRASE = "پاک‌سازی کامل"
_tokens: dict[str, tuple[float, str]] = {}


def _ser(v):
    if isinstance(v, Decimal):
        return format(v, "f")
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def export_json(db: Session) -> dict:
    tables = {}
    for name, model in TABLES:
        cols = [c.key for c in inspect(model).mapper.column_attrs if c.key not in SECRET_COLUMNS.get(name, set())]
        tables[name] = [{c: _ser(getattr(row, c)) for c in cols} for row in db.scalars(select(model))]
    return {"app": "CapitalPilot", "schema_version": SCHEMA_VERSION, "app_version": __version__,
            "exported_at": now_local().isoformat(), "tables": tables}


def _parse_value(col, v):
    if v is None:
        return None
    t = col.type
    pt = getattr(t, "python_type", None)
    try:
        if pt is Decimal or t.__class__.__name__ == "DecimalType":
            return Decimal(str(v))
        if pt is datetime:
            return datetime.fromisoformat(v)
        if pt is date:
            return date.fromisoformat(v)
    except (ValueError, ArithmeticError, TypeError, NotImplementedError):
        raise ValidationFailure(f"مقدار نامعتبر در فایل پشتیبان: {v!r}")
    return v


def validate_backup(data: dict) -> dict[str, list[dict]]:
    if not isinstance(data, dict) or data.get("app") != "CapitalPilot":
        raise ValidationFailure("این فایل، پشتیبان CapitalPilot نیست.")
    if data.get("schema_version") not in SUPPORTED_VERSIONS:
        raise ValidationFailure(f"نسخه فایل پشتیبان ({data.get('schema_version')}) پشتیبانی نمی‌شود.")
    tables = data.get("tables")
    if not isinstance(tables, dict):
        raise ValidationFailure("ساختار فایل پشتیبان نامعتبر است.")
    parsed: dict[str, list[dict]] = {}
    for name, model in TABLES:
        rows = tables.get(name)
        if rows is None and data.get("schema_version") == 1 and name not in V1_TABLES:
            rows = []  # پشتیبان نسخهٔ ۱: جدول‌های جدید خالی‌اند و پس از بازیابی ساخته می‌شوند
        if not isinstance(rows, list):
            raise ValidationFailure(f"جدول «{name}» در فایل پشتیبان وجود ندارد.")
        mapper = inspect(model).mapper
        cols = {c.key: c for c in mapper.columns}
        out = []
        for r in rows:
            if not isinstance(r, dict):
                raise ValidationFailure(f"ردیف نامعتبر در جدول {name}.")
            unknown = set(r) - set(cols)
            if unknown:
                raise ValidationFailure(f"ستون ناشناخته در جدول {name}: {', '.join(sorted(unknown))}")
            out.append({k: _parse_value(cols[k], v) for k, v in r.items()})
        parsed[name] = out
    if not parsed["app_settings"]:
        raise ValidationFailure("تنظیمات در فایل پشتیبان وجود ندارد.")
    for r in parsed["prices"]:  # پشتیبان‌های قدیمی‌تر از ۲٫۱ ستون origin ندارند
        if "origin" not in r:
            r["origin"] = "online" if (r.get("provider_id") or (r.get("fetched_at") and (r.get("price_kind") or "") != "manual")) else "manual"
    # بررسی سازگاری دفتر کل پیش از هر تغییری در دیتابیس
    recs = []
    from .finance.types import TxRec
    for r in parsed["transactions"]:
        recs.append(TxRec(r["id"], r["tx_date"], r["tx_type"], r["platform_id"], r.get("asset_id"), r.get("quantity"),
                          r.get("unit_price"), r.get("fee") or Decimal(0), r["total_amount"], r.get("fx_rate"),
                          r.get("plan_period_id")))
    by_portfolio: dict = {}
    for r, rec in zip(parsed["transactions"], recs):
        by_portfolio.setdefault(r.get("portfolio_id"), []).append(rec)
    try:
        for group in by_portfolio.values():
            replay(group)
    except LedgerError as e:
        raise ValidationFailure(f"تراکنش‌های فایل پشتیبان ناسازگار است: {e.message}")
    return parsed


def save_db_backup(db: Session | None, label: str = "manual") -> dict:
    """نسخه پشتیبان فایل دیتابیس (SQLite با API امن backup) و نسخه JSON کنار آن."""
    s = get_settings()
    s.backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = now_local().strftime("%Y%m%d-%H%M%S")
    files = []
    path = s.sqlite_path
    if path and path.exists():
        dest = s.backup_dir / f"capitalpilot-{label}-{stamp}.db"
        src = sqlite3.connect(str(path))
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        files.append(dest.name)
    elif db is not None:
        dest = s.backup_dir / f"capitalpilot-{label}-{stamp}.json"
        dest.write_text(json.dumps(export_json(db), ensure_ascii=False), encoding="utf-8")
        files.append(dest.name)
    _prune(s.backup_dir)
    return {"files": files, "dir": str(s.backup_dir)}


def _prune(d, keep: int = 30):
    files = sorted((f for f in d.iterdir() if f.is_file() and f.name.startswith("capitalpilot-")), key=lambda f: f.stat().st_mtime)
    for f in files[:-keep] if len(files) > keep else []:
        f.unlink(missing_ok=True)


def list_backups() -> list[dict]:
    d = get_settings().backup_dir
    if not d.exists():
        return []
    return [{"name": f.name, "size": f.stat().st_size, "created": datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds")}
            for f in sorted(d.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True) if f.is_file() and f.name.startswith("capitalpilot-")]


def _wipe(db: Session) -> None:
    for _, model in reversed(TABLES):
        db.execute(delete(model))
    db.flush()


def restore_json(db: Session, data: dict) -> dict:
    parsed = validate_backup(data)
    save_db_backup(db, "pre-restore")
    try:
        _wipe(db)
        for name, model in TABLES:
            for r in parsed[name]:
                db.add(model(**r))
            db.flush()
        db.commit()
        if data.get("schema_version") == 1:
            from ..migrations.steps import backfill_v2
            backfill_v2(db)
            db.commit()
        from .marketdata.service import ensure_default_providers
        ensure_default_providers(db)  # پشتیبان نسخه‌های قدیمی‌تر منبع Iran Market Data ندارد؛ (غیرفعال) اضافه می‌شود
        db.commit()
    except Exception as e:
        db.rollback()
        log.exception("restore failed")
        if isinstance(e, AppError):
            raise
        raise AppError("بازیابی ناموفق بود و تغییری اعمال نشد. جزئیات در لاگ ثبت شده است.", status_code=500, code="restore_failed")
    out = {"restored": {k: len(v) for k, v in parsed.items()}, "warnings": []}
    if parsed["price_providers"]:
        out["warnings"].append("کلیدهای API در پشتیبان نگهداری نمی‌شوند؛ برای منابع قیمت دارای کلید، کلید را دوباره وارد کنید.")
    return out


# ---- پاک‌سازی چندمرحله‌ای ----
def request_reset(scope: str) -> dict:
    now = time.time()
    for k in [k for k, (exp, _) in _tokens.items() if exp < now]:
        _tokens.pop(k, None)
    token = secrets.token_urlsafe(16)
    _tokens[token] = (now + 300, scope)
    return {"token": token, "expires_in": 300, "phrase": RESET_PHRASE, "scope": scope}


def confirm_reset(db: Session, token: str, phrase: str, scope: str) -> dict:
    entry = _tokens.get(token)
    if not entry or entry[0] < time.time():
        raise ValidationFailure("مرحله اول پاک‌سازی منقضی شده یا نامعتبر است؛ از ابتدا شروع کنید.")
    if entry[1] != scope:
        raise ValidationFailure("نوع پاک‌سازی با مرحله اول هم‌خوان نیست.")
    if phrase.strip() != RESET_PHRASE:
        raise ValidationFailure("عبارت تأیید صحیح نیست.")
    _tokens.pop(token, None)
    backup = save_db_backup(db, "pre-reset")
    try:
        if scope == "all":
            _wipe(db)
            db.execute(delete(m.MarketSymbol))  # کش Iran Market Data؛ با دریافت دوباره بازسازی می‌شود
            db.execute(delete(m.MarketSnapshot))
            db.commit()
            seed_defaults(db)
        else:
            for model in (m.Transaction, m.PriceFetchLog, m.Price, m.FxRate):
                db.execute(delete(model))
            db.commit()
            sync_plan(db, today_local(), apply_to_past_unpaid=True)
            db.commit()
    except Exception:
        db.rollback()
        log.exception("reset failed")
        raise AppError("پاک‌سازی ناموفق بود. جزئیات در لاگ ثبت شد.", status_code=500, code="reset_failed")
    return {"ok": True, "scope": scope, "backup": backup}
