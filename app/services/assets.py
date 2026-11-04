"""مدیریت پویای دارایی‌ها: CRUD، منابع قیمت، بایگانی/بازیابی و حذف ایمن.

قاعدهٔ مالی: ویرایش نام، وزن هدف یا منبع قیمت هرگز به تراکنش‌ها یا بهای خرید تاریخی دست نمی‌زند؛
موجودی فقط از تراکنش‌ها محاسبه می‌شود.
"""
from __future__ import annotations

import json
from decimal import Decimal

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from .. import models as m
from ..errors import ConflictError, NotFoundError, ValidationFailure
from . import catalog
from .clock import now_local
from .repository import get_default_portfolio

SORTS = {"name": m.Asset.name, "symbol": m.Asset.symbol, "type": m.Asset.asset_type, "created": m.Asset.id,
         "weight": m.Asset.target_weight, "order": m.Asset.sort_order}


def loads(s: str, default):
    try:
        v = json.loads(s) if s else default
        return v if isinstance(v, type(default)) else default
    except ValueError:
        return default


def source_dict(s: m.AssetPriceSource) -> dict:
    return {"id": s.id, "provider_id": s.provider_id, "provider": s.provider.name if s.provider else None,
            "provider_kind": s.provider.kind if s.provider else None, "priority": s.priority,
            "external_id": s.external_id, "price_field": s.price_field, "is_enabled": s.is_enabled,
            "interval_minutes": s.interval_minutes, "last_attempt_at": s.last_attempt_at,
            "last_success_at": s.last_success_at, "last_status": s.last_status, "last_error": s.last_error}


def asset_dict(db: Session, a: m.Asset, with_sources: bool = True) -> dict:
    t = db.get(m.AssetType, a.asset_type)
    d = {"id": a.id, "platform_id": a.platform_id, "platform": a.platform.name if a.platform else None,
         "name": a.name, "name_en": a.name_en, "symbol": a.symbol, "asset_type": a.asset_type,
         "asset_type_label": t.label if t else a.asset_type, "market": a.market, "unit": a.unit,
         "price_provider": "", "target_weight": a.target_weight, "price_currency": a.price_currency, "buy_fee_rate": a.buy_fee_rate,
         "decimals": a.decimals, "fractional_units": a.decimals > 0 or a.fractional_units,
         "min_quantity": a.min_quantity, "initial_price": a.initial_price, "is_active": a.is_active,
         "is_archived": a.is_archived, "archived_at": a.archived_at,
         "status": "archived" if a.is_archived else ("active" if a.is_active else "inactive"),
         "note": a.note, "description": a.note, "sort_order": a.sort_order, "extra": loads(a.extra, {}),
         "fetch_interval_minutes": a.fetch_interval_minutes}
    if with_sources:
        d["sources"] = [source_dict(s) for s in sorted(
            db.scalars(select(m.AssetPriceSource).where(m.AssetPriceSource.asset_id == a.id)), key=lambda s: s.priority)]
        d["price_provider"] = d["sources"][0]["provider_kind"] if d["sources"] else ""
    return d


def dependencies(db: Session, a: m.Asset) -> dict:
    def n(model, col):
        return db.scalar(select(func.count()).select_from(model).where(col == a.id)) or 0
    return {"transactions": n(m.Transaction, m.Transaction.asset_id), "prices": n(m.Price, m.Price.asset_id),
            "price_sources": n(m.AssetPriceSource, m.AssetPriceSource.asset_id),
            "portfolios": n(m.PortfolioAsset, m.PortfolioAsset.asset_id),
            "fetch_logs": n(m.PriceFetchLog, m.PriceFetchLog.asset_id)}


def list_assets(db: Session, *, q: str | None, asset_type: str | None, platform_id: int | None, status: str,
                sort: str, desc: bool, page: int, page_size: int, portfolio_member_of: int | None = None):
    cond = []
    if q:
        like = f"%{q.strip()}%"
        cond.append(or_(m.Asset.name.like(like), m.Asset.name_en.like(like), m.Asset.symbol.like(like), m.Asset.note.like(like)))
    if asset_type:
        cond.append(m.Asset.asset_type == asset_type)
    if platform_id:
        cond.append(m.Asset.platform_id == platform_id)
    if status == "active":
        cond += [m.Asset.is_active.is_(True), m.Asset.is_archived.is_(False)]
    elif status == "inactive":
        cond += [m.Asset.is_active.is_(False), m.Asset.is_archived.is_(False)]
    elif status == "archived":
        cond.append(m.Asset.is_archived.is_(True))
    elif status == "live":  # همه به‌جز بایگانی‌شده
        cond.append(m.Asset.is_archived.is_(False))
    if portfolio_member_of:
        cond.append(m.Asset.id.in_(select(m.PortfolioAsset.asset_id).where(m.PortfolioAsset.portfolio_id == portfolio_member_of)))
    col = SORTS.get(sort, m.Asset.sort_order)
    total = db.scalar(select(func.count()).select_from(m.Asset).where(*cond)) or 0
    stmt = select(m.Asset).where(*cond).order_by(col.desc() if desc else col.asc(), m.Asset.id).limit(page_size).offset((page - 1) * page_size)
    return total, list(db.scalars(stmt))


