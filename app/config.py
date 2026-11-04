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
    price_allow_private_hosts: bool = False  # فقط برای منبع قیمت داخل شبکهٔ خودتان (پیش‌فرض: مسدود)

    # رمزنگاری کلیدهای API ذخیره‌شده در دیتابیس؛ اگر خالی باشد کلید تصادفی در data/.secret_key ساخته می‌شود.
    secret_key: str = Field(default="", repr=False)

    # --- Market Data Engine ---
    scheduler_enabled: bool = True  # کلید کلی؛ تنظیم دقیق‌تر در صفحهٔ «منابع قیمت»
    scheduler_tick_seconds: int = 30
    # آدرس‌های پایه (مستندات و آدرس‌ها در README ذکر شده‌اند؛ در پنل قابل تغییرند)
    tsetmc_base_url: str = "http://old.tsetmc.com/tsev2/data"
    tsetmc_service_url: str = "http://service.tsetmc.com/tsev2/data"
    bitpin_base_url: str = "https://api.bitpin.ir"
    # Iran Market Data (نسخهٔ ۲٫۳): فایل JSON عمومی و بدون کلید؛ هر ۳۰ دقیقه منتشر می‌شود. جایگزین (آینه): jsDelivr
    iranmarket_url: str = "https://raw.githubusercontent.com/iran-market/iran-market.github.io/main/data/latest-toman.json"
    iranmarket_max_bytes: int = 20_000_000  # سقف حجم فایل (فایل فعلی حدود ۱ مگابایت است)
    iranmarket_raw_keep: int = 5  # تعداد پاسخ‌های خام فشرده‌ای که برای عیب‌یابی نگه داشته می‌شود
    iranmarket_stale_after_minutes: int = 0  # 0 = خودکار: max(۹۰، سه برابر بازهٔ دریافت)؛ پس از آن کل دادهٔ دریافت‌شده «قدیمی» است
    iranmarket_history_ttl_minutes: int = 360  # کش تاریخچهٔ روزانهٔ نماد (فایل‌های history روزی یک‌بار ساخته می‌شوند)
    # StreamData / Servix: مستندات عمومی تأییدشده‌ای وجود ندارد؛ آدرس و کلید را خودتان از سرویس‌دهنده بگیرید.
    streamdata_base_url: str = ""
    streamdata_api_key: str = Field(default="", repr=False)
    servix_base_url: str = ""
    servix_api_key: str = Field(default="", repr=False)
    # ساعات بازار بورس تهران (شنبه تا چهارشنبه)، به وقت APP_TIMEZONE
    # --- موتور کنترل کیفیت قیمت (نسخهٔ ۲٫۱) ---
    quality_conflict_pct: float = 10.0  # اختلاف بیش از این درصد بین دو منبع تازه = «اختلاف غیرعادی»؛ قیمت تا تصمیم کاربر وارد ارزش‌گذاری نمی‌شود
    quality_jump_pct: float = 20.0  # تغییر بیش از این درصد نسبت به قیمت قبلی همان منبع = هشدار «تغییر شدید»
    quality_max_lag_minutes: int = 180  # فاصلهٔ زمان منبع با زمان دریافت (فقط بازارهای ۲۴ساعته/در ساعات باز بورس)
    quality_provider_down_failures: int = 3  # تعداد خطای پیاپی برای «قطع ارتباط»
    quality_compare_window_hours: int = 24  # پنجرهٔ مقایسهٔ قیمت منابع

    tse_open_time: str = "08:45"
    tse_close_time: str = "12:45"

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
