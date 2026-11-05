"""v2.1 — لایهٔ کنترل کیفیت قیمت و مرکز هوشمندی قیمت‌ها.
همهٔ درخواست‌های بیرونی با MockTransport شبیه‌سازی می‌شوند؛ هیچ داده‌ای از شبکهٔ واقعی نیست."""
from datetime import date, datetime, timedelta
from decimal import Decimal as D

import httpx
import pytest

from app.errors import AppError  # noqa: F401  (اطمینان از import)
from app.services.marketdata import quality
from app.services.marketdata.base import ProviderError
from tests.test_marketdata import (Mock, custom_provider, enable, isolate_engine, make_asset, now, sources,  # noqa: F401
                                   tse_line)

INTEL = "/api/market-data/intelligence"


def fresh(minutes_ago=0):
    return (now() - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")


def asset_row(client, asset_id):
    items = client.get(f"{INTEL}/assets", params={"asset_id": asset_id}).json()["items"]
    return items[0]


def buy(client, asset_id, qty="100", amount="50000000"):
    plats = {x["name"]: x["id"] for x in client.get("/api/platforms").json()}
    client.post("/api/transactions", json={"tx_date": (date.today() - timedelta(days=3)).isoformat(), "tx_type": "deposit",
                                           "platform_id": plats["مفید"], "amount": amount})
    r = client.post("/api/transactions", json={"tx_date": (date.today() - timedelta(days=2)).isoformat(), "tx_type": "buy",
                                               "asset_id": asset_id, "quantity": qty, "unit_price": "10000"})
    assert r.status_code == 201, r.text


def purge_provider(client, pid):
    req = client.post(f"/api/market-data/providers/{pid}/purge/request")
    assert req.status_code == 200, req.text
    t = req.json()
    r = client.post(f"/api/market-data/providers/{pid}/purge/confirm", json={"token": t["token"], "phrase": t["phrase"]})
    assert r.status_code == 200, r.text


def holding(client, asset_id):
    return next(x for x in client.get("/api/portfolio").json()["assets"] if x["id"] == asset_id)


# ------------------------------------------------------------------- لایهٔ خالص
def test_assess_quote_rules():
    n = datetime(2026, 11, 4, 12, 0)
    kw = dict(now=n, asset_currency="IRT", max_age_days=3)
    ok = quality.assess_quote(raw_price=D("125000"), unit="IRR", source_time=n - timedelta(minutes=1), **kw)
    assert ok.valid and ok.price == D("12500") and "10" in ok.conversion_note and ok.raw_unit == "IRR" and ok.raw_price == D("125000")
    assert "unit_converted" in ok.flags
    for bad in (D("0"), D("-5")):
        a = quality.assess_quote(raw_price=bad, unit="IRT", source_time=n, **kw)
        assert not a.valid and "non_positive" in a.flags
    fut = quality.assess_quote(raw_price=D("5"), unit="IRT", source_time=n + timedelta(hours=3), **kw)
    assert not fut.valid and "future_time" in fut.flags
    old = quality.assess_quote(raw_price=D("5"), unit="IRT", source_time=n - timedelta(days=9), **kw)
    assert not old.valid and "stale" in old.flags
    nots = quality.assess_quote(raw_price=D("5"), unit="IRT", source_time=None, **kw)
    assert nots.valid and "no_source_time" in nots.flags
    jump = quality.assess_quote(raw_price=D("140"), unit="IRT", source_time=n, prev_price=D("100"), **kw)
    assert jump.valid and "jump" in jump.flags
    with pytest.raises(ProviderError) as e:
        quality.assess_quote(raw_price=D("5"), unit="USD", source_time=n, **kw)
    assert e.value.code == "currency_mismatch"
    lag = quality.assess_quote(raw_price=D("5"), unit="IRT", source_time=n - timedelta(hours=5), market="24h", **kw)
    assert lag.valid and "time_lag" in lag.flags


def test_convert_units_are_exact_and_traceable():
    assert quality.convert_unit(D("125000"), "IRR", "IRT") == D("12500")
    assert quality.convert_unit(D("12500"), "IRT", "IRR") == D("125000")
    assert quality.convert_unit(D("7"), "toman", "IRT") == D("7")
    assert quality.convert_unit(D("1.5"), "USD", "USD") == D("1.5")
    with pytest.raises(ProviderError):
        quality.convert_unit(D("1"), "USD", "IRT")  # بدون نرخ ارز تبدیل خاموش ممنوع است


# ------------------------------------------------------------------- ذخیرهٔ قیمت آنلاین
def test_online_price_is_stored_with_source_time_and_conversion_trace(client):
    from sqlalchemy import select
    from app import models as m
    from app.database import SessionLocal
    mock = Mock().install()
    mock.routes["/instinfofast.aspx"] = lambda req: tse_line(last=125000)
    ts = enable(client, "tsetmc")
    a = make_asset(client, sources=sources((ts["id"], "111222", {})))
    assert client.post(f"/api/assets/{a['id']}/refresh-price").json()["ok"]
    with SessionLocal() as db:
        p = db.scalar(select(m.Price).where(m.Price.asset_id == a["id"]))
        assert p.origin == "online" and p.source == "TSETMC" and p.fetched_at and p.source_time
        assert p.raw_price == D("125000") and p.raw_unit == "IRR" and p.price == D("12500") and "10" in p.conversion_note
        assert '"TSETMC"' in p.via
    row = asset_row(client, a["id"])
    assert row["status"] == "valid" and row["origin"] == "online" and D(str(row["price"])) == 12500
    lg = row["last_good"]
    assert D(str(lg["raw_price"])) == 125000 and lg["raw_unit"] == "IRR" and lg["conversion_note"]
    assert row["fx"] is None  # قیمت تومانی؛ نرخ ارز لازم نیست


def test_every_online_price_has_timestamp_and_source(client):
    from sqlalchemy import select
    from app import models as m
    from app.database import SessionLocal
    mock = Mock().install()
    mock.routes["/instinfofast.aspx"] = lambda req: tse_line(last=125000)
    mock.routes["/v1/quote/F"] = lambda req: {"data": {"price": "13000"}}  # بدون زمان منبع
    ts = enable(client, "tsetmc")
    cu = custom_provider(client, field_map={"price": "$.data.price"})
    a = make_asset(client, sources=sources((ts["id"], "1", {}), (cu["id"], "F", {})))
    client.post(f"/api/assets/{a['id']}/refresh-price?all_sources=true")
    with SessionLocal() as db:
        rows = list(db.scalars(select(m.Price).where(m.Price.origin == "online")))
        assert len(rows) == 2
        assert all(r.fetched_at is not None and r.source for r in rows)
        nots = next(r for r in rows if r.source == "API من")
        assert "no_source_time" in quality.flags_of(nots)  # زمان منبع نبود → برچسب و زمان دریافت ثبت شد


def test_manual_price_is_distinguishable_and_survives_provider_purge(client):
    from sqlalchemy import select
    from app import models as m
    from app.database import SessionLocal
    mock = Mock().install()
    mock.routes["/instinfofast.aspx"] = lambda req: tse_line(last=125000)
    ts = enable(client, "tsetmc")
    a = make_asset(client, sources=sources((ts["id"], "1", {})))
    client.post("/api/prices", json={"asset_id": a["id"], "price": "9000", "recorded_at": fresh(120)})
    client.post(f"/api/assets/{a['id']}/refresh-price")
    items = client.get("/api/prices", params={"asset_id": a["id"]}).json()
    items = items["items"] if isinstance(items, dict) else items
    assert {i["origin"] for i in items} == {"manual", "online"}
    # حذف کامل منبع، مبدأ قیمت ثبت‌شده را عوض نمی‌کند
    purge_provider(client, ts["id"])
    with SessionLocal() as db:
        online = list(db.scalars(select(m.Price).where(m.Price.asset_id == a["id"], m.Price.origin == "online")))
        manual = list(db.scalars(select(m.Price).where(m.Price.asset_id == a["id"], m.Price.origin == "manual")))
        assert len(online) == 1 and len(manual) == 1 and online[0].source == "TSETMC"


# ------------------------------------------------------------------- اختلاف منابع
def two_source_asset(client, second_price="15000"):
    mock = Mock().install()
    mock.routes["/instinfofast.aspx"] = lambda req: tse_line(last=125000)
    mock.routes["/v1/quote/F"] = lambda req: {"data": {"price": second_price, "updated": fresh(1)}}
    ts = enable(client, "tsetmc")
    cu = custom_provider(client)
    a = make_asset(client, sources=sources((ts["id"], "1", {}), (cu["id"], "F", {})))
    buy(client, a["id"])
    client.post(f"/api/assets/{a['id']}/refresh-price?all_sources=true")
    return mock, ts, cu, a


def test_source_disagreement_blocks_valuation_and_does_not_pick_a_price(client):
    mock, ts, cu, a = two_source_asset(client, "15000")  # ۱۲٬۵۰۰ در برابر ۱۵٬۰۰۰ = ۲۰٪ اختلاف
    row = asset_row(client, a["id"])
    assert row["status"] == "conflict" and row["comparison"]["conflict"] is True
    assert D(str(row["comparison"]["spread_pct"])) >= 10 and len(row["comparison"]["rows"]) == 2
    cur = next(x for x in client.get("/api/prices/current").json()["items"] if x["asset_id"] == a["id"])
    assert cur["ok"] is False and cur["reason"] == "conflict" and cur["price"] is None
    assert holding(client, a["id"])["value"] is None
    alerts = client.get(f"{INTEL}/alerts").json()
    dis = [x for x in alerts["items"] if x["type"] == "source_disagreement"]
    assert dis and dis[0]["severity"] == "critical" and dis[0]["asset_id"] == a["id"]


def test_conflict_resolved_by_explicit_user_decision_only(client):
    mock, ts, cu, a = two_source_asset(client, "15000")
    # قیمت دستی تازه = تصمیم صریح کاربر
    client.post("/api/prices", json={"asset_id": a["id"], "price": "13000", "recorded_at": fresh(0)})
    row = asset_row(client, a["id"])
    assert row["status"] == "manual" and D(str(row["price"])) == 13000
    assert D(str(holding(client, a["id"])["value"])) == 1_300_000
    assert not [x for x in client.get(f"{INTEL}/alerts").json()["items"] if x["type"] == "source_disagreement"]


def test_small_difference_is_not_a_conflict(client):
    mock, ts, cu, a = two_source_asset(client, "12800")  # ≈ ۲٫۴٪
    row = asset_row(client, a["id"])
    assert row["status"] == "valid" and row["comparison"]["conflict"] is False
    assert D(str(row["comparison"]["spread_pct"])) < 10


# ------------------------------------------------------------------- fallback
def test_fallback_used_only_if_valid_and_recorded(client):
    mock = Mock().install()
    mock.routes["/instinfofast.aspx"] = httpx.Response(503, text="down")
    mock.routes["/v1/quote/F"] = lambda req: {"data": {"price": "0", "updated": fresh(0)}}
    ts = enable(client, "tsetmc", retry_count=0)
    cu = custom_provider(client)
    a = make_asset(client, sources=sources((ts["id"], "1", {}), (cu["id"], "F", {})))
    r = client.post(f"/api/assets/{a['id']}/refresh-price").json()
    assert r["ok"] is False  # جایگزین صفر نامعتبر است و استفاده نمی‌شود
    assert asset_row(client, a["id"])["status"] in ("missing", "invalid")
    mock.routes["/v1/quote/F"] = lambda req: {"data": {"price": "13100", "updated": fresh(0)}}
    from app.services.marketdata.engine import get_engine
    get_engine().clear_cache()
    r = client.post(f"/api/assets/{a['id']}/refresh-price").json()
    assert r["ok"] and r["provider"] == "API من"
    row = asset_row(client, a["id"])
    assert row["using_fallback"] is True and row["primary_down"] is True and row["status"] == "valid"
    roles = {s["provider"]: s["role"] for s in row["sources"]}
    assert roles == {"TSETMC": "primary", "API من": "fallback"}
    via = row["last_good"]["via"]
    assert [v["provider"] for v in via] == ["TSETMC", "API من"] and via[0]["status"] != "ok"


def test_priority_change_swaps_primary_and_backup(client):
    mock, ts, cu, a = two_source_asset(client, "12800")
    body = [{"provider_id": cu["id"], "external_id": "F", "priority": 1}, {"provider_id": ts["id"], "external_id": "1", "priority": 2}]
    assert client.put(f"/api/assets/{a['id']}/price-sources", json=body).status_code == 200
    row = asset_row(client, a["id"])
    assert [(s["provider"], s["role"]) for s in row["sources"]] == [("API من", "primary"), ("TSETMC", "fallback")]


def test_last_good_price_and_latest_attempt_are_separate(client):
    mock = Mock().install()
    mock.routes["/instinfofast.aspx"] = lambda req: tse_line(last=125000)
    ts = enable(client, "tsetmc", retry_count=0)
    a = make_asset(client, sources=sources((ts["id"], "1", {})))
    client.post(f"/api/assets/{a['id']}/refresh-price")
    mock.routes["/instinfofast.aspx"] = httpx.Response(500, text="boom")
    from app.services.marketdata.engine import get_engine
    get_engine().clear_cache()
    client.post(f"/api/assets/{a['id']}/refresh-price")
    row = asset_row(client, a["id"])
    assert D(str(row["price"])) == 12500 and row["status"] == "valid"          # آخرین قیمت موفق حفظ می‌شود
    assert row["latest_attempt"]["status"] == "error" and row["latest_attempt"]["error"]  # وضعیت واکشی جدید جداست


# ------------------------------------------------------------------- هشدارها
def alert_types(client, **params):
    return {(x["type"], x["asset_id"], x["provider_id"]) for x in client.get(f"{INTEL}/alerts", params=params).json()["items"]}


def test_provider_down_alert_after_consecutive_failures(client):
    mock = Mock().install()
    mock.routes["/instinfofast.aspx"] = httpx.Response(503, text="down")
    ts = enable(client, "tsetmc", retry_count=0)
    a = make_asset(client, sources=sources((ts["id"], "1", {})))
    from app.services.marketdata.engine import get_engine
    for _ in range(3):
        get_engine().clear_cache()
        client.post(f"/api/assets/{a['id']}/refresh-price")
    types = {t[0] for t in alert_types(client)}
    assert "provider_down" in types
    assert asset_row(client, a["id"])["primary_down"] is True
    ov = client.get(f"{INTEL}/overview").json()
    assert ov["summary"]["error"] == 1 and ov["summary"]["enabled"] == 2 and ov["summary"]["requests"] == 3
    assert ov["summary"]["success_rate"] == 0


def test_wrong_currency_alert(client):
    mock = Mock().install()
    mock.routes["/v1/quote/F"] = lambda req: {"data": {"price": "187.2", "updated": fresh(0)}}
    cu = custom_provider(client, input_currency="USD")
    a = make_asset(client, sources=sources((cu["id"], "F", {})))
    r = client.post(f"/api/assets/{a['id']}/refresh-price").json()
    assert r["ok"] is False and r["attempts"][0]["status"] == "currency_mismatch"
    assert "wrong_currency" in {t[0] for t in alert_types(client)}
    assert asset_row(client, a["id"])["status"] == "missing"


def test_future_time_and_time_lag_alerts(client):
    mock = Mock().install()
    mock.routes["/instinfofast.aspx"] = lambda req: tse_line(last=125000, when=now() + timedelta(days=2))
    mock.routes["/v1/quote/F"] = lambda req: {"data": {"price": "13000", "updated": fresh(300)}}  # ۵ ساعت قدیمی در بازار ۲۴ساعته
    ts = enable(client, "tsetmc", retry_count=0)
    cu = custom_provider(client, market="24h")
    a = make_asset(client, sources=sources((ts["id"], "1", {}), (cu["id"], "F", {})))
    client.post(f"/api/assets/{a['id']}/refresh-price")
    al = [x for x in client.get(f"{INTEL}/alerts").json()["items"] if x["type"] == "time_mismatch"]
    assert {x["provider"] for x in al} == {"TSETMC", "API من"}
    row = asset_row(client, a["id"])
    assert row["status"] == "valid"  # قیمت دارای تأخیر با برچسب معتبر است؛ قیمت آینده هرگز
    assert "time_lag" in row["last_good"]["flags"]


def test_sharp_change_alert_and_invalid_price_never_valued(client):
    mock = Mock().install()
    ph = {"p": ("10000", 20)}
    mock.routes["/v1/quote/F"] = lambda req: {"data": {"price": ph["p"][0], "updated": fresh(ph["p"][1])}}
    cu = custom_provider(client)
    a = make_asset(client, sources=sources((cu["id"], "F", {})))
    from app.services.marketdata.engine import get_engine
    client.post(f"/api/assets/{a['id']}/refresh-price")
    ph["p"] = ("14000", 5)
    get_engine().clear_cache()
    client.post(f"/api/assets/{a['id']}/refresh-price")
    sc = [x for x in client.get(f"{INTEL}/alerts").json()["items"] if x["type"] == "sharp_change"]
    assert sc and sc[0]["asset_id"] == a["id"] and sc[0]["value"] > 20
    assert D(str(asset_row(client, a["id"])["price"])) == 14000  # تغییر شدید برچسب می‌خورد اما قیمت واقعی منبع حذف نمی‌شود


def test_stale_price_alert_and_label(client):
    a = make_asset(client)
    client.post("/api/prices", json={"asset_id": a["id"], "price": "9000", "recorded_at": (now() - timedelta(days=10)).isoformat(timespec="seconds")})
    row = asset_row(client, a["id"])
    assert row["status"] == "stale" and row["status_text"] == "قدیمی" and row["price"] is not None and row["age_days"] >= 10
    assert "stale_price" in {t[0] for t in alert_types(client)}
    buy(client, a["id"])
    assert holding(client, a["id"])["value"] is None  # قیمت کهنه در ارزش‌گذاری نمی‌آید


def test_approving_invalid_price_is_rejected(client):
    from sqlalchemy import select
    from app import models as m
    from app.database import SessionLocal
    a = make_asset(client)
    with SessionLocal() as db:
        p = m.Price(asset_id=a["id"], price=D("0"), currency="IRT", recorded_at=now(), source="X", is_approved=False, is_valid=False,
                    validity_note="صفر", origin="online", fetched_at=now())
        db.add(p)
        db.commit()
        pid = p.id
    r = client.post(f"/api/prices/{pid}/approve")
    assert r.status_code == 422
    with SessionLocal() as db:
        assert db.get(m.Price, pid).is_approved is False


# ------------------------------------------------------------------- گزارش‌ها و لاگ‌ها
def test_provider_stats_performance_and_filtered_logs(client):
    mock = Mock().install()
    mock.routes["/instinfofast.aspx"] = lambda req: tse_line(last=125000)
    ts = enable(client, "tsetmc", retry_count=0)
    a = make_asset(client, name="الف", sources=sources((ts["id"], "1", {})))
    b = make_asset(client, name="ب", sources=sources((ts["id"], "2", {})))
    client.post(f"/api/assets/{a['id']}/refresh-price")
    mock.routes["/instinfofast.aspx"] = httpx.Response(500, text="x")
    client.post(f"/api/assets/{b['id']}/refresh-price")
    ov = client.get(f"{INTEL}/overview", params={"days": 3}).json()
    row = next(p for p in ov["providers"] if p["name"] == "TSETMC")
    assert row["requests"] == 2 and row["ok"] == 1 and row["errors"] == 1 and row["success_rate"] == 50.0
    assert row["avg_latency_ms"] is not None
    perf = client.get(f"{INTEL}/performance", params={"days": 3, "provider_id": ts["id"]}).json()
    assert len(perf["days"]) >= 3 and perf["series"][0]["total"]["requests"] == 2
    today = date.today().isoformat()
    logs = client.get(f"{INTEL}/logs", params={"provider_id": ts["id"], "date_from": today, "date_to": today}).json()
    assert logs["total"] == 2
    assert client.get(f"{INTEL}/logs", params={"asset_id": b["id"]}).json()["total"] == 1
    assert client.get(f"{INTEL}/logs", params={"status": "error"}).json()["total"] == 1
    assert client.get(f"{INTEL}/logs", params={"date_to": (date.today() - timedelta(days=2)).isoformat()}).json()["total"] == 0
    assert client.get(f"{INTEL}/logs", params={"page_size": 5, "page": 2}).json()["items"] == []
    assert client.get(f"{INTEL}/assets", params={"status": "bogus"}).status_code == 422


def test_fresh_database_shows_no_prices_at_all(client):
    items = client.get(f"{INTEL}/assets").json()["items"]
    assert items and all(r["status"] == "missing" and r["price"] is None for r in items)
    assert client.get(f"{INTEL}/alerts").json()["total"] == 0
    assert client.get(f"{INTEL}/overview").json()["summary"]["requests"] == 0


# ------------------------------------------------------------------- یکپارچگی تاریخچه
def test_changing_or_deleting_sources_never_changes_transactions_or_prices(client):
    from sqlalchemy import select
    from app import models as m
    from app.database import SessionLocal
    mock, ts, cu, a = two_source_asset(client, "12800")
    client.post("/api/prices", json={"asset_id": a["id"], "price": "12600", "recorded_at": fresh(0)})
    before_pf = client.get("/api/portfolio").json()
    before_tx = client.get("/api/transactions").json()
    with SessionLocal() as db:
        before_prices = [(p.id, p.price, p.source, p.origin, p.recorded_at) for p in db.scalars(select(m.Price).order_by(m.Price.id))]
    # جایگزینی منابع دارایی با فهرست خالی، سپس حذف کامل یک منبع
    assert client.put(f"/api/assets/{a['id']}/price-sources", json=[]).status_code == 200
    client.put(f"/api/assets/{a['id']}/price-sources", json=[{"provider_id": cu["id"], "external_id": "F", "priority": 1}])
    purge_provider(client, cu["id"])
    with SessionLocal() as db:
        after_prices = [(p.id, p.price, p.source, p.origin, p.recorded_at) for p in db.scalars(select(m.Price).order_by(m.Price.id))]
    assert after_prices == before_prices
    assert client.get("/api/transactions").json() == before_tx
    after_pf = client.get("/api/portfolio").json()
    assert after_pf["assets"] == before_pf["assets"]