# ---------------- ایجاد/ویرایش ----------------
def _apply_sources(db: Session, a: m.Asset, sources) -> None:
    pids = [s.provider_id for s in sources]
    if len(set(pids)) != len(pids):
        raise ValidationFailure("هر منبع قیمت را فقط یک بار می‌توان برای یک دارایی تعریف کرد.")
    existing = {s.provider_id: s for s in db.scalars(select(m.AssetPriceSource).where(m.AssetPriceSource.asset_id == a.id))}
    ordered = sorted(enumerate(sources), key=lambda t: (t[1].priority, t[0]))
    keep = set()
    for rank, (_, s) in enumerate(ordered, start=1):
        pv = db.get(m.PriceProvider, s.provider_id)
        if pv is None or pv.is_archived:
            raise NotFoundError("منبع قیمت انتخاب‌شده یافت نشد یا بایگانی شده است.")
        if pv.kind not in ("manual",) and not s.external_id.strip():
            raise ValidationFailure(f"شناسهٔ دارایی در منبع «{pv.name}» را وارد کنید.")
        row = existing.get(s.provider_id)
        if row is None:
            row = m.AssetPriceSource(asset_id=a.id, provider_id=s.provider_id)
            db.add(row)
        row.priority, row.external_id, row.price_field = rank, s.external_id.strip(), s.price_field
        row.is_enabled, row.interval_minutes = s.is_enabled, s.interval_minutes
        keep.add(s.provider_id)
    for pid, row in existing.items():
        if pid not in keep:
            db.delete(row)


def apply_asset(db: Session, a: m.Asset, p, *, creating: bool) -> None:
    if p.fractional_units and not p.decimals:
        p.decimals = 6  # سازگاری با نسخهٔ ۱
    platform = db.get(m.Platform, p.platform_id)
    if platform is None:
        raise NotFoundError("پلتفرم یافت نشد.")
    if (creating or a.platform_id != p.platform_id) and platform.is_archived:
        raise ValidationFailure("پلتفرم انتخاب‌شده بایگانی شده است.")
    if not creating and a.platform_id != p.platform_id:
        if db.scalar(select(m.Transaction.id).where(m.Transaction.asset_id == a.id).limit(1)):
            raise ValidationFailure("پلتفرم دارایی دارای تراکنش قابل تغییر نیست. همین ابزار را روی پلتفرم دیگر "
                                    "به‌عنوان دارایی جدید با موجودی مستقل تعریف کنید.")
    cur = db.get(m.Currency, p.price_currency.upper())
    if cur is None or not cur.is_active:
        raise ValidationFailure("واحد پول انتخاب‌شده معتبر/فعال نیست.")
    t = db.get(m.AssetType, p.asset_type)
    if t is None or (not t.is_active and (creating or a.asset_type != p.asset_type)):
        raise ValidationFailure("نوع دارایی نامعتبر یا غیرفعال است.")
    extra = catalog.validate_extra(db, p.asset_type, p.extra)
    dup = db.scalar(select(m.Asset.id).where(m.Asset.platform_id == p.platform_id, m.Asset.name == p.name,
                                             m.Asset.id != (a.id or 0)))
    if dup:
        raise ConflictError("در این پلتفرم دارایی دیگری با همین نام وجود دارد.")
    if not creating and p.decimals < a.decimals:
        # کاهش اعشار مجاز نباید موجودی‌های اعشاری قبلی را نامعتبر کند
        for (q,) in db.execute(select(m.Transaction.quantity).where(m.Transaction.asset_id == a.id, m.Transaction.quantity.is_not(None))):
            exp = q.normalize().as_tuple().exponent
            if isinstance(exp, int) and -exp > p.decimals:
                raise ValidationFailure("تراکنش‌های ثبت‌شده با اعشار بیشتر وجود دارد؛ تعداد اعشار مجاز را کم نکنید.")
    a.platform_id, a.name, a.name_en, a.symbol, a.asset_type = p.platform_id, p.name, p.name_en, p.symbol, p.asset_type
    a.market, a.unit, a.price_currency, a.decimals, a.min_quantity = p.market, p.unit, cur.code, p.decimals, p.min_quantity
    a.fractional_units = p.decimals > 0
    a.target_weight, a.initial_price, a.buy_fee_rate = p.target_weight, p.initial_price, p.buy_fee_rate
    a.is_active, a.note, a.fetch_interval_minutes = p.is_active, p.note, p.fetch_interval_minutes
    a.extra = json.dumps(extra, ensure_ascii=False)


