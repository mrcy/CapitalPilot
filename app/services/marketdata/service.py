"""مدیریت منابع قیمت (Provider) در دیتابیس: CRUD، بایگانی/حذف ایمن، تست اتصال. کلید API هرگز بازگردانده نمی‌شود."""
from __future__ import annotations

import json
from decimal import Decimal
from urllib.parse import urlparse

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from ... import models as m
from ...config import get_settings
from ...errors import ConflictError, NotFoundError, ValidationFailure
from ..clock import now_local
from . import crypto
from .base import ProviderConfig, ProviderError
from .jsonpath import validate_path

KIND_INFO = {
    "tsetmc": {
        "label": "TSETMC (بورس تهران)", "needs_url": False, "needs_key": False, "supports_search": True,
        "supports_history": True, "default_unit": "IRR", "default_market": "tse", "id_label": "شناسهٔ نماد (insCode)",
        "price_fields": ["last", "close", "nav"],
        "description": "آخرین معامله، قیمت پایانی، NAV صندوق‌ها و تاریخچه. قیمت‌ها ریال هستند و به تومان تبدیل می‌شوند.",
        "defaults": {"auto_approve": True, "market": "tse", "input_currency": "IRR", "refresh_interval_minutes": 15},
    },
    "bitpin": {
        "label": "بیت‌پین (بازارهای تکی)", "needs_url": False, "needs_key": False, "supports_search": True,
        "supports_history": True, "default_unit": "IRT", "default_market": "24h", "id_label": "نماد بازار (مثل BTC_IRT)",
        "price_fields": [],
        "description": "قیمت لحظه‌ای، آخرین معامله و تغییر ۲۴ساعتهٔ بازارهای تکی. سبدهای آمادهٔ بیت‌پین پشتیبانی نمی‌شوند.",
        "defaults": {"auto_approve": True, "market": "24h", "input_currency": "IRT", "refresh_interval_minutes": 10},
    },
    "streamdata": {
        "label": "StreamData (سهام و شاخص خارجی)", "needs_url": True, "needs_key": True, "supports_search": False,
        "supports_history": False, "default_unit": "USD", "default_market": "none", "id_label": "نماد در سرویس",
        "price_fields": [],
        "description": "اختیاری. آدرس و کلید را از سرویس‌دهنده بگیرید و مسیر JSON قیمت را تنظیم کنید. قیمت به دلار ثبت و با نرخ ارز جدا به تومان تبدیل می‌شود.",
        "defaults": {"input_currency": "USD", "market": "none", "refresh_interval_minutes": 60},
    },
    "servix": {
        "label": "Servix (طلا، ارز و ...)", "needs_url": True, "needs_key": True, "supports_search": False,
        "supports_history": False, "default_unit": "IRT", "default_market": "none", "id_label": "شناسهٔ آیتم در سرویس",
        "price_fields": [],
        "description": "اختیاری. آدرس، کلید و مسیر JSON را از مستندات سرویس‌دهنده وارد کنید.",
        "defaults": {"input_currency": "IRT", "market": "none", "refresh_interval_minutes": 30},
    },
    "custom_api": {
        "label": "Custom API (JSON)", "needs_url": True, "needs_key": False, "supports_search": False,
        "supports_history": False, "default_unit": "IRT", "default_market": "none", "id_label": "مقدار {symbol} در درخواست",
        "price_fields": [],
        "description": "هر API با پاسخ JSON: آدرس، پارامترها، احراز هویت و مسیر JSONPath قیمت/زمان/واحد را خودتان تعریف کنید.",
        "defaults": {"market": "none", "refresh_interval_minutes": 30},
    },
    "manual": {
        "label": "قیمت دستی", "needs_url": False, "needs_key": False, "supports_search": False, "supports_history": False,
        "default_unit": "IRT", "default_market": "none", "id_label": "", "price_fields": [],
        "description": "ثبت دستی قیمت توسط شما؛ به‌عنوان آخرین منبع در زنجیرهٔ اولویت استفاده می‌شود.",
        "defaults": {"auto_approve": True},
    },
}

DEFAULT_PROVIDERS = [
    ("TSETMC", "tsetmc"), ("بیت‌پین (Bitpin)", "bitpin"), ("StreamData", "streamdata"), ("Servix", "servix"),
    ("Custom API", "custom_api"), ("قیمت دستی", "manual"),
]


def _j(s: str, default):
    try:
        v = json.loads(s) if s else default
        return v if isinstance(v, type(default)) else default
    except ValueError:
        return default


def ensure_default_providers(db: Session) -> None:
    """ایجاد منابع پیش‌فرض (غیرفعال؛ فقط «قیمت دستی» فعال). اتصال خودکار با فعال‌سازی توسط کاربر شروع می‌شود."""
    for name, kind in DEFAULT_PROVIDERS:
        if db.scalar(select(m.PriceProvider.id).where(m.PriceProvider.kind == kind).limit(1)) is not None:
            continue
        d = KIND_INFO[kind]["defaults"]
        db.add(m.PriceProvider(name=name, kind=kind, is_enabled=(kind == "manual"), auto_approve=d.get("auto_approve", False),
                               market=d.get("market", "none"), input_currency=d.get("input_currency", ""),
                               refresh_interval_minutes=d.get("refresh_interval_minutes", 30)))
    db.flush()


