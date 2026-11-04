"""ساختارهای داده خالص برای محاسبات مالی (جدا از ORM)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

ZERO = Decimal("0")
HUNDRED = Decimal("100")
BASE_CURRENCY = "IRT"


@dataclass(frozen=True)
class TxRec:
    id: int
    date: date
    type: str
    platform_id: int
    asset_id: int | None
    quantity: Decimal | None
    unit_price: Decimal | None
    fee: Decimal
    total: Decimal
    fx_rate: Decimal | None = None
    plan_period_id: int | None = None


@dataclass(frozen=True)
class AssetRec:
    id: int
    platform_id: int
    name: str
    symbol: str
    type: str
    target_weight: Decimal
    price_currency: str = BASE_CURRENCY
    buy_fee_rate: Decimal = ZERO
    fractional: bool = False
    active: bool = True
    decimals: int = 0  # تعداد اعشار مجاز تعداد (۰ = عدد صحیح)
    min_quantity: Decimal = ZERO


@dataclass(frozen=True)
class PlatformRec:
    id: int
    name: str
    kind: str = "other"
    active: bool = True


@dataclass(frozen=True)
class PriceRec:
    id: int
    asset_id: int
    price: Decimal
    currency: str
    recorded_at: datetime
    approved: bool = True
    source: str = "manual"


@dataclass(frozen=True)
class FxRec:
    id: int
    currency: str
    rate: Decimal
    recorded_at: datetime
    approved: bool = True
    source: str = "manual"


@dataclass(frozen=True)
class PlanRec:
    id: int
    seq: int
    due_date: date
    planned: Decimal


@dataclass(frozen=True)
class Config:
    initial_capital: Decimal = Decimal("100000000")
    monthly_contribution: Decimal = Decimal("50000000")
    horizon_months: int = 12
    start_date: date = date(2026, 1, 1)
    max_drawdown_pct: Decimal = Decimal("25")
    concentration_limit_pct: Decimal = Decimal("35")
    deviation_warning_pp: Decimal = Decimal("5")
    max_price_age_days: int = 3
    calendar: str = "jalali"


@dataclass
class DataSet:
    config: Config
    platforms: list[PlatformRec] = field(default_factory=list)
    assets: list[AssetRec] = field(default_factory=list)
    txs: list[TxRec] = field(default_factory=list)
    prices: list[PriceRec] = field(default_factory=list)
    fx: list[FxRec] = field(default_factory=list)
    periods: list[PlanRec] = field(default_factory=list)

    def asset(self, asset_id: int) -> AssetRec | None:
        return next((a for a in self.assets if a.id == asset_id), None)

    def platform(self, platform_id: int) -> PlatformRec | None:
        return next((p for p in self.platforms if p.id == platform_id), None)
