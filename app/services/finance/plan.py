"""برنامه واریزی: تقویم دوره‌ها، وضعیت و مقایسه برنامه با واقعی."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from ..calendar_utils import add_months_calendar, month_key, month_label
from .types import Config, DataSet, HUNDRED, ZERO


def generate_schedule(cfg: Config) -> list[tuple[int, date, Decimal]]:
    """seq=0: سرمایه اولیه در تاریخ شروع؛ seq=k: واریزی ماهانه k-ام، k ماه بعد از شروع."""
    out = [(0, cfg.start_date, cfg.initial_capital)]
    for k in range(1, cfg.horizon_months + 1):
        out.append((k, add_months_calendar(cfg.start_date, k, cfg.calendar), cfg.monthly_contribution))
    return out


def plan_target_total(ds: DataSet) -> Decimal:
    return sum((p.planned for p in ds.periods), ZERO)


def plan_status(ds: DataSet, today: date) -> dict:
    cfg = ds.config
    actual_by_period: dict[int, Decimal] = defaultdict(lambda: ZERO)
    deposits_by_period: dict[int, list] = defaultdict(list)
    unlinked = ZERO
    total_deposits = ZERO
    for t in ds.txs:
        if t.type != "deposit":
            continue
        total_deposits += t.total
        if t.plan_period_id is None:
            unlinked += t.total
        else:
            actual_by_period[t.plan_period_id] += t.total
            deposits_by_period[t.plan_period_id].append(t)
    rows = []
    planned_due = ZERO
    actual_due = ZERO
    arrears = ZERO
    surplus = unlinked
    for p in sorted(ds.periods, key=lambda p: p.seq):
        actual = actual_by_period.get(p.id, ZERO)
        diff = actual - p.planned
        due = p.due_date < today
        if actual >= p.planned and p.planned > 0:
            status = "paid" if diff == 0 else "extra"
        elif actual > 0:
            status = "partial_overdue" if p.due_date < today else "partial"
        else:
            status = "overdue" if p.due_date < today else ("due" if p.due_date == today else "upcoming")
        if due:
            planned_due += p.planned
            actual_due += actual
            arrears += max(ZERO, p.planned - actual)
        surplus += max(ZERO, diff)
        paid_dates = sorted(t.date for t in deposits_by_period.get(p.id, []))
        rows.append({
            "id": p.id, "seq": p.seq, "kind": "initial" if p.seq == 0 else "monthly", "due_date": p.due_date,
            "planned": p.planned, "actual": actual, "diff": diff, "status": status,
            "paid_dates": paid_dates, "label": month_label(month_key(p.due_date, cfg.calendar), cfg.calendar),
            "completion_pct": (actual / p.planned * HUNDRED) if p.planned > 0 else None,
        })
    target = plan_target_total(ds)
    monthly: dict[tuple[int, int], dict] = {}
    for t in ds.txs:
        if t.type in ("deposit", "withdrawal"):
            k = month_key(t.date, cfg.calendar)
            m = monthly.setdefault(k, {"deposits": ZERO, "withdrawals": ZERO})
            m["deposits" if t.type == "deposit" else "withdrawals"] += t.total
    monthly_rows = [
        {"key": f"{k[0]}-{k[1]:02d}", "label": month_label(k, cfg.calendar), **v, "net": v["deposits"] - v["withdrawals"]}
        for k, v in sorted(monthly.items())
    ]
    return {
        "periods": rows,
        "target_total": target,
        "total_deposits": total_deposits,
        "unlinked_deposits": unlinked,
        "planned_due_to_date": planned_due,
        "actual_in_due_periods": actual_due,
        "arrears": arrears,
        "surplus": surplus,
        "net_diff_to_date": actual_due - planned_due,
        "realization_pct": (total_deposits / target * HUNDRED) if target > 0 else None,
        "realization_to_date_pct": (actual_due / planned_due * HUNDRED) if planned_due > 0 else None,
        "gap_to_target": target - total_deposits,
        "monthly_totals": monthly_rows,
        "unpaid_count": sum(1 for r in rows if r["status"] in ("overdue", "partial_overdue")),
    }
