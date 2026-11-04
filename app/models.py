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
# انواع دارایی اکنون پویا هستند (جدول asset_types)؛ این فهرست فقط کلیدهای سیستمی اولیه است.
SYSTEM_ASSET_TYPES = ("fund", "stock", "digital", "gold", "silver", "copper", "currency", "fixed_income", "commodity", "index", "other")
PROVIDER_KINDS = ("tsetmc", "bitpin", "streamdata", "servix", "custom_api", "manual")


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
    # زمان‌بند دریافت قیمت (Market Data Engine)
    scheduler_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    scheduler_default_interval_minutes: Mapped[int] = mapped_column(Integer, default=30)
    scheduler_market_hours_only: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class SchemaMigration(Base):
    """ثبت مهاجرت‌های اعمال‌شده روی دیتابیس (نسخه‌بندی ساختار)."""

    __tablename__ = "schema_migrations"
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    applied_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AssetType(Base):
    """نوع دارایی (پویا). fields_schema فهرست فیلدهای اختصاصی این نوع است (JSON)."""

    __tablename__ = "asset_types"
    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    label: Mapped[str] = mapped_column(String(80))
    label_en: Mapped[str] = mapped_column(String(80), default="")
    color: Mapped[str] = mapped_column(String(16), default="")  # gold | blue | green | slate | hex
    fields_schema: Mapped[str] = mapped_column(Text, default="[]")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Platform(Base):
    __tablename__ = "platforms"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    kind: Mapped[str] = mapped_column(String(32), default="other")  # funds | digital | other
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
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
    note: Mapped[str] = mapped_column(Text, default="")  # توضیحات
    # --- فیلدهای مدیریت پویا ---
    name_en: Mapped[str] = mapped_column(String(120), default="")
    market: Mapped[str] = mapped_column(String(40), default="")
    unit: Mapped[str] = mapped_column(String(32), default="واحد")
    decimals: Mapped[int] = mapped_column(Integer, default=0)  # تعداد اعشار مجاز تعداد
    min_quantity: Mapped[Decimal] = mapped_column(DecimalType, default=Decimal("0"))
    initial_price: Mapped[Decimal | None] = mapped_column(DecimalType, nullable=True)  # اختیاری؛ فقط اطلاعاتی
    extra: Mapped[str] = mapped_column(Text, default="{}")  # فیلدهای اختصاصی نوع (JSON)
    fetch_interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    platform: Mapped[Platform] = relationship(back_populates="assets")


class Portfolio(Base):
    """سبد سرمایه‌گذاری مستقل با برنامه و ترکیب هدف مخصوص خود."""

    __tablename__ = "portfolios"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    initial_capital: Mapped[Decimal] = mapped_column(DecimalType, default=Decimal("0"))
    monthly_contribution: Mapped[Decimal] = mapped_column(DecimalType, default=Decimal("0"))
    horizon_months: Mapped[int] = mapped_column(Integer, default=12)
    max_drawdown_pct: Mapped[Decimal] = mapped_column(DecimalType, default=Decimal("25"))
    plan_start_date: Mapped[date] = mapped_column(Date)
    target_mode: Mapped[str] = mapped_column(String(8), default="percent")  # percent | amount
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    members: Mapped[list["PortfolioAsset"]] = relationship(back_populates="portfolio")