def to_config(pv: m.PriceProvider) -> ProviderConfig:
    return ProviderConfig(
        id=pv.id, name=pv.name, kind=pv.kind, base_url=pv.base_url, auth_type=pv.auth_type, auth_param_name=pv.auth_param_name,
        api_key=crypto.decrypt(pv.api_key_enc), request_params={str(k): str(v) for k, v in _j(pv.request_params, {}).items()},
        field_map={str(k): str(v) for k, v in _j(pv.field_map, {}).items()}, options=_j(pv.config, {}),
        input_currency=pv.input_currency, timeout=float(pv.timeout_seconds))


def provider_dict(db: Session, pv: m.PriceProvider) -> dict:
    n_src = db.scalar(select(func.count()).select_from(m.AssetPriceSource).where(m.AssetPriceSource.provider_id == pv.id)) or 0
    n_px = db.scalar(select(func.count()).select_from(m.Price).where(m.Price.provider_id == pv.id)) or 0
    s = get_settings()
    env_key = bool(getattr(s, f"{pv.kind}_api_key", "")) if pv.kind in ("streamdata", "servix") else False
    env_url = bool(getattr(s, f"{pv.kind}_base_url", "")) if pv.kind in ("streamdata", "servix") else False
    info = KIND_INFO.get(pv.kind, {})
    return {
        "id": pv.id, "name": pv.name, "kind": pv.kind, "kind_label": info.get("label", pv.kind), "is_enabled": pv.is_enabled,
        "is_archived": pv.is_archived, "base_url": pv.base_url, "auth_type": pv.auth_type, "auth_param_name": pv.auth_param_name,
        "has_api_key": bool(pv.api_key_enc), "api_key_from_env": env_key, "base_url_from_env": env_url,
        "request_params": _j(pv.request_params, {}), "field_map": _j(pv.field_map, {}), "config": _j(pv.config, {}),
        "input_currency": pv.input_currency, "market": pv.market, "refresh_interval_minutes": pv.refresh_interval_minutes,
        "min_interval_seconds": pv.min_interval_seconds, "retry_count": pv.retry_count,
        "retry_delay_seconds": pv.retry_delay_seconds, "timeout_seconds": pv.timeout_seconds, "auto_approve": pv.auto_approve,
        "last_attempt_at": pv.last_attempt_at, "last_success_at": pv.last_success_at, "last_status": pv.last_status,
        "last_error": pv.last_error, "last_latency_ms": pv.last_latency_ms, "consecutive_failures": pv.consecutive_failures,
        "source_count": n_src, "price_count": n_px, "status": provider_status(pv),
    }


def provider_status(pv: m.PriceProvider) -> str:
    if pv.is_archived:
        return "archived"
    if not pv.is_enabled:
        return "disabled"
    if pv.kind == "manual":
        return "ok"
    if pv.last_status == "ok":
        return "ok"
    if pv.last_status == "error":
        return "error"
    return "unknown"


def _validate_url(url: str, auth_type: str) -> None:
    if not url:
        return
    probe = url.replace("{symbol}", "x")
    u = urlparse(probe)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValidationFailure("آدرس API باید با http:// یا https:// شروع شود.")
    if u.scheme == "http" and auth_type != "none":
        raise ValidationFailure("برای ارسال کلید API فقط آدرس https مجاز است.")


