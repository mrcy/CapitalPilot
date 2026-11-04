"""مدل‌های ورودی (Pydantic) با اعتبارسنجی."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TxType = Literal["buy", "sell", "deposit", "withdrawal", "dividend", "fee", "adjustment"]
AssetType = Literal["gold", "fund", "index", "digital", "cash", "other"]
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


class AssetIn(Strict):
    platform_id: int
    name: str = Field(min_length=1, max_length=120)
    symbol: str = Field(default="", max_length=40)
    asset_type: AssetType = "other"
    target_weight: Decimal = Field(default=Decimal(0), ge=0, le=100, decimal_places=4)
    price_currency: str = Field(default="IRT", max_length=16)
    buy_fee_rate: Decimal = Field(default=Decimal(0), ge=0, le=100, decimal_places=4)
    fractional_units: bool = False
    is_active: bool = True
    price_provider: str = Field(default="", max_length=40)
    price_provider_params: dict | None = None
    note: str = Field(default="", max_length=1000)


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
