from datetime import date, datetime, timedelta
from decimal import Decimal as D
import io

import pytest
from openpyxl import load_workbook


def today():
    from app.services.clock import today_local
    return today_local()


def ids(client):
    assets = {a["name"]: a for a in client.get("/api/assets").json()["assets"]}
    plats = {p["name"]: p["id"] for p in client.get("/api/meta").json()["platforms"]}
    return assets, plats


def post_tx(client, **kw):
    r = client.post("/api/transactions", json=kw)
    return r


def put_price(client, asset_id, price, when=None, **kw):
    body = {"asset_id": asset_id, "price": str(price), "recorded_at": (when or datetime.now()).isoformat(timespec="seconds"), **kw}
    r = client.post("/api/prices", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_seed_defaults(client):
    meta = client.get("/api/meta").json()
    s = meta["settings"]
    assert D(str(s["initial_capital"])) == 100_000_000 and D(str(s["monthly_contribution"])) == 50_000_000
    assert s["horizon_months"] == 12 and D(str(s["max_drawdown_pct"])) == 25 and s["allocation_ok"]
    plan = {p["name"]: p for p in s["plan_by_asset"]}
    assert D(str(plan["صندوق عیار"]["initial"])) == 25_000_000 and D(str(plan["صندوق آوند"]["monthly"])) == 5_000_000
    assert D(str(plan["شاخص S&P 500"]["initial"])) == 20_000_000
    assert D(str(s["plan_target_total"])) == 700_000_000
    c = client.get("/api/contributions").json()
    assert len(c["periods"]) == 13
    # برنامه هدف نباید تراکنش واقعی بسازد
    assert client.get("/api/transactions").json()["total"] == 0
    assert [p["platform"] for p in c["platform_targets"]] == ["مفید", "بیت‌پین"]


def test_empty_dashboard_has_messages_not_numbers(client):
    d = client.get("/api/dashboard").json()
    assert d["has_data"] is False
    assert d["cards"]["total_return"]["available"] is False
    assert d["cards"]["xirr"]["available"] is False
    assert client.get("/api/risk").json()["status"]["level"] == "unknown"
    for k in ("daily", "monthly", "quarterly", "yearly", "full_period", "asset_pnl", "deposits", "withdrawals",
              "platforms", "target_comparison", "risk"):
        assert client.get(f"/api/reports/{k}").status_code == 200, k


def setup_portfolio(client):
    a, p = ids(client)
    d0 = (today() - timedelta(days=10)).isoformat()
    assert post_tx(client, tx_date=d0, tx_type="deposit", platform_id=p["مفید"], amount="100000000").status_code == 201
    r = post_tx(client, tx_date=d0, tx_type="buy", asset_id=a["صندوق عیار"]["id"], quantity="1000", unit_price="20000", fee="50000")
    assert r.status_code == 201, r.text
    return a, p, d0


def test_transaction_flow_and_calculations(client):
    a, p, d0 = setup_portfolio(client)
    aid = a["صندوق عیار"]["id"]
    # قیمت روز ثبت نشده → ارزش‌گذاری ناقص و بدون عددسازی
    port = client.get("/api/portfolio").json()
    row = next(x for x in port["assets"] if x["id"] == aid)
    assert D(str(row["cost_basis"])) == 20_050_000 and D(str(row["avg_cost"])) == D("20050")
    assert row["value"] is None and row["quote"]["ok"] is False and port["valuation_complete"] is False
    assert client.get("/api/dashboard").json()["cards"]["total_return"]["available"] is False
    put_price(client, aid, 21000)
    port = client.get("/api/portfolio").json()
    row = next(x for x in port["assets"] if x["id"] == aid)
    assert D(str(row["value"])) == 21_000_000 and D(str(row["unrealized"])) == 950_000
    t = port["totals"]
    assert D(str(t["cash"])) == 100_000_000 - 20_050_000
    # هویت حسابداری: ارزش + برداشت − واریزی = مجموع سود/زیان
    assert D(str(t["total_value"])) + D(str(t["withdrawals"])) - D(str(t["deposits"])) == D(str(t["total_pnl"]))
    d = client.get("/api/dashboard").json()
    assert d["cards"]["total_return"]["available"] is True
    assert round(d["cards"]["total_return"]["pct"], 4) == 0.95
    # فروش و سود تحقق‌یافته با میانگین موزون
    r = post_tx(client, tx_date=today().isoformat(), tx_type="sell", asset_id=aid, quantity="400", unit_price="22000", fee="10000")
    assert r.status_code == 201
    port = client.get("/api/portfolio").json()
    row = next(x for x in port["assets"] if x["id"] == aid)
    assert D(str(row["realized"])) == D("8800000") - D("10000") - D("20050") * 400


def test_validation_and_edit_delete_recalc(client):
    a, p, d0 = setup_portfolio(client)
    aid = a["صندوق عیار"]["id"]
    sell = post_tx(client, tx_date=today().isoformat(), tx_type="sell", asset_id=aid, quantity="600", unit_price="21000").json()["transaction"]
    # فروش بیش از موجودی
    r = post_tx(client, tx_date=today().isoformat(), tx_type="sell", asset_id=aid, quantity="401", unit_price="21000")
    assert r.status_code == 422 and "موجودی" in r.json()["error"]["message"]
    # حذف خرید باعث ناسازگاری فروش می‌شود → رد
    buy_id = next(t["id"] for t in client.get("/api/transactions").json()["items"] if t["tx_type"] == "buy")
    r = client.delete(f"/api/transactions/{buy_id}")
    assert r.status_code == 422 and r.json()["error"]["code"] == "ledger_inconsistent"
    assert client.get("/api/transactions").json()["total"] == 3
    # ویرایش فروش با تعداد کمتر
    r = client.put(f"/api/transactions/{sell['id']}", json={"tx_date": today().isoformat(), "tx_type": "sell", "asset_id": aid,
                                                              "quantity": "200", "unit_price": "21000", "fee": "0"})
    assert r.status_code == 200
    row = next(x for x in client.get("/api/portfolio").json()["assets"] if x["id"] == aid)
    assert D(str(row["units"])) == 800
    assert D(str(row["realized"])) == 200 * 21000 - D("20050") * 200
    # حذف فروش → موجودی برمی‌گردد و سود تحقق‌یافته صفر
    assert client.delete(f"/api/transactions/{sell['id']}").status_code == 200
    row = next(x for x in client.get("/api/portfolio").json()["assets"] if x["id"] == aid)
    assert D(str(row["units"])) == 1000 and D(str(row["realized"])) == 0
    # ورودی‌های نامعتبر
    bad = [
        dict(tx_date=(today() + timedelta(days=3)).isoformat(), tx_type="deposit", platform_id=p["مفید"], amount="10"),
        dict(tx_date=d0, tx_type="buy", asset_id=aid, quantity="-1", unit_price="10"),
        dict(tx_date=d0, tx_type="buy", asset_id=aid, quantity="1"),
        dict(tx_date=d0, tx_type="deposit", platform_id=p["مفید"], amount="0"),
        dict(tx_date=d0, tx_type="deposit", amount="10"),
        dict(tx_date=d0, tx_type="buy", asset_id=a["شاخص S&P 500"]["id"], platform_id=p["مفید"], quantity="1", unit_price="1"),
        dict(tx_date=d0, tx_type="bogus", amount="1"),
        dict(tx_date=d0, tx_type="deposit", platform_id=p["مفید"], amount="abc"),
    ]
    for b in bad:
        assert client.post("/api/transactions", json=b).status_code == 422, b
    # بدون SQL injection در جستجو
    assert client.get("/api/transactions", params={"q": "'; DROP TABLE transactions;--"}).status_code == 200
    assert client.get("/api/transactions").json()["total"] == 2


def test_negative_cash_is_warning_not_error(client):
    a, p = ids(client)
    r = post_tx(client, tx_date=today().isoformat(), tx_type="buy", asset_id=a["صندوق عیار"]["id"], quantity="1", unit_price="1000")
    assert r.status_code == 201 and r.json()["warnings"]


def test_price_validity_rules(client):
    a, p, d0 = setup_portfolio(client)
    aid = a["صندوق عیار"]["id"]
    put_price(client, aid, 25000, datetime.now() - timedelta(days=9))  # قدیمی
    port = client.get("/api/portfolio").json()
    row = next(x for x in port["assets"] if x["id"] == aid)
    assert row["value"] is None and row["quote"]["reason"] == "stale"
    cur = {x["asset_id"]: x for x in client.get("/api/prices/current").json()["items"]}[aid]
    assert cur["ok"] is False and cur["price"] is None
    put_price(client, aid, 30000, is_approved=False)  # تأییدنشده
    assert next(x for x in client.get("/api/portfolio").json()["assets"] if x["id"] == aid)["value"] is None
    pid = client.get("/api/prices", params={"approved": False}).json()[0]["id"]
    assert client.post(f"/api/prices/{pid}/approve").status_code == 200
    assert D(str(next(x for x in client.get("/api/portfolio").json()["assets"] if x["id"] == aid)["value"])) == 30_000_000
    # واحد پول نامعتبر / آینده / صفر
    assert client.post("/api/prices", json={"asset_id": aid, "price": "5", "currency": "USD"}).status_code == 422
    assert client.post("/api/prices", json={"asset_id": aid, "price": "0"}).status_code == 422
    fut = (datetime.now() + timedelta(days=2)).isoformat(timespec="seconds")
    assert client.post("/api/prices", json={"asset_id": aid, "price": "5", "recorded_at": fut}).status_code == 422
    # دریافت خودکار بدون پیکربندی، بدون اختلال
    assert client.post("/api/prices/fetch").json() == {"results": []}


def test_fx_valuation_and_effect(client):
    a, p = ids(client)
    spx = a["شاخص S&P 500"]
    body = {k: spx[k] for k in ("platform_id", "name", "symbol", "asset_type", "target_weight", "buy_fee_rate", "fractional_units",
                                "is_active", "price_provider", "note")}
    body["price_currency"] = "USD"
    body["fractional_units"] = True
    assert client.put(f"/api/assets/{spx['id']}", json=body).status_code == 200
    d0 = (today() - timedelta(days=5)).isoformat()
    post_tx(client, tx_date=d0, tx_type="deposit", platform_id=p["بیت‌پین"], amount="100000000")
    r = post_tx(client, tx_date=d0, tx_type="buy", asset_id=spx["id"], quantity="10", unit_price="5000000", fx_rate="50000")
    assert r.status_code == 201, r.text
    put_price(client, spx["id"], 110)
    row = next(x for x in client.get("/api/portfolio").json()["assets"] if x["id"] == spx["id"])
    assert row["value"] is None and row["quote"]["reason"] == "no_fx"
    assert client.post("/api/fx", json={"currency": "IRT", "rate": "1"}).status_code == 422
    assert client.post("/api/fx", json={"currency": "USD", "rate": "55000"}).status_code == 201
    port = client.get("/api/portfolio").json()
    row = next(x for x in port["assets"] if x["id"] == spx["id"])
    assert D(str(row["value"])) == 10 * 110 * 55000
    fx = port["fx"][0]
    # بهای ارزی = 5,000,000×10/50,000 = 1000 دلار ؛ اثر قیمت = (1100−1000)×55000 ؛ اثر نرخ = 1000×(55000−50000)
    assert D(str(fx["asset_price_effect"])) == 5_500_000 and D(str(fx["fx_rate_effect"])) == 5_000_000
    assert D(str(fx["total_unrealized"])) == D(str(row["unrealized"]))


def test_contribution_recording_and_status(client):
    c = client.get("/api/contributions").json()
    seq1 = next(p for p in c["periods"] if p["seq"] == 1)
    r = client.post("/api/contributions/1/record", json={"date": today().isoformat(), "amount": "50000000"})
    assert r.status_code == 201, r.text
    deps = client.get("/api/transactions", params={"tx_type": "deposit"}).json()["items"]
    by_plat = {d["platform"]: D(str(d["total_amount"])) for d in deps}
    assert by_plat == {"مفید": D(30_000_000), "بیت‌پین": D(20_000_000)}
    c = client.get("/api/contributions").json()
    p1 = next(p for p in c["periods"] if p["seq"] == 1)
    assert D(str(p1["actual"])) == 50_000_000 and p1["status"] in ("paid", "extra")
    assert D(str(c["total_deposits"])) == 50_000_000
    assert round(c["realization_pct"], 4) == round(50 / 700 * 100, 4)
    # تغییر مبلغ ماهانه از تنظیمات: دوره‌های آینده به‌روز می‌شوند، دوره پرداخت‌شده ثابت می‌ماند
    s = client.get("/api/settings").json()
    s.update(monthly_contribution="40000000")
    for k in ("plan_target_total", "allocation_sum", "allocation_ok", "plan_by_asset"):
        s.pop(k)
    r = client.put("/api/settings", json=s)
    assert r.status_code == 200, r.text
    c = client.get("/api/contributions").json()
    assert D(str(next(p for p in c["periods"] if p["seq"] == 1)["planned"])) == 50_000_000
    assert D(str(next(p for p in c["periods"] if p["seq"] == 5)["planned"])) == 40_000_000


def test_rebalance_endpoint(client):
    a, p, d0 = setup_portfolio(client)
    for name, asset in a.items():
        put_price(client, asset["id"], 20000 if name == "صندوق عیار" else 10000)
    r = client.get("/api/rebalance", params={"source": "custom", "amount": "50000000"}).json()
    assert r["available"] and r["sells"] == []
    rows = {x["name"]: x for x in r["rows"]}
    assert rows["صندوق عیار"]["status"] == "above_target"
    assert all(D(str(x["units"])) == int(D(str(x["units"]))) for x in r["rows"])
    assert D(str(r["total_spend"])) <= 50_000_000
    r = client.get("/api/rebalance", params={"source": "custom"})
    assert r.status_code == 422


def test_exports(client):
    a, p, d0 = setup_portfolio(client)
    put_price(client, a["صندوق عیار"]["id"], 21000)
    r = client.get("/api/reports/asset_pnl/export", params={"format": "xlsx"})
    assert r.status_code == 200 and r.content[:2] == b"PK"
    ws = load_workbook(io.BytesIO(r.content)).active
    nums = [c.value for row in ws.iter_rows() for c in row if isinstance(c.value, (int, float))]
    assert 20_050_000 in nums or 20050000.0 in nums
    assert any(c.number_format == "#,##0" for row in ws.iter_rows() for c in row if isinstance(c.value, (int, float)))
    r = client.get("/api/reports/deposits/export", params={"format": "csv"})
    assert r.content.startswith("\ufeff".encode()) and b"100000000" in r.content
    for key in ("monthly", "risk", "platforms", "target_comparison", "full_period"):
        r = client.get(f"/api/reports/{key}/export", params={"format": "pdf"})
        assert r.status_code == 200 and r.content[:4] == b"%PDF", key
    assert client.get("/api/reports/nope").status_code == 404


def test_backup_restore_and_reset(client):
    a, p, d0 = setup_portfolio(client)
    put_price(client, a["صندوق عیار"]["id"], 21000)
    before = client.get("/api/portfolio").json()["totals"]
    backup = client.get("/api/backup/export").content
    assert client.post("/api/backup/restore", content=backup).status_code == 422  # بدون تأیید
    # پاک‌سازی چندمرحله‌ای
    req = client.post("/api/data/reset/request", json={"scope": "data"}).json()
    assert client.post("/api/data/reset/confirm", json={"token": req["token"], "phrase": "غلط", "scope": "data"}).status_code == 422
    assert client.post("/api/data/reset/confirm", json={"token": "x", "phrase": req["phrase"], "scope": "data"}).status_code == 422
    assert client.post("/api/data/reset/confirm", json={"token": req["token"], "phrase": req["phrase"], "scope": "data"}).status_code == 200
    assert client.get("/api/transactions").json()["total"] == 0
    r = client.post("/api/backup/restore", params={"confirm": True}, content=backup)
    assert r.status_code == 200, r.text
    after = client.get("/api/portfolio").json()["totals"]
    assert before == after
    # فایل نامعتبر تغییری ایجاد نمی‌کند
    assert client.post("/api/backup/restore", params={"confirm": True}, content=b"{bad").status_code == 422
    assert client.post("/api/backup/restore", params={"confirm": True}, content=b'{"app":"x"}').status_code == 422
    assert client.get("/api/transactions").json()["total"] == 2
    # نسخه فایل دیتابیس
    assert client.post("/api/backup/db").json()["files"]


def test_allocation_weights_and_asset_management(client):
    a, p = ids(client)
    w = {str(x["id"]): "20" for x in a.values()}
    assert client.put("/api/assets/target-weights", json={"weights": w}).status_code == 200
    w["1"] = "30"
    assert client.put("/api/assets/target-weights", json={"weights": w}).status_code == 422
    new = client.post("/api/assets", json={"platform_id": p["مفید"], "name": "صندوق تست", "asset_type": "fund", "target_weight": "0"})
    assert new.status_code == 201
    nid = new.json()["id"]
    assert client.post("/api/assets", json={"platform_id": p["مفید"], "name": "صندوق تست"}).status_code == 409
    assert client.post(f"/api/assets/{nid}/active", params={"active": False}).json()["is_active"] is False
    assert client.get(f"/api/assets/{nid}").json()["name"] == "صندوق تست"
    assert client.get("/api/assets/9999").status_code == 404


def test_risk_drawdown_not_hidden_by_deposits(client):
    a, p = ids(client)
    aid = a["صندوق عیار"]["id"]
    d1, d2, d3 = [(today() - timedelta(days=n)).isoformat() for n in (3, 2, 1)]
    post_tx(client, tx_date=d1, tx_type="deposit", platform_id=p["مفید"], amount="1000000")
    post_tx(client, tx_date=d1, tx_type="buy", asset_id=aid, quantity="100", unit_price="10000")
    put_price(client, aid, 10000, datetime.fromisoformat(d1 + "T12:00:00"))
    put_price(client, aid, 7000, datetime.fromisoformat(d2 + "T12:00:00"))
    post_tx(client, tx_date=d2, tx_type="deposit", platform_id=p["مفید"], amount="5000000")
    put_price(client, aid, 7000, datetime.now())
    risk = client.get("/api/risk").json()
    dd = risk["drawdown"]
    assert dd["available"] and dd["current_drawdown_pct"] == 30.0
    assert risk["status"]["level"] == "critical"
    assert any(x["level"] == "critical" for x in risk["alerts"])
    assert "تضمین" in risk["disclaimer"]


def test_basic_auth_and_docs(client):
    assert client.get("/api/docs").status_code == 200
    assert client.get("/").status_code == 200
    assert client.get("/api/nothing").status_code == 404