def save_provider(db: Session, p, pid: int | None = None) -> m.PriceProvider:
    pv = db.get(m.PriceProvider, pid) if pid else None
    if pid and pv is None:
        raise NotFoundError("منبع قیمت یافت نشد.")
    if pv is not None and pv.kind != p.kind:
        raise ValidationFailure("نوع منبع قیمت پس از ساخت قابل تغییر نیست.")
    if db.scalar(select(m.PriceProvider.id).where(m.PriceProvider.name == p.name, m.PriceProvider.id != (pid or 0))):
        raise ConflictError("منبعی با این نام وجود دارد.")
    _validate_url(p.base_url, p.auth_type)
    if p.auth_type in ("header", "query") and not p.auth_param_name:
        raise ValidationFailure("برای این نوع احراز هویت، نام هدر/پارامتر را وارد کنید.")
    for key, path in p.field_map.items():
        if path.strip():
            try:
                validate_path(path)
            except ProviderError as e:
                raise ValidationFailure(f"مسیر JSON «{key}» نامعتبر است: {e.message}")
    if p.kind in ("custom_api", "streamdata", "servix") and p.is_enabled:
        s = get_settings()
        has_url = bool(p.base_url or getattr(s, f"{p.kind}_base_url", ""))
        if not has_url:
            raise ValidationFailure("برای فعال‌سازی، آدرس API را وارد کنید.")
        if not p.field_map.get("price"):
            raise ValidationFailure("برای فعال‌سازی، مسیر JSON قیمت (field_map.price) را وارد کنید.")
    if pv is None:
        pv = m.PriceProvider(kind=p.kind)
        db.add(pv)
    pv.name, pv.is_enabled, pv.base_url, pv.auth_type, pv.auth_param_name = p.name, p.is_enabled, p.base_url, p.auth_type, p.auth_param_name
    pv.request_params = json.dumps(p.request_params, ensure_ascii=False)
    pv.field_map = json.dumps({k: v for k, v in p.field_map.items() if v.strip()}, ensure_ascii=False)
    pv.config = json.dumps({k: v for k, v in p.config.items() if v not in (None, "")}, ensure_ascii=False)
    pv.input_currency, pv.market = p.input_currency.upper(), p.market
    pv.refresh_interval_minutes, pv.min_interval_seconds = p.refresh_interval_minutes, p.min_interval_seconds
    pv.retry_count, pv.retry_delay_seconds, pv.timeout_seconds, pv.auto_approve = p.retry_count, p.retry_delay_seconds, p.timeout_seconds, p.auto_approve
    if p.clear_api_key:
        pv.api_key_enc = ""
    elif p.api_key:
        pv.api_key_enc = crypto.encrypt(p.api_key.strip())
    db.commit()
    return pv


def set_enabled(db: Session, pv: m.PriceProvider, enabled: bool) -> m.PriceProvider:
    if enabled and pv.is_archived:
        raise ValidationFailure("منبع بایگانی‌شده را ابتدا بازیابی کنید.")
    pv.is_enabled = enabled
    db.commit()
    return pv


def archive_provider(db: Session, pv: m.PriceProvider, archive: bool) -> m.PriceProvider:
    pv.is_archived = archive
    if archive:
        pv.is_enabled = False
    db.commit()
    return pv


def dependencies(db: Session, pv: m.PriceProvider) -> dict:
    return {
        "price_sources": db.scalar(select(func.count()).select_from(m.AssetPriceSource).where(m.AssetPriceSource.provider_id == pv.id)) or 0,
        "prices": db.scalar(select(func.count()).select_from(m.Price).where(m.Price.provider_id == pv.id)) or 0,
        "fetch_logs": db.scalar(select(func.count()).select_from(m.PriceFetchLog).where(m.PriceFetchLog.provider_id == pv.id)) or 0,
    }


def delete_provider(db: Session, pv: m.PriceProvider) -> None:
    dep = dependencies(db, pv)
    if dep["price_sources"] or dep["prices"]:
        raise ConflictError("این منبع به دارایی‌ها یا قیمت‌های ثبت‌شده وابسته است؛ آن را غیرفعال/بایگانی کنید "
                            "یا از حذف دائمی چندمرحله‌ای استفاده کنید.", code="has_dependencies", details=dep)
    db.execute(delete(m.PriceFetchLog).where(m.PriceFetchLog.provider_id == pv.id))
    db.delete(pv)
    db.commit()


def purge_provider(db: Session, pv: m.PriceProvider) -> dict:
    """حذف دائمی: تنظیمات منبع از دارایی‌ها برداشته می‌شود؛ قیمت‌های ثبت‌شده حفظ می‌شوند (فقط ارتباط provider قطع می‌شود)."""
    dep = dependencies(db, pv)
    db.execute(delete(m.AssetPriceSource).where(m.AssetPriceSource.provider_id == pv.id))
    db.execute(delete(m.PriceFetchLog).where(m.PriceFetchLog.provider_id == pv.id))
    db.execute(update(m.Price).where(m.Price.provider_id == pv.id).values(provider_id=None))
    db.delete(pv)
    db.commit()
    return dep


def log_dict(l: m.PriceFetchLog, names: dict[int, str], assets: dict[int, str]) -> dict:
    return {"id": l.id, "ts": l.ts, "provider_id": l.provider_id, "provider": names.get(l.provider_id),
            "asset_id": l.asset_id, "asset": assets.get(l.asset_id), "ok": l.ok, "status": l.status,
            "message": l.message, "latency_ms": l.latency_ms, "price": l.price}


def list_logs(db: Session, *, provider_id: int | None, asset_id: int | None, only_errors: bool, limit: int) -> list[dict]:
    q = select(m.PriceFetchLog).order_by(m.PriceFetchLog.ts.desc(), m.PriceFetchLog.id.desc()).limit(limit)
    if provider_id:
        q = q.where(m.PriceFetchLog.provider_id == provider_id)
    if asset_id:
        q = q.where(m.PriceFetchLog.asset_id == asset_id)
    if only_errors:
        q = q.where(m.PriceFetchLog.ok.is_(False))
    names = {p.id: p.name for p in db.scalars(select(m.PriceProvider))}
    assets = {a.id: a.name for a in db.scalars(select(m.Asset))}
    return [log_dict(l, names, assets) for l in db.scalars(q)]
