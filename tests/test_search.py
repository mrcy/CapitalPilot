"""v2.4 — جست‌وجوی سراسری بازار.

دادهٔ آزمون همان نسخهٔ واقعی فایل Iran Market Data است (۱۰۴۲ نماد) که از مسیر واقعی دریافت/پردازش وارد دیتابیس می‌شود؛
هیچ فهرست ساختگی نماد در آزمون‌ها یا کد نیست. هیچ درخواست شبکه‌ای انجام نمی‌شود.
"""
import time

import httpx
import pytest

from app.services import search as S
from app.services.marketdata import http
from tests.test_marketdata import Mock, custom_provider, enable, isolate_engine, make_asset, now, pv_by_kind, sources  # noqa: F401
from tests.test_iranmarket import IM, all_symbols, fast_im, refresh, setup_im  # noqa: F401
from tests.iranmarket_data import rec, records, retimed


@pytest.fixture()
def loaded(client):
    """دیتابیس با دادهٔ واقعی؛ بازگشت (client, payload)."""
    payload = retimed(25)
    setup_im(client, payload)
    r = refresh(client)
    assert r["status"] == "ok" and r["symbols"] == 1042
    return client, payload


def find(client, q, group="all", **kw):
    r = client.get("/api/search", params={"q": q, "group": group, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def flat(d):
    return [it for g in d["groups"] for it in g["items"]] + d["items"]


def top(client, q):
    d = find(client, q)
    its = flat(d)
    assert its, f"نتیجه‌ای برای {q!r} نبود"
    # بالاترین رتبه = بالاترین tier در بین همهٔ گروه‌ها
    return max(its, key=lambda x: x["tier"])


def ids(d):
    return [it["id"] for it in flat(d)]


def counts_of(client):
    out = {}
    for t in ("assets", "transactions", "prices", "asset_price_sources", "portfolio_assets", "market_symbols", "fx_rates"):
        out[t] = None
    from sqlalchemy import func, select
    from app import models as m
    from app.database import SessionLocal
    with SessionLocal() as db:
        for t, mod in (("assets", m.Asset), ("transactions", m.Transaction), ("prices", m.Price), ("asset_price_sources", m.AssetPriceSource),
                       ("portfolio_assets", m.PortfolioAsset), ("market_symbols", m.MarketSymbol), ("fx_rates", m.FxRate)):
            out[t] = db.scalar(select(func.count()).select_from(mod))
    return out


# ---------------------------------------------------------------- ۱ تا ۵: نام، نماد، اعداد، ی/ک
def test_search_by_persian_name(loaded):
    c, _ = loaded
    t = top(c, "طلای ۱۸")
    assert t["symbol"] == "GOLD_18K_IRR" and t["name_fa"].startswith("طلای")
    d = find(c, "سکه امامی")
    assert flat(d)[0]["symbol"] == "COIN_EMAMI_IRR" and flat(d)[0]["match"] == "name_exact"


def test_search_by_english_name(loaded):
    c, _ = loaded
    t = top(c, "bitcoin")
    assert t["symbol"] == "BTC_USD" and t["match"] == "name_exact"
    assert top(c, "Emami gold coin")["symbol"] == "COIN_EMAMI_IRR"
    assert top(c, "brent crude")["symbol"] == "BRENT_USD"


def test_search_by_symbol_exact_and_partial(loaded):
    c, _ = loaded
    t = top(c, "GOLD_18K_IRR")
    assert t["symbol"] == "GOLD_18K_IRR" and t["match"] == "symbol_exact" and t["tier"] == S.TIER_SYMBOL_EXACT
    assert top(c, "gold 18k irr")["symbol"] == "GOLD_18K_IRR"       # فاصله به‌جای _ و حروف کوچک
    t = top(c, "usd_irr_f")                                         # بخشی از symbol (پیشوند)
    assert t["symbol"] == "USD_IRR_FREE" and t["match"] == "symbol_prefix"
    d = find(c, "GC5")
    assert flat(d)[0]["symbol"] == "GC5" and all(it["symbol"].startswith("GC5") for it in flat(d)[:5])
    # BTC: توکن دقیق نماد (دارایی پایه) قبل از تطبیق‌های ضعیف‌تر
    d = find(c, "BTC")
    assert flat(d)[0]["symbol"] in ("BTC_USD", "BTC_IRR") and flat(d)[0]["match"] == "symbol_token"


def test_persian_and_english_digits_are_equivalent(loaded):
    c, _ = loaded
    a, b, d = (ids(find(c, q)) for q in ("طلای ۱۸", "طلای 18", "طلای ١٨"))   # فارسی، انگلیسی، عربی-هندی
    assert a == b == d and "sym:GOLD_18K_IRR" in a
    assert find(c, "gold 18k")["normalized"] == "gold 18k"
    assert find(c, "۱۸ k")["normalized"] == find(c, "18 K")["normalized"] == "18 k"


def test_arabic_and_persian_letters_and_spaces_are_equivalent(loaded):
    c, _ = loaded
    assert ids(find(c, "سكه امامي")) == ids(find(c, "سکه امامی")) != []        # ك/ک و ي/ی
    assert ids(find(c, "  سکه   امامی  ")) == ids(find(c, "سکه امامی"))           # فاصلهٔ اضافه
    assert top(c, "بیتکوین")["symbol"] == "BTC_USD" and top(c, "بیت کوین")["symbol"] == "BTC_USD"  # نیم‌فاصله/فاصله
    assert ids(find(c, "اوند")) == ids(find(c, "آوند")) and "asset:" in " ".join(ids(find(c, "اوند")))   # آ/ا هم یکسان است (دارایی «صندوق آوند»)
    assert S.fold("كيك ۱۲٣") == "کیک 123" and S.fold("بیت‌کوین") == "بیت کوین" and S.compact("بیت‌کوین") == "بیتکوین"


# ---------------------------------------------------------------- ۶: دسته‌بندی و صفحه‌بندی
def test_results_are_grouped_and_paginated(loaded):
    c, _ = loaded
    d = find(c, "طلا")
    keys = [g["key"] for g in d["groups"]]
    assert "gold_coin" in keys and "funds" in keys
    assert d["counts"]["all"] == d["total"] and d["counts"]["gold_coin"] >= 50
    assert all(len(g["items"]) <= 5 for g in d["groups"])
    # «مشاهدهٔ همهٔ نتایج هر دسته»: صفحه‌بندی روی همان گروه، بدون تکرار و با جمع برابر شمارندهٔ همان گروه
    p1 = find(c, "طلا", "gold_coin", page_size=30, page=1)
    p2 = find(c, "طلا", "gold_coin", page_size=30, page=2)
    assert p1["total"] == p2["total"] == d["counts"]["gold_coin"]
    assert len(p1["items"]) == 30 and not ({x["id"] for x in p1["items"]} & {x["id"] for x in p2["items"]})
    assert all(it["group"] == "gold_coin" for it in p1["items"] + p2["items"])
    # هر فیلتر سریع پاسخ معتبر می‌دهد
    for g in S.GROUP_KEYS:
        assert find(c, "ی", g, page_size=5)["group"] == g
    assert c.get("/api/search", params={"q": "x", "group": "nope"}).status_code == 422


def test_group_classification_uses_real_categories(loaded):
    c, _ = loaded
    got = {}
    for q in ("USD_IRR_FREE", "GOLD_18K_IRR", "COIN_EMAMI_IRR", "BTC_USD", "BRENT_USD", "ZINC", "XAU_USD", "GC55", "NASDAQ_US", "XRP_IRR"):
        its = flat(find(c, q))
        got[q] = next(i["group"] for i in its if i["symbol"] == q)
    assert got == {"USD_IRR_FREE": "currency", "GOLD_18K_IRR": "gold_coin", "COIN_EMAMI_IRR": "gold_coin", "BTC_USD": "crypto", "BRENT_USD": "commodity_energy",
                   "ZINC": "commodity_energy", "XAU_USD": "gold_coin", "GC55": "funds", "NASDAQ_US": "bourse", "XRP_IRR": "crypto"}


def test_ranking_priority(loaded):
    c, _ = loaded
    # ۱) تطبیق دقیق symbol  ۲) نام دقیق  ۳) بخشی از نام  ۴) نام انگلیسی و مترادف‌ها
    assert S.TIER_SYMBOL_EXACT > S.TIER_NAME_EXACT > S.TIER_NAME_START > S.TIER_NAME_WORD > S.TIER_NAME_CONTAINS > S.TIER_EN_WORD > S.TIER_SYNONYM > S.TIER_FUZZY
    cases = [("GOLD_18K_IRR", "GOLD_18K_IRR", "symbol_exact"), ("سکه امامی", "COIN_EMAMI_IRR", "name_exact"), ("Emami gold coin", "COIN_EMAMI_IRR", "name_exact"),
             ("طلای ۱۸", "GOLD_18K_IRR", "name_start"), ("لای ۱۸ عیار", "GOLD_18K_IRR", "name_contains"), ("Brent", "BRENT_USD", "symbol_token")]
    for q, sym, how in cases:
        t = top(c, q)
        assert (t["symbol"], t["match"], t["tier"]) == (sym, how, {"symbol_exact": S.TIER_SYMBOL_EXACT, "name_exact": S.TIER_NAME_EXACT, "name_start": S.TIER_NAME_START,
                                                                   "name_contains": S.TIER_NAME_CONTAINS, "symbol_token": S.TIER_SYMBOL_TOKEN}[how]), q
    syn = [i for i in flat(find(c, "دلار", "crypto", page_size=50))]
    assert syn and all(i["match"] == "synonym" and i["tier"] == S.TIER_SYNONYM for i in syn)
    # ترتیب نتیجه‌ها: نام دقیق قبل از بخشی از نام، و هر دو قبل از مترادف
    seq = [it["tier"] for it in flat(find(c, "bitcoin", "crypto", page_size=10))]
    assert seq == sorted(seq, reverse=True) and seq[0] == S.TIER_NAME_EXACT and S.TIER_SYNONYM in seq
    d = find(c, "سکه امامی")
    tiers = [it["tier"] for it in d["groups"][0]["items"]]
    assert tiers == sorted(tiers, reverse=True)
    # نماد دقیق از نام دقیق مهم‌تر است: داراییِ من با symbol «GC5» و نماد GC5 هر دو tier 100، ولی نام دقیق کمتر
    first = flat(find(c, "GC5"))[0]
    assert first["match"] == "symbol_exact"


def test_synonyms_and_category_names(loaded):
    c, _ = loaded
    assert top(c, "دلار")["symbol"] == "USD_IRR_FREE"          # نام + محبوب
    d = find(c, "gold", per_group=10)
    assert any(i["symbol"] == "XAU_USD" for i in flat(find(c, "gold", "gold_coin", page_size=60)))
    syn = find(c, "usd", per_group=20)
    assert any(i["match"] == "symbol_token" for i in flat(syn))
    # نام دسته و بازار
    d = find(c, "بازار طلا و سکه")
    assert any(i["kind"] == "market" and i["market_label"] == "بازار طلا و سکهٔ ایران" for i in flat(d))
    assert find(c, "رمزارز")["counts"]["crypto"] >= 60
    # مترادف: «bitcoin» ← BTC (دارایی پایه)، نه هر نمادی که USD دارد
    syms = [i["symbol"] for i in flat(find(c, "دلار", "crypto", page_size=50))]
    assert "BTC_USD" not in syms


def test_typo_tolerant_search(loaded):
    c, _ = loaded
    for q, want in (("بیتکون", "BTC_USD"), ("bitcion", "BTC_USD"), ("zink", "ZINC"), ("دلر", "USD_IRR_FREE")):
        d = find(c, q)
        its = flat(d)
        assert any(i["symbol"] == want for i in flat(find(c, q, "all", per_group=20))), q
        assert d["fuzzy"] is True and all(i["match"] == "fuzzy" for i in its), q
    # تقریبی فقط وقتی تطبیق درستی نیست؛ و بی‌ربط نتیجه نمی‌دهد
    assert find(c, "bitcoin")["fuzzy"] is False
    assert find(c, "qzxwvkj")["total"] == 0
    assert S.edit_distance("bitcoin", "bitcion", 1) == 1 and S.edit_distance("abc", "xyz", 1) == 2


def test_results_come_from_real_data_only(loaded):
    c, payload = loaded
    real = {r["symbol"] for r in records(payload)}
    seen = set()
    for q in ("طلا", "دلار", "bitcoin", "نفت", "GC", "ی"):
        for it in flat(find(c, q, per_group=20)):
            if it["kind"] == "symbol":
                seen.add(it["symbol"])
    assert seen and seen <= real
    assert find(c, "یک نماد ساختگی که وجود ندارد")["total"] == 0


# ---------------------------------------------------------------- ۱۳: قدیمی/نامعتبر/ناموجود هرگز «معتبر» نیست
def test_stale_prices_are_never_shown_as_valid(loaded):
    c, payload = loaded
    r = rec(payload, "ZINC")
    assert r["stale"] is True
    it = next(i for i in flat(find(c, "ZINC")) if i["symbol"] == "ZINC")
    assert it["status"] == "stale" and it["status_text"] == "قدیمی" and it["live"] is False
    assert it["price"] is not None and it["age_text"]            # آخرین قیمت شناخته‌شده همراه هشدار نمایش داده می‌شود
    ok = next(i for i in flat(find(c, "GOLD_18K_IRR")) if i["symbol"] == "GOLD_18K_IRR")
    assert ok["status"] == "valid" and ok["live"] is True and ok["status_reason"] == ""
    # همهٔ نمادهای stale فایل در جست‌وجو هم stale‌اند (دقیقاً همان منطق صفحهٔ بازار جامع)
    d = find(c, "ی", "commodity_energy", page_size=100)
    for it in d["items"]:
        if it["kind"] == "symbol":
            assert it["live"] == (it["status"] == "valid")
            if it["status"] != "valid":
                assert it["status_reason"]


def test_invalid_and_missing_prices_are_not_live_prices(client):
    p = retimed(25)
    bad = rec(p, "GOLD_18K_IRR")
    bad["timestamp"], bad["timestamp_tehran"] = "not-a-time", None            # زمان خراب ⇒ نامعتبر
    nop = rec(p, "COIN_EMAMI_IRR")
    nop["price"] = None                                                       # بدون قیمت ⇒ ناموجود
    setup_im(client, p)
    refresh(client)
    a = next(i for i in flat(find(client, "GOLD_18K_IRR")) if i["symbol"] == "GOLD_18K_IRR")
    assert a["status"] == "invalid" and a["status_text"] == "نامعتبر" and a["live"] is False
    assert a["price"] is None and a["change_pct"] is None and a["status_reason"]
    b = next(i for i in flat(find(client, "COIN_EMAMI_IRR")) if i["symbol"] == "COIN_EMAMI_IRR")
    assert b["status"] == "missing" and b["status_text"] == "ناموجود" and b["live"] is False and b["price"] is None


def test_asset_price_states_in_results(client):
    from datetime import timedelta
    plat = {x["name"]: x["id"] for x in client.get("/api/platforms").json()}
    fresh = make_asset(client, name="دارایی تازه")
    old = make_asset(client, name="دارایی کهنه")
    none = make_asset(client, name="دارایی بدون قیمت")
    today = client.get("/api/meta").json()["today"]
    client.post("/api/prices", json={"asset_id": fresh["id"], "price": "1000", "recorded_at": f"{today}T10:00:00", "source": "manual"})
    from datetime import date
    old_day = (date.fromisoformat(today) - timedelta(days=20)).isoformat()
    r = client.post("/api/prices", json={"asset_id": old["id"], "price": "900", "recorded_at": f"{old_day}T10:00:00", "source": "manual"})
    assert r.status_code == 201, r.text
    by = {i["name_fa"]: i for i in flat(find(client, "دارایی", "mine"))}
    assert by["دارایی تازه"]["status"] == "valid" and by["دارایی تازه"]["live"] and by["دارایی تازه"]["price"] == "1000"
    assert by["دارایی کهنه"]["status"] == "stale" and not by["دارایی کهنه"]["live"]
    assert by["دارایی بدون قیمت"]["status"] == "missing" and by["دارایی بدون قیمت"]["price"] is None
    assert all(i["kind"] == "asset" and i["platform"] for i in by.values())


# ---------------------------------------------------------------- دارایی‌های من، پلتفرم‌ها و بازارها
def test_my_assets_platforms_and_markets(loaded):
    c, _ = loaded
    a = make_asset(client=c, name="صندوق شاخص تست", symbol="TSTX", name_en="Test Index Fund", market="بورس تهران")
    d = find(c, "تست", "mine")
    assert d["total"] >= 1 and all(i["kind"] == "asset" for i in d["items"])
    assert any(i["asset_id"] == a["id"] for i in d["items"])
    # با نام انگلیسی، نماد، پلتفرم و بازار هم پیدا می‌شود
    for q in ("Test Index", "TSTX", "tstx", "مفید", "بورس تهران"):
        assert any(i["kind"] == "asset" and i["asset_id"] == a["id"] for i in flat(find(c, q, per_group=20))), q
    # پلتفرم‌ها: از جدول پلتفرم‌ها (مفید از دادهٔ پیش‌فرض)
    pl = [i for i in flat(find(c, "مفید")) if i["kind"] == "platform"]
    assert pl and pl[0]["name_fa"] == "مفید" and pl[0]["asset_count"] >= 1
    # بازارها: از دادهٔ واقعی نمادها
    mk = [i for i in flat(find(c, "بازار آزاد ایران")) if i["kind"] == "market"]
    assert mk and mk[0]["market"] == "iran_free" and mk[0]["count"] > 100
    # دارایی بایگانی‌شده در جست‌وجو نیست
    c.post(f"/api/assets/{a['id']}/archive")
    assert not any(i["kind"] == "asset" and i["asset_id"] == a["id"] for i in flat(find(c, "TSTX", per_group=20)))


# ---------------------------------------------------------------- ۱۰: بدون شبکه و آفلاین
def _network_trap():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        raise httpx.ConnectError("offline", request=request)

    http.set_test_transport(httpx.MockTransport(handler))
    return calls


def test_search_works_offline_and_never_hits_network(loaded):
    c, _ = loaded
    calls = _network_trap()
    for q in ("طلا", "bitcoin", "BTC", "دلار", "بیتکون", "ی", "ZINC"):
        assert find(c, q)["total"] > 0
    assert c.get("/api/search/suggestions").status_code == 200
    assert calls == []   # حتی یک درخواست هم به بیرون ارسال نشد
    # حتی وقتی دریافت واقعی شکست می‌خورد، جست‌وجو روی آخرین داده‌های ذخیره‌شده ادامه می‌دهد
    c.post("/api/iran-market/refresh")
    assert calls, "دریافت دستی باید تلاش کرده باشد (و شکست خورده باشد)"
    d = find(c, "سکه امامی")
    assert flat(d)[0]["symbol"] == "COIN_EMAMI_IRR" and d["data_state"]["has_data"] is True


def test_stale_snapshot_flags_every_price_as_not_live(loaded, monkeypatch):
    c, _ = loaded
    from datetime import timedelta
    from app.services.marketdata import iranmarket as im
    future = im.now_local() + timedelta(days=2)       # فایل قدیمی شد (قطع طولانی اینترنت)
    monkeypatch.setattr(S, "now_local", lambda: future)
    monkeypatch.setattr(im, "now_local", lambda: future)
    d = find(c, "طلای ۱۸")
    it = flat(d)[0]
    assert it["symbol"] == "GOLD_18K_IRR" and it["status"] == "stale" and it["live"] is False
    ds = d["data_state"]
    assert ds["stale"] is True and ds["reason"] and ds["has_data"] and ds["offline_capable"]


def test_empty_database_state(client):
    d = find(client, "طلا")
    assert d["data_state"]["has_data"] is False and d["data_state"]["symbols"] == 0
    assert all(i["kind"] != "symbol" for i in flat(d))                       # فقط دارایی‌های پیش‌فرض خود برنامه؛ نمادی وجود ندارد
    s = client.get("/api/search/suggestions").json()
    assert s["popular_symbols"] == [] and s["data_state"]["has_data"] is False
    assert all(find(client, t)["total"] > 0 for t in s["popular_terms"])     # عبارت محبوب فقط با نتیجهٔ واقعی
    assert find(client, "")["total"] == 0 and find(client, "   ")["groups"] == []


# ---------------------------------------------------------------- پیشنهادها
def test_suggestions_are_real(loaded):
    c, _ = loaded
    a = make_asset(c, name="دارایی متصل")
    c.post("/api/search/link", json={"symbol": "USDT_IRR", "asset_id": a["id"], "confirm": True})
    s = c.get("/api/search/suggestions").json()
    syms = [x["symbol"] for x in s["popular_symbols"]]
    assert syms[0] == "USDT_IRR" and s["popular_symbols"][0]["mine"] is True   # نمادهای متصل به دارایی‌های من اول
    assert {"USD_IRR_FREE", "GOLD_18K_IRR", "BTC_USD"} <= set(syms)
    real = {i["symbol"] for i in all_symbols(c)}
    assert set(syms) <= real and len(real) == 1042
    assert all(x["status"] in ("valid", "stale", "invalid", "missing") for x in s["popular_symbols"])
    assert s["popular_terms"] and all(find(c, t)["total"] > 0 for t in s["popular_terms"])
    assert s["data_state"]["has_data"] is True


def test_suggestions_skip_symbols_missing_from_data(client):
    p = retimed(25)
    for lst in p["data"]["categories"].values():
        lst[:] = [r for r in lst if r["symbol"] != "BRENT_USD"]
    setup_im(client, p)
    refresh(client)
    syms = [x["symbol"] for x in client.get("/api/search/suggestions").json()["popular_symbols"]]
    assert "BRENT_USD" not in syms and "USD_IRR_FREE" in syms


# ---------------------------------------------------------------- ۷: اتصال به دارایی موجود (فقط با تأیید)
def test_link_requires_explicit_confirmation(loaded):
    c, _ = loaded
    a = make_asset(c, name="ارز من", currency="IRT")
    before = counts_of(c)
    r = c.post("/api/search/link", json={"symbol": "USD_IRR_FREE", "asset_id": a["id"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "not_confirmed"
    assert counts_of(c) == before
    r = c.post("/api/search/link", json={"symbol": "USD_IRR_FREE", "asset_id": a["id"], "confirm": True})
    assert r.status_code == 200, r.text
    assert r.json()["link"]["currency"] == "IRT" and r.json()["link"]["confirmed_at"]
    after = counts_of(c)
    assert after["asset_price_sources"] == before["asset_price_sources"] + 1
    assert after["transactions"] == before["transactions"] and after["prices"] == before["prices"] and after["assets"] == before["assets"]
    src = c.get(f"/api/assets/{a['id']}").json()["sources"][0]
    assert src["external_id"] == "USD_IRR_FREE" and src["link"]["confirmed_at"] and src["provider_kind"] == "iranmarket"


def test_link_unit_must_be_acknowledged_and_currency_must_match(loaded):
    c, _ = loaded
    a = make_asset(c, name="طلا من", currency="IRT")
    r = c.post("/api/search/link", json={"symbol": "GOLD_18K_IRR", "asset_id": a["id"], "confirm": True})   # قیمت «هر گرم»
    assert r.status_code == 422 and r.json()["error"]["code"] == "unit_not_acknowledged"
    r = c.post("/api/search/link", json={"symbol": "GOLD_18K_IRR", "asset_id": a["id"], "confirm": True, "ack_unit": True})
    assert r.status_code == 200, r.text
    b = make_asset(c, name="رمزارز من", currency="IRT")
    r = c.post("/api/search/link", json={"symbol": "BTC_USD", "asset_id": b["id"], "confirm": True, "ack_unit": True})   # USD روی دارایی IRT
    assert r.status_code == 422 and r.json()["error"]["code"] == "link_blocked"
    assert c.get(f"/api/assets/{b['id']}").json()["sources"] == []
    d = make_asset(c, name="ین من", currency="IRT")
    r = c.post("/api/search/link", json={"symbol": "JPY_IRR_FREE", "asset_id": d["id"], "confirm": True, "ack_unit": True})  # اندازهٔ واحد ۱۰۰
    assert r.status_code == 422 and r.json()["error"]["code"] == "link_blocked"
    assert c.post("/api/search/link", json={"symbol": "NOPE_SYMBOL", "asset_id": d["id"], "confirm": True}).json()["error"]["code"] == "symbol_not_found"
    assert c.post("/api/search/link", json={"symbol": "USD_IRR_FREE", "asset_id": 99999, "confirm": True}).status_code == 404


def test_duplicate_link_is_prevented(loaded):
    c, _ = loaded
    a1, a2 = make_asset(c, name="دلار یک"), make_asset(c, name="دلار دو")
    assert c.post("/api/search/link", json={"symbol": "USD_IRR_FREE", "asset_id": a1["id"], "confirm": True}).status_code == 200
    # همان نماد به دارایی دیگر
    r = c.post("/api/search/link", json={"symbol": "USD_IRR_FREE", "asset_id": a2["id"], "confirm": True})
    assert r.status_code == 409 and r.json()["error"]["code"] == "symbol_already_linked"
    assert r.json()["error"]["details"]["asset"] == "دلار یک"
    # همان دارایی با نماد دیگر
    r = c.post("/api/search/link", json={"symbol": "EUR_IRR_FREE", "asset_id": a1["id"], "confirm": True})
    assert r.status_code == 409 and r.json()["error"]["code"] == "asset_already_linked"
    # ایجاد دارایی جدید از همان نماد هم همان جلوگیری را دارد
    plat = c.get("/api/platforms").json()[0]["id"]
    r = c.post("/api/search/create-asset", json={"symbol": "USD_IRR_FREE", "platform_id": plat, "confirm": True})
    assert r.status_code == 409 and r.json()["error"]["code"] == "symbol_already_linked"
    # وضعیت اتصال در نتیجه دیده می‌شود
    it = next(i for i in flat(find(c, "USD_IRR_FREE")) if i["symbol"] == "USD_IRR_FREE")
    assert [x["name"] for x in it["linked_assets"]] == ["دلار یک"] and it["linked_assets"][0]["asset_id"] == a1["id"]
    # با قطع اتصال، دوباره آزاد می‌شود
    assert c.delete(f"/api/iran-market/link?asset_id={a1['id']}").json()["ok"] is True
    assert c.post("/api/search/link", json={"symbol": "USD_IRR_FREE", "asset_id": a2["id"], "confirm": True}).status_code == 200


def test_link_refuses_archived_asset(loaded):
    c, _ = loaded
    a = make_asset(c, name="بایگانی")
    c.post(f"/api/assets/{a['id']}/archive")
    r = c.post("/api/search/link", json={"symbol": "USD_IRR_FREE", "asset_id": a["id"], "confirm": True})
    assert r.status_code == 422 and r.json()["error"]["code"] == "asset_archived"


# ---------------------------------------------------------------- ۸: ایجاد دارایی از روی نماد (بدون تراکنش و موجودی)
def _dashboard_total(c):
    return c.get("/api/portfolio").json()


def test_create_asset_from_symbol_creates_no_transaction_or_holding(loaded):
    c, _ = loaded
    plat = {x["name"]: x["id"] for x in c.get("/api/platforms").json()}["مفید"]
    pf2 = c.post("/api/portfolios", json={"name": "سبد دوم"}).json()
    before = counts_of(c)
    port_before = _dashboard_total(c)
    r = c.post("/api/search/create-asset", json={"symbol": "USD_IRR_FREE", "platform_id": plat, "portfolio_id": pf2["id"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "not_confirmed"
    assert counts_of(c) == before
    r = c.post("/api/search/create-asset", json={"symbol": "USD_IRR_FREE", "platform_id": plat, "portfolio_id": pf2["id"], "confirm": True})
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["transactions_created"] == 0 and out["portfolio_ids"] == [pf2["id"]] and out["asset_type"] == "currency"
    after = counts_of(c)
    assert after["assets"] == before["assets"] + 1 and after["transactions"] == before["transactions"]
    assert after["asset_price_sources"] == before["asset_price_sources"] + 1 and after["portfolio_assets"] == before["portfolio_assets"] + 1
    a = c.get(f"/api/assets/{out['asset_id']}").json()
    assert a["name"] == "دلار آمریکا (بازار آزاد)" and a["symbol"] == "USD_IRR_FREE" and a["name_en"].startswith("US Dollar")
    assert a["price_currency"] == "IRT" and str(a["target_weight"]) in ("0", "0.0000") and a["sources"][0]["external_id"] == "USD_IRR_FREE"
    assert a["sources"][0]["link"]["confirmed_at"]
    # موجودی/ارزش سبد دست‌نخورده است و هیچ تراکنشی نیست
    assert c.get("/api/transactions").json()["total"] == 0
    p2 = c.get("/api/portfolio", params={"portfolio_id": pf2["id"]}).json()
    row = next(x for x in p2["assets"] if x["id"] == out["asset_id"])
    assert str(row["units"]) in ("0", "0.0", "0E-8") or float(row["units"]) == 0
    assert float(row["value"] or 0) == 0
    assert _dashboard_total(c)["totals"] == port_before["totals"]


def test_create_asset_from_symbol_validations(loaded):
    c, _ = loaded
    plat = c.get("/api/platforms").json()[0]["id"]
    body = {"platform_id": plat, "confirm": True}
    # قیمت به واحد گرم نیازمند تأیید واحد است و اعشار مناسب دارد
    r = c.post("/api/search/create-asset", json={**body, "symbol": "GOLD_18K_IRR"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "unit_not_acknowledged"
    r = c.post("/api/search/create-asset", json={**body, "symbol": "GOLD_18K_IRR", "ack_unit": True, "name": "طلای آبشده من"})
    assert r.status_code == 201, r.text
    a = c.get(f"/api/assets/{r.json()['asset_id']}").json()
    assert a["name"] == "طلای آبشده من" and a["asset_type"] == "gold" and a["unit"] == "گرم" and a["decimals"] == 4
    # واحد POINTS ارز سیستم نیست ⇒ بدون حدس رد می‌شود
    r = c.post("/api/search/create-asset", json={**body, "symbol": "NASDAQ_US"})
    assert r.status_code == 422 and r.json()["error"]["code"] in ("currency_unsupported", "link_blocked")
    # اندازهٔ واحد ۱۰۰ پشتیبانی نمی‌شود
    assert c.post("/api/search/create-asset", json={**body, "symbol": "JPY_IRR_FREE", "ack_unit": True}).status_code == 422
    # نماد ناموجود و پلتفرم ناموجود
    assert c.post("/api/search/create-asset", json={**body, "symbol": "NOPE"}).json()["error"]["code"] == "symbol_not_found"
    assert c.post("/api/search/create-asset", json={"platform_id": 9999, "confirm": True, "symbol": "EUR_IRR_FREE"}).status_code == 404
    # نام تکراری در همان پلتفرم
    ok = c.post("/api/search/create-asset", json={**body, "symbol": "EUR_IRR_FREE", "name": "نام تکراری"})
    assert ok.status_code == 201
    dup = c.post("/api/search/create-asset", json={**body, "symbol": "AFN_IRR_FREE", "name": "نام تکراری"})
    assert dup.status_code == 409
    # نوع دارایی ناموجود به «سایر» برمی‌گردد
    r = c.post("/api/search/create-asset", json={**body, "symbol": "QAR_IRR_FREE", "asset_type": "inactive_type"})
    assert r.status_code == 201 and c.get(f"/api/assets/{r.json()['asset_id']}").json()["asset_type"] == "other"
    extra = c.post("/api/search/create-asset", json={**body, "symbol": "EUR_IRR_FREE", "bogus": 1})
    assert extra.status_code == 422


def test_created_asset_price_is_not_fabricated_and_stale_never_valid(loaded):
    c, payload = loaded
    plat = c.get("/api/platforms").json()[0]["id"]
    stale_sym = next(r["symbol"] for r in records(payload) if r.get("stale") and r["currency"] == "IRT" and r["unit"] == "unit" and r.get("price"))
    r = c.post("/api/search/create-asset", json={"symbol": stale_sym, "platform_id": plat, "confirm": True})
    assert r.status_code == 201, r.text
    aid = r.json()["asset_id"]
    # فعلاً هیچ قیمتی برای دارایی ساخته نشده؛ قیمت قدیمی ⇒ نتیجهٔ دارایی «معتبر» نیست
    it = next(i for i in flat(find(c, stale_sym, "mine")) if i["kind"] == "asset" and i["asset_id"] == aid)
    assert it["status"] != "valid" and it["live"] is False
    ref = c.post(f"/api/assets/{aid}/refresh-price").json()
    it = next(i for i in flat(find(c, stale_sym, "mine")) if i["kind"] == "asset" and i["asset_id"] == aid)
    assert it["status"] != "valid" and it["live"] is False, ref
    cur = {x["asset_id"]: x for x in c.get("/api/prices/current").json()["items"]}[aid]
    assert cur["ok"] is False        # در ارزش‌گذاری استفاده نمی‌شود


def test_created_asset_with_valid_symbol_gets_price_when_source_enabled(loaded):
    c, _ = loaded
    plat = c.get("/api/platforms").json()[0]["id"]
    r = c.post("/api/search/create-asset", json={"symbol": "USD_IRR_FREE", "platform_id": plat, "confirm": True})
    assert r.status_code == 201, r.text
    assert r.json()["price_fetch"] and r.json()["price_fetch"]["ok"] is True
    it = next(i for i in flat(find(c, "USD_IRR_FREE", "mine")) if i["kind"] == "asset")
    assert it["status"] == "valid" and it["live"] is True and it["price"] and it["source"]


# ---------------------------------------------------------------- افزودن به سبد
def test_add_asset_to_portfolio(loaded):
    c, _ = loaded
    a = make_asset(c, name="دارایی سبد")
    pf2 = c.post("/api/portfolios", json={"name": "سبد دوم"}).json()
    before = counts_of(c)
    assert c.post("/api/search/add-to-portfolio", json={"asset_id": a["id"], "portfolio_id": pf2["id"]}).json()["error"]["code"] == "not_confirmed"
    assert counts_of(c) == before
    r = c.post("/api/search/add-to-portfolio", json={"asset_id": a["id"], "portfolio_id": pf2["id"], "confirm": True})
    assert r.status_code == 201, r.text
    after = counts_of(c)
    assert after["portfolio_assets"] == before["portfolio_assets"] + 1 and after["transactions"] == before["transactions"]
    pf = c.get(f"/api/portfolios/{pf2['id']}").json()
    member = next(x for x in pf["members"] if x["asset_id"] == a["id"])
    assert str(member["target_weight"]) in ("0", "0.0000")
    assert c.post("/api/search/add-to-portfolio", json={"asset_id": a["id"], "portfolio_id": pf2["id"], "confirm": True}).status_code == 409
    # نتیجهٔ جست‌وجو سبدهای دارایی را نشان می‌دهد
    it = next(i for i in flat(find(c, "دارایی سبد", "mine")) if i["asset_id"] == a["id"])
    assert pf2["id"] in [p["id"] for p in it["portfolios"]]
    c.post(f"/api/assets/{a['id']}/archive")
    assert c.post("/api/search/add-to-portfolio", json={"asset_id": a["id"], "portfolio_id": 1, "confirm": True}).status_code in (409, 422)
    assert c.post("/api/search/add-to-portfolio", json={"asset_id": 99999, "portfolio_id": 1, "confirm": True}).status_code == 404


# ---------------------------------------------------------------- محدودیت‌های مهم
def test_search_is_read_only(loaded):
    c, _ = loaded
    make_asset(c, name="دارایی فقط‌خواندنی")
    before = counts_of(c)
    for q in ("طلا", "bitcoin", "ی", "بیتکون", "دارایی", "GC5", ""):
        for g in ("all", "mine", "currency", "other"):
            find(c, q, g)
    c.get("/api/search/suggestions")
    assert counts_of(c) == before
    # هیچ مسیر نوشتنی بدون confirm اجرا نمی‌شود
    assert c.post("/api/search/link", json={"symbol": "USD_IRR_FREE", "asset_id": 1}).status_code == 422
    assert c.post("/api/search/create-asset", json={"symbol": "USD_IRR_FREE", "platform_id": 1}).status_code == 422
    assert c.post("/api/search/add-to-portfolio", json={"asset_id": 1, "portfolio_id": 1}).status_code == 422
    assert counts_of(c) == before
    assert c.put("/api/search", json={}).status_code == 405 and c.delete("/api/search").status_code == 405


def test_existing_data_and_valuation_untouched_by_actions(loaded):
    c, _ = loaded
    plat = {x["name"]: x["id"] for x in c.get("/api/platforms").json()}["مفید"]
    before = c.get("/api/portfolio").json()
    r = c.post("/api/search/create-asset", json={"symbol": "EUR_IRR_FREE", "platform_id": plat, "confirm": True})
    assert r.status_code == 201
    after = c.get("/api/portfolio").json()
    assert after["totals"] == before["totals"] and after["valuation_complete"] == before["valuation_complete"]
    old = {x["id"]: x for x in before["assets"]}
    assert old and {k: v for k, v in {x["id"]: x for x in after["assets"]}.items() if k in old} == old   # دارایی‌ها و موجودی‌های قبلی دست‌نخورده
    assert c.get("/api/transactions").json()["total"] == 0


def test_validation_and_limits(loaded):
    c, _ = loaded
    assert c.get("/api/search", params={"q": "x" * 81}).status_code == 422
    assert c.get("/api/search", params={"q": "x", "page_size": 101}).status_code == 422
    assert c.get("/api/search", params={"q": "x", "page": 0}).status_code == 422
    # کاراکترهای خاص خطا نمی‌دهند
    for q in ("%", "_", "'; drop table assets;--", "\\", "<script>alert(1)</script>", "😀", "a" * 80):
        assert c.get("/api/search", params={"q": q}).status_code == 200


def test_search_speed_with_full_file(loaded):
    c, _ = loaded
    find(c, "طلا")  # گرم‌کردن کش fold
    t = time.perf_counter()
    for q in ("طلا", "bitcoin", "ی", "بیتکون"):
        find(c, q)
    assert (time.perf_counter() - t) / 4 < 1.5       # حد بسیار گشاده؛ معمولاً چند ده میلی‌ثانیه


# ---------------------------------------------------------------- واحدها (بدون سرور)
def test_fold_and_query_helpers():
    assert S.fold("  طلای   ۱۸  ") == "طلای 18" and S.fold("USD/IRR_free") == "usd irr free"
    assert S.fold("ﺑﻴﺖ‌ﻛﻮﻳﻦ") == "بیت کوین"                    # حروف عربی/ارائه
    assert S.fold("آوند") == S.fold("اوند") and S.fold("") == "" and S.fold(None) == ""
    q = S.parse_query("bitcoin")
    assert "btc" in q.alts[0] and "بیتکوین" in q.alts[0]
    assert S.alternatives("دلار") and "usd" in S.alternatives("دلار")
    assert S.edit_distance("دلار", "دلر", 1) == 1 and S.edit_distance("abcd", "abdc", 1) == 1 and S.edit_distance("abcdef", "uvwxyz", 2) == 3


def test_group_classifier_units():
    cb, cu = {"BTC", "XRP"}, {"USD", "EUR"}
    cl = S.classify_group
    assert cl("other", "other", "XRP_IRR", "XRP_IRR", "XRP_IRR", cb, cu) == "crypto"
    assert cl("other", "other", "YEMEN_USD_SELL", "", "", cb, cu) == "currency"
    assert cl("other", "other", "IME_OPTION_X", "", "", cb, cu) == "commodity_energy"
    assert cl("coin", "iran_gold", "GC55", "صندوق طلای جواهر", "GC55", cb, cu) == "funds"
    assert cl("index", "global", "NASDAQ_US", "", "", cb, cu) == "bourse"
    assert cl("index", "global", "DIFF_USD_JPY", "", "", cb, cu) == "other"
    assert cl("precious_metal", "global", "SILVER", "انس نقره", "Silver", cb, cu) == "commodity_energy"
    assert cl("precious_metal", "global", "XAU_USD", "انس طلا", "Gold ounce", cb, cu) == "gold_coin"
    assert cl("something_new", "x", "FOO", "", "", cb, cu) == "other"       # دستهٔ جدید در فایل = «سایر»
