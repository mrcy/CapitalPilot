# یادداشت‌های انتشار — CapitalPilot 2.4.0 (نسخهٔ Production)

تاریخ انتشار: ۱۳ آبان ۱۴۰۵ (۲۰۲۶-۱۱-۰۴) · نسخه: `2.4.0` · طرح‌واره دیتابیس: ۴

این نسخه همان قابلیت‌های نسخهٔ ۲٫۴ است که برای **نصب روی سرور شخصی و استفادهٔ Production** بسته‌بندی و سخت‌سازی شده است. به قابلیت‌های مالی و ساختار برنامه دست نخورده است.

## قابلیت‌های اصلی (خلاصهٔ ۲٫۰ تا ۲٫۴)

* داشبورد، چند سبد/استراتژی، دارایی‌ها و انواع پویا، پلتفرم‌ها، تراکنش‌ها، تقویم واریزی، پیشنهاد خرید (بدون هیچ سفارش خودکار)، مرکز ریسک و گزارش‌ها (Excel/CSV/PDF)
* موتور داده‌های بازار: TSETMC، Bitpin، StreamData، Servix، Custom API، قیمت دستی؛ زمان‌بند مستقل؛ لایهٔ کنترل کیفیت قیمت (اعتبار، اختلاف منابع، fallback)
* **Iran Market Data** (۲٫۳): هزاران نماد ایران با اتصال تأییدشده به دارایی
* **جست‌وجوی سراسری بازار** (۲٫۴، `Ctrl/⌘+K`): فقط‌خواندنی؛ اتصال/ساخت دارایی/افزودن به سبد فقط با تأیید صریح

## تازه در بستهٔ Production

**نصب و عملیات**
* `install.sh` — نصب یک‌دستوری روی Ubuntu 24.04 (کاربر سیستمی، venv، وابستگی‌های قفل‌شده، `.env`، مجوزها، migration، systemd، تایمر پشتیبان شبانه، بررسی سلامت). idempotent؛ هرگز `.env`/دیتابیس/سرویس ویرایش‌شده را بدون اجازه بازنویسی نمی‌کند
* `update.sh` — به‌روزرسانی با SHA256، پشتیبان دیتابیس/تنظیمات/کد، migration، بررسی سلامت با تطبیق نسخه و **بازگشت خودکار** در صورت خطا؛ `--rollback`
* `backup.sh` / `restore.sh` — پشتیبان کامل (اختیاری با `.env` و رمزنگاری AES-256) و بازیابی با نسخهٔ ایمنی و بازگشت در خطا
* `python -m app.manage` — `version | check | migrate | backup | restore`
* `deploy/` — قالب واحدهای systemd (سخت‌سازی‌شده) و Nginx (Reverse Proxy، Rate limit، بستن Swagger)
* `Dockerfile` و `docker-compose.yml` به‌روز: کاربر غیر root، یک worker، `/data`، پورت فقط روی `127.0.0.1`
* `requirements.lock` — نسخه‌های دقیق آزموده‌شده (wheel برای Python 3.12 روی x86_64 و aarch64 موجود است)

**امنیت** (جزئیات: `docs/SECURITY.md`)
* `APP_ENV=production`: هشدار پیکربندی ناایمن در لاگ و HSTS روی HTTPS
* `ALLOWED_HOSTS` (Trusted Host)، `CORS_ORIGINS` (پیش‌فرض بسته)، `DOCS_ENABLED=false` (Swagger خاموش)، هدر `Permissions-Policy`
* دیتابیس و فایل‌های WAL با مجوز `600`، پوشهٔ پشتیبان `700`، پشتیبان‌ها `600`؛ کلید رمزنگاری `600`
* مسیر ثابت داده/پشتیبان/لاگ: `DATA_DIR`، `BACKUP_DIR`، `LOG_DIR` (و `CAPITALPILOT_ENV_FILE` برای محل `.env`)
* پشتیبان SQLite به‌صورت یک فایل مستقل (بدون `-wal/-shm`)

