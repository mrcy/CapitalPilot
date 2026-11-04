"""مرکز مدیریت ریسک: افت سرمایه، تمرکز، انحراف از ترکیب هدف و سهم دارایی‌ها در ریسک."""
from __future__ import annotations

import math
from decimal import Decimal

from .performance import Point
from .types import HUNDRED, ZERO, DataSet
from .valuation import PortfolioValuation, PriceBook, end_of_day

DISCLAIMER = ("هشدار افت ۲۵٪ (یا سقف تعیین‌شده) فقط یک ابزار پایش است و تضمین نمی‌کند "
              "که افت سرمایه از آن مقدار بیشتر نشود.")


def drawdown_levels(max_dd: Decimal) -> dict:
    return {
        "watch": float(max_dd) * 0.48,    # ~۱۲٪: نزدیک شدن به سطح هشدار
        "warning": float(max_dd) * 0.60,  # ۱۵٪
        "serious": float(max_dd) * 0.80,  # ۲۰٪
        "critical": float(max_dd),        # ۲۵٪
    }


def _fmt(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".")


def drawdown_status(dd: dict, max_dd: Decimal) -> dict:
    lv = drawdown_levels(max_dd)
    if not dd.get("available"):
        return {"level": "unknown", "levels": lv, "message": dd.get("reason", "")}
    cur = dd["current_drawdown_pct"]
    if cur >= lv["critical"]:
        level, msg = "critical", f"وضعیت بحرانی: افت سبد به {_fmt(cur)}٪ رسیده و از سقف تحمل ({_fmt(lv['critical'])}٪) عبور کرده است."
    elif cur >= lv["serious"]:
        level, msg = "serious", f"هشدار جدی: افت سبد {_fmt(cur)}٪ است (آستانه {_fmt(lv['serious'])}٪)."
    elif cur >= lv["warning"]:
        level, msg = "warning", f"هشدار: افت سبد {_fmt(cur)}٪ است و از آستانه {_fmt(lv['warning'])}٪ عبور کرده است."
    elif cur >= lv["watch"]:
        level, msg = "watch", f"توجه: افت سبد {_fmt(cur)}٪ است و به آستانه هشدار {_fmt(lv['warning'])}٪ نزدیک می‌شود."
    else:
        level, msg = "ok", f"افت فعلی سبد {_fmt(cur)}٪ است و در محدوده عادی قرار دارد."
    return {"level": level, "levels": lv, "message": msg}


def asset_risk_contributions(ds: DataSet, val: PortfolioValuation, points: list[Point], book: PriceBook,
                             min_obs: int = 8) -> dict:
    """سهم هر دارایی در ریسک کل (روش کوواریانس: w_i·(Σw)_i / σ²)."""
    held = [r for r in val.assets if r.value and r.value > 0]
    if not held:
        return {"available": False, "reason": "دارایی دارای ارزش در سبد وجود ندارد.", "rows": []}
    total = sum((r.value for r in held), ZERO)
    exposure = {r.asset.id: float(r.value / total) for r in held}
    rows = [{"asset_id": r.asset.id, "name": r.asset.name, "weight_pct": exposure[r.asset.id] * 100} for r in held]
    dates = [p.date for p in points if p.index is not None]
    prices: dict[int, list[float]] = {r.asset.id: [] for r in held}
    used = []
    for d in dates:
        qs = {r.asset.id: book.quote(r.asset, end_of_day(d)) for r in held}
        if all(q.ok for q in qs.values()):
            used.append(d)
            for aid, q in qs.items():
                prices[aid].append(float(q.price_irt))
    if len(used) < min_obs + 1:
        return {"available": False, "rows": rows,
                "reason": f"برای محاسبه سهم آماری هر دارایی در ریسک حداقل {min_obs + 1} نقطه قیمت هم‌زمان لازم است "
                          f"(اکنون {len(used)}). تا آن زمان فقط سهم وزنی نمایش داده می‌شود."}
    ids = list(prices)
    rets = {i: [prices[i][k] / prices[i][k - 1] - 1 for k in range(1, len(used))] for i in ids}
    n = len(used) - 1
    mean = {i: sum(rets[i]) / n for i in ids}

    def cov(i, j):
        return sum((rets[i][k] - mean[i]) * (rets[j][k] - mean[j]) for k in range(n)) / (n - 1)

    w = exposure
    mcr = {i: sum(w[j] * cov(i, j) for j in ids) for i in ids}
    var_p = sum(w[i] * mcr[i] for i in ids)
    if var_p <= 0:
        return {"available": False, "rows": rows, "reason": "نوسان قیمت‌های ثبت‌شده صفر است؛ سهم ریسک قابل محاسبه نیست."}
    for r in rows:
        i = r["asset_id"]
        r["risk_share_pct"] = w[i] * mcr[i] / var_p * 100
        r["volatility_pct"] = math.sqrt(max(cov(i, i), 0)) * 100
    return {"available": True, "rows": rows, "observations": n, "portfolio_volatility_pct": math.sqrt(var_p) * 100,
            "note": "نوسان بر اساس فاصله‌های ثبت قیمت (نه سالانه) است و به تعداد/فاصله قیمت‌های ثبت‌شده حساسیت دارد."}


