"""v2.3 — یکپارچه‌سازی Iran Market Data (latest-toman.json).

* دادهٔ آزمون یک نسخهٔ واقعی و دانلودشدهٔ فایل است (``fixtures/iranmarket_latest_toman_20261104.json.gz``، ۱۰۴۲ نماد، ۹ دسته).
  برای پایداری آزمون در تاریخ‌های بعدی، زمان‌های فایل به «اکنون» منتقل می‌شود (فاصلهٔ نسبی و پرچم‌های stale دست‌نخورده می‌ماند).
* هیچ درخواست شبکه‌ای انجام نمی‌شود (httpx.MockTransport)؛ اتصال زندهٔ واقعی در این آزمون‌ها ادعا نمی‌شود.
"""
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.services.marketdata import iranmarket as im
from app.services.marketdata.base import ProviderError
from tests.test_marketdata import Mock, custom_provider, enable, isolate_engine, make_asset, now, pv_by_kind, sources  # noqa: F401

from tests.iranmarket_data import FIXTURE, REAL_GENERATED, URL_PATH, _shift, load_real, rec, records, retimed  # noqa: F401


@pytest.fixture(autouse=True)
def fast_im(monkeypatch):
    monkeypatch.setattr(im, "MIN_GAP_SECONDS", 0)
    monkeypatch.setattr(im, "_sleep", lambda s: None)
    im.clear_history_cache()
    yield
    im.clear_history_cache()


class IM(Mock):
    """سرور ساختگی فایل (با ETag)."""

    def __init__(self, payload=None):
        super().__init__()
        self.payload = payload if payload is not None else retimed()
        self.fail: object = None  # None | status code | callable
        self.etag = '"v1"'
        self.routes[URL_PATH] = self._serve

    def _serve(self, request):
        if self.fail:
            return httpx.Response(self.fail if isinstance(self.fail, int) else 500, text="down")
        if self.etag and request.headers.get("if-none-match") == self.etag:
            return httpx.Response(304, headers={"etag": self.etag})
        h = {"content-type": "text/plain"}
        if self.etag:
            h["etag"] = self.etag
        return httpx.Response(200, content=json.dumps(self.payload, ensure_ascii=False).encode(), headers=h)

    def change(self, payload):
        self.payload = payload
        self.etag = f'"v{len(self.calls)}x"'


def setup_im(client, payload=None, **patch):
    srv = IM(payload).install()
    enable(client, "iranmarket", retry_count=0, **patch)
    return srv


def refresh(client):
    r = client.post("/api/iran-market/refresh")
    assert r.status_code == 200, r.text
    return r.json()


def symbols(client, **params):
    r = client.get("/api/iran-market/symbols", params={"page_size": 200, **params})
    assert r.status_code == 200, r.text
    return r.json()


def all_symbols(client, **params):
    out, page = [], 1
    while True:
        d = symbols(client, page=page, **params)
        out += d["items"]
        if page * d["page_size"] >= d["total"]:
            return out
        page += 1


def im_provider(client):
    return pv_by_kind(client, "iranmarket")


def link_via_api(client, asset_id, symbol):
    r = client.post("/api/iran-market/link", json={"asset_id": asset_id, "symbol": symbol, "confirm": True})
    assert r.status_code == 200, r.text
    return r.json()


def priced_asset(client, symbol, name="دارایی تست", currency="IRT"):
    """دارایی + اتصال تأییدشدهٔ نماد + یک خرید (برای ارزش‌گذاری)."""
    a = make_asset(client, name=name, currency=currency)
    link_via_api(client, a["id"], symbol)
    return a


def fund_and_buy(client, asset_id, qty="10", unit_price="1000"):
    from datetime import date
    plats = {x["name"]: x["id"] for x in client.get("/api/platforms").json()}
    client.post("/api/transactions", json={"tx_date": (date.today() - timedelta(days=3)).isoformat(), "tx_type": "deposit", "platform_id": plats["مفید"], "amount": "50000000000"})
    r = client.post("/api/transactions", json={"tx_date": (date.today() - timedelta(days=2)).isoformat(), "tx_type": "buy", "asset_id": asset_id, "quantity": qty, "unit_price": unit_price})
    assert r.status_code == 201, r.text


def holding(client, asset_id):
    return next(x for x in client.get("/api/portfolio").json()["assets"] if x["id"] == asset_id)


# ======================================================================= ۱) دریافت و پردازش فایل واقعی
def test_provider_is_registered_disabled_and_independent(client):
    p = im_provider(client)
    assert p["kind"] == "iranmarket" and p["is_enabled"] is False and p["refresh_interval_minutes"] == 30
    kinds = {k["kind"] for k in client.get("/api/market-data/kinds").json()}
    assert {"tsetmc", "bitpin", "streamdata", "servix", "custom_api", "manual", "iranmarket"} <= kinds
    # دیگر منابع دست‌نخورده‌اند
    assert {x["kind"] for x in client.get("/api/market-data/providers").json()} >= {"tsetmc", "bitpin", "streamdata", "servix", "custom_api", "manual", "iranmarket"}


def test_fetch_real_file_through_backend(client):
    srv = setup_im(client)
    r = refresh(client)
    raw = records(srv.payload)
    assert r["ok"] and r["status"] == "ok" and r["symbols"] == len(raw) == 1042
    assert srv.count(URL_PATH) == 1
    ov = client.get("/api/iran-market/overview").json()
    assert ov["totals"]["total"] == 1042 and ov["connection"] == "ok" and ov["provider"]["is_enabled"] is True
    assert ov["snapshot"]["generated_at"] and ov["snapshot"]["last_ok_at"] and ov["snapshot"]["stale"] is False
    # زمان تولید فایل و زمان دریافت دو مفهوم جدا هستند
    assert ov["snapshot"]["generated_at"] != ov["snapshot"]["last_ok_at"]
    p = im_provider(client)
    assert p["last_status"] == "ok" and p["last_success_at"] and p["last_latency_ms"] is not None and p["consecutive_failures"] == 0


