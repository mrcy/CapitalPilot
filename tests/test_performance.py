from datetime import date, datetime
from decimal import Decimal as D

from app.services.finance.performance import build_series, drawdown_summary, monthly_performance, portfolio_xirr, xirr, period_stats
from app.services.finance.valuation import make_book, value_portfolio
from tests.helpers import asset, dataset, price, tx


def base_ds():
    txs = [tx("deposit", "2026-01-01", total=1_000_000), tx("buy", "2026-01-01", asset=1, qty=100, price=10_000)]
    prices = [price(1, 10_000, "2026-01-01"), price(1, 9_000, "2026-01-02"), price(1, 8_000, "2026-01-03"),
              price(1, 12_000, "2026-01-04")]
    return dataset(txs, prices, assets=[asset(1, "A", 100)])


def test_stale_price_not_used_as_current():
    ds = base_ds()
    val = value_portfolio(ds, datetime(2026, 1, 20, 12))
    assert not val.complete and val.unpriced[0].quote.reason == "stale"
    assert val.unpriced[0].quote.last_price == 12_000  # فقط اطلاع؛ ارزش‌گذاری نشده
    assert val.assets_value == 0
    val2 = value_portfolio(ds, datetime(2026, 1, 4, 20))
    assert val2.complete and val2.assets_value == D("1200000") and val2.unrealized == D("200000")


def test_unapproved_price_ignored():
    ds = base_ds()
    ds.prices.append(price(1, 99_999, "2026-01-04T13:00:00", approved=False))
    assert value_portfolio(ds, datetime(2026, 1, 4, 20)).assets_value == D("1200000")


def test_drawdown_ignores_deposits():
    ds = base_ds()
    # روز ۳ ارزش 800k؛ سپس واریز ۱ میلیون روز ۳ — نباید افت را پنهان کند
    ds.txs.append(tx("deposit", "2026-01-03", total=1_000_000))
    pts = build_series(ds, date(2026, 1, 4))
    dd = drawdown_summary(pts, date(2026, 1, 4), D(25))
    # شاخص: ۱۰۰ → ۹۰ (روز۲) → ۸۰ (روز ۳) ؛ روز ۴ ارزش دارایی ۱.۲M + نقد ۱M = 2.2M ؛ ۸۰ × (2.2M)/(0.8M+1M)... 
    d3 = next(p for p in pts if p.date == date(2026, 1, 3))
    assert round(d3.index, 6) == 80.0
    assert dd["max_drawdown_pct"] == 20.0
    # روز ۴: V=2.2M، قبل: V=1.8M ، جریان=0 → r=1.2222
    assert round(dd["current_index"], 2) == round(80 * 2.2 / 1.8, 2)
    assert dd["current_drawdown_pct"] == 2.2222


def test_pure_deposit_is_not_return():
    ds = dataset([tx("deposit", "2026-01-01", total=100), tx("deposit", "2026-02-01", total=900)], [], assets=[asset(1, "A", 100)])
    pts = build_series(ds, date(2026, 2, 1))
    assert [round(p.index, 6) for p in pts if p.index is not None] == [100.0, 100.0]


def test_incomplete_points_excluded():
    ds = base_ds()
    ds.txs.append(tx("deposit", "2026-02-20", total=10))
    pts = build_series(ds, date(2026, 2, 20))
    last = pts[-1]
    assert not last.complete and last.index is None


def test_xirr_known_value():
    r = xirr([(date(2026, 1, 1), -1000.0), (date(2027, 1, 1), 1100.0)])
    assert abs(r - 0.1) < 1e-6


def test_portfolio_xirr_messages():
    ds = dataset([], [], assets=[asset(1, "A", 100)])
    assert not portfolio_xirr(ds, D(0), True, date(2026, 5, 1))["available"]
    ds = base_ds()
    assert "۳۰ روز" in portfolio_xirr(ds, D(1_200_000), True, date(2026, 1, 20))["reason"]
    assert not portfolio_xirr(ds, D(1_200_000), False, date(2026, 6, 20))["available"]
    ds.txs.append(tx("withdrawal", "2026-03-01", total=100_000))
    res = portfolio_xirr(ds, D(1_200_000), True, date(2027, 1, 1))
    assert res["available"] and res["annual_pct"] > 0


def test_monthly_and_period_stats():
    ds = base_ds()
    pts = build_series(ds, date(2026, 1, 4))
    ms = monthly_performance(pts, "gregorian")
    assert len(ms) == 1 and ms[0]["return_pct"] == 20.0 and ms[0]["pnl"] == D("200000")
    ps = period_stats(pts, date(2026, 1, 1), date(2026, 1, 31))
    assert ps["pnl"] == D("200000") and ps["deposits"] == D("1000000")