def build_alerts(ds: DataSet, val: PortfolioValuation, dd: dict, dd_status: dict) -> list[dict]:
    cfg = ds.config
    alerts: list[dict] = []
    if dd_status["level"] in ("watch", "warning", "serious", "critical"):
        alerts.append({"level": dd_status["level"], "code": "drawdown", "title": "افت سرمایه", "message": dd_status["message"]})
    if val.unpriced:
        names = "، ".join(r.asset.name for r in val.unpriced)
        alerts.append({"level": "warning", "code": "stale_prices", "title": "قیمت نامعتبر",
                       "message": f"برای این دارایی‌ها قیمت معتبر امروز وجود ندارد: {names}. ارزش آن‌ها در جمع سبد لحاظ نشده است."})
    if any(v < 0 for v in val.state.cash.values()):
        alerts.append({"level": "warning", "code": "negative_cash", "title": "نقدینگی منفی",
                       "message": "نقدینگی یک یا چند پلتفرم منفی است؛ احتمالاً واریزی ثبت نشده یا تراکنشی اشتباه است."})
    if val.assets_value > 0:
        for r in val.assets:
            if r.value is None or r.value <= 0:
                continue
            w = r.value / val.assets_value * HUNDRED
            if w > cfg.concentration_limit_pct:
                alerts.append({"level": "serious", "code": "concentration", "title": "تمرکز بیش از حد",
                               "message": f"«{r.asset.name}» {w:.1f}٪ سبد است (سقف تمرکز {cfg.concentration_limit_pct.normalize():f}٪)."})
            if r.asset.active:
                dev = w - r.asset.target_weight
                if abs(dev) >= cfg.deviation_warning_pp * 2:
                    alerts.append({"level": "serious", "code": "deviation", "title": "انحراف شدید از ترکیب هدف",
                                   "message": f"وزن «{r.asset.name}» {w:.1f}٪ و هدف {r.asset.target_weight.normalize():f}٪ است ({dev:+.1f} واحد درصد)."})
                elif abs(dev) >= cfg.deviation_warning_pp:
                    alerts.append({"level": "watch", "code": "deviation", "title": "انحراف از ترکیب هدف",
                                   "message": f"وزن «{r.asset.name}» {w:.1f}٪ و هدف {r.asset.target_weight.normalize():f}٪ است ({dev:+.1f} واحد درصد)."})
    order = {"critical": 0, "serious": 1, "warning": 2, "watch": 3, "info": 4}
    alerts.sort(key=lambda a: order.get(a["level"], 9))
    return alerts