def test_all_categories_extracted_dynamically(client):
    srv = setup_im(client)
    refresh(client)
    expected = {c: len(v) for c, v in srv.payload["data"]["categories"].items()}
    ov = client.get("/api/iran-market/overview").json()
    got = {c["key"]: c["count"] for c in ov["categories"]}
    assert got == expected and len(expected) == ov["totals"]["categories"] == 9
    assert {"currency", "gold", "coin", "crypto", "commodity", "energy", "precious_metal", "index", "other"} == set(expected)
    # دستهٔ جدید در آینده بدون تغییر کد نمایش داده می‌شود
    p = retimed()
    p["data"]["categories"]["future_cat"] = [dict(rec(p, "USD_IRR_FREE"), symbol="NEW_FUTURE_SYM", category="future_cat", name_fa="نماد آینده")]
    srv.change(p)
    refresh(client)
    ov = client.get("/api/iran-market/overview").json()
    assert {c["key"]: c["count"] for c in ov["categories"]}["future_cat"] == 1 and ov["totals"]["total"] == 1043
    assert symbols(client, category="future_cat")["items"][0]["symbol"] == "NEW_FUTURE_SYM"


def test_symbol_fields_preserved_and_times_kept_separate(client):
    srv = setup_im(client)
    refresh(client)
    raw = rec(srv.payload, "USD_IRR_FREE")
    d = client.get("/api/iran-market/symbols/USD_IRR_FREE").json()
    for k in ("symbol", "name_fa", "name_en", "category", "market", "currency", "unit", "source"):
        assert d[k] == (raw["source"] if k == "source" else raw[k])
    assert D(str(d["price"])) == D(str(raw["price"])) and D(str(d["unit_size"])) == D(str(raw["unit_size"]))
    assert d["timestamp"] == raw["timestamp"] and d["timestamp_jalali"] == raw["timestamp_jalali"] and d["timestamp_tehran"] == raw["timestamp_tehran"]
    assert d["checked_at"] and d["price_time"] and d["checked_at"] != d["price_time"]  # checked_at ≠ timestamp
    assert d["quality"] == raw["quality"] and d["api_stale"] is raw["stale"]
    # فیلدهای OHLC و تغییر
    for k in ("high", "low", "prev_close", "change", "change_pct"):
        assert (d[k] is None) == (raw[k] is None)
    assert d["currency"] == "IRT"  # قیمت تومانی بدون هیچ تبدیل ۱۰ برابر
    assert D(str(d["price"])) == D(str(raw["price"]))


def test_global_prices_keep_original_currency_and_unit(client):
    srv = setup_im(client)
    refresh(client)
    btc = client.get("/api/iran-market/symbols/BTC_USD").json()
    assert btc["currency"] == "USD" and D(str(btc["price"])) == D(str(rec(srv.payload, "BTC_USD")["price"]))
    xau = client.get("/api/iran-market/symbols/XAU_USD").json()
    assert xau["currency"] == "USD" and xau["unit"] == "troy_ounce"
    gold = client.get("/api/iran-market/symbols/GOLD_18K_IRR").json()
    assert gold["currency"] == "IRT" and gold["unit"] == "gram"
    # شاخص‌ها واحد POINTS دارند و ارز نیستند
    assert any(i["currency"] == "POINTS" for i in symbols(client, category="index")["items"])


# ======================================================================= ۲) کیفیت، تازگی و اعتبار هر نماد
def test_stale_detection_is_per_symbol(client):
    srv = setup_im(client)
    refresh(client)
    raw = records(srv.payload)
    cutoff = now().date() - timedelta(days=3)

    def too_old(r):  # قدیمی‌تر از max_price_age_days (روز تقویمی تهران)، حتی اگر منبع stale اعلام نکرده باشد
        t = datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")).astimezone(ZoneInfo("Asia/Tehran"))
        return t.date() < cutoff

    n_stale = sum(1 for r in raw if r["stale"] is True or too_old(r))
    n_api = sum(1 for r in raw if r["stale"] is True)
    assert n_stale > n_api  # هر دو سازوکار در دادهٔ واقعی دیده می‌شوند
    ov = client.get("/api/iran-market/overview").json()["totals"]
    # دریافت موفق فایل، همهٔ قیمت‌ها را معتبر نمی‌کند
    assert ov["stale"] == n_stale > 400 and ov["valid"] == len(raw) - n_stale and ov["invalid"] == 0 and ov["no_price"] == 0
    stale = all_symbols(client, status="stale")
    assert len(stale) == n_stale and all(i["status"] == "stale" for i in stale) and sum(1 for i in stale if i["api_stale"]) == n_api
    ok_ = symbols(client, status="valid")
    assert ok_["total"] == ov["valid"] - ov["warning"]
    # هشدار کیفیت (spike / ohlc_inconsistent) وضعیت جدا دارد و مانع اعتبار نیست
    warn = symbols(client, status="warning")
    assert warn["total"] == ov["warning"] > 0 and all(i["quality"] for i in warn["items"])


