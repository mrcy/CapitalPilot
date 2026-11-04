"""مدل‌های ورودی (Pydantic) با اعتبارسنجی."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TxType = Literal["buy", "sell", "deposit", "withdrawal", "dividend", "fee", "adjustment"]
Money = Decimal
MAX = Decimal("1e15")


class Strict(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class SettingsIn(Strict):
    initial_capital: Decimal = Field(ge=0, le=MAX, decimal_places=4)
    monthly_contribution: Decimal = Field(ge=0, le=MAX, decimal_places=4)
    horizon_months: int = Field(ge=1, le=600)
    plan_start_date: date
    max_drawdown_pct: Decimal = Field(gt=0, le=100)
    concentration_limit_pct: Decimal = Field(gt=0, le=100)
    deviation_warning_pp: Decimal = Field(gt=0, le=100)
    max_price_age_days: int = Field(ge=0, le=365)
    calendar: Literal["jalali", "gregorian"]
    currency_label: str = Field(min_length=1, max_length=16)
    apply_to_past_unpaid: bool = False

    @model_validator(mode="before")
    @classmethod
    def drop_readonly(cls, v):
        """کلیدهای فقط‌خواندنی GET /api/settings که کلاینت‌ها ممکن است برگردانند نادیده گرفته می‌شوند."""
        if isinstance(v, dict):
            v = {k: x for k, x in v.items() if k not in ("portfolio_id", "portfolio_name", "scheduler_enabled")}
        return v


class CurrencyIn(Strict):
    code: str = Field(min_length=2, max_length=16, pattern=r"^[A-Za-z0-9_]+$")
    name: str = Field(min_length=1, max_length=64)
    symbol: str = Field(default="", max_length=16)
    is_active: bool = True

    @field_validator("code")
    @classmethod
    def upper(cls, v: str) -> str:
        return v.upper()


class PlatformIn(Strict):
    name: str = Field(min_length=1, max_length=80)
    kind: str = Field(default="other", max_length=32)
    is_active: bool = True
    note: str = Field(default="", max_length=500)
    sort_order: int = Field(default=0, ge=0, le=10000)


class FieldDef(Strict):
    key: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    label: str = Field(min_length=1, max_length=60)
    type: Literal["text", "number", "select"] = "text"
    options: list[str] | None = Field(default=None, max_length=50)


class AssetTypeIn(Strict):
    key: str = Field(min_length=2, max_length=32, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=80)
    label_en: str = Field(default="", max_length=80)
    color: str = Field(default="", max_length=16, pattern=r"^(|gold|blue|green|red|slate|#[0-9A-Fa-f]{6})$")
    fields: list[FieldDef] = Field(default_factory=list, max_length=30)
    is_active: bool = True
    sort_order: int = Field(default=100, ge=0, le=10000)


class PriceSourceIn(Strict):
    provider_id: int
    external_id: str = Field(default="", max_length=120)
    price_field: Literal["", "last", "close", "nav"] = ""
    priority: int = Field(default=1, ge=1, le=20)
    is_enabled: bool = True
    interval_minutes: int | None = Field(default=None, ge=1, le=10080)


class AssetIn(Strict):
    platform_id: int
    name: str = Field(min_length=1, max_length=120)
    name_en: str = Field(default="", max_length=120)
    symbol: str = Field(default="", max_length=40)
    asset_type: str = Field(default="other", min_length=2, max_length=32, pattern=r"^[a-z][a-z0-9_]*$")
    market: str = Field(default="", max_length=40)
    unit: str = Field(default="واحد", min_length=1, max_length=32)
    price_currency: str = Field(default="IRT", max_length=16)
    decimals: int = Field(default=0, ge=0, le=12)
    min_quantity: Decimal = Field(default=Decimal(0), ge=0, max_digits=30, decimal_places=8)
    target_weight: Decimal = Field(default=Decimal(0), ge=0, le=100, decimal_places=4)
    initial_price: Decimal | None = Field(default=None, gt=0, max_digits=30, decimal_places=8)
    buy_fee_rate: Decimal = Field(default=Decimal(0), ge=0, le=100, decimal_places=4)
    is_active: bool = True
    fetch_interval_minutes: int | None = Field(default=None, ge=1, le=10080)
    note: str = Field(default="", max_length=1000)
    extra: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    sources: list[PriceSourceIn] | None = None  # None: بدون تغییر در ویرایش
    # فیلدهای قدیمی نسخهٔ ۱ (برای سازگاری پذیرفته می‌شوند): اعشار مجاز را با decimals مشخص کنید و منبع قیمت را با sources.
    fractional_units: bool | None = None
    price_provider: str | None = Field(default=None, max_length=40)
    price_provider_params: dict | None = None
    portfolio_id: int | None = None  # فقط هنگام ایجاد: سبدی که دارایی به آن اضافه شود (پیش‌فرض: سبد اصلی)


class ConfirmIn(Strict):
    token: str
    phrase: str


class PortfolioIn(Strict):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    initial_capital: Decimal = Field(default=Decimal(0), ge=0, le=MAX, decimal_places=4)
    monthly_contribution: Decimal = Field(default=Decimal(0), ge=0, le=MAX, decimal_places=4)
    horizon_months: int = Field(default=12, ge=1, le=600)
    max_drawdown_pct: Decimal = Field(default=Decimal(25), gt=0, le=100)
    plan_start_date: date | None = None
    target_mode: Literal["percent", "amount"] = "percent"
    apply_to_past_unpaid: bool = False


class PortfolioMemberIn(Strict):
    asset_id: int
    target_weight: Decimal = Field(default=Decimal(0), ge=0, le=100, decimal_places=4)
    target_amount: Decimal = Field(default=Decimal(0), ge=0, le=MAX, decimal_places=4)
    is_active: bool = True


class PortfolioTargetsIn(Strict):
    members: list[PortfolioMemberIn]


class ProviderIn(Strict):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["tsetmc", "bitpin", "streamdata", "servix", "custom_api", "manual"]
    is_enabled: bool = False
    base_url: str = Field(default="", max_length=300)
    auth_type: Literal["none", "bearer", "header", "query"] = "none"
    auth_param_name: str = Field(default="", max_length=80)
    api_key: str | None = Field(default=None, max_length=500, repr=False)  # فقط نوشتنی؛ هرگز بازگردانده نمی‌شود
    clear_api_key: bool = False
    request_params: dict[str, str] = Field(default_factory=dict)
    field_map: dict[str, str] = Field(default_factory=dict)
    config: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    input_currency: str = Field(default="", max_length=16)
    market: Literal["tse", "24h", "none"] = "none"
    refresh_interval_minutes: int = Field(default=30, ge=1, le=10080)
    min_interval_seconds: Decimal = Field(default=Decimal(1), ge=0, le=3600)
    retry_count: int = Field(default=2, ge=0, le=5)
    retry_delay_seconds: Decimal = Field(default=Decimal(2), ge=0, le=60)
    timeout_seconds: Decimal = Field(default=Decimal(8), ge=1, le=60)
    auto_approve: bool = False


class SchedulerSettingsIn(Strict):
    scheduler_enabled: bool
    scheduler_default_interval_minutes: int = Field(ge=1, le=10080)
    scheduler_market_hours_only: bool


class TargetWeightsIn(Strict):
    weights: dict[int, Decimal]

    @field_validator("weights")
    @classmethod
    def check(cls, v):
        for k, w in v.items():
            if w < 0 or w > 100:
                raise ValueError("وزن هدف باید بین ۰ و ۱۰۰ باشد")
        return v


class TransactionIn(Strict):
    tx_date: date
    tx_type: TxType
    platform_id: int | None = None
    asset_id: int | None = None
    quantity: Decimal | None = Field(default=None, max_digits=30, decimal_places=8)
    unit_price: Decimal | None = Field(default=None, max_digits=30, decimal_places=8)
    fee: Decimal = Field(default=Decimal(0), ge=0, max_digits=30, decimal_places=4)
    amount: Decimal | None = Field(default=None, max_digits=30, decimal_places=4)
    fx_rate: Decimal | None = Field(default=None, gt=0, max_digits=30, decimal_places=8)
    plan_period_id: int | None = None
    portfolio_id: int | None = None
    note: str = Field(default="", max_length=1000)
    record_price: bool = False


class PriceIn(Strict):
    asset_id: int
    price: Decimal = Field(gt=0, max_digits=30, decimal_places=8)
    currency: str | None = Field(default=None, max_length=16)
    recorded_at: datetime | None = None
    source: str = Field(default="manual", min_length=1, max_length=120)
    is_approved: bool = True
    note: str = Field(default="", max_length=500)


class FxIn(Strict):
    currency: str = Field(max_length=16)
    rate: Decimal = Field(gt=0, max_digits=30, decimal_places=8)
    recorded_at: datetime | None = None
    source: str = Field(default="manual", min_length=1, max_length=120)
    is_approved: bool = True
    note: str = Field(default="", max_length=500)


class ContributionRecordIn(Strict):
    date: date
    amount: Decimal | None = Field(default=None, gt=0, max_digits=30, decimal_places=4)
    allocations: dict[int, Decimal] | None = None  # platform_id -> amount
    note: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def one_of(self):
        if self.amount is None and not self.allocations:
            raise ValueError("مبلغ یا تخصیص هر پلتفرم را وارد کنید")
        return self


class PlanPeriodPatch(Strict):
    planned_amount: Decimal | None = Field(default=None, ge=0, max_digits=30, decimal_places=4)
    due_date: date | None = None
    note: str | None = Field(default=None, max_length=500)


class ResetRequestIn(Strict):
    scope: Literal["data", "all"] = "data"


class ResetConfirmIn(Strict):
    token: str
    phrase: str
    scope: Literal["data", "all"] = "data"
