"""گزارش‌های مالی. هر گزارش ساختار یکسان دارد تا خروجی CSV/Excel/PDF و نمایش وب از یک منبع تولید شوند.

ساختار: {key, title, subtitle, columns:[{key,label,type}], rows:[{...}], summary:[{label,value,type}], notes:[]}
انواع ستون: text | date | money | number | units | percent
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from ..errors import ValidationFailure
from .calendar_utils import current_year_month, fmt_date, month_label, month_key, period_bounds
from .finance import ledger as lg
from .finance.performance import build_series, drawdown_summary, period_stats
from .finance.plan import plan_status
from .finance.risk import DISCLAIMER, drawdown_status
from .finance.types import HUNDRED, ZERO, DataSet
from .finance.valuation import end_of_day, make_book, value_portfolio
from .summary import platform_rows, asset_rows, totals

REPORTS = [
    ("daily", "گزارش روزانه", ["date"]),
    ("monthly", "گزارش ماهانه", ["year", "month"]),
    ("quarterly", "گزارش فصلی", ["year", "quarter"]),
    ("yearly", "گزارش سالانه", ["year"]),
    ("full_period", "گزارش کل دوره سرمایه‌گذاری", []),
    ("asset_pnl", "گزارش سود و زیان هر دارایی", []),
    ("deposits", "گزارش واریزی‌ها", ["date_from", "date_to"]),
    ("withdrawals", "گزارش برداشت‌ها", ["date_from", "date_to"]),
    ("platforms", "گزارش عملکرد هر پلتفرم", []),
    ("target_comparison", "گزارش مقایسه با ترکیب هدف", []),
    ("risk", "گزارش ریسک و افت سرمایه", []),
]
TITLES = {k: t for k, t, _ in REPORTS}


def catalog() -> list[dict]:
    return [{"key": k, "title": t, "params": p} for k, t, p in REPORTS]


def col(key, label, type_="text"):
    return {"key": key, "label": label, "type": type_}


def S(label, value, type_="money"):
    return {"label": label, "value": value, "type": type_}


def _na(label, reason):
    return {"label": label, "value": None, "type": "text", "note": reason}


def _period_report(ds: DataSet, now: datetime, key: str, start: date, end: date, title: str) -> dict:
    cfg = ds.config
    end_eff = min(end, now.date())
    book = make_book(ds)
    notes = []
    if start > now.date():
        raise ValidationFailure("این بازه هنوز آغاز نشده است.")
    if end > now.date():
        notes.append("بازه هنوز تمام نشده است؛ گزارش تا امروز محاسبه شد.")
    pts = build_series(ds, end_eff, book)
    ps = period_stats(pts, start, end_eff)
    as_of = end_of_day(end_eff) if end_eff < now.date() else now
    val = value_portfolio(ds, as_of, book)
    before = lg.replay(ds.txs, upto=start - timedelta(days=1)) if start > date.min else lg.LedgerState()
    cols = [col("asset", "دارایی"), col("platform", "پلتفرم"), col("units", "تعداد واحد", "units"),
            col("price", "قیمت پایان دوره", "money"), col("value", "ارزش پایان دوره", "money"),
            col("cost", "بهای تمام‌شده", "money"), col("unrealized", "سود/زیان تحقق‌نیافته", "money"),
            col("realized", "سود/زیان تحقق‌یافته در دوره", "money"), col("dividends", "سود نقدی در دوره", "money")]
    plat = {p.id: p.name for p in ds.platforms}
    rows = []
    for v in val.assets:
        b = before.positions.get(v.asset.id)
        rows.append({
            "asset": v.asset.name, "platform": plat.get(v.asset.platform_id, ""), "units": v.pos.units,
            "price": v.quote.price_irt if v.quote.ok else None, "value": v.value, "cost": v.pos.cost,
            "unrealized": v.unrealized, "realized": v.pos.realized - (b.realized if b else ZERO),
            "dividends": v.pos.dividends - (b.dividends if b else ZERO),
        })
    in_period = [t for t in ds.txs if start <= t.date <= end_eff]
    fees = sum((t.total if t.type == "fee" else (t.fee if t.type in ("buy", "sell") else ZERO) for t in in_period), ZERO)
    summary = [S("تاریخ شروع", start, "date"), S("تاریخ پایان", end_eff, "date")]
    if ps["available"]:
        summary += [S("ارزش ابتدای بازه", ps["opening_value"]), S("واریزی‌های بازه", ps["deposits"]),
                    S("برداشت‌های بازه", ps["withdrawals"]), S("ارزش پایان بازه", ps["closing_value"]),
                    S("سود/زیان بازه (بدون احتساب واریزی/برداشت)", ps["pnl"]),
                    S("بازده زمانی بازه (TWR)", ps["return_pct"], "percent")]
    else:
        summary += [_na("نتیجه بازه", ps["reason"])]
    summary += [S("کل کارمزدهای بازه", fees)]
    if not val.complete:
        notes.append("برای برخی دارایی‌ها قیمت معتبر در پایان بازه وجود ندارد؛ ارزش آن‌ها محاسبه نشد: "
                     + "، ".join(r.asset.name for r in val.unpriced))
    return {"key": key, "title": title, "subtitle": f"{fmt_date(start, cfg.calendar)} تا {fmt_date(end_eff, cfg.calendar)}",
            "columns": cols, "rows": rows, "summary": summary, "notes": notes}


def build_report(ds: DataSet, key: str, params: dict, now: datetime) -> dict:
    cfg = ds.config
    cal = cfg.calendar
    today = now.date()
    if key == "daily":
        d = params.get("date") or today
        return _period_report(ds, now, key, d, d, f"گزارش روزانه — {fmt_date(d, cal)}")
    if key in ("monthly", "quarterly", "yearly"):
        cy, cm = current_year_month(today, cal)
        year = int(params.get("year") or cy)
        kind = {"monthly": "month", "quarterly": "quarter", "yearly": "year"}[key]
        idx = int(params.get("month") or params.get("quarter") or (cm if kind == "month" else (cm - 1) // 3 + 1)) if kind != "year" else 1
        try:
            s, e, label = period_bounds(kind, year, idx, cal)
        except (ValueError, TypeError) as ex:
            raise ValidationFailure(f"بازه نامعتبر است: {ex}")
        return _period_report(ds, now, key, s, e, f"{TITLES[key]} — {label}")
    if key == "full_period":
        first = min((t.date for t in ds.txs), default=None)
        if first is None:
            return {"key": key, "title": TITLES[key], "subtitle": "", "columns": [], "rows": [], "summary": [],
                    "notes": ["هنوز تراکنشی ثبت نشده است."]}
        return _period_report(ds, now, key, first, today, TITLES[key])
    if key == "asset_pnl":
        return _asset_pnl(ds, now)
    if key in ("deposits", "withdrawals"):
        return _flows(ds, key, params, now)
    if key == "platforms":
        return _platforms(ds, now)
    if key == "target_comparison":
        return _target(ds, now)
    if key == "risk":
        return _risk(ds, now)
    raise ValidationFailure("گزارش نامعتبر است.")


def _asset_pnl(ds, now):
    val = value_portfolio(ds, now)
    ar = asset_rows(ds, val)
    cols = [col("asset", "دارایی"), col("platform", "پلتفرم"), col("units", "تعداد واحد", "units"),
            col("total_bought", "مجموع مبلغ خرید", "money"), col("cost", "بهای تمام‌شده باقیمانده", "money"),
            col("value", "ارزش روز", "money"), col("realized", "تحقق‌یافته", "money"), col("dividends", "سود نقدی", "money"),
            col("fees", "کارمزد مستقل", "money"), col("unrealized", "تحقق‌نیافته", "money"),
            col("total", "جمع سود/زیان", "money"), col("ret", "بازده (٪ از مبلغ خرید)", "percent")]
    rows = [{"asset": r["name"], "platform": r["platform"], "units": r["units"], "total_bought": r["total_bought"],
             "cost": r["cost_basis"], "value": r["value"], "realized": r["realized"], "dividends": r["dividends"],
             "fees": r["fees"], "unrealized": r["unrealized"], "total": r["total_pnl"], "ret": r["return_pct"]} for r in ar]
    t = totals(val)
    notes = [] if val.complete else ["برای برخی دارایی‌ها قیمت معتبر وجود ندارد؛ سود/زیان آن‌ها محاسبه نشد."]
    return {"key": "asset_pnl", "title": TITLES["asset_pnl"], "subtitle": f"تا {fmt_date(now, ds.config.calendar)}",
            "columns": cols, "rows": rows, "notes": notes,
            "summary": [S("سود/زیان تحقق‌یافته (فروش)", t["realized_sales"]), S("سود نقدی", t["dividends"]),
                        S("کارمزد مستقل", t["fees"]), S("سود/زیان تحقق‌نیافته", t["unrealized"]),
                        S("اثر اصلاحات موجودی", t["asset_adjustments"] + t["cash_adjustments"]),
                        S("جمع کل سود/زیان", t["total_pnl"])]}


def _flows(ds, key, params, now):
    cal = ds.config.calendar
    ty = "deposit" if key == "deposits" else "withdrawal"
    d1, d2 = params.get("date_from"), params.get("date_to")
    plat = {p.id: p.name for p in ds.platforms}
    per = {p.id: p for p in ds.periods}
    txs = sorted((t for t in ds.txs if t.type == ty and (not d1 or t.date >= d1) and (not d2 or t.date <= d2)),
                 key=lg.tx_sort_key)
    cols = [col("date", "تاریخ", "date"), col("platform", "پلتفرم"), col("amount", "مبلغ", "money")]
    if ty == "deposit":
        cols += [col("period", "دوره برنامه")]
    rows = []
    for t in txs:
        r = {"date": t.date, "platform": plat.get(t.platform_id, ""), "amount": t.total}
        if ty == "deposit":
            p = per.get(t.plan_period_id)
            r["period"] = ("سرمایه اولیه" if p.seq == 0 else f"واریزی ماه {p.seq}") if p else "خارج از برنامه"
        rows.append(r)
    total = sum((t.total for t in txs), ZERO)
    summary = [S("تعداد", len(txs), "number"), S("جمع کل", total)]
    if ty == "deposit":
        ps = plan_status(ds, now.date())
        summary += [S("مجموع برنامه‌ریزی‌شده (کل افق)", ps["target_total"]), S("عقب‌ماندگی تا امروز", ps["arrears"]),
                    S("اضافه‌واریزی", ps["surplus"]),
                    S("درصد تحقق برنامه", ps["realization_pct"], "percent") if ps["realization_pct"] is not None else _na("درصد تحقق برنامه", "برنامه‌ای تعریف نشده")]
    return {"key": key, "title": TITLES[key], "subtitle": "", "columns": cols, "rows": rows, "summary": summary, "notes": []}


def _platforms(ds, now):
    val = value_portfolio(ds, now)
    pr = platform_rows(ds, val)
    cols = [col("platform", "پلتفرم"), col("deposits", "واریزی‌ها", "money"), col("withdrawals", "برداشت‌ها", "money"),
            col("assets_value", "ارزش دارایی‌ها", "money"), col("cash", "نقدینگی", "money"),
            col("total_value", "ارزش کل", "money"), col("realized", "تحقق‌یافته", "money"),
            col("unrealized", "تحقق‌نیافته", "money"), col("pnl", "سود/زیان کل", "money"),
            col("ret", "بازده (٪ از واریزی)", "percent"), col("weight", "وزن فعلی", "percent"),
            col("target", "وزن هدف", "percent")]
    rows = [{"platform": r["platform"], "deposits": r["deposits"], "withdrawals": r["withdrawals"],
             "assets_value": r["assets_value"], "cash": r["cash"], "total_value": r["total_value"],
             "realized": r["realized"], "unrealized": r["unrealized"], "pnl": r["total_pnl"], "ret": r["return_pct"],
             "weight": r["weight"], "target": r["target_weight"]} for r in pr]
    return {"key": "platforms", "title": TITLES["platforms"], "subtitle": f"تا {fmt_date(now, ds.config.calendar)}",
            "columns": cols, "rows": rows, "summary": [S("ارزش کل سبد", val.total_value)],
            "notes": [] if val.complete else ["برای برخی دارایی‌ها قیمت معتبر ثبت نشده است."]}


def _target(ds, now):
    val = value_portfolio(ds, now)
    ar = [r for r in asset_rows(ds, val) if r["active"]]
    inv = val.assets_value
    cols = [col("asset", "دارایی"), col("platform", "پلتفرم"), col("value", "ارزش فعلی", "money"),
            col("weight", "وزن فعلی", "percent"), col("target", "وزن هدف", "percent"),
            col("dev", "اختلاف (واحد درصد)", "percent"), col("target_value", "ارزش هدف (با ارزش فعلی سبد)", "money"),
            col("gap", "کمبود(+)/مازاد(−) نسبت به هدف", "money")]
    rows = []
    for r in ar:
        tv = inv * r["target_weight"] / HUNDRED
        rows.append({"asset": r["name"], "platform": r["platform"], "value": r["value"], "weight": r["weight"],
                     "target": r["target_weight"], "dev": r["deviation_pp"], "target_value": tv,
                     "gap": (tv - r["value"]) if r["value"] is not None else None})
    return {"key": "target_comparison", "title": TITLES["target_comparison"], "subtitle": f"تا {fmt_date(now, ds.config.calendar)}",
            "columns": cols, "rows": rows,
            "summary": [S("ارزش دارایی‌ها", inv), S("مجموع وزن‌های هدف", sum((r["target_weight"] for r in ar), ZERO), "percent")],
            "notes": ["پیشنهاد فروش داده نمی‌شود؛ برای متعادل‌سازی از صفحه «پیشنهاد خرید» استفاده کنید."]
            + ([] if val.complete else ["قیمت معتبر برخی دارایی‌ها موجود نیست؛ وزن‌ها دقیق نیستند."])}


def _risk(ds, now):
    cfg = ds.config
    book = make_book(ds)
    pts = build_series(ds, now.date(), book)
    dd = drawdown_summary(pts, now.date(), cfg.max_drawdown_pct)
    st = drawdown_status(dd, cfg.max_drawdown_pct)
    cols = [col("date", "تاریخ", "date"), col("value", "ارزش کل سبد", "money"), col("net", "سرمایه خالص واریزشده", "money"),
            col("index", "شاخص بازده (مبنا ۱۰۰)", "number"), col("dd", "افت از اوج (٪)", "percent")]
    rows = [{"date": p["date"], "value": p["value"] if p["complete"] else None, "net": p["net_invested"],
             "index": p["index"], "dd": p["drawdown_pct"]} for p in dd["series"]]
    summary = [S("سقف افت قابل تحمل", cfg.max_drawdown_pct, "percent")]
    if dd["available"]:
        summary += [S("افت فعلی از اوج", dd["current_drawdown_pct"], "percent"),
                    S("بیشترین افت ثبت‌شده", dd["max_drawdown_pct"], "percent"),
                    S("تاریخ اوج", dd["peak_date"], "date"), S("وضعیت", st["message"], "text")]
    else:
        summary.append(_na("افت سرمایه", dd["reason"]))
    return {"key": "risk", "title": TITLES["risk"], "subtitle": "", "columns": cols, "rows": rows, "summary": summary,
            "notes": [DISCLAIMER, "افت سرمایه روی بازده تعدیل‌شده با جریان نقدی محاسبه می‌شود؛ واریزی جدید سود محسوب نمی‌شود."]}