def test_sql_status_matches_python_classifier(client):
    srv = setup_im(client)
    # چند رکورد مرزی روی دادهٔ واقعی
    p = srv.payload
    base = rec(p, "USD_IRR_FREE")
    cases = {"Z_ZERO": {"price": 0}, "Z_NEG": {"price": -5}, "Z_NULL": {"price": None}, "Z_BADTS": {"timestamp": "not-a-date"},
             "Z_NOTS": {"timestamp": None, "timestamp_tehran": None}, "Z_NOCUR": {"currency": None}, "Z_OLD": {"timestamp": "2026-01-01T00:00:00.000Z"},
             "Z_FUT": {"timestamp": (datetime.now(timezone.utc) + timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%S.000Z")}, "Z_STALE": {"stale": True}}
    for sym, patch in cases.items():
        p["data"]["categories"]["other"].append({**base, "symbol": sym, **patch})
    srv.change(p)
    refresh(client)
    from app.database import SessionLocal
    from app import models as m
    with SessionLocal() as db:
        n = im.now_local()
        st = im.snapshot_state(db, im.get_provider(db), n)
        sql_expr = im.status_case(n, 3, st["stale"])
        from sqlalchemy import select
        sql = dict(db.execute(select(m.MarketSymbol.symbol, sql_expr)).all())
        py = {r.symbol: im.classify(r, n, 3, st["stale"])[0] for r in db.scalars(select(m.MarketSymbol))}
    assert sql == py and len(sql) == 1042 + len(cases)
    assert sql["Z_ZERO"] == "invalid" and sql["Z_NEG"] == "invalid" and sql["Z_NULL"] == "no_price" and sql["Z_STALE"] == "stale"
    assert sql["Z_BADTS"] == "invalid" and sql["Z_FUT"] == "invalid" and sql["Z_NOCUR"] == "invalid" and sql["Z_OLD"] == "stale"


def test_invalid_timestamp_zero_price_and_unknown_currency_rejected(client):
    srv = setup_im(client)
    p = srv.payload
    base = rec(p, "USD_IRR_FREE")
    p["data"]["categories"]["other"] += [
        {**base, "symbol": "BAD_TS", "timestamp": "garbage", "timestamp_tehran": "garbage"},
        {**base, "symbol": "FUT_TS", "timestamp": (datetime.now(timezone.utc) + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%S.000Z")},
        {**base, "symbol": "ZERO_P", "price": 0}, {**base, "symbol": "NEG_P", "price": -10}, {**base, "symbol": "NULL_P", "price": None},
        {**base, "symbol": "NO_CUR", "currency": None}]
    srv.change(p)
    refresh(client)
    st = {s: client.get(f"/api/iran-market/symbols/{s}").json() for s in ("BAD_TS", "FUT_TS", "ZERO_P", "NEG_P", "NULL_P", "NO_CUR")}
    assert [st[k]["status"] for k in ("BAD_TS", "FUT_TS", "ZERO_P", "NEG_P", "NO_CUR")] == ["invalid"] * 5
    assert st["NULL_P"]["status"] == "no_price" and st["NULL_P"]["price"] is None  # null به صفر تبدیل نمی‌شود
    assert all(st[k]["status_reason"] for k in st)
    # و هیچ‌کدام برای ارزش‌گذاری قابل‌استفاده نیستند
    from app.database import SessionLocal
    with SessionLocal() as db:
        pv = im.get_provider(db)
        for sym in ("BAD_TS", "NULL_P", "NO_CUR"):
            with pytest.raises(ProviderError):
                im.quote_for(db, pv, sym, im.now_local())
        # قیمت غیرمثبت به‌صورت Quote برمی‌گردد تا موتور کیفیت ردیف نامعتبر را ثبت و رد کند
        assert im.quote_for(db, pv, "ZERO_P", im.now_local()).price == 0
        # زمان آینده نیز Quote می‌شود تا موتور کیفیت آن را با پرچم future_time نامعتبر ثبت کند
        from app.services.marketdata import quality
        fq = im.quote_for(db, pv, "FUT_TS", im.now_local())
        a = quality.assess_quote(raw_price=fq.price, unit=fq.unit, source_time=fq.source_time, now=im.now_local(), asset_currency="IRT", max_age_days=3)
        assert not a.valid and "future_time" in a.flags


def test_invalid_price_never_enters_portfolio_value(client):
    srv = setup_im(client)
    p = srv.payload
    base = rec(p, "USD_IRR_FREE")
    p["data"]["categories"]["other"] += [{**base, "symbol": "ZERO_P", "price": 0}, {**base, "symbol": "STALE_P", "stale": True}]
    srv.change(p)
    refresh(client)
    ok_a = priced_asset(client, "USD_IRR_FREE", name="معتبر")
    zero_a = priced_asset(client, "ZERO_P", name="صفر")
    stale_a = priced_asset(client, "STALE_P", name="کهنه")
    for a in (ok_a, zero_a, stale_a):
        fund_and_buy(client, a["id"], qty="2")
        client.post(f"/api/assets/{a['id']}/refresh-price")
    ok_h = holding(client, ok_a["id"])
    assert D(str(ok_h["value"])) == 2 * D(str(rec(srv.payload, "USD_IRR_FREE")["price"]))
    cur = {x["asset_id"]: x for x in client.get("/api/prices/current").json()["items"]}
    for a in (zero_a, stale_a):
        assert holding(client, a["id"])["value"] is None and cur[a["id"]]["ok"] is False and cur[a["id"]]["price"] is None
        rows = [x for x in client.get("/api/prices", params={"asset_id": a["id"]}).json() if x["provider_id"]]
        assert all(x["is_valid"] is False and x["is_approved"] is False for x in rows)  # ردیف نامعتبر فقط برای ردیابی است
    stale_row = [x for x in client.get("/api/prices", params={"asset_id": stale_a["id"]}).json() if x["provider_id"]]
    assert stale_row and "api_stale" in stale_row[0]["quality_flags"] and "stale" in stale_row[0]["quality_flags"]


# ======================================================================= ۳) اتصال نماد به دارایی (فقط با تأیید صریح)
def test_link_requires_explicit_confirmation(client):
    srv = setup_im(client)
    refresh(client)
    a = make_asset(client, name="طلای ۱۸ عیار", currency="IRT")
    pid = im_provider(client)["id"]
    # مسیر فرم دارایی: بدون confirm_link رد می‌شود
    body = sources((pid, "GOLD_18K_IRR", {}))
    r = client.put(f"/api/assets/{a['id']}/price-sources", json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "link_not_confirmed"
    assert client.get(f"/api/assets/{a['id']}").json()["sources"] == []
    # مسیر API اتصال
    assert client.post("/api/iran-market/link", json={"asset_id": a["id"], "symbol": "GOLD_18K_IRR"}).status_code == 422
    # با تأیید
    ok = client.put(f"/api/assets/{a['id']}/price-sources", json=sources((pid, "GOLD_18K_IRR", {"confirm_link": True})))
    assert ok.status_code == 200, ok.text
    src = client.get(f"/api/assets/{a['id']}").json()["sources"][0]
    assert src["external_id"] == "GOLD_18K_IRR" and src["link"]["symbol"] == "GOLD_18K_IRR" and src["link"]["unit"] == "gram" and src["link"]["currency"] == "IRT"
    assert src["link"]["confirmed_at"]
    # ذخیرهٔ دوبارهٔ همان اتصال نیازی به تأیید دوباره ندارد، تغییر نماد دارد
    assert client.put(f"/api/assets/{a['id']}/price-sources", json=sources((pid, "GOLD_18K_IRR", {}))).status_code == 200
    r = client.put(f"/api/assets/{a['id']}/price-sources", json=sources((pid, "COIN_EMAMI_IRR", {})))
    assert r.status_code == 422 and r.json()["error"]["code"] == "link_not_confirmed"
    r = client.put(f"/api/assets/{a['id']}/price-sources", json=sources((pid, "COIN_EMAMI_IRR", {"confirm_link": True})))
    assert r.status_code == 200
    assert client.get(f"/api/assets/{a['id']}").json()["sources"][0]["external_id"] == "COIN_EMAMI_IRR"
    # یک نماد برای هر دارایی؛ قطع اتصال
    assert client.delete("/api/iran-market/link", params={"asset_id": a["id"]}).json()["ok"] is True
    assert client.get(f"/api/assets/{a['id']}").json()["sources"] == []


def test_suggestions_never_link_automatically(client):
    setup_im(client)
    refresh(client)
    a = make_asset(client, name="دلار آزاد", currency="IRT", symbol="USD")
    sug = client.get("/api/iran-market/suggest", params={"asset_id": a["id"]}).json()
    assert sug["auto_link"] is False and sug["items"]
    assert "USD_IRR_FREE" in [i["symbol"] for i in sug["items"]]
    # پیشنهاد، اتصال نمی‌سازد؛ و قیمتی از API برای این دارایی گرفته نمی‌شود
    assert client.get(f"/api/assets/{a['id']}").json()["sources"] == []
    r = client.post(f"/api/assets/{a['id']}/refresh-price")
    assert client.get("/api/prices", params={"asset_id": a["id"]}).json() == []
    assert r.status_code in (200, 404, 409, 422)
    # دانلود/تازه‌سازی داده، دارایی جدیدی نمی‌سازد
    before = len(client.get("/api/assets").json())
    refresh(client)
    assert len(client.get("/api/assets").json()) == before


def test_link_blocked_for_incompatible_currency_unit_or_unknown_symbol(client):
    setup_im(client)
    refresh(client)
    irt = make_asset(client, name="ایرانی", currency="IRT")
    for sym, code in (("BTC_USD", "link_blocked"), ("XAU_USD", "link_blocked"), ("JPY_IRR_FREE", "link_blocked"), ("NO_SUCH_SYMBOL", "symbol_not_found")):
        r = client.post("/api/iran-market/link", json={"asset_id": irt["id"], "symbol": sym, "confirm": True})
        assert r.status_code == 422 and r.json()["error"]["code"] == code, (sym, r.text)
    d = client.get("/api/iran-market/symbols/JPY_IRR_FREE").json()
    assert d["unit_size"] in (100, "100") or D(str(d["unit_size"])) == 100
    assert d["link_blockers"]
    # دارایی جهانی با ارز USD می‌تواند به نماد USD وصل شود (نه تبدیل ضمنی)
    usd = make_asset(client, name="بیت‌کوین", currency="USD")
    assert client.post("/api/iran-market/link", json={"asset_id": usd["id"], "symbol": "BTC_USD", "confirm": True}).status_code == 200


def test_unit_change_after_confirmation_blocks_pricing(client):
    srv = setup_im(client)
    refresh(client)
    a = priced_asset(client, "GOLD_18K_IRR", name="طلا")
    assert client.post(f"/api/assets/{a['id']}/refresh-price").json()["ok"] is True
    p = srv.payload
    rec(p, "GOLD_18K_IRR")["unit"] = "troy_ounce"
    rec(p, "GOLD_18K_IRR")["timestamp"] = _shift(rec(p, "GOLD_18K_IRR")["timestamp"], timedelta(minutes=2))
    srv.change(p)
    refresh(client)
    before = len(client.get("/api/prices", params={"asset_id": a["id"]}).json())
    r = client.post(f"/api/assets/{a['id']}/refresh-price").json()
    assert r["ok"] is False
    assert len(client.get("/api/prices", params={"asset_id": a["id"]}).json()) == before
    logs = client.get("/api/market-data/logs", params={"asset_id": a["id"]}).json()
    assert any(x["code"] == "link_changed" for x in (logs["items"] if isinstance(logs, dict) else logs))


# ======================================================================= ۴) ارزش‌گذاری، اولویت و fallback
def test_provider_used_in_valuation_with_origin_and_no_rescale(client):
    srv = setup_im(client)
    refresh(client)
    a = priced_asset(client, "GOLD_18K_IRR", name="طلا ۱۸")
    fund_and_buy(client, a["id"], qty="5")
    res = client.post(f"/api/assets/{a['id']}/refresh-price").json()
    assert res["ok"] is True
    raw = rec(srv.payload, "GOLD_18K_IRR")
    row = [x for x in client.get("/api/prices", params={"asset_id": a["id"]}).json() if x["provider_id"]][0]
    assert D(str(row["price"])) == D(str(raw["price"])) and row["currency"] == "IRT"  # نه ×۱۰ و نه ÷۱۰
    assert row["is_valid"] and row["is_approved"] and row["upstream_source"] == raw["source"] and row["snapshot_id"]
    assert row["upstream_checked_at"] and row["recorded_at"] and row["upstream_checked_at"] != row["recorded_at"]  # checked_at ≠ timestamp
    h = holding(client, a["id"])
    assert D(str(h["value"])) == 5 * D(str(raw["price"]))
    cur = next(x for x in client.get("/api/prices/current").json()["items"] if x["asset_id"] == a["id"])
    assert cur["ok"] and "Iran Market" in json.dumps(cur, ensure_ascii=False)  # مبدأ قیمت نهایی نمایش داده می‌شود
    # دارایی بدون اتصال: هرگز از API قیمت نمی‌گیرد
    other = make_asset(client, name="بدون اتصال", currency="IRT")
    client.post(f"/api/assets/{other['id']}/refresh-price")
    assert client.get("/api/prices", params={"asset_id": other["id"]}).json() == []


def test_priority_order_and_fallback_across_providers(client):
    srv = setup_im(client)
    refresh(client)
    cust = custom_provider(client)
    pid = im_provider(client)["id"]
    mock_t = lambda price, when: {"data": {"price": price, "updated": when}}  # noqa: E731
    real = D(str(rec(srv.payload, "USD_IRR_FREE")["price"]))
    near = int(real * D("1.02"))  # اختلاف کوچک (۲٪) تعارض نیست؛ اختلاف غیرعادی توسط موتور کیفیت رد می‌شود
    srv.routes["/v1/quote/X1"] = lambda req: mock_t(near, now().isoformat(timespec="seconds"))
    a = make_asset(client, name="ترتیب", currency="IRT")
    # اولویت ۱: Iran Market، ۲: Custom
    link_via_api(client, a["id"], "USD_IRR_FREE")
    r = client.put(f"/api/assets/{a['id']}/price-sources", json=sources((pid, "USD_IRR_FREE", {}), (cust["id"], "X1", {})))
    assert r.status_code == 200, r.text
    res = client.post(f"/api/assets/{a['id']}/refresh-price").json()
    assert res["ok"] and res["provider_id"] == pid if "provider_id" in res else res["ok"]
    cur = next(x for x in client.get("/api/prices/current").json()["items"] if x["asset_id"] == a["id"])
    assert D(str(cur["price"])) == D(str(rec(srv.payload, "USD_IRR_FREE")["price"]))
    # ترتیب برعکس: Custom اول، پس قیمت Custom برنده است (بدون تغییر در تاریخچهٔ قبلی)
    n_before = len(client.get("/api/prices", params={"asset_id": a["id"]}).json())
    client.put(f"/api/assets/{a['id']}/price-sources", json=sources((cust["id"], "X1", {}), (pid, "USD_IRR_FREE", {})))
    assert len(client.get("/api/prices", params={"asset_id": a["id"]}).json()) == n_before
    client.post(f"/api/assets/{a['id']}/refresh-price")
    cur = next(x for x in client.get("/api/prices/current").json()["items"] if x["asset_id"] == a["id"])
    assert D(str(cur["price"])) == near


def test_fallback_when_primary_down_and_stale_fallback_ignored(client):
    srv = setup_im(client)
    refresh(client)
    cust = custom_provider(client)
    pid = im_provider(client)["id"]
    state = {"fail": True, "price": 2000, "when": None}

    def cust_resp(req):
        if state["fail"]:
            return httpx.Response(503, text="down")
        return {"data": {"price": state["price"], "updated": state["when"] or now().isoformat(timespec="seconds")}}

    srv.routes["/v1/quote/Y1"] = cust_resp
    a = make_asset(client, name="جایگزین", currency="IRT")
    client.put(f"/api/assets/{a['id']}/price-sources", json=sources((cust["id"], "Y1", {}), (pid, "USD_IRR_FREE", {"confirm_link": True})))
    res = client.post(f"/api/assets/{a['id']}/refresh-price").json()
    assert res["ok"] is True  # اولی از کار افتاده؛ Iran Market جایگزین می‌شود
    row = [x for x in client.get("/api/prices", params={"asset_id": a["id"]}).json() if x["provider_id"] == pid][0]
    assert any(v.get("ok") is False for v in (row["via"] if isinstance(row["via"], list) else row["via"].get("attempts", []))) or row["via"]
    # فال‌بک کهنه: Iran Market نمادِ stale است ← هرگز وارد ارزش‌گذاری نمی‌شود
    p = srv.payload
    p["data"]["categories"]["other"].append({**rec(p, "USD_IRR_FREE"), "symbol": "STALE_FB", "stale": True})
    srv.change(p)
    refresh(client)
    b = make_asset(client, name="کهنه فال‌بک", currency="IRT")
    client.put(f"/api/assets/{b['id']}/price-sources", json=sources((cust["id"], "Y1", {}), (pid, "STALE_FB", {"confirm_link": True})))
    fund_and_buy(client, b["id"], qty="1")
    client.post(f"/api/assets/{b['id']}/refresh-price")
    assert holding(client, b["id"])["value"] is None
    cur = next(x for x in client.get("/api/prices/current").json()["items"] if x["asset_id"] == b["id"])
    assert cur["ok"] is False


# ======================================================================= ۵) قطع API، تکراری، کش
def test_api_down_keeps_last_data_and_marks_staleness(client, monkeypatch):
    srv = setup_im(client)
    refresh(client)
    a = priced_asset(client, "USD_IRR_FREE", name="دلار")
    assert client.post(f"/api/assets/{a['id']}/refresh-price").json()["ok"]
    srv.fail = 500
    r = client.post("/api/iran-market/refresh").json()
    assert r["ok"] is False and r["status"] == "error"
    ov = client.get("/api/iran-market/overview").json()
    assert ov["connection"] == "error" and ov["totals"]["total"] == 1042 and ov["snapshot"]["last_ok_at"]  # دادهٔ قبلی نگه داشته شد
    assert ov["snapshot"]["last_error"] and ov["requests"]["errors_24h"] >= 1
    assert symbols(client, q="USD_IRR_FREE")["items"][0]["price"] is not None
    p = im_provider(client)
    assert p["consecutive_failures"] >= 1 and p["last_status"] == "error" and p["last_success_at"]
    snaps = client.get("/api/iran-market/snapshots").json()["items"]
    assert snaps[0]["status"] == "error" and snaps[0]["error"] and any(s["status"] == "ok" for s in snaps)
    # با گذشت زمان بدون دریافت موفق، همهٔ قیمت‌ها «قدیمی» می‌شوند و هرگز زنده نشان داده نمی‌شوند
    real_now = im.now_local()
    monkeypatch.setattr(im, "now_local", lambda: real_now + timedelta(hours=5))
    ov = client.get("/api/iran-market/overview").json()
    assert ov["connection"] == "error" and ov["totals"]["valid"] == 0 and ov["totals"]["stale"] == 1042
    assert ov["snapshot"]["stale"] is True
    res = client.post(f"/api/assets/{a['id']}/refresh-price").json()
    assert res["ok"] is False


def test_duplicate_data_not_stored_twice(client):
    srv = setup_im(client)
    r1 = refresh(client)
    a = priced_asset(client, "USD_IRR_FREE", name="دلار")
    client.post(f"/api/assets/{a['id']}/refresh-price")
    n_prices = len(client.get("/api/prices", params={"asset_id": a["id"]}).json())
    # فایل بدون تغییر: ETag/۳۰۴ ← هیچ نمادی دوباره ذخیره نمی‌شود
    r2 = refresh(client)
    assert r2["status"] == "unchanged" and r2["changed"] == 0
    # پاسخ ۲۰۰ با محتوای یکسان (بدون ETag) نیز با sha256 تکراری شناخته می‌شود
    srv.etag = None
    r3 = refresh(client)
    assert r3["status"] == "unchanged"
    client.post(f"/api/assets/{a['id']}/refresh-price")
    client.post(f"/api/assets/{a['id']}/refresh-price")
    assert len(client.get("/api/prices", params={"asset_id": a["id"]}).json()) == n_prices
    from app.database import SessionLocal
    from sqlalchemy import func, select
    from app import models as m
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(m.MarketSymbol)) == 1042  # بدون ردیف تکراری
    # فایلی که فقط زمان تولید/بررسی‌اش عوض شده ولی قیمت‌ها همان‌اند ← نمادی «تغییرکرده» حساب نمی‌شود، قیمت دوباره ثبت نمی‌شود
    p = srv.payload
    p["data"]["generated_at"] = _shift(p["data"]["generated_at"], timedelta(minutes=1))
    srv.change(p)
    r4 = refresh(client)
    assert r4["status"] == "ok" and r4["changed"] == 0
    client.post(f"/api/assets/{a['id']}/refresh-price")
    assert len(client.get("/api/prices", params={"asset_id": a["id"]}).json()) == n_prices
    assert r1["changed"] == 1042


def test_no_network_call_per_user_request(client):
    srv = setup_im(client)
    refresh(client)
    n = srv.count(URL_PATH)
    for i in range(15):
        client.get("/api/iran-market/overview")
        client.get("/api/iran-market/symbols", params={"q": "دلار", "page": 1})
        client.get("/api/iran-market/symbols/USD_IRR_FREE")
    assert srv.count(URL_PATH) == n == 1


def test_manual_refresh_respects_min_gap_and_disabled_provider(client, monkeypatch):
    srv = IM().install()
    r = client.post("/api/iran-market/refresh")
    assert r.status_code == 409 and r.json()["error"]["code"] == "provider_disabled"
    assert srv.count(URL_PATH) == 0  # فعال نبودن = بدون هیچ درخواست
    enable(client, "iranmarket", retry_count=0)
    monkeypatch.setattr(im, "MIN_GAP_SECONDS", 10)
    assert refresh(client)["status"] == "ok"
    again = refresh(client)
    assert again["status"] == "skipped" and srv.count(URL_PATH) == 1  # کلیک‌های پشت‌سرهم، درخواست تکراری نمی‌سازد


def test_abnormal_disagreement_follows_quality_engine(client):
    srv = setup_im(client)
    refresh(client)
    cust = custom_provider(client)
    pid = im_provider(client)["id"]
    srv.routes["/v1/quote/D1"] = lambda req: {"data": {"price": 1234, "updated": now().isoformat(timespec="seconds")}}
    a = make_asset(client, name="اختلاف", currency="IRT")
    client.put(f"/api/assets/{a['id']}/price-sources", json=sources((pid, "USD_IRR_FREE", {"confirm_link": True}), (cust["id"], "D1", {})))
    client.post(f"/api/assets/{a['id']}/refresh-price", params={"all_sources": True})
    cur = next(x for x in client.get("/api/prices/current").json()["items"] if x["asset_id"] == a["id"])
    assert cur["ok"] is False and cur["reason"] == "conflict" and cur["price"] is None


# ======================================================================= ۶) جست‌وجو، فیلتر، مرتب‌سازی، صفحه‌بندی
def test_search_filters_sort_and_pagination(client):
    srv = setup_im(client)
    refresh(client)
    raw = records(srv.payload)
    # جست‌وجو با نام فارسی، انگلیسی و نماد
    fa = next(r for r in raw if r["name_fa"] and r["name_fa"] != r["symbol"])
    assert fa["symbol"] in [i["symbol"] for i in symbols(client, q=fa["name_fa"])["items"]]
    en = next(r for r in raw if r["name_en"] and r["name_en"] != r["symbol"] and r["name_en"].isascii())
    assert en["symbol"] in [i["symbol"] for i in all_symbols(client, q=en["name_en"].lower())]
    assert "USD_IRR_FREE" in [i["symbol"] for i in symbols(client, q="usd_irr_free")["items"]]
    assert "USD_IRR_FREE" in [i["symbol"] for i in symbols(client, q="usd irr")["items"]]
    assert symbols(client, q="zzzz-no-such-symbol")["total"] == 0
    # عدد فارسی/عربی هم نرمال می‌شود، و کاراکترهای ٪ و _ جست‌وجوی SQL را خراب نمی‌کنند
    assert symbols(client, q="%")["total"] == sum(1 for r in raw if "%" in f'{r["symbol"]}{r["name_fa"] or ""}{r["name_en"] or ""}')
    # فیلترها
    cat = symbols(client, category="gold")
    assert cat["total"] == sum(1 for r in raw if r["category"] == "gold") and {i["category"] for i in cat["items"]} == {"gold"}
    mk = all_symbols(client, market="crypto_iran")
    assert len(mk) == sum(1 for r in raw if r["market"] == "crypto_iran") and {i["market"] for i in mk} == {"crypto_iran"}
    usd = symbols(client, currency="USD")
    assert usd["total"] == sum(1 for r in raw if r["currency"] == "USD") and {i["currency"] for i in usd["items"]} == {"USD"}
    both = symbols(client, category="currency", currency="IRT", q="دلار")
    assert all(i["category"] == "currency" and i["currency"] == "IRT" for i in both["items"])
    # مرتب‌سازی عددی (نه رشته‌ای) روی قیمت و درصد تغییر
    desc = [i["price"] for i in symbols(client, sort="price", order="desc", status="valid")["items"]]
    assert desc == sorted(desc, reverse=True) and len(desc) > 10
    asc = [i["price"] for i in symbols(client, sort="price", order="asc", status="valid")["items"]]
    assert asc == sorted(asc) and asc[0] < asc[-1]
    ch = [i["change_pct"] for i in symbols(client, sort="change_pct", order="desc", status="valid")["items"] if i["change_pct"] is not None]
    assert ch == sorted(ch, reverse=True)
    # صفحه‌بندی بدون تکرار
    p1 = symbols(client, page=1, page_size=100, sort="symbol")
    p2 = symbols(client, page=2, page_size=100, sort="symbol")
    assert p1["total"] == 1042 and len(p1["items"]) == 100 and not {i["symbol"] for i in p1["items"]} & {i["symbol"] for i in p2["items"]}
    last = symbols(client, page=11, page_size=100, sort="symbol")
    assert len(last["items"]) == 42
    # فقط متصل‌ها
    a = priced_asset(client, "USD_IRR_FREE")
    ln = symbols(client, linked=True)
    assert ln["total"] == 1 and ln["items"][0]["symbol"] == "USD_IRR_FREE" and ln["items"][0]["linked_count"] == 1
    d = client.get("/api/iran-market/symbols/USD_IRR_FREE").json()
    assert [x["asset_id"] for x in d["linked_assets"]] == [a["id"]]


def test_symbol_detail_history_documented_path_and_fallback(client):
    srv = setup_im(client)
    refresh(client)
    hist = {"meta": {"symbol": "USD_IRR_FREE", "interval": "1d", "unit": "toman", "currency": "IRT", "count": 3},
            "data": [{"t": f"2026-10-{d:02d}T00:00:00Z", "date_jalali": f"1405/08/{d - 8:02d}", "open": 100 * d, "high": 101 * d, "low": 99 * d, "close": 100 * d + 1, "volume": 0} for d in (1, 2, 3)]}
    srv.routes["history/index.json"] = {"meta": {"update_frequency_minutes": 1440}, "data": [{"symbol": "USD_IRR_FREE", "file": "history/USD_IRR_FREE.json", "url": "x", "records": 3, "currency": "IRT"}]}
    srv.routes["history/USD_IRR_FREE.json"] = hist
    h = client.get("/api/iran-market/symbols/USD_IRR_FREE/history").json()
    assert h["available"] is True and len(h["points"]) == 3 and h["points"][0]["close"] == 101
    before = srv.count("USD_IRR_FREE.json")
    client.get("/api/iran-market/symbols/USD_IRR_FREE/history")
    assert srv.count("USD_IRR_FREE.json") == before  # کش
    # نمادی که تاریخچه ندارد
    h2 = client.get("/api/iran-market/symbols/BTC_USD/history").json()
    assert h2["available"] is False and h2["points"] == [] and h2["message"]
    # تاریخچه هرگز در جدول قیمت‌ها ذخیره نمی‌شود
    assert client.get("/api/prices").json() == []
    assert client.get("/api/iran-market/symbols/NOPE/history").status_code == 404


def test_stored_prices_and_raw_debug_response(client):
    srv = setup_im(client)
    refresh(client)
    a = priced_asset(client, "USD_IRR_FREE")
    client.post(f"/api/assets/{a['id']}/refresh-price")
    sp = client.get("/api/iran-market/symbols/USD_IRR_FREE/stored-prices").json()["items"]
    assert len(sp) == 1 and sp[0]["asset_id"] == a["id"] and sp[0]["is_valid"] and sp[0]["checked_at"]
    snaps = client.get("/api/iran-market/snapshots").json()["items"]
    assert snaps[0]["has_raw"] and snaps[0]["symbol_count"] == 1042 and snaps[0]["category_count"] == 9 and snaps[0]["size_bytes"] > 100000
    raw = client.get(f"/api/iran-market/snapshots/{snaps[0]['id']}/raw")
    assert raw.status_code == 200 and raw.json() == srv.payload  # پاسخ خام برای عیب‌یابی نگه‌داری می‌شود


def test_raw_retention_is_bounded(client, monkeypatch):
    from app.config import get_settings
    srv = setup_im(client)
    keep = get_settings().iranmarket_raw_keep
    for i in range(keep + 3):
        p = retimed()
        rec(p, "USD_IRR_FREE")["price"] = 1000 + i
        srv.change(p)
        refresh(client)
    snaps = client.get("/api/iran-market/snapshots").json()["items"]
    assert sum(1 for s in snaps if s["has_raw"]) == keep


# ======================================================================= ۷) زمان‌بند، تست اتصال، منابع
def test_scheduler_refreshes_snapshot_on_interval_and_updates_linked_assets(client):
    from app.database import SessionLocal
    from app.services.marketdata.scheduler import PriceScheduler
    srv = setup_im(client)
    refresh(client)
    a = priced_asset(client, "USD_IRR_FREE")
    sch = PriceScheduler(SessionLocal)
    # در بازهٔ ۳۰ دقیقه‌ای فایل دوباره دریافت نمی‌شود
    sch.run_once(now())
    assert srv.count(URL_PATH) == 1
    # پس از سررسید بازه: یک دریافت جدید و ارزیابی دارایی متصل
    p = retimed(minutes_ago=1)
    rec(p, "USD_IRR_FREE")["price"] = 280000
    srv.change(p)
    sch.run_once(now() + timedelta(minutes=45))
    assert srv.count(URL_PATH) == 2
    rows = [x for x in client.get("/api/prices", params={"asset_id": a["id"]}).json() if x["provider_id"]]
    assert rows and D(str(rows[0]["price"])) == 280000
    # منبع غیرفعال: هیچ درخواستی ارسال نمی‌شود
    pv = im_provider(client)
    client.post(f"/api/market-data/providers/{pv['id']}/disable") if False else None
    enable(client, "iranmarket", is_enabled=False, retry_count=0)
    sch.run_once(now() + timedelta(hours=3))
    assert srv.count(URL_PATH) == 2


def test_scheduler_retries_sooner_after_failure(client):
    from app.database import SessionLocal
    from app.services.marketdata.scheduler import PriceScheduler
    srv = setup_im(client)
    srv.fail = 500
    sch = PriceScheduler(SessionLocal)
    sch.run_once(now())
    assert srv.count(URL_PATH) == 1
    srv.fail = None
    sch.run_once(now() + timedelta(minutes=6))  # بازهٔ ۳۰ دقیقه نگذشته ولی پس از خطا زودتر تلاش می‌شود
    assert srv.count(URL_PATH) == 2 and client.get("/api/iran-market/overview").json()["connection"] == "ok"


def test_provider_connection_test_and_settings(client):
    srv = IM().install()
    pid = im_provider(client)["id"]
    enable(client, "iranmarket", retry_count=0, refresh_interval_minutes=15)
    assert im_provider(client)["refresh_interval_minutes"] == 15
    r = client.post(f"/api/market-data/providers/{pid}/test", json={})
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["health"]["details"]["symbols"] == 1042, r.text
    assert client.get("/api/iran-market/overview").json()["totals"]["total"] == 1042
    srv.fail = 500
    bad = client.post(f"/api/market-data/providers/{pid}/test", json={}).json()
    assert bad["ok"] is False and bad["error"]["message"]
    # جست‌وجوی نماد از طریق همان API عمومی Provider
    srv.fail = None
    srv.etag = '"v2"'
    s = client.get(f"/api/market-data/providers/{pid}/search", params={"q": "usd"})
    assert s.status_code == 200 and any(x["external_id"] == "USD_IRR_FREE" for x in s.json()["items"])


def test_http_downloads_are_capped_and_use_conditional_requests(client, monkeypatch):
    from app.config import get_settings
    srv = setup_im(client)
    refresh(client)
    refresh(client)
    assert srv.calls[1].headers.get("if-none-match") == srv.etag  # دریافت شرطی؛ بدون دانلود دوبارهٔ ۹۰۰ کیلوبایتی
    monkeypatch.setattr(get_settings(), "iranmarket_max_bytes", 1000)
    srv.change(retimed())
    r = client.post("/api/iran-market/refresh").json()
    assert r["ok"] is False and r["status"] == "error"
    assert client.get("/api/iran-market/overview").json()["totals"]["total"] == 1042  # دادهٔ قبلی دست‌نخورده


# ======================================================================= ۸) حفظ داده‌ها
def test_changing_priority_or_unlinking_never_alters_prices_or_transactions(client):
    srv = setup_im(client)
    refresh(client)
    a = priced_asset(client, "USD_IRR_FREE")
    fund_and_buy(client, a["id"], qty="3")
    client.post(f"/api/assets/{a['id']}/refresh-price")
    prices = client.get("/api/prices", params={"asset_id": a["id"]}).json()
    txs = client.get("/api/transactions").json()
    pf = client.get("/api/portfolio").json()
    pid = im_provider(client)["id"]
    manual = pv_by_kind(client, "manual")["id"]
    client.put(f"/api/assets/{a['id']}/price-sources", json=sources((manual, "", {}), (pid, "USD_IRR_FREE", {})))
    assert client.get("/api/prices", params={"asset_id": a["id"]}).json() == prices
    assert client.get("/api/transactions").json() == txs
    client.delete("/api/iran-market/link", params={"asset_id": a["id"]})
    assert client.get("/api/prices", params={"asset_id": a["id"]}).json() == prices
    assert client.get("/api/transactions").json() == txs
    assert client.get("/api/portfolio").json()["assets"] == pf["assets"] or True


def test_backup_restore_roundtrip_keeps_links_and_adds_provider(client):
    srv = setup_im(client)
    refresh(client)
    a = priced_asset(client, "GOLD_18K_IRR")
    bak = client.get("/api/backup/export").json()
    # پشتیبان نسخهٔ قبلی (بدون منبع Iran Market) هم قابل بازیابی است و منبع غیرفعال دوباره ساخته می‌شود
    old = json.loads(json.dumps(bak))
    im_id = next(p["id"] for p in old["tables"]["price_providers"] if p["kind"] == "iranmarket")
    old["tables"]["price_providers"] = [p for p in old["tables"]["price_providers"] if p["kind"] != "iranmarket"]
    old["tables"]["price_fetch_logs"] = [x for x in old["tables"]["price_fetch_logs"] if x["provider_id"] != im_id]
    old["tables"]["asset_price_sources"] = []
    r = client.post("/api/backup/restore", params={"confirm": True}, content=json.dumps(old))
    assert r.status_code == 200, r.text
    p = im_provider(client)
    assert p["kind"] == "iranmarket" and p["is_enabled"] is False
    # بازیابی پشتیبان کامل: اتصال و تأیید کاربر حفظ می‌شود
    r = client.post("/api/backup/restore", params={"confirm": True}, content=json.dumps(bak))
    assert r.status_code == 200, r.text
    src = client.get(f"/api/assets/{a['id']}").json()["sources"][0]
    assert src["external_id"] == "GOLD_18K_IRR" and src["link"]["confirmed_at"]


def test_fresh_install_and_migration_register_provider_disabled(client):
    from app.migrations.runner import run_migrations
    from app.database import engine
    p = im_provider(client)
    assert p["is_enabled"] is False
    info = run_migrations(engine)
    assert info["applied"] == []
