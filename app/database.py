"""اتصال دیتابیس و نوع ستون Decimal دقیق.

SQLite نوع Decimal واقعی ندارد و Numeric را به float تبدیل می‌کند (خطای دقت).
بنابراین در SQLite مقدار به‌صورت متن ذخیره می‌شود و در PostgreSQL از NUMERIC(38, 12)
استفاده می‌شود؛ مهاجرت بین دو دیتابیس بدون تغییر کد ممکن است.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Iterator

from sqlalchemy import Numeric, String, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from .config import get_settings


class DecimalType(TypeDecorator):
    impl = String(64)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(String(64))
        return dialect.type_descriptor(Numeric(38, 12, asdecimal=True))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, Decimal):
            value = Decimal(str(value))
        if dialect.name == "sqlite":
            return format(value, "f")
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value if isinstance(value, Decimal) else Decimal(str(value))


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None) -> Engine:
    settings = get_settings()
    url = url or settings.database_url
    kwargs: dict = {"future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        path = settings.sqlite_path if url == settings.database_url else None
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    return engine


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