class PortfolioAsset(Base):
    """عضویت دارایی در سبد + وزن هدف (درصدی) یا مبلغ هدف. حذف عضویت تراکنش‌ها را حذف نمی‌کند."""

    __tablename__ = "portfolio_assets"
    __table_args__ = (UniqueConstraint("portfolio_id", "asset_id", name="uq_portfolio_asset"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"), index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    target_weight: Mapped[Decimal] = mapped_column(DecimalType, default=Decimal("0"))
    target_amount: Mapped[Decimal] = mapped_column(DecimalType, default=Decimal("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    portfolio: Mapped[Portfolio] = relationship(back_populates="members")
    asset: Mapped["Asset"] = relationship()


class PlanPeriod(Base):
    """دوره‌های برنامه واریزی: seq=0 سرمایه اولیه، seq>=1 واریزی‌های ماهانه."""

    __tablename__ = "plan_periods"
    __table_args__ = (UniqueConstraint("portfolio_id", "seq", name="uq_plan_portfolio_seq"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int | None] = mapped_column(ForeignKey("portfolios.id"), nullable=True, index=True)
    seq: Mapped[int] = mapped_column(Integer)
    due_date: Mapped[date] = mapped_column(Date)
    planned_amount: Mapped[Decimal] = mapped_column(DecimalType)
    note: Mapped[str] = mapped_column(Text, default="")


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (Index("ix_tx_date", "tx_date"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tx_date: Mapped[date] = mapped_column(Date)
    portfolio_id: Mapped[int | None] = mapped_column(ForeignKey("portfolios.id"), nullable=True, index=True)
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
    __table_args__ = (
        Index("ix_price_asset_time", "asset_id", "recorded_at"),
        # جلوگیری از ثبت دوباره یک قیمت دریافتی (ردیف‌های دستی provider_id=NULL هستند و مشمول نیستند)
        UniqueConstraint("asset_id", "provider_id", "source_time", "price_kind", name="uq_price_fetch_dedupe"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"))
    price: Mapped[Decimal] = mapped_column(DecimalType)
    currency: Mapped[str] = mapped_column(ForeignKey("currencies.code"), default="IRT")
    recorded_at: Mapped[datetime] = mapped_column(DateTime)  # زمان قیمت در منبع (در نبود آن زمان دریافت)
    source: Mapped[str] = mapped_column(String(120), default="manual")
    is_approved: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str] = mapped_column(Text, default="")
    # --- Market Data Engine ---
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("price_providers.id"), nullable=True, index=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    price_kind: Mapped[str] = mapped_column(String(16), default="")  # last | close | nav | manual
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    validity_note: Mapped[str] = mapped_column(Text, default="")
    # --- کنترل کیفیت (نسخهٔ ۲٫۱) ---
    origin: Mapped[str] = mapped_column(String(8), default="manual")  # manual | online (مستقل از provider_id که با حذف منبع خالی می‌شود)
    raw_price: Mapped[Decimal | None] = mapped_column(DecimalType, nullable=True)  # قیمت خام منبع قبل از تبدیل واحد
    raw_unit: Mapped[str] = mapped_column(String(16), default="")
    conversion_note: Mapped[str] = mapped_column(Text, default="")  # مثال: «۱۲۳۰۰۰ IRR ÷ ۱۰ = ۱۲۳۰۰ IRT»
    quality_flags: Mapped[str] = mapped_column(Text, default="[]")  # JSON: ["jump","time_lag","no_source_time",...]
    via: Mapped[str] = mapped_column(Text, default="[]")  # JSON: زنجیرهٔ منابعی که تا رسیدن به این قیمت امتحان شدند
    user_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)  # تأیید صریح کاربر (حل اختلاف منابع)
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


class PriceProvider(Base):
    """منبع قیمت (Provider). کلید API فقط رمزنگاری‌شده و فقط در سرور نگهداری می‌شود."""

    __tablename__ = "price_providers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    kind: Mapped[str] = mapped_column(String(24))  # tsetmc | bitpin | streamdata | servix | custom_api | manual
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    base_url: Mapped[str] = mapped_column(String(300), default="")
    auth_type: Mapped[str] = mapped_column(String(16), default="none")  # none | bearer | header | query
    auth_param_name: Mapped[str] = mapped_column(String(80), default="")
    api_key_enc: Mapped[str] = mapped_column(Text, default="")
    request_params: Mapped[str] = mapped_column(Text, default="{}")  # JSON: پارامترهای ثابت درخواست
    field_map: Mapped[str] = mapped_column(Text, default="{}")  # JSON: مسیر JSONPath فیلدها
    config: Mapped[str] = mapped_column(Text, default="{}")  # JSON: تنظیمات اختصاصی نوع
    input_currency: Mapped[str] = mapped_column(String(16), default="")
    market: Mapped[str] = mapped_column(String(8), default="none")  # tse | 24h | none
    refresh_interval_minutes: Mapped[int] = mapped_column(Integer, default=30)
    min_interval_seconds: Mapped[Decimal] = mapped_column(DecimalType, default=Decimal("1"))
    retry_count: Mapped[int] = mapped_column(Integer, default=2)
    retry_delay_seconds: Mapped[Decimal] = mapped_column(DecimalType, default=Decimal("2"))
    timeout_seconds: Mapped[Decimal] = mapped_column(DecimalType, default=Decimal("8"))
    auto_approve: Mapped[bool] = mapped_column(Boolean, default=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str] = mapped_column(String(16), default="")  # ok | error | ""
    last_error: Mapped[str] = mapped_column(Text, default="")
    last_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AssetPriceSource(Base):
    """منبع(های) قیمت یک دارایی با اولویت: 1 = اصلی، 2 = جایگزین، ..."""

    __tablename__ = "asset_price_sources"
    __table_args__ = (UniqueConstraint("asset_id", "provider_id", name="uq_asset_provider"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("price_providers.id"), index=True)
    priority: Mapped[int] = mapped_column(Integer, default=1)
    external_id: Mapped[str] = mapped_column(String(120), default="")  # شناسه در منبع (مثلاً insCode یا BTC_IRT)
    price_field: Mapped[str] = mapped_column(String(16), default="")  # last | close | nav (برای TSETMC)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str] = mapped_column(String(16), default="")
    last_error: Mapped[str] = mapped_column(Text, default="")
    asset: Mapped[Asset] = relationship()
    provider: Mapped[PriceProvider] = relationship()


class PriceFetchLog(Base):
    __tablename__ = "price_fetch_logs"
    __table_args__ = (Index("ix_fetchlog_ts", "ts"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime)
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("price_providers.id"), nullable=True, index=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"), nullable=True, index=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="")  # ok duplicate stale invalid error rate_limited
    code: Mapped[str] = mapped_column(String(32), default="")  # کد خطای ارائه‌دهنده (currency_mismatch, network, ...)
    message: Mapped[str] = mapped_column(Text, default="")
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price: Mapped[Decimal | None] = mapped_column(DecimalType, nullable=True)
