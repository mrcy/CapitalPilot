from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


class ProviderError(Exception):
    pass


@dataclass
class ProviderQuote:
    price: Decimal
    currency: str
    recorded_at: datetime | None = None


class PriceProvider(ABC):
    name = ""
    label = ""
    param_help: dict[str, str] = {}

    @abstractmethod
    def fetch(self, params: dict) -> ProviderQuote:
        """دریافت قیمت؛ در صورت هر مشکل ProviderError با پیام فارسی برمی‌گرداند."""
