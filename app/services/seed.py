"""داده‌های اولیه: ترکیب هدف سبد و برنامه سرمایه‌گذاری.

توجه: مبالغ سرمایه اولیه و واریزی ماهانه «برنامه هدف» هستند و هیچ خرید یا واریز واقعی‌ای
در دیتابیس ایجاد نمی‌شود؛ فقط پس از ثبت تراکنش واقعی توسط کاربر وارد حساب‌ها می‌شوند.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from .clock import today_local
from .repository import sync_plan

CURRENCIES = [
    ("IRT", "تومان", "تومان", True),
    ("USD", "دلار آمریکا", "$", False),
    ("USDT", "تتر", "USDT", False),
]

PLATFORMS = [
    ("مفید", "funds", "کارگزاری مفید — صندوق‌های سرمایه‌گذاری"),
    ("بیت‌پین", "digital", "پلتفرم بیت‌پین"),
    ("بورس", "exchange", "بورس اوراق بهادار تهران و فرابورس"),
    ("بورس کالا", "commodity", "بورس کالای ایران"),
    ("کارگزاری دیگر", "broker", "سایر کارگزاری‌ها"),
    ("بازار خارجی", "foreign", "بازارهای خارجی"),
    ("شخصی", "personal", "نگهداری شخصی (سکه، طلا و ...)"),
    ("سایر", "other", "سایر پلتفرم‌ها"),
]

# فیلد اختصاصی نوع: key, label, type (text|number|select), options

_F = lambda key, label, typ="text", options=None: {"key": key, "label": label, "type": typ, **({"options": options} if options else {})}  # noqa: E731
# (کلید، عنوان فارسی، عنوان انگلیسی، رنگ، فیلدهای اختصاصی)
ASSET_TYPES = [
    ("fund", "صندوق سرمایه‌گذاری", "Fund", "green",
     [_F("fund_kind", "نوع صندوق", "select", ["درآمد ثابت", "سهامی", "مختلط", "طلا", "شاخصی", "اهرمی", "سایر"]),
      _F("manager", "مدیر صندوق")]),
    ("stock", "سهام", "Stock", "green", [_F("sector", "صنعت"), _F("isin", "کد ISIN")]),
    ("digital", "رمزارز", "Crypto", "blue", [_F("network", "شبکه")]),
    ("gold", "طلا", "Gold", "gold", [_F("purity", "عیار", "number"), _F("form", "شکل", "select", ["سکه", "شمش", "آبشده", "صندوق", "سایر"])]),
    ("silver", "نقره", "Silver", "slate", [_F("purity", "عیار", "number")]),
    ("copper", "مس", "Copper", "slate", []),
    ("currency", "ارز", "Currency", "slate", [_F("currency_code", "کد ارز")]),
    ("fixed_income", "درآمد ثابت", "Fixed income", "green", [_F("annual_rate", "نرخ سود سالانه ٪", "number"), _F("maturity", "سررسید")]),
    ("commodity", "کالا", "Commodity", "slate", []),
    ("index", "شاخص", "Index", "blue", [_F("exchange", "بورس/بازار مرجع")]),
    ("other", "سایر", "Other", "slate", []),
]
LEGACY_TYPE_LABELS = {"cash": "نقد"}

# (پلتفرم، نام، نماد، نوع، وزن هدف ٪)
ASSETS = [
    ("مفید", "صندوق عیار", "عیار", "gold", "25"),
    ("مفید", "صندوق اطلس", "اطلس", "fund", "25"),
    ("مفید", "صندوق آوند", "آوند", "fund", "10"),
    ("بیت‌پین", "شاخص S&P 500", "SPX", "index", "20"),
    ("بیت‌پین", "سرمایه پایدار", "", "digital", "20"),
]


def ensure_asset_types(db: Session) -> None:
    import json
    for i, (key, label, label_en, color, fields) in enumerate(ASSET_TYPES):
        if db.get(m.AssetType, key) is None:
            db.add(m.AssetType(key=key, label=label, label_en=label_en, color=color, is_system=True, sort_order=i,
                               fields_schema=json.dumps(fields, ensure_ascii=False)))
    db.flush()
    # نوع‌هایی که در دارایی‌های موجود (نسخهٔ قبل) استفاده شده‌اند ولی تعریف نشده‌اند
    used = {r for (r,) in db.execute(select(m.Asset.asset_type).distinct())}
    for key in sorted(used):
        if key and db.get(m.AssetType, key) is None:
            db.add(m.AssetType(key=key, label=LEGACY_TYPE_LABELS.get(key, key), is_system=False, sort_order=100))
    db.flush()


def ensure_platforms(db: Session) -> dict[str, m.Platform]:
    out = {}
    for i, (name, kind, note) in enumerate(PLATFORMS):
        p = db.scalar(select(m.Platform).where(m.Platform.name == name))
        if p is None:
            p = m.Platform(name=name, kind=kind, note=note, sort_order=i)
            db.add(p)
            db.flush()
        out[name] = p
    return out


def is_seeded(db: Session) -> bool:
    return db.get(m.AppSettings, 1) is not None


def seed_defaults(db: Session, start_date: date | None = None) -> None:
    for code, name, symbol, base in CURRENCIES:
        if db.get(m.Currency, code) is None:
            db.add(m.Currency(code=code, name=name, symbol=symbol, is_base=base))
    db.flush()
    ensure_asset_types(db)
    plat = ensure_platforms(db)
    from .marketdata.service import ensure_default_providers
    ensure_default_providers(db)
    for i, (pname, name, symbol, typ, w) in enumerate(ASSETS):
        exists = db.scalar(select(m.Asset).where(m.Asset.platform_id == plat[pname].id, m.Asset.name == name))
        if exists is None:
            db.add(m.Asset(platform_id=plat[pname].id, name=name, symbol=symbol, asset_type=typ,
                           target_weight=Decimal(w), sort_order=i, price_currency="IRT"))
    if db.get(m.AppSettings, 1) is None:
        db.add(m.AppSettings(id=1, plan_start_date=start_date or today_local()))
    db.flush()
    ensure_default_portfolio(db)
    sync_plan(db, today_local())
    db.commit()


def ensure_default_portfolio(db: Session) -> m.Portfolio:
    """سبد پیش‌فرض «سبد اصلی»؛ پارامترها از تنظیمات و وزن هدف دارایی‌ها از خود دارایی‌ها کپی می‌شود (idempotent)."""
    from .repository import get_default_portfolio, get_settings_row

    pf = db.scalar(select(m.Portfolio).where(m.Portfolio.is_default.is_(True)))
    created = False
    if pf is None:
        r = get_settings_row(db)
        pf = db.scalar(select(m.Portfolio).order_by(m.Portfolio.id))
        if pf is None:
            pf = m.Portfolio(name="سبد اصلی", description="سبد پیش‌فرض سرمایه‌گذاری", initial_capital=r.initial_capital,
                             monthly_contribution=r.monthly_contribution, horizon_months=r.horizon_months,
                             max_drawdown_pct=r.max_drawdown_pct, plan_start_date=r.plan_start_date, is_default=True)
            db.add(pf)
            created = True
        else:
            pf.is_default = True
        db.flush()
    if created:
        for a in db.scalars(select(m.Asset).order_by(m.Asset.sort_order, m.Asset.id)):
            db.add(m.PortfolioAsset(portfolio_id=pf.id, asset_id=a.id, target_weight=a.target_weight, is_active=a.is_active))
        db.flush()
    return get_default_portfolio(db)
