"""مدیریت پویا: دارایی، صندوق، پلتفرم، نوع دارایی، سبد، بایگانی/حذف ایمن و صحت مالی."""
from datetime import datetime, timedelta
from decimal import Decimal as D

import pytest


def today():
    from app.services.clock import today_local
    return today_local()


def meta_ids(client):
    assets = {a["name"]: a for a in client.get("/api/assets").json()["assets"]}
    plats = {p["name"]: p["id"] for p in client.get("/api/platforms").json()}
    return assets, plats


def new_asset(client, plat, **kw):
    body = {"platform_id": plat, "name": "صندوق نمونه", "symbol": "نمونه", "asset_type": "fund", "target_weight": "0"}
    body.update(kw)
    r = client.post("/api/assets", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def deposit(client, plat, amount="100000000", portfolio_id=None, d=None):
    body = {"tx_date": (d or today() - timedelta(days=5)).isoformat(), "tx_type": "deposit", "platform_id": plat, "amount": amount}
    if portfolio_id:
        body["portfolio_id"] = portfolio_id
    r = client.post("/api/transactions", json=body)
    assert r.status_code == 201, r.text


def buy(client, asset_id, qty, price, fee="0", portfolio_id=None, d=None):
    body = {"tx_date": (d or today() - timedelta(days=4)).isoformat(), "tx_type": "buy", "asset_id": asset_id,
            "quantity": str(qty), "unit_price": str(price), "fee": str(fee)}
    if portfolio_id:
        body["portfolio_id"] = portfolio_id
    return client.post("/api/transactions", json=body)


def price(client, asset_id, p, when=None):
    r = client.post("/api/prices", json={"asset_id": asset_id, "price": str(p), "recorded_at": (when or datetime.now()).isoformat(timespec="seconds")})
    assert r.status_code == 201, r.text


# ---------------------------------------------------------------- پلتفرم‌ها
def test_seed_platforms_and_types(client):
    names = [p["name"] for p in client.get("/api/platforms").json()]
    for n in ["مفید", "بیت‌پین", "بورس", "بورس کالا", "کارگزاری دیگر", "بازار خارجی", "شخصی", "سایر"]:
        assert n in names
    types = {t["key"] for t in client.get("/api/asset-types").json()}
    assert {"fund", "stock", "digital", "gold", "silver", "copper", "currency", "fixed_income", "commodity", "index", "other"} <= types


def test_add_edit_archive_delete_platform(client):
    r = client.post("/api/platforms", json={"name": "کارگزاری آزمون", "kind": "broker"})
    assert r.status_code == 201
    pid = r.json()["id"]
    assert client.post("/api/platforms", json={"name": "کارگزاری آزمون"}).status_code == 409
    r = client.put(f"/api/platforms/{pid}", json={"name": "کارگزاری آزمون ۲", "kind": "broker", "note": "x"})
    assert r.json()["name"] == "کارگزاری آزمون ۲"
    a = new_asset(client, pid, name="دارایی روی پلتفرم")
    # پلتفرم دارای دارایی حذف نمی‌شود
    assert client.delete(f"/api/platforms/{pid}").status_code == 409
    assert client.post(f"/api/platforms/{pid}/archive").json()["is_archived"] is True
    # روی پلتفرم بایگانی‌شده دارایی جدید ساخته نمی‌شود
    r = client.post("/api/assets", json={"platform_id": pid, "name": "دیگر", "asset_type": "fund"})
    assert r.status_code == 422
    assert client.post(f"/api/platforms/{pid}/restore").json()["is_archived"] is False
    assert client.delete(f"/api/assets/{a['id']}").status_code == 200
    assert client.delete(f"/api/platforms/{pid}").status_code == 200


def test_platform_with_transactions_cannot_be_deleted(client):
    _, plats = meta_ids(client)
    deposit(client, plats["مفید"])
    r = client.delete(f"/api/platforms/{plats['مفید']}")
    assert r.status_code == 409 and r.json()["error"]["code"] == "has_transactions"


# ---------------------------------------------------------------- نوع دارایی
def test_custom_asset_type_with_extra_fields(client):
    body = {"key": "bond_x", "label": "اوراق ویژه", "fields": [
        {"key": "rate", "label": "نرخ", "type": "number"},
        {"key": "kind", "label": "نوع", "type": "select", "options": ["الف", "ب"]}]}
    assert client.post("/api/asset-types", json=body).status_code == 201
    _, plats = meta_ids(client)
    a = new_asset(client, plats["بورس"], name="اوراق ۱", asset_type="bond_x", extra={"rate": "23.5", "kind": "الف"})
    assert a["extra"] == {"rate": "23.5", "kind": "الف"}
    r = client.post("/api/assets", json={"platform_id": plats["بورس"], "name": "اوراق ۲", "asset_type": "bond_x", "extra": {"zzz": "1"}})
    assert r.status_code == 422
    r = client.post("/api/assets", json={"platform_id": plats["بورس"], "name": "اوراق ۳", "asset_type": "bond_x", "extra": {"kind": "ج"}})
    assert r.status_code == 422
    # نوع در حال استفاده حذف نمی‌شود؛ نوع بدون استفاده حذف می‌شود
    assert client.delete("/api/asset-types/bond_x").status_code == 409
    assert client.delete("/api/assets/%d" % a["id"]).status_code == 200
    assert client.delete("/api/asset-types/bond_x").status_code == 200
    assert client.delete("/api/asset-types/fund").status_code == 422  # سیستمی
    assert client.post("/api/assets", json={"platform_id": plats["بورس"], "name": "x", "asset_type": "ghost"}).status_code == 422


# ---------------------------------------------------------------- دارایی/صندوق
def test_add_edit_asset_full_fields(client):
    _, plats = meta_ids(client)
    a = new_asset(client, plats["بورس"], name="صندوق کارا", name_en="Kara Fund", symbol="کارا", market="TSETMC", unit="واحد",
                  decimals=0, min_quantity="10", initial_price="1200", note="توضیح",
                  sources=[])
    assert a["name_en"] == "Kara Fund" and a["market"] == "TSETMC" and D(str(a["min_quantity"])) == 10
    assert a["status"] == "active"
    body = {k: a[k] for k in ("platform_id", "name", "name_en", "symbol", "asset_type", "market", "unit", "price_currency",
                              "decimals", "min_quantity", "target_weight", "initial_price", "buy_fee_rate", "is_active", "note")}
    body.update(name="صندوق کارا (ویرایش)", symbol="کارا۲", asset_type="stock")
    r = client.put(f"/api/assets/{a['id']}", json=body)
    assert r.status_code == 200 and r.json()["name"] == "صندوق کارا (ویرایش)" and r.json()["asset_type"] == "stock"
    # نام تکراری روی همان پلتفرم
    other = new_asset(client, plats["بورس"], name="دیگری")
    body["name"] = "دیگری"
    assert client.put(f"/api/assets/{a['id']}", json=body).status_code == 409
    # جستجو/فیلتر/مرتب‌سازی/صفحه‌بندی
    r = client.get("/api/assets", params={"q": "کارا", "asset_type": "stock"}).json()
    assert r["total"] == 1 and r["assets"][0]["id"] == a["id"]
    r = client.get("/api/assets", params={"page_size": 3, "page": 2, "sort": "name"}).json()
    assert len(r["assets"]) == 3 and r["total"] >= 7
    r = client.get("/api/assets", params={"platform_id": plats["بورس"]}).json()
    assert {x["name"] for x in r["assets"]} == {"صندوق کارا (ویرایش)", "دیگری"}


def test_min_quantity_and_decimals_enforced(client):
    _, plats = meta_ids(client)
    a = new_asset(client, plats["مفید"], name="با حداقل", min_quantity="10", decimals=0)
    deposit(client, plats["مفید"])
    assert buy(client, a["id"], 5, 1000).status_code == 422          # کمتر از حداقل
    assert buy(client, a["id"], "10.5", 1000).status_code == 422     # اعشار غیرمجاز
    assert buy(client, a["id"], 10, 1000).status_code == 201
    c = new_asset(client, plats["مفید"], name="اعشاری", decimals=3)
    assert buy(client, c["id"], "1.234", 1000).status_code == 201
    assert buy(client, c["id"], "1.2345", 1000).status_code == 422


def test_same_instrument_on_two_platforms_is_independent(client):
    _, plats = meta_ids(client)
    a1 = new_asset(client, plats["مفید"], name="صندوق مشترک", symbol="مشترک")
    a2 = new_asset(client, plats["بورس"], name="صندوق مشترک", symbol="مشترک")
    deposit(client, plats["مفید"]); deposit(client, plats["بورس"])
    assert buy(client, a1["id"], 100, 1000).status_code == 201
    assert buy(client, a2["id"], 30, 1500).status_code == 201
    port = {x["id"]: x for x in client.get("/api/portfolio").json()["assets"]}
    assert D(str(port[a1["id"]]["units"])) == 100 and D(str(port[a2["id"]]["units"])) == 30
    assert D(str(port[a1["id"]]["avg_cost"])) == 1000 and D(str(port[a2["id"]]["avg_cost"])) == 1500
    # فروش از یکی روی دیگری اثر نمی‌گذارد
    r = client.post("/api/transactions", json={"tx_date": today().isoformat(), "tx_type": "sell", "asset_id": a2["id"], "quantity": "31", "unit_price": "1600"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "ledger_inconsistent"


# ---------------------------------------------------------------- بایگانی و حذف
def test_delete_without_transactions_and_block_with_transactions(client):
    _, plats = meta_ids(client)
    free = new_asset(client, plats["مفید"], name="بدون معامله")
    used = new_asset(client, plats["مفید"], name="با معامله")
    deposit(client, plats["مفید"])
    assert buy(client, used["id"], 10, 1000).status_code == 201
    assert client.delete(f"/api/assets/{free['id']}").status_code == 200
    assert client.get(f"/api/assets/{free['id']}").status_code == 404
    r = client.delete(f"/api/assets/{used['id']}")
    assert r.status_code == 409 and r.json()["error"]["code"] == "has_transactions"
    dep = client.get(f"/api/assets/{used['id']}/dependencies").json()
    assert dep["archive_only"] is True and dep["dependencies"]["transactions"] == 1
    # حذف دائمی هم برای دارایی دارای تراکنش ممنوع است
    assert client.post(f"/api/assets/{used['id']}/purge/request").status_code == 422
    assert client.get("/api/transactions").json()["total"] == 2


def test_archive_restore_keeps_history_and_pnl(client):
    _, plats = meta_ids(client)
    a = new_asset(client, plats["مفید"], name="صندوق آرشیوی", target_weight="0")
    deposit(client, plats["مفید"])
    assert buy(client, a["id"], 100, 1000, fee="500").status_code == 201
    price(client, a["id"], 1300)
    before = {x["id"]: x for x in client.get("/api/portfolio").json()["assets"]}[a["id"]]
    assert D(str(before["unrealized"])) == 100 * 1300 - (100 * 1000 + 500)
    r = client.post(f"/api/assets/{a['id']}/archive")
    assert r.json()["status"] == "archived"
    after = {x["id"]: x for x in client.get("/api/portfolio").json()["assets"]}[a["id"]]
    assert after["unrealized"] == before["unrealized"] and after["units"] == before["units"]  # سود/زیان پاک نمی‌شود
    assert len(client.get("/api/transactions", params={"asset_id": a["id"]}).json()["items"]) == 1
    assert D(str(client.get("/api/dashboard").json()["cards"]["total_value"])) > 0
    # خرید جدید برای دارایی بایگانی‌شده ممنوع؛ فروش مجاز است
    assert buy(client, a["id"], 1, 1000).status_code == 422
    r = client.post("/api/transactions", json={"tx_date": today().isoformat(), "tx_type": "sell", "asset_id": a["id"], "quantity": "10", "unit_price": "1300"})
    assert r.status_code == 201
    # در فهرست پیش‌فرض (live) نیست ولی در «all/archived» هست
    assert a["id"] not in [x["id"] for x in client.get("/api/assets", params={"status": "live"}).json()["assets"]]
    assert a["id"] in [x["id"] for x in client.get("/api/assets", params={"status": "archived"}).json()["assets"]]
    assert client.post(f"/api/assets/{a['id']}/restore").json()["status"] == "active"
    assert buy(client, a["id"], 1, 1000).status_code == 201


def test_archived_asset_excluded_from_purchase_suggestions(client):
    assets, plats = meta_ids(client)
    pf_assets = client.get("/api/portfolios").json()[0]
    deposit(client, plats["مفید"]); deposit(client, plats["بیت‌پین"])
    for a in assets.values():
        price(client, a["id"], 1000)
    rows = client.get("/api/rebalance", params={"source": "custom", "amount": "10000000"}).json()["rows"]
    assert any(r["asset_id"] == assets["صندوق آوند"]["id"] for r in rows)
    client.post(f"/api/assets/{assets['صندوق آوند']['id']}/archive")
    rows = client.get("/api/rebalance", params={"source": "custom", "amount": "10000000"}).json()["rows"]
    assert all(r["asset_id"] != assets["صندوق آوند"]["id"] for r in rows)


def test_purge_requires_multistep_confirmation(client):
    _, plats = meta_ids(client)
    a = new_asset(client, plats["مفید"], name="حذف دائمی")
    price(client, a["id"], 1000)
    # قیمت ثبت‌شده دارد: حذف ساده ممنوع
    assert client.delete(f"/api/assets/{a['id']}").status_code == 409
    req = client.post(f"/api/assets/{a['id']}/purge/request").json()
    assert req["dependencies"]["prices"] == 1 and req["phrase"]
    assert client.post(f"/api/assets/{a['id']}/purge/confirm", json={"token": req["token"], "phrase": "اشتباه"}).status_code == 422
    # توکن پس از تلاش ناموفق هنوز معتبر است؛ ولی توکن دارایی دیگر پذیرفته نمی‌شود
    other = new_asset(client, plats["مفید"], name="دیگر")
    assert client.post(f"/api/assets/{other['id']}/purge/confirm", json={"token": req["token"], "phrase": req["phrase"]}).status_code == 422
    r = client.post(f"/api/assets/{a['id']}/purge/confirm", json={"token": req["token"], "phrase": req["phrase"]})
    assert r.status_code == 200 and r.json()["removed"]["prices"] == 1
    assert client.get(f"/api/assets/{a['id']}").status_code == 404


# ---------------------------------------------------------------- صحت مالی
def test_changing_name_weight_and_source_never_alters_history(client):
    assets, plats = meta_ids(client)
    a = assets["صندوق اطلس"]
    deposit(client, plats["مفید"])
    assert buy(client, a["id"], 200, 2500, fee="1000").status_code == 201
    tx_before = client.get("/api/transactions").json()["items"]
    pos_before = {x["id"]: x for x in client.get("/api/portfolio").json()["assets"]}[a["id"]]
    prov = next(p for p in client.get("/api/market-data/providers").json() if p["kind"] == "manual")
    body = {k: a[k] for k in ("platform_id", "name", "name_en", "symbol", "asset_type", "market", "unit", "price_currency", "decimals",
                              "min_quantity", "target_weight", "initial_price", "buy_fee_rate", "is_active", "note")}
    body.update(name="نام جدید اطلس", target_weight="10", initial_price="9999",
                sources=[{"provider_id": prov["id"], "priority": 1}])
    assert client.put(f"/api/assets/{a['id']}", json=body).status_code == 200
    tx_after = client.get("/api/transactions").json()["items"]
    for k in ("unit_price", "quantity", "fee", "total_amount", "tx_date", "asset_id"):
        assert [t[k] for t in tx_before] == [t[k] for t in tx_after]
    pos_after = {x["id"]: x for x in client.get("/api/portfolio").json()["assets"]}[a["id"]]
    for k in ("units", "avg_cost", "cost_basis"):
        assert pos_after[k] == pos_before[k]
    assert D(str(pos_after["avg_cost"])) == D("2505")  # (200*2500 + 1000) / 200 — قیمت اولیهٔ اطلاعاتی اثری ندارد


# ---------------------------------------------------------------- سبدها
def test_new_portfolio_targets_and_independence(client):
    assets, plats = meta_ids(client)
    r = client.post("/api/portfolios", json={"name": "سبد رشد", "initial_capital": "50000000", "monthly_contribution": "10000000",
                                             "horizon_months": 6, "max_drawdown_pct": "30", "plan_start_date": today().isoformat()})
    assert r.status_code == 201
    pf = r.json()
    assert pf["member_count"] == 0 and D(str(pf["plan_target_total"])) == 110_000_000
    pid = pf["id"]
    a, b = assets["صندوق اطلس"], assets["صندوق عیار"]
    # مجموع ۱۰۰ نیست → رد
    r = client.put(f"/api/portfolios/{pid}/targets", json={"members": [{"asset_id": a["id"], "target_weight": "60"}, {"asset_id": b["id"], "target_weight": "30"}]})
    assert r.status_code == 422
    r = client.put(f"/api/portfolios/{pid}/targets", json={"members": [{"asset_id": a["id"], "target_weight": "60"}, {"asset_id": b["id"], "target_weight": "40"}]})
    assert r.status_code == 200 and r.json()["portfolio"]["targets_ok"] is True
    # دوره‌های برنامهٔ سبد جدید ساخته شده
    c = client.get("/api/contributions", params={"portfolio_id": pid}).json()
    assert len(c["periods"]) == 7 and D(str(c["target_total"])) == 110_000_000
    # تراکنش‌ها در هر سبد مستقل‌اند
    deposit(client, plats["مفید"], portfolio_id=pid)
    assert buy(client, a["id"], 10, 1000, portfolio_id=pid).status_code == 201
    main = {x["id"]: x for x in client.get("/api/portfolio").json()["assets"]}
    second = {x["id"]: x for x in client.get("/api/portfolio", params={"portfolio_id": pid}).json()["assets"]}
    assert D(str(second[a["id"]]["units"])) == 10 and D(str(main[a["id"]]["units"])) == 0
    # دارایی که عضو سبد نیست در آن خریده نمی‌شود
    assert buy(client, assets["صندوق آوند"]["id"], 1, 1000, portfolio_id=pid).status_code == 422
    # حذف دارایی از سبد → تراکنش‌ها می‌مانند
    r = client.delete(f"/api/portfolios/{pid}/assets/{a['id']}")
    assert r.status_code == 200 and r.json()["kept_transactions"] == 2 - 1  # فقط خرید این دارایی
    tx = client.get("/api/transactions").json()["items"]
    assert sum(1 for t in tx if t["portfolio_id"] == pid) == 2
    second = {x["id"]: x for x in client.get("/api/portfolio", params={"portfolio_id": pid}).json()["assets"]}
    assert D(str(second[a["id"]]["units"])) == 10  # همچنان در گزارش
    # سبد دارای تراکنش حذف نمی‌شود، بایگانی می‌شود
    assert client.delete(f"/api/portfolios/{pid}").status_code == 409
    assert client.post(f"/api/portfolios/{pid}/archive").json()["is_archived"] is True
    assert client.post(f"/api/portfolios/{pid}/restore").json()["is_archived"] is False


def test_portfolio_amount_mode_and_default_rules(client):
    assets, _ = meta_ids(client)
    pf = client.post("/api/portfolios", json={"name": "مبلغ ثابت", "target_mode": "amount"}).json()
    r = client.put(f"/api/portfolios/{pf['id']}/targets", json={"members": [
        {"asset_id": assets["صندوق عیار"]["id"], "target_amount": "30000000"},
        {"asset_id": assets["صندوق اطلس"]["id"], "target_amount": "10000000"}]})
    assert r.status_code == 200
    eff = {m["asset_id"]: D(str(m["effective_weight"])) for m in r.json()["portfolio"]["members"]}
    assert eff[assets["صندوق عیار"]["id"]] == 75 and eff[assets["صندوق اطلس"]["id"]] == 25
    # پیش‌فرض
    default = next(p for p in client.get("/api/portfolios").json() if p["is_default"])
    assert client.post(f"/api/portfolios/{default['id']}/archive").status_code == 422
    assert client.delete(f"/api/portfolios/{default['id']}").status_code == 422
    assert client.delete(f"/api/portfolios/{pf['id']}").status_code == 200
    assert client.post("/api/portfolios", json={"name": default["name"]}).status_code == 409


def test_new_asset_joins_default_portfolio_and_weight_sync(client):
    _, plats = meta_ids(client)
    a = new_asset(client, plats["مفید"], name="عضو سبد", target_weight="0")
    d = client.get("/api/portfolios").json()[0]
    pf = client.get(f"/api/portfolios/{d['id']}").json()
    assert a["id"] in [m["asset_id"] for m in pf["members"]]
    assert client.post(f"/api/portfolios/{d['id']}/assets", json={"asset_id": a["id"]}).status_code == 409
