"""مدل‌های دیتابیس (SQLAlchemy 2.x).

نکات طراحی:
* تعداد واحد (quantity) و قیمت هر واحد (unit_price) جدا ذخیره می‌شوند.
* تمام مقادیر پولی Decimal هستند (DecimalType).
* تاریخ تراکنش‌ها میلادی (ISO) ذخیره می‌شود؛ تبدیل به شمسی فقط در نمایش انجام می‌شود.
* تاریخ‌وساعت قیمت‌ها به‌صورت naive و بر اساس منطقه زمانی برنامه (APP_TIMEZONE) ذخیره می‌شود.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base, DecimalType

TX_TYPES = ("buy", "sell", "deposit", "withdrawal", "dividend", "fee", "adjustment")
ASSET_TYPES = ("gold", "fund", "index", "digital", "cash", "other")


class Currency(Base):
    __tablename__ = "currencies"
    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    symbol: Mapped[str] = mapped_column(String(16), default="")
    is_base: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class AppSettings(Base):
    """تنظیمات سراسری (یک ردیف با id=1)."""

    __tablename__ = "app_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    initial_capital: Mapped[Decimal] = mapped_column(DecimalType, default=Decimal("100000000"))
    monthly_contribution: Mapped[Decimal] = mapped_column(DecimalType, default=Decimal("50000000"))
    horizon_months: Mapped[int] = mapped_column(Integer, default=12)
    plan_start_date: Mapped[date] = mapped_column(Date)
    max_drawdown_pct: Mapped[Decimal] = mapped_column(DecimalType, default=Decimal("25"))
    concentration_limit_pct: Mapped[Decimal] = mapped_column(DecimalType, default=Decimal("35"))
    deviation_warning_pp: Mapped[Decimal] = mapped_column(DecimalType, default=Decimal("5"))
    max_price_age_days: Mapped[int] = mapped_column(Integer, default=3)
    calendar: Mapped[str] = mapped_column(String(16), default="jalali")  # jalali | gregorian
    currency_label: Mapped[str] = mapped_column(String(16), default="تومان")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Platform(Base):
    __tablename__ = "platforms"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    kind: Mapped[str] = mapped_column(String(32), default="other")  # funds | digital | other
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str] = mapped_column(Text, default="")
    assets: Mapped[list["Asset"]] = relationship(back_populates="platform")


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (
        CheckConstraint("target_weight >= 0", name="ck_asset_target_nonneg"),
        UniqueConstraint("platform_id", "name", name="uq_asset_platform_name"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform_id: Mapped[int] = mapped_column(ForeignKey("platforms.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    symbol: Mapped[str] = mapped_column(String(40), default="")
    asset_type: Mapped[str] = mapped_column(String(16), default="other")
    target_weight: Mapped[Decimal] = mapped_column(DecimalType, default=Decimal("0"))  # درصد از کل سبد
    price_currency: Mapped[str] = mapped_column(ForeignKey("currencies.code"), default="IRT")
    buy_fee_rate: Mapped[Decimal] = mapped_column(DecimalType, default=Decimal("0"))  # درصد، برای پیشنهاد خرید
    fractional_units: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    price_provider: Mapped[str] = mapped_column(String(40), default="")  # خالی = فقط دستی
    price_provider_params: Mapped[str] = mapped_column(Text, default="")  # JSON
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    platform: Mapped[Platform] = relationship(back_populates="assets")


class PlanPeriod(Base):
    """دوره‌های برنامه واریزی: seq=0 سرمایه اولیه، seq>=1 واریزی‌های ماهانه."""

    __tablename__ = "plan_periods"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, unique=True)
    due_date: Mapped[date] = mapped_column(Date)
    planned_amount: Mapped[Decimal] = mapped_column(DecimalType)
    note: Mapped[str] = mapped_column(Text, default="")


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (Index("ix_tx_date", "tx_date"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tx_date: Mapped[date] = mapped_column(Date)
    platform_id: Mapped[int] = mapped_column(ForeignKey("platforms.id"), index=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"), index=True, nullable=True)
    tx_type: Mapped[str] = mapped_column(String(16))
    quantity: Mapped[Decimal | None] = mapped_column(DecimalType, nullable=True)
    unit_price: Mapped[Decimal | None] = mapped_column(DecimalType, nullable=True)  # همیشه به واحد پایه (تومان)
    fee: Mapped[Decimal] = mapped_column(DecimalType, default=Decimal("0"))
    total_amount: Mapped[Decimal] = mapped_column(DecimalType)  # محاسبه‌شده در Backend
    fx_rate: Mapped[Decimal | None] = mapped_column(DecimalType, nullable=True)  # نرخ تبدیل ارز در لحظه تراکنش
    plan_period_id: Mapped[int | None] = mapped_column(ForeignKey("plan_periods.id"), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    platform: Mapped[Platform] = relationship()
    asset: Mapped[Asset | None] = relationship()


class Price(Base):
    __tablename__ = "prices"
    __table_args__ = (Index("ix_price_asset_time", "asset_id", "recorded_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"))
    price: Mapped[Decimal] = mapped_column(DecimalType)
    currency: Mapped[str] = mapped_column(ForeignKey("currencies.code"), default="IRT")
    recorded_at: Mapped[datetime] = mapped_column(DateTime)
    source: Mapped[str] = mapped_column(String(120), default="manual")
    is_approved: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    asset: Mapped[Asset] = relationship()


class FxRate(Base):
    """نرخ تبدیل ارز به واحد پایه (تومان): rate = چند تومان برای هر یک واحد ارز."""

    __tablename__ = "fx_rates"
    __table_args__ = (Index("ix_fx_cur_time", "currency", "recorded_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    currency: Mapped[str] = mapped_column(ForeignKey("currencies.code"))
    rate: Mapped[Decimal] = mapped_column(DecimalType)
    recorded_at: Mapped[datetime] = mapped_column(DateTime)
    source: Mapped[str] = mapped_column(String(120), default="manual")
    is_approved: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
