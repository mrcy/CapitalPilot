"""مهاجرت پایگاه‌دادهٔ نسخهٔ ۱ → ۲ بدون از دست رفتن داده، و بازیابی پشتیبان نسخهٔ ۱."""
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

FIX = Path(__file__).parent / "fixtures"


def _jsonable(o):
    return json.loads(json.dumps(o, default=str, ensure_ascii=False))


def _eq(exp, got) -> bool:
    """مقایسهٔ عددی دقیق (Decimal) و زمان؛ خروجی v1 JSON با عدد اعشاری و v2 با رشته است."""
    from decimal import Decimal, InvalidOperation
    if isinstance(exp, dict):
        return isinstance(got, dict) and exp.keys() <= got.keys() and all(_eq(v, got[k]) for k, v in exp.items())
    if isinstance(exp, list):
        return isinstance(got, list) and len(exp) == len(got) and all(_eq(a, b) for a, b in zip(exp, got))
    if exp is None or got is None or isinstance(exp, bool) or isinstance(got, bool):
        return exp == got
    try:
        a, b = Decimal(str(exp)), Decimal(str(got))
        return abs(a - b) <= Decimal("1e-9") * max(Decimal(1), abs(a))  # گلدن فایل با float ذخیره شده است
    except InvalidOperation:
        return str(exp).replace(" ", "T") == str(got).replace(" ", "T")


def _subset(exp, got):
    assert _eq(exp, got)


@pytest.fixture()
def v1_engine(tmp_path):
    """دیتابیس واقعی نسخهٔ ۱ (dump تولیدشده با کد v1 همراه تراکنش خرید/فروش، قیمت و برنامهٔ ۱۳‌دوره‌ای)."""
    path = tmp_path / "v1.db"
    con = sqlite3.connect(path)
    con.executescript((FIX / "v1_dump.sql").read_text())
    con.commit()
    con.close()
    from app.database import make_engine
    eng = make_engine(f"sqlite:///{path}")
    yield eng
    eng.dispose()


def _counts(engine):
    with engine.connect() as c:
        return {t: c.execute(text(f"select count(*) from {t}")).scalar() for t in ("transactions", "prices", "assets", "plan_periods", "platforms", "fx_rates")}


def test_v1_database_migrates_losslessly(v1_engine):
    from app import models as m
    from app.migrations.runner import run_migrations
    from app.services import summary
    from app.services.repository import load_dataset
    before = _counts(v1_engine)
    with v1_engine.connect() as c:
        tx_before = c.execute(text("select id, asset_id, platform_id, tx_type, tx_date, quantity, unit_price, fee, total_amount from transactions order by id")).fetchall()
    assert "schema_migrations" not in inspect(v1_engine).get_table_names()
    info = run_migrations(v1_engine)
    assert info["fresh"] is False and info["applied"] == [1, 2] and info["backup"]
    from app.config import get_settings
    assert (get_settings().backup_dir / info["backup"]).exists()
    # ردیف‌ها و مقادیر تراکنش‌ها دقیقاً حفظ شده‌اند
    after = _counts(v1_engine)
    assert after["platforms"] == 8 and before["platforms"] == 2  # پلتفرم‌های جدید افزوده شده؛ قبلی‌ها حفظ‌اند
    assert {k: after[k] for k in before if k != "platforms"} == {k: before[k] for k in before if k != "platforms"}
    with v1_engine.connect() as c:
        tx_after = c.execute(text("select id, asset_id, platform_id, tx_type, tx_date, quantity, unit_price, fee, total_amount from transactions order by id")).fetchall()
    assert tx_before == tx_after
    # ساختار جدید
    tables = set(inspect(v1_engine).get_table_names())
    assert {"portfolios", "portfolio_assets", "asset_types", "price_providers", "asset_price_sources", "price_fetch_logs"} <= tables
    with Session(v1_engine) as db:
        pf = db.scalars(select(m.Portfolio)).all()
        assert len(pf) == 1 and pf[0].is_default
        assert all(t.portfolio_id == pf[0].id for t in db.scalars(select(m.Transaction)))
        assert all(p.portfolio_id == pf[0].id for p in db.scalars(select(m.PlanPeriod)))
        members = db.scalars(select(m.PortfolioAsset)).all()
        assert len(members) == 5 and round(sum(float(x.target_weight) for x in members)) == 100
        assert db.scalar(select(m.AssetType).where(m.AssetType.key == "fund")) is not None
        assert {p.name for p in db.scalars(select(m.Platform))} >= {"مفید", "بیت‌پین", "بورس", "سایر"}
        assert db.scalar(select(m.PriceProvider).where(m.PriceProvider.kind == "manual")).is_enabled
        # ارقام مالی با خروجی نسخهٔ ۱ یکسان است
        exp = json.loads((FIX / "v1_expected.json").read_text())
        now = datetime.fromisoformat(exp["as_of"])
        ds = load_dataset(db)
        got_pf = _jsonable(summary.portfolio(ds, now))
        assert _eq(exp["portfolio"], got_pf)
        assert set(got_pf) == set(exp["portfolio"])
        _subset(exp["dashboard_cards"], _jsonable(summary.dashboard(ds, now))["cards"])
    again = run_migrations(v1_engine)
    assert again["applied"] == [] and again["backup"] is None


