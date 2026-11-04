"""تنظیمات برنامه (از فایل .env یا متغیرهای محیطی)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "CapitalPilot"
    app_tagline: str = "کنترل سرمایه، تصمیم هوشمندانه"
    # SQLite برای نسخه اولیه؛ برای PostgreSQL: postgresql+psycopg://user:pass@host/db
    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'capitalpilot.db'}"
    app_timezone: str = "Asia/Tehran"
    data_dir: Path = BASE_DIR / "data"
    backup_dir: Path = BASE_DIR / "data" / "backups"
    log_dir: Path = BASE_DIR / "data" / "logs"
    log_level: str = "INFO"
    docs_enabled: bool = True
    seed_on_startup: bool = True

    # دسترسی (اختیاری): اگر هر دو مقدار تنظیم شوند، Basic Auth فعال می‌شود.
    basic_auth_user: str = ""
    basic_auth_password: str = ""

    # دریافت خودکار قیمت (اختیاری، پیش‌فرض غیرفعال).
    # کلید API فقط در سمت سرور نگهداری می‌شود و هرگز به مرورگر ارسال نمی‌شود.
    price_api_allowed_hosts: str = ""  # لیست میزبان‌های مجاز، جداشده با ویرگول
    price_api_key: str = Field(default="", repr=False)
    price_api_key_header: str = "Authorization"
    price_api_timeout_seconds: float = 8.0

    @property
    def allowed_price_hosts(self) -> set[str]:
        return {h.strip().lower() for h in self.price_api_allowed_hosts.split(",") if h.strip()}

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def sqlite_path(self) -> Path | None:
        if not self.is_sqlite:
            return None
        raw = self.database_url.split("///", 1)[-1]
        return Path(raw) if raw and raw != ":memory:" else None


@lru_cache
def get_settings() -> Settings:
    return Settings()
