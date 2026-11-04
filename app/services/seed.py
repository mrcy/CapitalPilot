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
]

# (پلتفرم، نام، نماد، نوع، وزن هدف ٪)
ASSETS = [
    ("مفید", "صندوق عیار", "عیار", "gold", "25"),
    ("مفید", "صندوق اطلس", "اطلس", "fund", "25"),
    ("مفید", "صندوق آوند", "آوند", "fund", "10"),
    ("بیت‌پین", "شاخص S&P 500", "SPX", "index", "20"),
    ("بیت‌پین", "سرمایه پایدار", "", "digital", "20"),
]


def is_seeded(db: Session) -> bool:
    return db.get(m.AppSettings, 1) is not None


def seed_defaults(db: Session, start_date: date | None = None) -> None:
    for code, name, symbol, base in CURRENCIES:
        if db.get(m.Currency, code) is None:
            db.add(m.Currency(code=code, name=name, symbol=symbol, is_base=base))
    db.flush()
    plat = {}
    for name, kind, note in PLATFORMS:
        p = db.scalar(select(m.Platform).where(m.Platform.name == name))
        if p is None:
            p = m.Platform(name=name, kind=kind, note=note)
            db.add(p)
            db.flush()
        plat[name] = p
    for i, (pname, name, symbol, typ, w) in enumerate(ASSETS):
        exists = db.scalar(select(m.Asset).where(m.Asset.platform_id == plat[pname].id, m.Asset.name == name))
        if exists is None:
            db.add(m.Asset(platform_id=plat[pname].id, name=name, symbol=symbol, asset_type=typ,
                           target_weight=Decimal(w), sort_order=i, price_currency="IRT"))
    if db.get(m.AppSettings, 1) is None:
        db.add(m.AppSettings(id=1, plan_start_date=start_date or today_local()))
    db.flush()
    sync_plan(db, today_local())
    db.commit()
