from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal as D
from itertools import count

from app.services.finance.types import AssetRec, Config, DataSet, PlatformRec, PriceRec, TxRec

_ids = count(1)


def tx(type_, d, platform=1, asset=None, qty=None, price=None, fee="0", total=None, fx=None, period=None, id=None):
    qty = None if qty is None else D(str(qty))
    price = None if price is None else D(str(price))
    fee = D(str(fee))
    if total is None:
        if type_ == "buy":
            total = qty * price + fee
        elif type_ == "sell":
            total = qty * price - fee
        elif type_ == "adjustment" and asset:
            total = qty * (price or D(0))
        else:
            raise ValueError("total required")
    return TxRec(id or next(_ids), d if isinstance(d, date) else date.fromisoformat(d), type_, platform, asset, qty, price, fee,
                 D(str(total)), None if fx is None else D(str(fx)), period)


def price(asset, p, when, currency="IRT", approved=True):
    return PriceRec(next(_ids), asset, D(str(p)), currency,
                    datetime.fromisoformat(when) if "T" in when or " " in when else datetime.fromisoformat(when + "T12:00:00"),
                    approved)


def asset(id_, name, weight, platform=1, type_="fund", currency="IRT", fee_rate="0", fractional=False, active=True):
    return AssetRec(id_, platform, name, name, type_, D(str(weight)), currency, D(str(fee_rate)), fractional, active)


def dataset(txs=(), prices=(), assets=None, cfg=None, fx=()):
    assets = assets if assets is not None else [asset(1, "A", 50), asset(2, "B", 50)]
    return DataSet(cfg or Config(start_date=date(2026, 1, 1), max_price_age_days=3), [PlatformRec(1, "P1")], list(assets),
                   list(txs), list(prices), list(fx), [])
