from datetime import date
from decimal import Decimal as D

import pytest

from app.services.finance.ledger import LedgerError, replay
from tests.helpers import tx


def test_weighted_average_with_fees_and_sale():
    txs = [
        tx("deposit", "2026-01-01", total=1_000_000),
        tx("buy", "2026-01-02", asset=1, qty=10, price=10_000, fee=500),      # cost 100,500
        tx("buy", "2026-01-03", asset=1, qty=10, price=12_000, fee=700),      # cost 120,700
        tx("sell", "2026-01-04", asset=1, qty=5, price=15_000, fee=300),      # proceeds 74,700
    ]
    s = replay(txs)
    p = s.positions[1]
    # میانگین = 221,200 / 20 = 11,060
    assert p.avg_cost == D("11060")
    assert p.units == 15
    assert p.cost == D("221200") - D("11060") * 5
    assert p.realized == D("74700") - D("55300")
    assert p.bought_cost == D("221200")
    # نقدینگی = 1,000,000 − 221,200 + 74,700
    assert s.total_cash == D("853500")


def test_full_sale_leaves_zero_cost_and_exact_realized():
    txs = [tx("deposit", "2026-01-01", total=100), tx("buy", "2026-01-01", asset=1, qty=3, price=D("10.3333")),
           tx("sell", "2026-01-02", asset=1, qty=3, price=11)]
    p = replay(txs).positions[1]
    assert p.units == 0 and p.cost == 0
    assert p.realized == D("33") - D("30.9999")


def test_sell_more_than_held_raises():
    txs = [tx("buy", "2026-01-01", asset=1, qty=2, price=10), tx("sell", "2026-01-02", asset=1, qty=3, price=10)]
    with pytest.raises(LedgerError):
        replay(txs)


def test_same_day_sell_after_buy_is_ordered_by_type_priority():
    txs = [tx("sell", "2026-01-02", asset=1, qty=1, price=12, id=1), tx("buy", "2026-01-02", asset=1, qty=1, price=10, id=2)]
    assert replay(txs).positions[1].realized == 2


def test_deposit_withdrawal_are_not_profit():
    txs = [tx("deposit", "2026-01-01", total=500), tx("withdrawal", "2026-01-05", total=200)]
    s = replay(txs)
    assert s.deposits == 500 and s.withdrawals == 200 and s.total_cash == 300
    assert s.realized_sales == 0


def test_dividend_fee_and_adjustments():
    txs = [
        tx("deposit", "2026-01-01", total=10_000),
        tx("buy", "2026-01-01", asset=1, qty=10, price=100),
        tx("dividend", "2026-01-02", asset=1, total=50),
        tx("fee", "2026-01-02", total=20),
        tx("adjustment", "2026-01-03", asset=1, qty=2, price=90),     # +2 unit, cost 180
        tx("adjustment", "2026-01-04", asset=1, qty=-1),              # -1 at avg
        tx("adjustment", "2026-01-04", total=-5),                    # cash adj
    ]
    s = replay(txs)
    p = s.positions[1]
    assert p.dividends == 50 and s.standalone_fees == 20
    assert p.units == 11
    assert p.cost == D("1180") - D("1180") / 12
    assert p.adjustments == D("180") - D("1180") / 12
    assert s.cash_adjustments == -5
    assert s.total_cash == D("10000") - 1000 + 50 - 20 - 5


def test_foreign_cost_tracking_and_incomplete_fx():
    txs = [tx("buy", "2026-01-01", asset=1, qty=10, price=100, fx=50), tx("buy", "2026-01-02", asset=1, qty=10, price=100)]
    p = replay(txs[:1]).positions[1]
    assert p.foreign_cost == D("20")
    assert replay(txs).positions[1].foreign_cost is None
