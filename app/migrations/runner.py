from __future__ import annotations

import logging
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from decimal import Decimal

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from .. import models as m
from ..config import get_settings
from ..database import Base
from . import steps

log = logging.getLogger("capitalpilot.migrations")

# (نسخه، نام، تابع) — مهاجرت‌های جدید را فقط به انتهای فهرست اضافه کنید.
MIGRATIONS = [
    (1, "baseline-v1", steps.m001_baseline),
    (2, "dynamic-management-portfolios-market-data", steps.m002_dynamic_management),
    (3, "price-quality-engine", steps.m003_price_quality),
]
LATEST_VERSION = MIGRATIONS[-1][0]


def _literal(col) -> str | None:
    """مقدار پیش‌فرض ثابت ستون برای ALTER TABLE (NOT NULL نیازمند DEFAULT است)."""
    d = col.default
    if d is None or not getattr(d, "is_scalar", False):
        return None
    v = d.arg
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, Decimal):
        return f"'{format(v, 'f')}'"
    return "'" + str(v).replace("'", "''") + "'"


def sync_columns(engine: Engine) -> list[str]:
    """افزودن ستون‌های جدید مدل‌ها به جدول‌های موجود (فقط افزایشی، بدون حذف)."""
    added: list[str] = []
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl_type = col.type.compile(dialect=engine.dialect)
                sql = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl_type}'
                lit = _literal(col)
                if lit is not None:
                    sql += f" DEFAULT {lit}"
                if not col.nullable and lit is not None:
                    sql += " NOT NULL"
                conn.execute(text(sql))
                added.append(f"{table.name}.{col.name}")
    if added:
        log.info("columns added: %s", ", ".join(added))
    return added


def _backup_sqlite(engine: Engine, label: str) -> str | None:
    s = get_settings()
    db_name = engine.url.database
    path = Path(db_name) if db_name and db_name != ":memory:" else None
    if engine.dialect.name != "sqlite" or not path or not path.exists():
        return None
    s.backup_dir.mkdir(parents=True, exist_ok=True)
    dest = s.backup_dir / f"capitalpilot-{label}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    src = sqlite3.connect(str(path))
    dst = sqlite3.connect(str(dest))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return dest.name


def run_migrations(engine: Engine) -> dict:
    """ساخت جدول‌های جدید، همگام‌سازی ستون‌ها و اجرای مهاجرت‌های اعمال‌نشده.

    دیتابیس تازه (بدون جدول) مستقیم با ساختار آخر ساخته و همهٔ نسخه‌ها ثبت می‌شود؛ داده‌های اولیه را seed می‌سازد.
    """
    insp = inspect(engine)
    had_data_tables = "assets" in set(insp.get_table_names())
    fresh = not had_data_tables
    info = {"fresh": fresh, "applied": [], "backup": None, "columns_added": []}
    if fresh:
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            for v, name, _ in MIGRATIONS:
                db.add(m.SchemaMigration(version=v, name=name))
            db.commit()
        info["applied"] = [v for v, _, _ in MIGRATIONS]
        return info

    # جدول schema_migrations ممکن است هنوز نباشد (دیتابیس نسخهٔ ۱)
    Base.metadata.create_all(engine)  # فقط جدول‌های جدید را می‌سازد
    with Session(engine) as db:
        done = {r.version for r in db.query(m.SchemaMigration)}
    pending = [(v, n, f) for v, n, f in MIGRATIONS if v not in done]
    if not pending:
        info["columns_added"] = sync_columns(engine)
        return info
    info["backup"] = _backup_sqlite(engine, f"pre-migration-v{pending[0][0]}")
    log.info("applying migrations %s (backup: %s)", [v for v, _, _ in pending], info["backup"])
    info["columns_added"] = sync_columns(engine)
    for v, name, fn in pending:
        try:
            fn(engine)
        except Exception:
            log.exception("migration %s failed; database backup: %s", name, info["backup"])
            raise
        with Session(engine) as db:
            db.add(m.SchemaMigration(version=v, name=name))
            db.commit()
        info["applied"].append(v)
    return info
