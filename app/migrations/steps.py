"""گام‌های مهاجرت. هر گام idempotent است."""
from __future__ import annotations

import json
import logging

from sqlalchemy import inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from .. import models as m

log = logging.getLogger("capitalpilot.migrations")


def m001_baseline(engine: Engine) -> None:
    """ساختار نسخهٔ ۱ (پایه). کاری لازم نیست."""


def _price_dedupe_index(engine: Engine) -> None:
    with engine.begin() as c:
        c.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_price_fetch_dedupe "
                       "ON prices (asset_id, provider_id, source_time, price_kind)"))


def _rebuild_plan_periods(engine: Engine) -> None:
    """حذف یکتایی سراسری seq (به‌جای آن یکتایی در هر سبد). در SQLite نیازمند بازسازی جدول است."""
    insp = inspect(engine)
    uniques = [tuple(u["column_names"]) for u in insp.get_unique_constraints("plan_periods")]
    idx_unique = [tuple(i["column_names"]) for i in insp.get_indexes("plan_periods") if i.get("unique")]
    if ("seq",) not in uniques and ("seq",) not in idx_unique:
        return
    if engine.dialect.name != "sqlite":
        # PostgreSQL: نام قید خودکار plan_periods_seq_key است
        with engine.begin() as c:
            c.execute(text("ALTER TABLE plan_periods DROP CONSTRAINT IF EXISTS plan_periods_seq_key"))
            c.execute(text("ALTER TABLE plan_periods ADD CONSTRAINT uq_plan_portfolio_seq UNIQUE (portfolio_id, seq)"))
        return
    table = m.PlanPeriod.__table__
    ddl = str(CreateTable(table).compile(dialect=engine.dialect)).replace("CREATE TABLE plan_periods", "CREATE TABLE plan_periods_new", 1)
    cols = ", ".join(f'"{c.name}"' for c in table.columns)
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute("PRAGMA foreign_keys=OFF")
        raw.commit()
        cur.execute("BEGIN")
        cur.execute("DROP TABLE IF EXISTS plan_periods_new")
        cur.execute(ddl)
        cur.execute(f"INSERT INTO plan_periods_new ({cols}) SELECT {cols} FROM plan_periods")
        cur.execute("DROP TABLE plan_periods")
        cur.execute("ALTER TABLE plan_periods_new RENAME TO plan_periods")
        for idx in table.indexes:
            cols_idx = ", ".join(f'"{c.name}"' for c in idx.columns)
            cur.execute(f'CREATE INDEX IF NOT EXISTS "{idx.name}" ON plan_periods ({cols_idx})')
        cur.execute("PRAGMA foreign_key_check")
        bad = cur.fetchall()
        if bad:
            raise RuntimeError(f"foreign key check failed after rebuilding plan_periods: {bad[:3]}")
        raw.commit()
        cur.execute("PRAGMA foreign_keys=ON")
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def _legacy_price_providers(db: Session) -> None:
    """دارایی‌هایی که در نسخهٔ ۱ «JSON عمومی» داشتند، به یک منبع Custom API (غیرفعال) تبدیل می‌شوند."""
    for a in db.scalars(select(m.Asset).where(m.Asset.price_provider != "")):
        try:
            params = json.loads(a.price_provider_params or "{}")
        except ValueError:
            params = {}
        url, path = params.get("url", ""), params.get("json_path", "")
        if not url or not path:
            continue
        name = f"Custom API — {a.name} (مهاجرت‌شده)"
        if db.scalar(select(m.PriceProvider).where(m.PriceProvider.name == name)):
            continue
        pv = m.PriceProvider(name=name, kind="custom_api", is_enabled=False, base_url=url,
                             field_map=json.dumps({"price": path}), input_currency=params.get("currency", ""),
                             config=json.dumps({"multiplier": str(params.get("multiplier", "1"))}))
        db.add(pv)
        db.flush()
        db.add(m.AssetPriceSource(asset_id=a.id, provider_id=pv.id, priority=1))


def backfill_v2(db: Session) -> None:
    """داده‌های نسخهٔ ۲ (idempotent): انواع دارایی، پلتفرم‌ها، منابع، سبد پیش‌فرض و ارتباط تراکنش‌ها با سبد."""
    from ..services.marketdata.service import ensure_default_providers
    from ..services.seed import ensure_asset_types, ensure_default_portfolio, ensure_platforms

    if db.get(m.AppSettings, 1) is None:
        return
    ensure_asset_types(db)
    ensure_platforms(db)
    ensure_default_providers(db)
    for a in db.scalars(select(m.Asset)):
        if a.fractional_units and not a.decimals:
            a.decimals = 6
    pf = ensure_default_portfolio(db)
    # عضویت دارایی‌هایی که هنوز عضو سبد پیش‌فرض نیستند
    members = {pa.asset_id for pa in db.scalars(select(m.PortfolioAsset).where(m.PortfolioAsset.portfolio_id == pf.id))}
    for a in db.scalars(select(m.Asset)):
        if a.id not in members:
            db.add(m.PortfolioAsset(portfolio_id=pf.id, asset_id=a.id, target_weight=a.target_weight, is_active=a.is_active))
    for t in db.scalars(select(m.Transaction).where(m.Transaction.portfolio_id.is_(None))):
        t.portfolio_id = pf.id
    for p in db.scalars(select(m.PlanPeriod).where(m.PlanPeriod.portfolio_id.is_(None))):
        p.portfolio_id = pf.id
    _legacy_price_providers(db)
    db.flush()


def m002_dynamic_management(engine: Engine) -> None:
    with Session(engine) as db:
        backfill_v2(db)
        db.commit()
    _rebuild_plan_periods(engine)
    _price_dedupe_index(engine)
