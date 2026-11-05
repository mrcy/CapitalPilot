"""موتور داده بازار: ارائه‌دهنده‌ها، دریافت قیمت، اعتبارسنجی، fallback، قیمت کهنه، تکراری، زمان‌بند.
همهٔ درخواست‌ها با httpx.MockTransport شبیه‌سازی می‌شوند (بدون دسترسی به شبکه)."""
import json
from datetime import datetime, timedelta
from decimal import Decimal as D

import httpx
import pytest


@pytest.fixture(autouse=True)
def isolate_engine():
    from app.services.marketdata import http
    from app.services.marketdata.engine import get_engine
    from app.services.marketdata.providers import bitpin
    get_engine().clear_cache()
    bitpin.clear_cache()
    yield
    http.set_test_transport(None)
    get_engine().clear_cache()
    bitpin.clear_cache()


class Mock:
    """پاسخ‌های قابل برنامه‌ریزی؛ هر درخواست ثبت می‌شود."""

    def __init__(self):
        self.routes: dict[str, object] = {}
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        for path, resp in self.routes.items():
            if request.url.path.endswith(path):
                r = resp(request) if callable(resp) else resp
                if isinstance(r, httpx.Response):
                    return r
                if isinstance(r, str):
                    return httpx.Response(200, text=r)
                return httpx.Response(200, json=r)
        return httpx.Response(404, text="not found")

    def install(self):
        from app.services.marketdata import http
        http.set_test_transport(httpx.MockTransport(self))
        return self

    def count(self, path: str) -> int:
        return sum(1 for c in self.calls if c.url.path.endswith(path))


def now():
    from app.services.clock import now_local
    return now_local()


def tse_line(last=125000, close=124000, when=None, nav="", nav_date=""):
    when = when or now()
    f = ["0"] * 17
    f[0], f[1], f[2], f[3], f[4], f[5] = "x", "I", str(last), str(close), "123000", "122000"
    f[6], f[7], f[9] = "126000", "121000", "5000"
    f[12], f[13] = when.strftime("%Y%m%d"), when.strftime("%H%M%S")
    f[14], f[15] = nav_date, nav
    return ",".join(f) + ";0,0,0;"


def pv_by_kind(client, kind):
    return next(p for p in client.get("/api/market-data/providers").json() if p["kind"] == kind)