def test_migration_allows_same_period_seq_in_other_portfolio(v1_engine):
    from app import models as m
    from app.migrations.runner import run_migrations
    run_migrations(v1_engine)
    with Session(v1_engine) as db:
        pf = db.scalars(select(m.Portfolio)).first()
        second = m.Portfolio(name="سبد دوم", initial_capital=0, monthly_contribution=0, plan_start_date=datetime(2026, 1, 1).date())
        db.add(second)
        db.flush()
        db.add(m.PlanPeriod(portfolio_id=second.id, seq=0, due_date=datetime(2026, 1, 1).date(), planned_amount=0))
        db.commit()  # قبلاً seq سراسری یکتا بود؛ حالا فقط در هر سبد


def test_v1_backup_file_restores_into_v2(client):
    """پشتیبان JSON نسخهٔ ۱ (بدون جدول‌های جدید) بازیابی و به ساختار جدید ارتقا می‌یابد."""
    from app.database import SessionLocal
    from app.services import backup
    d = client.get("/api/platforms").json()
    # یک پشتیبان v2 بگیر، به قالب v1 تبدیل کن (حذف جدول‌ها/ستون‌های جدید)
    plats = {p["name"]: p["id"] for p in d}
    client.post("/api/transactions", json={"tx_date": "2026-10-01", "tx_type": "deposit", "platform_id": plats["مفید"], "amount": "1000000"})
    data = client.get("/api/backup/export").json()
    assert data["schema_version"] == 2
    v1 = {"app": data["app"], "schema_version": 1, "tables": {k: data["tables"][k] for k in
          ("currencies", "app_settings", "platforms", "assets", "plan_periods", "transactions", "prices", "fx_rates")}}
    for r in v1["tables"]["assets"]:
        for k in ("portfolio_id", "is_archived", "name_en", "market", "unit", "decimals", "min_quantity", "initial_price", "extra", "archived_at", "fetch_interval_minutes", "note"):
            r.pop(k, None)
    for r in v1["tables"]["transactions"] + v1["tables"]["plan_periods"]:
        r.pop("portfolio_id", None)
    r = client.post("/api/backup/restore?confirm=true", json=v1)
    assert r.status_code == 200, r.text
    pf = client.get("/api/portfolios").json()
    assert len(pf) == 1 and pf[0]["member_count"] == 5
    tx = client.get("/api/transactions").json()
    assert tx["total"] == 1 and tx["items"][0]["portfolio_id"] == pf[0]["id"]
    assert len(client.get("/api/contributions").json()["periods"]) == 13


def test_v2_backup_roundtrip_with_portfolios_and_providers(client):
    plats = {p["name"]: p["id"] for p in client.get("/api/platforms").json()}
    pf = client.post("/api/portfolios", json={"name": "سبد پشتیبان"}).json()
    client.post("/api/market-data/providers", json={"name": "منبع من", "kind": "custom_api", "base_url": "https://x.example.com/{symbol}",
                                                    "field_map": {"price": "$.p"}, "input_currency": "IRT", "api_key": "K", "auth_type": "bearer"})
    client.post("/api/transactions", json={"tx_date": "2026-10-01", "tx_type": "deposit", "platform_id": plats["مفید"], "amount": "1000000", "portfolio_id": pf["id"]})
    data = client.get("/api/backup/export").json()
    assert "api_key_enc" not in json.dumps(data)
    r = client.post("/api/backup/restore?confirm=true", json=data)
    assert r.status_code == 200 and r.json()["warnings"]
    assert "سبد پشتیبان" in {p["name"] for p in client.get("/api/portfolios").json()}
    prov = next(p for p in client.get("/api/market-data/providers").json() if p["name"] == "منبع من")
    assert prov["has_api_key"] is False  # کلید در پشتیبان نبود
    assert client.get("/api/transactions", params={"portfolio_id": pf["id"]}).json()["total"] == 1


def test_reset_all_restores_defaults(client):
    req = client.post("/api/data/reset/request", json={"scope": "all"})
    assert req.status_code == 200, req.text
    tok = req.json()
    r = client.post("/api/data/reset/confirm", json={"token": tok["token"], "phrase": tok["phrase"], "scope": "all"})
    assert r.status_code == 200, r.text
    assert len(client.get("/api/assets").json()["assets"]) == 5
    assert len(client.get("/api/platforms").json()) == 8
    assert len(client.get("/api/portfolios").json()) == 1
