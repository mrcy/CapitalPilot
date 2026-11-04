"""ترکیب محاسبات مالی برای داشبورد، سبد، دارایی‌ها و مرکز ریسک (فقط خواندنی)."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from .finance import ledger as lg
from .finance.performance import (
    build_series, drawdown_summary, monthly_performance, portfolio_xirr,
)
from .finance.plan import plan_status
from .finance.risk import DISCLAIMER, asset_risk_contributions, build_alerts, drawdown_status
from .finance.types import HUNDRED, ZERO, DataSet
from .finance.valuation import (
    AssetValuation, PortfolioValuation, make_book, value_portfolio,
)


def _q(v: AssetValuation) -> dict:
    q = v.quote
    return {
        "ok": q.ok, "price": q.price_irt, "native_price": q.native_price, "currency": q.currency, "fx_rate": q.fx_rate,
        "recorded_at": q.recorded_at, "age_days": q.age_days, "reason": q.reason, "reason_text": q.reason_text,
        "last_price": q.last_price, "last_recorded_at": q.last_recorded_at,
    }


def asset_rows(ds: DataSet, val: PortfolioValuation) -> list[dict]:
    plat = {p.id: p.name for p in ds.platforms}
    invested = val.assets_value
    rows = []
    for v in val.assets:
        a, p = v.asset, v.pos
        w = (v.value / invested * HUNDRED) if (v.value is not None and invested > 0 and val.complete) else (
            ZERO if (v.value == 0 and invested > 0 and val.complete) else None)
        rows.append({
            "id": a.id, "name": a.name, "symbol": a.symbol, "asset_type": a.type, "platform_id": a.platform_id,
            "platform": plat.get(a.platform_id, ""), "active": a.active, "price_currency": a.price_currency,
            "units": p.units, "avg_cost": p.avg_cost, "cost_basis": p.cost, "total_bought": p.bought_cost,
            "quote": _q(v), "value": v.value, "unrealized": v.unrealized, "unrealized_pct": v.unrealized_pct,
            "realized": p.realized, "dividends": p.dividends, "fees": p.fees, "adjustments": p.adjustments,
            "total_pnl": v.total_pnl, "return_pct": v.return_pct,
            "weight": w, "target_weight": a.target_weight,
            "deviation_pp": (w - a.target_weight) if w is not None and a.active else None,
            "buy_fee_rate": a.buy_fee_rate, "fractional_units": a.fractional,
        })
    return rows


def totals(val: PortfolioValuation) -> dict:
    s = val.state
    unreal = val.unrealized
    realized_total = s.realized_sales + s.dividends - s.total_fees + s.cash_adjustments
    total_pnl = realized_total + s.asset_adjustments + unreal
    return {
        "deposits": s.deposits, "withdrawals": s.withdrawals, "net_invested": s.deposits - s.withdrawals,
        "cash": val.cash, "assets_value": val.assets_value, "total_value": val.total_value, "cost_basis": val.cost_basis,
        "realized_total": realized_total, "realized_sales": s.realized_sales, "dividends": s.dividends,
        "fees": s.total_fees, "cash_adjustments": s.cash_adjustments, "asset_adjustments": s.asset_adjustments,
        "unrealized": unreal, "total_pnl": total_pnl,
    }


def total_return(t: dict, complete: bool) -> dict:
    if t["deposits"] <= 0:
        return {"available": False, "reason": "هنوز واریزی ثبت نشده است؛ بازدهی قابل محاسبه نیست."}
    if not complete:
        return {"available": False, "reason": "برای برخی دارایی‌ها قیمت معتبر ثبت نشده است؛ بازدهی کل محاسبه نشد."}
    return {"available": True, "pct": t["total_pnl"] / t["deposits"] * HUNDRED, "pnl": t["total_pnl"]}


def cash_by_platform(ds: DataSet, val: PortfolioValuation) -> list[dict]:
    s = val.state
    return [{"platform_id": p.id, "platform": p.name, "cash": s.cash.get(p.id, ZERO),
             "deposits": s.deposits_by_platform.get(p.id, ZERO), "withdrawals": s.withdrawals_by_platform.get(p.id, ZERO)}
            for p in ds.platforms]


def platform_rows(ds: DataSet, val: PortfolioValuation) -> list[dict]:
    """عملکرد هر پلتفرم: بازپخش جداگانه تراکنش‌های همان پلتفرم."""
    book = make_book(ds)
    out = []
    for p in ds.platforms:
        sub = [t for t in ds.txs if t.platform_id == p.id and t.date <= val.as_of.date()]
        st = lg.replay(sub)
        assets = [a for a in ds.assets if a.platform_id == p.id]
        from .finance.valuation import value_asset
        from .finance.ledger import Position
        vals = [value_asset(a, st.positions.get(a.id, Position(a.id)), book.quote(a, val.as_of)) for a in assets]
        complete = all(v.value is not None for v in vals)
        av = sum((v.value for v in vals if v.value is not None), ZERO)
        unreal = sum((v.unrealized for v in vals if v.unrealized is not None), ZERO)
        realized = st.realized_sales + st.dividends - st.total_fees + st.cash_adjustments
        pnl = realized + st.asset_adjustments + unreal
        tw = sum((a.target_weight for a in assets if a.active), ZERO)
        cur_w = (av / val.assets_value * HUNDRED) if (val.assets_value > 0 and val.complete) else None
        out.append({
            "platform_id": p.id, "platform": p.name, "assets_value": av, "cash": st.total_cash,
            "total_value": av + st.total_cash, "cost_basis": sum((v.pos.cost for v in vals), ZERO),
            "deposits": st.deposits, "withdrawals": st.withdrawals, "realized": realized, "unrealized": unreal,
            "total_pnl": pnl if complete else None,
            "return_pct": (pnl / st.deposits * HUNDRED) if (complete and st.deposits > 0) else None,
            "weight": cur_w, "target_weight": tw, "complete": complete,
            "deviation_pp": (cur_w - tw) if cur_w is not None else None,
        })
    return out


def type_allocation(rows: list[dict]) -> list[dict]:
    agg: dict[str, Decimal] = {}
    for r in rows:
        if r["value"]:
            agg[r["asset_type"]] = agg.get(r["asset_type"], ZERO) + r["value"]
    tot = sum(agg.values(), ZERO)
    return [{"type": k, "value": v, "weight": v / tot * HUNDRED if tot else ZERO} for k, v in agg.items()]


def fx_overview(rows: list[dict], val: PortfolioValuation) -> list[dict]:
    out = []
    for v in val.assets:
        if v.fx_effect is not None:
            out.append({"asset_id": v.asset.id, "name": v.asset.name, **v.fx_effect})
    return out


def risk_overview(ds: DataSet, now: datetime, val: PortfolioValuation | None = None, points=None) -> dict:
    cfg = ds.config
    book = make_book(ds)
    val = val or value_portfolio(ds, now, book)
    points = points if points is not None else build_series(ds, now.date(), book)
    dd = drawdown_summary(points, now.date(), cfg.max_drawdown_pct)
    st = drawdown_status(dd, cfg.max_drawdown_pct)
    alerts = build_alerts(ds, val, dd, st)
    contrib = asset_risk_contributions(ds, val, points, book)
    rows = asset_rows(ds, val)
    return {
        "drawdown": {k: v for k, v in dd.items() if k != "series"}, "status": st, "alerts": alerts,
        "contributions": contrib, "disclaimer": DISCLAIMER, "max_drawdown_limit": cfg.max_drawdown_pct,
        "concentration_limit": cfg.concentration_limit_pct,
        "exposure": [{"asset_id": r["id"], "name": r["name"], "asset_type": r["asset_type"], "value": r["value"],
                      "weight": r["weight"], "target_weight": r["target_weight"], "deviation_pp": r["deviation_pp"]}
                     for r in rows if r["value"]],
        "series": dd["series"],
    }


def dashboard(ds: DataSet, now: datetime) -> dict:
    cfg = ds.config
    book = make_book(ds)
    val = value_portfolio(ds, now, book)
    points = build_series(ds, now.date(), book)
    t = totals(val)
    ret = total_return(t, val.complete)
    xr = portfolio_xirr(ds, val.total_value, val.complete, now.date())
    plan = plan_status(ds, now.date())
    rows = asset_rows(ds, val)
    risk = risk_overview(ds, now, val, points)
    dd_full = drawdown_summary(points, now.date(), cfg.max_drawdown_pct)
    warnings = []
    if val.unpriced:
        warnings.append("قیمت معتبر امروز برای این دارایی‌ها ثبت نشده و در ارزش کل لحاظ نشده است: "
                        + "، ".join(r.asset.name for r in val.unpriced))
    return {
        "as_of": now,
        "has_data": bool(ds.txs),
        "valuation_complete": val.complete,
        "warnings": warnings,
        "cards": {
            **t,
            "total_return": ret, "xirr": xr,
            "plan_realization_pct": plan["realization_pct"], "plan_target_total": plan["target_total"],
            "gap_to_target": plan["gap_to_target"],
            "gap_to_target_value": plan["target_total"] - val.total_value,
        },
        "cash_by_platform": cash_by_platform(ds, val),
        "charts": {
            "growth": [{"date": p["date"], "value": p["value"], "complete": p["complete"]} for p in dd_full["series"]],
            "capital_vs_value": [{"date": p["date"], "net_invested": p["net_invested"], "deposits": p["deposits_cum"],
                                  "value": p["value"] if p["complete"] else None} for p in dd_full["series"]],
            "allocation": [{"name": r["name"], "value": r["value"], "weight": r["weight"], "asset_type": r["asset_type"]}
                           for r in rows if r["value"]] + ([{"name": "نقدینگی", "value": val.cash, "weight": None, "asset_type": "cash"}] if val.cash > 0 else []),
            "asset_returns": [{"name": r["name"], "return_pct": r["return_pct"], "pnl": r["total_pnl"], "asset_type": r["asset_type"]}
                              for r in rows if r["return_pct"] is not None],
            "monthly": monthly_performance(points, cfg.calendar),
            "drawdown": [{"date": p["date"], "drawdown_pct": p["drawdown_pct"]} for p in dd_full["series"] if p["drawdown_pct"] is not None],
        },
        "risk": {"status": risk["status"], "drawdown": risk["drawdown"], "alerts": risk["alerts"][:4], "disclaimer": DISCLAIMER},
        "plan": {k: plan[k] for k in ("arrears", "surplus", "unpaid_count", "realization_to_date_pct", "planned_due_to_date")},
    }


def portfolio(ds: DataSet, now: datetime) -> dict:
    book = make_book(ds)
    val = value_portfolio(ds, now, book)
    rows = asset_rows(ds, val)
    t = totals(val)
    return {
        "as_of": now, "valuation_complete": val.complete, "totals": t,
        "total_return": total_return(t, val.complete),
        "assets": rows, "platforms": platform_rows(ds, val), "types": type_allocation(rows),
        "cash_by_platform": cash_by_platform(ds, val), "fx": fx_overview(rows, val),
        "target_sum": sum((a.target_weight for a in ds.assets if a.active), ZERO),
        "warnings": ([("قیمت معتبر امروز ثبت نشده: " + "، ".join(r.asset.name for r in val.unpriced))] if val.unpriced else []),
        "emergency_fund_note": "ذخیره اضطراری جدا از این سبد است و در هیچ‌یک از محاسبات لحاظ نمی‌شود.",
    }