**مستندات**
* راهنمای نصب Ubuntu 24.04، Nginx و HTTPS، پشتیبان‌گیری و بازیابی، اتصال منابع قیمت، Docker، امنیت
* `docs/API.md` و `docs/openapi.json` (تولید خودکار با `tools/gen_api_docs.py`)

## تغییرات سازگاری

* ✅ **بدون تغییر در طرح‌واره، داده‌ها و محاسبات مالی.** دیتابیس‌های نسخه‌های قبلی با migration خودکار (و پشتیبان پیش از آن) ارتقا می‌یابند.
* متغیرهای محیطی تازه (همه اختیاری): `APP_ENV`، `ALLOWED_HOSTS`، `CORS_ORIGINS`، `CAPITALPILOT_ENV_FILE`. مقدارهای قبلی بدون تغییر کار می‌کنند.
* رفتار پیش‌فرض توسعه عوض نشده است (`./run.sh` مثل قبل). فقط وقتی `APP_ENV=production` یا `ALLOWED_HOSTS`/`CORS_ORIGINS` تنظیم شود رفتار امنیتی سخت‌تر اعمال می‌شود.
* Dockerfile: داده از `./data` به volume با نام `capitalpilot-data` (`/data`) رفته است. اگر قبلاً با Docker و `./data` کار می‌کردید، دیتابیس را با `manage restore` به volume ببرید یا در compose مسیر bind را برگردانید.

## نصب سریع

```bash
sudo apt install -y python3 python3-venv unzip curl nginx certbot python3-certbot-nginx
sha256sum -c SHA256SUMS.txt
sudo unzip CapitalPilot-v2.4.0-production.zip -d /opt && sudo mv /opt/CapitalPilot-v2.4.0 /opt/capitalpilot
cd /opt/capitalpilot && sudo ./install.sh --domain capital.example.com --basic-auth admin --nginx
```
ادامه: `docs/NGINX-HTTPS.md` ← `docs/PRICE-SOURCES.md`.

## محتوای بسته و آنچه عمداً نیست

* هست: backend، frontend (بدون CDN؛ فونت وزیرمتن و Chart.js محلی)، migrations، زمان‌بند، اسکریپت‌ها، Dockerfile/compose، README فارسی، `.env.example`، آزمون‌ها و fixtureهای لازم، مستندات.
* نیست: `.env`، هر کلید/رمز، دیتابیس و پشتیبان، `.venv`، `node_modules`، `.git`، کش‌ها، لاگ‌ها.

## محدودیت‌ها و نکات صادقانه

* محیط ساخت Python 3.11 روی Debian 12 بود؛ **Python 3.12، Ubuntu 24.04، Nginx، certbot و Docker در آن اجرا نشد.** اسکریپت‌ها با کاربر و مسیر واقعی و یک `systemctl` شبیه‌ساز آزموده شدند (نصب، به‌روزرسانی، بازگشت خودکار، پشتیبان رمزنگاری‌شده، بازیابی)، واحدهای systemd با `systemd-analyze verify` سنجیده و واحد سخت‌سازی‌شدهٔ برنامه با systemd 252 (Debian 12) واقعاً اجرا شد (راه‌اندازی، نوشتن دیتابیس، سرویس پشتیبان؛ systemd 255 اوبونتو آزموده نشد) و وجود wheel برای Python 3.12 بررسی شد.
* اتصال زندهٔ TSETMC و Bitpin و سرویس‌های ایرانی آزموده نشد؛ سرور خارج از ایران ممکن است مسدود شود (`docs/PRICE-SOURCES.md`).
* `raw.githubusercontent.com` از محیط ساخت در دسترس نبود؛ پردازش Iran Market Data با نمونهٔ واقعی ذخیره‌شده آزموده شد.
* فقط یک worker پشتیبانی می‌شود (زمان‌بند داخل فرایند است).
* برنامه تک‌کاربره است؛ برای سرور عمومی Basic Auth/VPN و HTTPS الزامی است.