def make_asset(client, name="صندوق تست", platform="مفید", currency="IRT", sources=None, **kw):
    plats = {p["name"]: p["id"] for p in client.get("/api/platforms").json()}
    body = {"platform_id": plats[platform], "name": name, "symbol": "تست", "asset_type": "fund", "price_currency": currency,
            "sources": sources or []}
    body.update(kw)
    r = client.post("/api/assets", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def enable(client, kind, **patch):
    p = pv_by_kind(client, kind)
    body = {k: p[k] for k in ("name", "kind", "base_url", "auth_type", "auth_param_name", "request_params", "field_map", "config",
                              "input_currency", "market", "refresh_interval_minutes", "min_interval_seconds", "retry_count",
                              "retry_delay_seconds", "timeout_seconds", "auto_approve")}
    body.update(is_enabled=True, min_interval_seconds="0", retry_delay_seconds="0")
    body.update(patch)
    r = client.put(f"/api/market-data/providers/{p['id']}", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def custom_provider(client, name="API من", **kw):
    body = {"name": name, "kind": "custom_api", "is_enabled": True, "base_url": "https://prices.example.com/v1/quote/{symbol}",
            "auth_type": "header", "auth_param_name": "X-API-KEY", "api_key": "SECRET-KEY-123",
            "field_map": {"price": "$.data.price", "time": "$.data.updated"}, "input_currency": "IRT",
            "min_interval_seconds": "0", "retry_delay_seconds": "0", "retry_count": 0, "auto_approve": True}
    body.update(kw)
    r = client.post("/api/market-data/providers", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def sources(*pairs):
    return [{"provider_id": pid, "external_id": ext, "priority": i + 1, **extra} for i, (pid, ext, extra) in enumerate(pairs)]


# ------------------------------------------------------------------- ارائه‌دهنده‌ها
def test_default_providers_disabled_and_keys_never_returned(client):
    provs = {p["kind"]: p for p in client.get("/api/market-data/providers").json()}
    assert set(provs) >= {"tsetmc", "bitpin", "streamdata", "servix", "custom_api", "manual"}
    assert provs["manual"]["is_enabled"] and not provs["tsetmc"]["is_enabled"]
    p = custom_provider(client)
    assert p["has_api_key"] is True and "api_key" not in p and "api_key_enc" not in p
    assert "SECRET-KEY-123" not in json.dumps(client.get("/api/market-data/providers").json())
    # در دیتابیس رمز شده است
    from app.database import SessionLocal
    from app import models as m
    with SessionLocal() as db:
        row = db.get(m.PriceProvider, p["id"])
        assert row.api_key_enc and "SECRET-KEY-123" not in row.api_key_enc
    # پشتیبان‌گیری کلید را شامل نمی‌شود
    assert "SECRET-KEY-123" not in client.get("/api/backup/export").text
    assert "api_key_enc" not in client.get("/api/backup/export").text


def test_provider_validation(client):
    bad = {"name": "بد", "kind": "custom_api", "base_url": "http://x.example.com/q", "auth_type": "bearer", "api_key": "k"}
    assert client.post("/api/market-data/providers", json=bad).status_code == 422          # کلید روی http
    bad = {"name": "بد۲", "kind": "custom_api", "base_url": "https://x.example.com", "field_map": {"price": "$.a[b"}}
    assert client.post("/api/market-data/providers", json=bad).status_code == 422          # مسیر JSON نامعتبر
    bad = {"name": "بد۳", "kind": "custom_api", "is_enabled": True, "base_url": "https://x.example.com"}
    assert client.post("/api/market-data/providers", json=bad).status_code == 422          # فعال بدون مسیر قیمت
    # اندپوینت بدون کلید حتی با env خالی فعال نمی‌شود
    sd = pv_by_kind(client, "streamdata")
    r = client.post(f"/api/market-data/providers/{sd['id']}/enable")
    assert r.status_code == 422


def test_connect_custom_provider_and_test_connection(client):
    mock = Mock().install()
    mock.routes["/v1/quote/AAPL"] = lambda req: {"data": {"price": "187.25", "updated": now().isoformat(timespec="seconds")}}
    p = custom_provider(client, input_currency="USD", config={"sample_symbol": "AAPL"})
    r = client.post(f"/api/market-data/providers/{p['id']}/test", json={"external_id": "AAPL"}).json()
    assert r["ok"] is True and D(str(r["quote"]["price"])) == D("187.25") and r["quote"]["unit"] == "USD"
    assert mock.calls[-1].headers["X-API-KEY"] == "SECRET-KEY-123"
    assert "SECRET-KEY-123" not in json.dumps(r)
    after = client.get(f"/api/market-data/providers/{p['id']}").json()
    assert after["last_status"] == "ok" and after["last_success_at"]
    # خطای احراز هویت پیام فارسی و کد مشخص می‌دهد
    mock.routes["/v1/quote/AAPL"] = httpx.Response(401, text="no")
    r = client.post(f"/api/market-data/providers/{p['id']}/test", json={"external_id": "AAPL"}).json()
    assert r["ok"] is False and r["error"]["code"] == "auth"
    assert client.get(f"/api/market-data/providers/{p['id']}").json()["last_error"]


def test_tsetmc_provider_quote_fields_search_history(client):
    mock = Mock().install()
    mock.routes["/instinfofast.aspx"] = lambda req: tse_line(nav="118500", nav_date=now().strftime("%Y%m%d"))
    mock.routes["/search.aspx"] = "عیار,صندوق طلا عیار,111222,x,x,x,x,1;اطلس,صندوق اطلس,333444,x,x,x,x,0"
    hist_rows = "\n".join(f"X,{(now() - timedelta(days=i)).strftime('%Y%m%d')},1,1,1,{1000 + i},1,1,0,D,1,1" for i in range(1, 4))
    mock.routes["/Export-txt.aspx"] = "<TICKER>,<DTYYYYMMDD>,<FIRST>,<HIGH>,<LOW>,<CLOSE>,<VALUE>,<VOL>,<OPENINT>,<PER>,<OPEN>,<LAST>\n" + hist_rows
    ts = enable(client, "tsetmc")
    from app.services.marketdata.providers import build_provider
    from app.services.marketdata.service import to_config
    from app.database import SessionLocal
    from app import models as m
    with SessionLocal() as db:
        prov = build_provider(to_config(db.get(m.PriceProvider, ts["id"])))
    last = prov.get_quote("111222", "last")
    assert last.price == 125000 and last.unit == "IRR" and last.kind == "last"
    assert prov.get_quote("111222", "close").price == 124000
    nav = prov.get_quote("111222", "nav")
    assert nav.price == 118500 and nav.kind == "nav"
    found = client.get(f"/api/market-data/providers/{ts['id']}/search", params={"q": "عیار"}).json()["items"]
    assert [f["external_id"] for f in found] == ["111222", "333444"] and found[0]["symbol"] == "عیار"
    hist = prov.get_history("111222", (now() - timedelta(days=10)).date(), now().date())
    assert [h.price for h in hist] == [D(1003), D(1002), D(1001)]
    # شناسهٔ نامعتبر قبل از ارسال درخواست رد می‌شود
    from app.services.marketdata.base import ProviderError
    with pytest.raises(ProviderError):
        prov.get_quote("1;rm", "last")
    # NAV بدون مقدار معتبر
    mock.routes["/instinfofast.aspx"] = lambda req: tse_line(nav="", nav_date="")
    with pytest.raises(ProviderError) as e:
        prov.get_quote("111222", "nav")
    assert e.value.code == "no_data"


def test_bitpin_single_market_and_basket_rejected(client):
    mock = Mock().install()
    mock.routes["/mkt/tickers/"] = [{"symbol": "BTC_IRT", "price": "6500000000", "high": "6600000000", "low": "6400000000", "daily_change_price": 1.5},
                                    {"symbol": "ETH_USDT", "price": "3200.5", "daily_change_price": -0.4}]
    mock.routes["/tv/get_bars/"] = lambda req: [{"ts": int((now() - timedelta(days=1)).timestamp()), "open": "1", "high": "2", "low": "1", "close": "1500", "volume": "3"}]
    bp = enable(client, "bitpin")
    r = client.post(f"/api/market-data/providers/{bp['id']}/test", json={"external_id": "BTC_IRT"}).json()
    assert r["ok"] and D(str(r["quote"]["price"])) == 6_500_000_000 and r["quote"]["unit"] == "IRT"
    assert r["quote"]["extra"]["change_24h_pct"] == "1.5"
    usdt = client.post(f"/api/market-data/providers/{bp['id']}/test", json={"external_id": "ETH_USDT"}).json()
    assert usdt["quote"]["unit"] == "USDT"
    basket = client.post(f"/api/market-data/providers/{bp['id']}/test", json={"external_id": "سرمایه پایدار"}).json()
    assert basket["ok"] is False and basket["error"]["code"] == "config" and "سبد" in basket["error"]["message"]
    found = client.get(f"/api/market-data/providers/{bp['id']}/search", params={"q": "btc"}).json()["items"]
    assert [f["external_id"] for f in found] == ["BTC_IRT"]


# ------------------------------------------------------------------- دریافت و ذخیرهٔ قیمت
def test_fetch_price_converts_rial_to_toman_and_records_fields(client):
    mock = Mock().install()
    mock.routes["/instinfofast.aspx"] = lambda req: tse_line(last=125000)
    ts = enable(client, "tsetmc")
    a = make_asset(client, sources=sources((ts["id"], "111222", {"price_field": "last"})))
    r = client.post(f"/api/assets/{a['id']}/refresh-price").json()
    assert r["ok"] and r["status"] == "ok" and D(str(r["price"])) == 12500  # ۱۲۵٬۰۰۰ ریال = ۱۲٬۵۰۰ تومان
    h = client.get("/api/market-data/history", params={"asset_id": a["id"]}).json()
    pt = h["series"][0]["points"][0]
    assert D(str(pt["price"])) == 12500 and pt["is_valid"] and pt["is_approved"] and pt["kind"] == "last"
    from app.database import SessionLocal
    from app import models as m
    from sqlalchemy import select
    with SessionLocal() as db:
        p = db.scalar(select(m.Price).where(m.Price.asset_id == a["id"]))
        assert p.provider_id == ts["id"] and p.currency == "IRT" and p.fetched_at and p.source_time and p.source == "TSETMC"
    # قیمت در ارزش‌گذاری استفاده می‌شود
    plats = {x["name"]: x["id"] for x in client.get("/api/platforms").json()}
    from datetime import date
    client.post("/api/transactions", json={"tx_date": (date.today() - timedelta(days=3)).isoformat(), "tx_type": "deposit", "platform_id": plats["مفید"], "amount": "10000000"})
    client.post("/api/transactions", json={"tx_date": (date.today() - timedelta(days=2)).isoformat(), "tx_type": "buy", "asset_id": a["id"], "quantity": "100", "unit_price": "10000"})
    row = next(x for x in client.get("/api/portfolio").json()["assets"] if x["id"] == a["id"])
    assert D(str(row["value"])) == 1_250_000 and D(str(row["avg_cost"])) == 10000  # بهای خرید مستقل از قیمت بازار


def test_invalid_prices_are_recorded_but_never_valued(client):
    mock = Mock().install()
    ts = enable(client, "tsetmc")
    a = make_asset(client, sources=sources((ts["id"], "111222", {})))
    # صفر / ساختار نامعتبر / قیمت آینده / قیمت کهنه
    mock.routes["/instinfofast.aspx"] = lambda req: tse_line(last=0)
    r = client.post(f"/api/assets/{a['id']}/refresh-price").json()
    assert not r["ok"] and r["status"] == "unavailable" and r["attempts"][0]["status"] in ("invalid", "no_data")
    mock.routes["/instinfofast.aspx"] = lambda req: tse_line(last=125000, when=now() + timedelta(days=2))
    r = client.post(f"/api/assets/{a['id']}/refresh-price").json()
    assert not r["ok"] and r["attempts"][0]["status"] == "invalid"
    mock.routes["/instinfofast.aspx"] = lambda req: tse_line(last=125000, when=now() - timedelta(days=30))
    from app.services.marketdata.engine import get_engine
    get_engine().clear_cache()
    r = client.post(f"/api/assets/{a['id']}/refresh-price").json()
    assert not r["ok"] and r["attempts"][0]["status"] == "stale"
    pts = client.get("/api/market-data/history", params={"asset_id": a["id"]}).json()["series"]
    assert pts and all(not p["is_valid"] for p in pts[0]["points"])
    # هیچ‌کدام در ارزش‌گذاری/قیمت جاری وارد نمی‌شوند
    cur = next(x for x in client.get("/api/prices/current").json()["items"] if x["asset_id"] == a["id"])
    assert cur["ok"] is False and cur["price"] is None
    logs = client.get("/api/market-data/logs", params={"asset_id": a["id"]}).json()
    assert len(logs) >= 3 and all(not l["ok"] for l in logs)


def test_primary_down_falls_back_to_secondary_and_logs_error(client):
    mock = Mock().install()
    mock.routes["/instinfofast.aspx"] = httpx.Response(503, text="down")
    mock.routes["/v1/quote/FUND1"] = lambda req: {"data": {"price": "13100", "updated": now().isoformat(timespec="seconds")}}
    ts = enable(client, "tsetmc", retry_count=0)
    cu = custom_provider(client)
    a = make_asset(client, sources=sources((ts["id"], "111222", {}), (cu["id"], "FUND1", {})))
    r = client.post(f"/api/assets/{a['id']}/refresh-price").json()
    assert r["ok"] and r["provider"] == "API من" and D(str(r["price"])) == 13100
    assert [x["ok"] for x in r["attempts"]] == [False, True] and r["attempts"][0]["status"] == "http"
    logs = client.get("/api/market-data/logs", params={"only_errors": "true"}).json()
    assert len(logs) == 1 and logs[0]["provider"] == "TSETMC" and "503" in logs[0]["message"]
    assert client.get(f"/api/market-data/providers/{ts['id']}").json()["last_status"] == "error"
    assert client.get(f"/api/market-data/providers/{cu['id']}").json()["last_status"] == "ok"
    # priority از ابتدا: اگر اولی سالم باشد دومی صدا زده نمی‌شود
    mock.routes["/instinfofast.aspx"] = lambda req: tse_line(last=125000, when=now() + timedelta(seconds=1))
    n = mock.count("/v1/quote/FUND1")
    client.post(f"/api/assets/{a['id']}/refresh-price")
    assert mock.count("/v1/quote/FUND1") == n


def test_all_sources_fail_reports_unavailable_and_old_price_not_shown_as_live(client):
    mock = Mock().install()
    ts = enable(client, "tsetmc", retry_count=0)
    a = make_asset(client, sources=sources((ts["id"], "111222", {})))
    # قیمت دستی قدیمی (۱۰ روز پیش)
    client.post("/api/prices", json={"asset_id": a["id"], "price": "9000", "recorded_at": (now() - timedelta(days=10)).isoformat(timespec="seconds")})
    mock.routes["/instinfofast.aspx"] = httpx.Response(500, text="x")
    r = client.post(f"/api/assets/{a['id']}/refresh-price").json()
    assert r["ok"] is False and r["status"] == "unavailable" and r["stale"] is True
    assert "در دسترس نیست" in r["message"]
    cur = client.get("/api/market-data/status").json()
    assert cur["stale_prices"] >= 1
    # قیمت قدیمی در ارزش‌گذاری نمی‌آید
    plats = {x["name"]: x["id"] for x in client.get("/api/platforms").json()}
    from datetime import date
    client.post("/api/transactions", json={"tx_date": (date.today() - timedelta(days=12)).isoformat(), "tx_type": "deposit", "platform_id": plats["مفید"], "amount": "5000000"})
    client.post("/api/transactions", json={"tx_date": (date.today() - timedelta(days=11)).isoformat(), "tx_type": "buy", "asset_id": a["id"], "quantity": "10", "unit_price": "8000"})
    row = next(x for x in client.get("/api/portfolio").json()["assets"] if x["id"] == a["id"])
    assert row["value"] is None
    assert client.get("/api/dashboard").json()["valuation_complete"] is False


def test_duplicate_price_not_stored_twice(client):
    mock = Mock().install()
    when = now() - timedelta(minutes=5)
    mock.routes["/instinfofast.aspx"] = lambda req: tse_line(last=125000, when=when)
    ts = enable(client, "tsetmc")
    a = make_asset(client, sources=sources((ts["id"], "111222", {})))
    from app.services.marketdata.engine import get_engine
    r1 = client.post(f"/api/assets/{a['id']}/refresh-price").json()
    get_engine().clear_cache()
    r2 = client.post(f"/api/assets/{a['id']}/refresh-price").json()
    assert r1["status"] == "ok" and r2["status"] == "duplicate" and r2["ok"]
    pts = client.get("/api/market-data/history", params={"asset_id": a["id"]}).json()["series"][0]["points"]
    assert len(pts) == 1
    # قیمت جدید با زمان منبع جدید ثبت می‌شود
    mock.routes["/instinfofast.aspx"] = lambda req: tse_line(last=126000, when=when + timedelta(minutes=2))
    get_engine().clear_cache()
    assert client.post(f"/api/assets/{a['id']}/refresh-price").json()["status"] == "ok"
    assert len(client.get("/api/market-data/history", params={"asset_id": a["id"]}).json()["series"][0]["points"]) == 2


def test_unapproved_prices_do_not_enter_valuation_until_approved(client):
    mock = Mock().install()
    mock.routes["/v1/quote/Z"] = lambda req: {"data": {"price": "5000", "updated": now().isoformat(timespec="seconds")}}
    cu = custom_provider(client, auto_approve=False)
    a = make_asset(client, sources=sources((cu["id"], "Z", {})))
    r = client.post(f"/api/assets/{a['id']}/refresh-price").json()
    assert r["ok"] and r["approved"] is False and "تأیید" in r["message"]
    plats = {x["name"]: x["id"] for x in client.get("/api/platforms").json()}
    from datetime import date
    client.post("/api/transactions", json={"tx_date": (date.today() - timedelta(days=1)).isoformat(), "tx_type": "deposit", "platform_id": plats["مفید"], "amount": "1000000"})
    client.post("/api/transactions", json={"tx_date": (date.today() - timedelta(days=1)).isoformat(), "tx_type": "buy", "asset_id": a["id"], "quantity": "10", "unit_price": "4000"})
    row = lambda: next(x for x in client.get("/api/portfolio").json()["assets"] if x["id"] == a["id"])
    assert row()["value"] is None
    pid = client.get("/api/market-data/history", params={"asset_id": a["id"]}).json()["series"][0]["points"][0]["id"]
    assert client.post(f"/api/prices/{pid}/approve").status_code == 200
    assert D(str(row()["value"])) == 50000


def test_foreign_currency_price_needs_fx_not_silently_converted(client):
    mock = Mock().install()
    mock.routes["/v1/quote/SPY"] = lambda req: {"data": {"price": "500.5", "updated": now().isoformat(timespec="seconds")}}
    cu = custom_provider(client, name="خارجی", input_currency="USD")
    a = make_asset(client, name="شاخص خارجی", platform="بازار خارجی", currency="USD", sources=sources((cu["id"], "SPY", {})))
    r = client.post(f"/api/assets/{a['id']}/refresh-price").json()
    assert r["ok"] and D(str(r["price"])) == D("500.5") and r["currency"] == "USD"
    # دارایی تومانی با منبع دلاری: ثبت نمی‌شود (تبدیل ارز خودکار نداریم)
    b = make_asset(client, name="دارایی تومانی", sources=sources((cu["id"], "SPY", {})))
    r = client.post(f"/api/assets/{b['id']}/refresh-price").json()
    assert not r["ok"] and r["attempts"][0]["status"] == "currency_mismatch"


def test_retry_with_backoff_and_cache_prevents_duplicate_requests(client):
    from app.database import SessionLocal
    from app import models as m
    from app.services.marketdata.engine import MarketDataEngine
    calls = {"n": 0}

    def flaky(req):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, text="x")
        return {"data": {"price": "100", "updated": now().isoformat(timespec="seconds")}}

    mock = Mock().install()
    mock.routes["/v1/quote/Q"] = flaky
    cu = custom_provider(client, retry_count=3, retry_delay_seconds="2")
    sleeps = []
    eng = MarketDataEngine(sleep=sleeps.append, cache_ttl=60)
    with SessionLocal() as db:
        pv = db.get(m.PriceProvider, cu["id"])
        q, cached, _ = eng.fetch_quote(pv, "Q")
        assert q.price == 100 and not cached and calls["n"] == 3 and sleeps == [2.0, 4.0]  # backoff نمایی
        q2, cached2, _ = eng.fetch_quote(pv, "Q")
        assert cached2 and calls["n"] == 3  # از کش، بدون درخواست تکراری
        # خطای غیرقابل‌تکرار (۴۰۱) تکرار نمی‌شود
        mock.routes["/v1/quote/R"] = httpx.Response(401, text="x")
        from app.services.marketdata.base import ProviderError
        before = len(mock.calls)
        with pytest.raises(ProviderError):
            eng.fetch_quote(pv, "R")
        assert len(mock.calls) == before + 1


def test_rate_limit_throttles_between_requests(client):
    from app.database import SessionLocal
    from app import models as m
    from app.services.marketdata.engine import MarketDataEngine
    mock = Mock().install()
    mock.routes["/v1/quote/Q"] = lambda req: {"data": {"price": "100", "updated": now().isoformat(timespec="seconds")}}
    cu = custom_provider(client, min_interval_seconds="2")
    clock = {"t": 100.0}
    sleeps = []

    def sleep(s):
        sleeps.append(s)
        clock["t"] += s

    eng = MarketDataEngine(sleep=sleep, monotonic=lambda: clock["t"], cache_ttl=0)
    with SessionLocal() as db:
        pv = db.get(m.PriceProvider, cu["id"])
        eng.fetch_quote(pv, "Q")
        clock["t"] += 0.5
        eng.fetch_quote(pv, "Q")
    assert sleeps and abs(sleeps[0] - 1.5) < 0.01


# ------------------------------------------------------------------- زمان‌بند
def _scheduler():
    from app.database import SessionLocal
    from app.services.marketdata.engine import MarketDataEngine
    from app.services.marketdata.scheduler import PriceScheduler
    return PriceScheduler(SessionLocal, MarketDataEngine(sleep=lambda s: None, cache_ttl=0))


def test_scheduler_respects_interval_market_hours_and_toggle(client):
    mock = Mock().install()
    mock.routes["/v1/quote/Q"] = lambda req: {"data": {"price": "100", "updated": "2026-11-04T09:59:00"}}
    cu = custom_provider(client, refresh_interval_minutes=30)
    a = make_asset(client, sources=sources((cu["id"], "Q", {})))
    sch = _scheduler()
    t0 = datetime(2026, 11, 4, 10, 0)  # چهارشنبه
    # غیرفعال
    client.put("/api/market-data/scheduler", json={"scheduler_enabled": False, "scheduler_default_interval_minutes": 15, "scheduler_market_hours_only": True})
    assert sch.run_once(t0) == {"skipped": "disabled"}
    r = client.put("/api/market-data/scheduler", json={"scheduler_enabled": True, "scheduler_default_interval_minutes": 15, "scheduler_market_hours_only": True})
    assert r.status_code == 200 and r.json()["enabled"] is True
    res = sch.run_once(t0)
    assert res["due"] == 1 and res["ok"] == 1
    # قبل از سررسید بازه (۳۰ دقیقهٔ منبع) اجرا نمی‌شود
    assert sch.run_once(t0 + timedelta(minutes=10))["due"] == 0
    assert sch.run_once(t0 + timedelta(minutes=31))["due"] == 1
    # بازه‌ٔ اختصاصی دارایی بر منبع مقدم است
    body = {k: a[k] for k in ("platform_id", "name", "name_en", "symbol", "asset_type", "market", "unit", "price_currency", "decimals",
                              "min_quantity", "target_weight", "initial_price", "buy_fee_rate", "is_active", "note")}
    body["fetch_interval_minutes"] = 5
    assert client.put(f"/api/assets/{a['id']}", json=body).status_code == 200
    assert sch.run_once(t0 + timedelta(minutes=31 + 6))["due"] == 1


def test_scheduler_skips_tse_assets_when_market_closed(client):
    mock = Mock().install()
    mock.routes["/instinfofast.aspx"] = lambda req: tse_line(last=125000, when=datetime(2026, 11, 4, 10, 29))
    mock.routes["/TseClient2.aspx"] = "20261104;"
    ts = enable(client, "tsetmc")
    a = make_asset(client, sources=sources((ts["id"], "111222", {})))
    client.put("/api/market-data/scheduler", json={"scheduler_enabled": True, "scheduler_default_interval_minutes": 1, "scheduler_market_hours_only": True})
    sch = _scheduler()
    closed = sch.run_once(datetime(2026, 11, 6, 10, 0))   # جمعه
    assert closed["due"] == 0 and closed["skipped_market_closed"] == 1
    night = sch.run_once(datetime(2026, 11, 4, 20, 0))    # چهارشنبه شب
    assert night["due"] == 0 and night["skipped_market_closed"] == 1
    assert mock.count("/instinfofast.aspx") == 0
    # بازار باز: دریافت می‌شود
    sch2 = _scheduler()
    opened = sch2.run_once(datetime(2026, 11, 4, 10, 30))
    assert opened["due"] == 1
    # حالت «فقط ساعات بازار» خاموش → همیشه
    client.put("/api/market-data/scheduler", json={"scheduler_enabled": True, "scheduler_default_interval_minutes": 1, "scheduler_market_hours_only": False})
    assert _scheduler().run_once(datetime(2026, 11, 6, 10, 0))["due"] == 1


def test_scheduler_one_failure_does_not_block_others(client):
    mock = Mock().install()
    mock.routes["/v1/quote/GOOD"] = lambda req: {"data": {"price": "100", "updated": "2026-11-04T09:59:00"}}
    mock.routes["/v1/quote/BAD"] = httpx.Response(500, text="x")
    cu = custom_provider(client)
    make_asset(client, name="خراب", sources=sources((cu["id"], "BAD", {})))
    make_asset(client, name="سالم", sources=sources((cu["id"], "GOOD", {})))
    client.put("/api/market-data/scheduler", json={"scheduler_enabled": True, "scheduler_default_interval_minutes": 1, "scheduler_market_hours_only": False})
    res = _scheduler().run_once(datetime(2026, 11, 4, 10, 0))
    assert res["due"] == 2 and res["ok"] == 1 and res["failed"] == 1
    st = client.get("/api/market-data/scheduler").json()
    assert st["enabled"] is True


# ------------------------------------------------------------------- داشبورد/وضعیت
def test_dashboard_market_block(client):
    d = client.get("/api/dashboard").json()["management"]
    assert d["total_assets"] == 5 and d["active_assets"] == 5 and d["platform_count"] == 8
    ms = d["market"]
    for k in ("providers", "stale_prices", "missing_prices", "last_update_at", "errors_24h", "recent_errors", "scheduler"):
        assert k in ms
    assert ms["providers"]["enabled"] == 1 and ms["missing_prices"] == 5  # فقط «دستی» فعال؛ هیچ قیمتی ثبت نشده


def test_history_import_creates_valid_points_without_duplicates(client):
    mock = Mock().install()
    hist = "<TICKER>,<DTYYYYMMDD>,<FIRST>,<HIGH>,<LOW>,<CLOSE>,<VALUE>,<VOL>,<OPENINT>,<PER>,<OPEN>,<LAST>\n" + "\n".join(
        f"X,{(now() - timedelta(days=i)).strftime('%Y%m%d')},1,1,1,{100000 + i * 1000},1,1,0,D,1,1" for i in range(1, 6))
    mock.routes["/Export-txt.aspx"] = hist
    ts = enable(client, "tsetmc")
    a = make_asset(client, sources=sources((ts["id"], "111222", {})))
    r = client.post("/api/market-data/history/import", json={"asset_id": a["id"], "provider_id": ts["id"], "days": 30}).json()
    assert r["stored"] == 5
    r = client.post("/api/market-data/history/import", json={"asset_id": a["id"], "provider_id": ts["id"], "days": 30}).json()
    assert r["stored"] == 0 and r["duplicates"] == 5
    pts = client.get("/api/market-data/history", params={"asset_id": a["id"]}).json()["series"][0]["points"]
    assert len(pts) == 5 and D(str(pts[0]["price"])) == D("10500")  # ۱۰۵٬۰۰۰ ریال → ۱۰٬۵۰۰ تومان


def test_private_hosts_blocked_for_custom_api(client):
    from app.services.marketdata import http
    from app.services.marketdata.base import ProviderError
    http.set_test_transport(None)
    with pytest.raises(ProviderError) as e:
        http.check_url("https://127.0.0.1/x", allow_http=False, has_credentials=False, enforce_allowlist=False)
    assert e.value.code == "config"
    with pytest.raises(ProviderError):
        http.check_url("http://example.com/x", allow_http=False, has_credentials=False, enforce_allowlist=False)


def test_jsonpath_extraction():
    from app.services.marketdata.jsonpath import extract
    data = {"data": {"items": [{"symbol": "A", "p": 1}, {"symbol": "B", "p": 2}]}, "last": [5, 6]}
    assert extract(data, "$.data.items[1].p") == 2
    assert extract(data, "$.data.items[?(@.symbol=='B')].p") == 2
    assert extract(data, "last[-1]") == 6
    from app.services.marketdata.base import ProviderError
    with pytest.raises(ProviderError):
        extract(data, "$.nope.x")
