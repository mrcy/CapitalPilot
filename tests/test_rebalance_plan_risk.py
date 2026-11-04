from datetime import date, datetime
from decimal import Decimal as D

from app.services.finance.plan import generate_schedule, plan_status
from app.services.finance.rebalance import suggest_allocation
from app.services.finance.risk import build_alerts, drawdown_status, asset_risk_contributions
from app.services.finance.types import Config, PlanRec
from app.services.finance.performance import build_series, drawdown_summary
from app.services.finance.valuation import make_book, value_portfolio
from tests.helpers import asset, dataset, price, tx


def ds_two(a_units, b_units, pa=100, pb=100):
    txs = [tx("deposit", "2026-01-01", total=10**9), tx("buy", "2026-01-01", asset=1, qty=a_units, price=pa),
           tx("buy", "2026-01-01", asset=2, qty=b_units, price=pb)]
    prices = [price(1, pa, "2026-01-02"), price(2, pb, "2026-01-02")]
    return dataset(txs, prices, assets=[asset(1, "A", 50), asset(2, "B", 50)])


NOW = datetime(2026, 1, 2, 20)


def test_rebalance_prioritises_underweight_and_never_sells():
    ds = ds_two(300, 100)  # A=30000 (75%), B=10000 (25%)
    val = value_portfolio(ds, NOW)
    r = suggest_allocation(ds, val, D(20000))
    rows = {x["asset_id"]: x for x in r["rows"]}
    # مجموع بعد 60000 → هدف هر کدام 30000 ؛ A به هدف رسیده، B نیاز 20000
    assert rows[1]["units"] == 0 and rows[1]["status"] == "above_target"
    assert rows[2]["units"] == 200 and rows[2]["total_cost"] == D(20000)
    assert r["sells"] == []
    assert r["leftover"] == 0


def test_rebalance_scaled_when_money_insufficient_and_integer_units_with_fee():
    ds = ds_two(300, 100)
    ds.assets[1] = asset(2, "B", 50, fee_rate="1")  # کارمزد ۱٪
    val = value_portfolio(ds, NOW)
    r = suggest_allocation(ds, val, D(10000))
    rb = next(x for x in r["rows"] if x["asset_id"] == 2)
    # هزینه هر واحد 101 → 99 واحد = 9999
    assert rb["units"] == 99 and rb["fee"] == D("99")
    assert r["total_spend"] == D(9999) + D(0)
    assert r["total_spend"] <= 10000
    assert all(x["units"] == int(x["units"]) for x in r["rows"])
    assert r["extra_to_reach_target_without_selling"] == D(20000)


def test_rebalance_initial_split_matches_target():
    ds = dataset([], [price(1, 1000, "2026-01-02"), price(2, 2000, "2026-01-02")])
    val = value_portfolio(ds, NOW)
    r = suggest_allocation(ds, val, D("100000000"))
    ra = {x["asset_id"]: x for x in r["rows"]}
    assert ra[1]["ideal_amount"] == D("50000000") and ra[1]["units"] == 50000 and ra[2]["units"] == 25000


def test_rebalance_unavailable_when_held_asset_has_no_price():
    ds = ds_two(10, 10)
    ds.prices.clear()
    r = suggest_allocation(ds, value_portfolio(ds, NOW), D(1000))
    assert not r["available"]


def test_plan_schedule_and_status():
    cfg = Config(initial_capital=D(100), monthly_contribution=D(50), horizon_months=3, start_date=date(2026, 1, 15), calendar="gregorian")
    sch = generate_schedule(cfg)
    assert [s[1] for s in sch] == [date(2026, 1, 15), date(2026, 2, 15), date(2026, 3, 15), date(2026, 4, 15)]
    ds = dataset([tx("deposit", "2026-01-15", total=100, period=10), tx("deposit", "2026-02-16", total=30, period=11),
                  tx("deposit", "2026-02-20", total=5)], cfg=cfg)
    ds.periods = [PlanRec(10 + i, s[0], s[1], s[2]) for i, s in enumerate(sch)]
    st = plan_status(ds, date(2026, 3, 20))
    by = {p["seq"]: p for p in st["periods"]}
    assert by[0]["status"] == "paid" and by[1]["status"] == "partial_overdue" and by[2]["status"] == "overdue"
    assert by[3]["status"] == "upcoming"
    assert st["arrears"] == D(20) + D(50) and st["unlinked_deposits"] == D(5)
    assert st["target_total"] == D(250) and st["total_deposits"] == D(135)
    assert round(st["realization_pct"], 2) == 54.0


def test_drawdown_status_levels_and_alerts():
    ds = ds_two(100, 100)
    ds.prices += [price(1, 50, "2026-01-03"), price(2, 50, "2026-01-03")]
    pts = build_series(ds, date(2026, 1, 3))
    dd = drawdown_summary(pts, date(2026, 1, 3), D(25))
    # ارزش از 20000 + نقد (1e9 - 20000)  → افت کوچک نسبت به کل (نقد)
    assert dd["available"] and dd["current_drawdown_pct"] < 1
    ds2 = dataset([tx("deposit", "2026-01-01", total=1000), tx("buy", "2026-01-01", asset=1, qty=10, price=100)],
                  [price(1, 100, "2026-01-01"), price(1, 70, "2026-01-02")], assets=[asset(1, "A", 100)])
    d2 = drawdown_summary(build_series(ds2, date(2026, 1, 2)), date(2026, 1, 2), D(25))
    assert d2["current_drawdown_pct"] == 30.0
    st = drawdown_status(d2, D(25))
    assert st["level"] == "critical"
    for pct, level in [(5, "ok"), (13, "watch"), (16, "warning"), (21, "serious"), (26, "critical")]:
        assert drawdown_status({"available": True, "current_drawdown_pct": pct}, D(25))["level"] == level


def test_concentration_and_deviation_alerts():
    ds = ds_two(900, 100)
    val = value_portfolio(ds, NOW)
    al = build_alerts(ds, val, {}, {"level": "ok"})
    codes = {a["code"] for a in al}
    assert {"concentration", "deviation"} <= codes
