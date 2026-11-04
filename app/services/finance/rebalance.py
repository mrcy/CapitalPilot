"""پیشنهاد تخصیص واریزی جدید و متعادل‌سازی بدون فروش غیرضروری.

منطق: ارزش هدف هر دارایی = وزن هدف × (ارزش فعلی دارایی‌ها + مبلغ جدید).
دارایی‌هایی که زیر هدف هستند «نیاز» دارند؛ مبلغ جدید به نسبت نیاز بین آن‌ها تقسیم می‌شود
(هرچه دارایی عقب‌تر باشد سهم بیشتری می‌گیرد). دارایی‌های بالاتر از هدف خرید نمی‌گیرند.
هیچ پیشنهاد فروشی داده نمی‌شود؛ انحراف بالا با واریزهای بعدی خنثی می‌شود.
"""
from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from .types import HUNDRED, ZERO, DataSet
from .valuation import PortfolioValuation

UNIT_PLACES = Decimal("0.000001")


def _floor_units(amount: Decimal, unit_cost: Decimal, fractional: bool) -> Decimal:
    if unit_cost <= 0 or amount <= 0:
        return ZERO
    raw = amount / unit_cost
    return raw.quantize(UNIT_PLACES, rounding=ROUND_DOWN) if fractional else raw.to_integral_value(rounding=ROUND_DOWN)


def suggest_allocation(ds: DataSet, val: PortfolioValuation, amount: Decimal) -> dict:
    warnings: list[str] = []
    if amount <= 0:
        return {"available": False, "reason": "مبلغ واریزی باید بزرگ‌تر از صفر باشد."}
    held_unpriced = [r for r in val.unpriced if r.pos.units > 0]
    if held_unpriced:
        names = "، ".join(r.asset.name for r in held_unpriced)
        return {"available": False,
                "reason": f"برای محاسبه وزن‌ها، قیمت معتبر امروز لازم است. قیمت این دارایی‌ها ثبت نشده یا قدیمی است: {names}"}
    rows = {r.asset.id: r for r in val.assets}
    active = [a for a in ds.assets if a.active]
    wsum = sum((a.target_weight for a in active), ZERO)
    if wsum <= 0:
        return {"available": False, "reason": "وزن هدف هیچ دارایی فعالی تعریف نشده است."}
    if wsum != HUNDRED:
        warnings.append(f"مجموع وزن‌های هدف {wsum.normalize():f}٪ است (نه ۱۰۰٪)؛ برای محاسبه نرمال‌سازی شد.")
    invested = val.assets_value
    total_after = invested + amount
    items = []
    need_sum = ZERO
    for a in active:
        v = rows[a.id].value if a.id in rows and rows[a.id].value is not None else ZERO
        tw = a.target_weight / wsum  # نسبت (۰..۱)
        need = max(ZERO, tw * total_after - v)
        need_sum += need
        items.append({"asset": a, "value": v, "tw": tw, "need": need,
                      "quote": rows[a.id].quote if a.id in rows else None})
    for it in items:
        it["ideal"] = amount * it["need"] / need_sum if need_sum > 0 else ZERO

    spent = {it["asset"].id: ZERO for it in items}
    units = {it["asset"].id: ZERO for it in items}
    unit_cost = {}
    for it in items:
        a = it["asset"]
        q = it["quote"]
        if q is not None and q.ok:
            unit_cost[a.id] = q.price_irt * (Decimal(1) + a.buy_fee_rate / HUNDRED)
            units[a.id] = _floor_units(it["ideal"], unit_cost[a.id], a.fractional)
            spent[a.id] = units[a.id] * unit_cost[a.id]
        elif it["ideal"] > 0:
            warnings.append(f"برای «{a.name}» قیمت معتبر ثبت نشده است؛ تعداد خرید قابل محاسبه نیست.")
    # تخصیص باقیمانده ناشی از گرد کردن (فقط عدد صحیح)
    remaining = amount - sum(spent.values(), ZERO)
    for _ in range(10000):
        cands = [
            it for it in items
            if it["asset"].id in unit_cost and not it["asset"].fractional
            and unit_cost[it["asset"].id] <= remaining
            and (it["ideal"] - spent[it["asset"].id]) * 2 >= unit_cost[it["asset"].id]
        ]
        if not cands:
            break
        best = max(cands, key=lambda it: it["ideal"] - spent[it["asset"].id])
        aid = best["asset"].id
        units[aid] += 1
        spent[aid] += unit_cost[aid]
        remaining -= unit_cost[aid]

    total_spent = sum(spent.values(), ZERO)
    value_after_total = invested + sum((units[i["asset"].id] * i["quote"].price_irt for i in items
                                        if i["asset"].id in unit_cost), ZERO)
    plat = {p.id: p.name for p in ds.platforms}
    out_rows = []
    by_platform: dict[int, Decimal] = {}
    for it in items:
        a = it["asset"]
        cw = (it["value"] / invested * HUNDRED) if invested > 0 else ZERO
        buy_value = units[a.id] * it["quote"].price_irt if a.id in unit_cost else ZERO
        fee = units[a.id] * it["quote"].price_irt * a.buy_fee_rate / HUNDRED if a.id in unit_cost else ZERO
        total_cost = buy_value + fee
        after_w = ((it["value"] + buy_value) / value_after_total * HUNDRED) if value_after_total > 0 else ZERO
        by_platform[a.platform_id] = by_platform.get(a.platform_id, ZERO) + total_cost
        if it["ideal"] > 0:
            status = "buy" if units[a.id] > 0 else ("no_price" if a.id not in unit_cost else "too_small")
        else:
            status = "above_target"
        out_rows.append({
            "asset_id": a.id, "name": a.name, "symbol": a.symbol, "asset_type": a.type, "platform_id": a.platform_id,
            "platform": plat.get(a.platform_id, ""), "current_value": it["value"], "current_weight": cw,
            "target_weight": a.target_weight, "deviation_pp": cw - a.target_weight,
            "ideal_amount": it["ideal"], "price": it["quote"].price_irt if a.id in unit_cost else None,
            "units": units[a.id], "buy_value": buy_value, "fee": fee, "total_cost": total_cost,
            "fee_rate": a.buy_fee_rate, "weight_after": after_w, "status": status, "fractional": a.fractional,
        })
    # مبلغ لازم برای رسیدن به هدف بدون فروش
    ratios = [it["value"] / it["tw"] for it in items if it["tw"] > 0]
    t_min = max(ratios) if ratios else ZERO
    extra_to_target = max(ZERO, t_min - invested)
    overweight = [r for r in out_rows if r["deviation_pp"] > 0]
    notes = []
    if overweight:
        notes.append("هیچ فروشی پیشنهاد نمی‌شود: دارایی‌های بالاتر از وزن هدف در این واریزی خرید نمی‌گیرند و با واریزهای بعدی به‌تدریج به هدف نزدیک می‌شوند.")
    return {
        "available": True, "amount": amount, "invested_value": invested, "total_after": total_after,
        "rows": out_rows, "total_spend": total_spent, "leftover": amount - total_spent,
        "by_platform": [{"platform_id": k, "platform": plat.get(k, ""), "amount": v} for k, v in by_platform.items()],
        "sells": [], "extra_to_reach_target_without_selling": extra_to_target,
        "warnings": warnings, "notes": notes,
        "disclaimer": "این برنامه سفارشی ارسال نمی‌کند؛ خرید باید توسط خودتان در پلتفرم انجام و سپس به‌عنوان تراکنش ثبت شود.",
    }