def create_asset(db: Session, p) -> m.Asset:
    a = m.Asset(sort_order=(db.scalar(select(func.max(m.Asset.sort_order))) or 0) + 1)
    apply_asset(db, a, p, creating=True)
    db.add(a)
    db.flush()
    if p.sources:
        _apply_sources(db, a, p.sources)
    pf = db.get(m.Portfolio, p.portfolio_id) if p.portfolio_id else get_default_portfolio(db)
    if pf is None:
        raise NotFoundError("سبد یافت نشد.")
    if not pf.is_archived:
        db.add(m.PortfolioAsset(portfolio_id=pf.id, asset_id=a.id, target_weight=p.target_weight, is_active=p.is_active))
    db.commit()
    return a


def update_asset(db: Session, a: m.Asset, p) -> m.Asset:
    old_weight = a.target_weight
    apply_asset(db, a, p, creating=False)
    if p.sources is not None:
        _apply_sources(db, a, p.sources)
    if p.target_weight != old_weight:
        pf = get_default_portfolio(db)
        pa = db.scalar(select(m.PortfolioAsset).where(m.PortfolioAsset.portfolio_id == pf.id, m.PortfolioAsset.asset_id == a.id))
        if pa is not None and pf.target_mode == "percent":
            pa.target_weight = p.target_weight
    db.commit()
    return a


def archive_asset(db: Session, a: m.Asset, archive: bool) -> m.Asset:
    a.is_archived = archive
    a.archived_at = now_local() if archive else None
    db.commit()
    return a


def _remove_dependents(db: Session, a: m.Asset, include_prices: bool) -> None:
    db.execute(delete(m.PortfolioAsset).where(m.PortfolioAsset.asset_id == a.id))
    db.execute(delete(m.AssetPriceSource).where(m.AssetPriceSource.asset_id == a.id))
    db.execute(delete(m.PriceFetchLog).where(m.PriceFetchLog.asset_id == a.id))
    if include_prices:
        db.execute(delete(m.Price).where(m.Price.asset_id == a.id))


def delete_asset(db: Session, a: m.Asset) -> None:
    """حذف کامل: فقط دارایی بدون تراکنش و بدون قیمت ثبت‌شده؛ عضویت سبد و تنظیمات منبع قیمت همراه حذف می‌شود."""
    dep = dependencies(db, a)
    if dep["transactions"]:
        raise ConflictError(f"این دارایی {dep['transactions']} تراکنش دارد و فقط قابل بایگانی است. "
                            "بایگانی، تاریخچه و گزارش‌ها را حفظ می‌کند و قابل بازیابی است.",
                            code="has_transactions", details=dep)
    if dep["prices"]:
        raise ConflictError(f"{dep['prices']} قیمت ثبت‌شده برای این دارایی وجود دارد. برای حذف دائمی از مسیر چندمرحله‌ای "
                            "حذف دائمی استفاده کنید یا آن را بایگانی کنید.", code="has_dependencies", details=dep)
    _remove_dependents(db, a, include_prices=False)
    db.delete(a)
    db.commit()


def purge_asset(db: Session, a: m.Asset) -> dict:
    """حذف دائمی پس از تأیید چندمرحله‌ای؛ دارایی دارای تراکنش هرگز حذف نمی‌شود."""
    dep = dependencies(db, a)
    if dep["transactions"]:
        raise ConflictError("دارایی دارای تراکنش هرگز حذف دائمی نمی‌شود؛ فقط بایگانی.", code="has_transactions", details=dep)
    _remove_dependents(db, a, include_prices=True)
    db.delete(a)
    db.commit()
    return dep
