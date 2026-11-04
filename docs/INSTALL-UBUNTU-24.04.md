# راهنمای نصب CapitalPilot روی Ubuntu 24.04

پشتهٔ هدف: **Ubuntu 24.04 LTS · Python 3.12 · FastAPI + Uvicorn · SQLite (پیش‌فرض) · systemd · Nginx (Reverse Proxy) · Let's Encrypt (HTTPS)**.
برنامه روی `127.0.0.1` گوش می‌دهد و فقط Nginx از بیرون در دسترس است.

> **صادقانه دربارهٔ آزمون‌ها:** محیط ساخت این بسته Python 3.11 روی Debian 12 بود و Ubuntu 24.04، Python 3.12، Nginx، certbot و Docker در آن اجرا نشد (systemd نسخهٔ ۲۵۲ روی Debian 12 در دسترس بود، نه نسخهٔ ۲۵۵ اوبونتو).
> آنچه آزموده شد: ۱۶۶+ آزمون Python، نصب و به‌روزرسانی و بازیابی با `install.sh`/`update.sh`/`restore.sh` روی کاربر و مسیرهای واقعی با یک `systemctl` شبیه‌ساز،
> بازگشت خودکار هنگام خطای migration و خطای راه‌اندازی، `systemd-analyze verify` روی واحدها، اجرای واقعی واحد سخت‌سازی‌شده با systemd 252 (راه‌اندازی، نوشتن در دیتابیس زیر `ProtectSystem=strict`، سرویس پشتیبان) و بررسی اینکه **همهٔ وابستگی‌های قفل‌شده برای Python 3.12 (x86_64 و aarch64) wheel آماده دارند**.
> اگر در اولین نصب خطایی دیدید، خروجی `journalctl -u capitalpilot -n 50` را بررسی کنید.

## ۰) پیش‌نیازها

* یک سرور Ubuntu 24.04 با دسترسی `sudo`، حداقل ۵۱۲ مگابایت RAM و ۱ گیگابایت دیسک آزاد
* دامنه‌ای که رکورد `A`/`AAAA` آن به IP سرور اشاره می‌کند (برای HTTPS)
* پورت‌های ۸۰ و ۴۴۳ باز در فایروال: `sudo ufw allow OpenSSH && sudo ufw allow "Nginx Full" && sudo ufw enable`

## ۱) انتقال و بررسی بسته

از کامپیوتر خودتان (نه از اینترنت عمومی بدون بررسی):

```bash
scp CapitalPilot-v2.4.0-production.zip SHA256SUMS.txt user@SERVER:/tmp/
ssh user@SERVER
cd /tmp && sha256sum -c SHA256SUMS.txt        # باید بنویسد: CapitalPilot-v2.4.0-production.zip: OK
```

## ۲) بسته‌های سیستمی

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip unzip curl nginx certbot python3-certbot-nginx
python3 --version     # Python 3.12.x
```

## ۳) استخراج در `/opt/capitalpilot`

```bash
sudo unzip /tmp/CapitalPilot-v2.4.0-production.zip -d /opt
sudo mv /opt/CapitalPilot-v2.4.0 /opt/capitalpilot
cd /opt/capitalpilot
```

> مسیر را زیر `/home` قرار ندهید؛ سرویس با `ProtectHome=true` اجرا می‌شود.

## ۴) نصب

```bash
sudo ./install.sh --domain capital.example.com --basic-auth admin --nginx
```

| گزینه | معنی |
|---|---|
| `--domain` | دامنه؛ در `ALLOWED_HOSTS` و نمونهٔ Nginx نوشته می‌شود (توصیه می‌شود حتماً بدهید) |
| `--basic-auth USER` | رمز تصادفی می‌سازد و در `.env` می‌گذارد؛ رمز **فقط یک‌بار** روی صفحه چاپ می‌شود. اگر Basic Auth روی Nginx یا VPN دارید لازم نیست |
| `--nginx` | نمونهٔ تنظیم را در `/etc/nginx/sites-available/capitalpilot` می‌نویسد (فعال نمی‌کند، بازنویسی نمی‌کند) |
| `--port N` | پورت داخلی (پیش‌فرض ۸۰۰۰) |
| `--data-dir`, `--backup-dir`, `--log-dir` | مسیر داده/پشتیبان/لاگ (پیش‌فرض `/var/lib/capitalpilot`, `…/backups`, `/var/log/capitalpilot`) |
| `--user` | کاربر سیستمیِ سرویس (پیش‌فرض `capitalpilot`) |
| `--no-systemd`, `--no-start`, `--no-backup-timer` | به‌ترتیب: بدون سرویس، بدون راه‌اندازی، بدون تایمر پشتیبان |
| `--yes` | بدون پرسش؛ پاسخ پیش‌فرض همیشه «بازنویسی نکن» است |

اسکریپت به ترتیب: پیش‌نیازها (Python ≥ ۳٫۱۱، venv، curl، دیسک، پورت) ← کاربر سیستمیِ بدون shell ← پوشه‌های داده/پشتیبان/لاگ با مجوز `700` ← venv و وابستگی‌ها ←
`.env` (فقط اگر وجود ندارد؛ مجوز `600`) ← `python -m app.manage check` ← migration دیتابیس ← واحد systemd و تایمر پشتیبان شبانه ← راه‌اندازی و `GET /api/health`.
**اجرای دوباره امن است:** `.env`، دیتابیس و واحد ویرایش‌شدهٔ شما بازنویسی نمی‌شود (در صورت تفاوت، نسخهٔ پیشنهادی کنار آن با پسوند `.new` گذاشته می‌شود).

## ۵) بررسی

```bash
systemctl status capitalpilot
curl -s -u admin:'PASSWORD' http://127.0.0.1:8000/api/health     # {"status":"ok","version":"2.4.0"}
sudo journalctl -u capitalpilot -f
sudo -u capitalpilot env CAPITALPILOT_ENV_FILE=/opt/capitalpilot/.env /opt/capitalpilot/.venv/bin/python -m app.manage check
```

## ۶) Nginx و HTTPS

ادامه در [NGINX-HTTPS.md](NGINX-HTTPS.md).

## مسیرهای پس از نصب

| چه | کجا | مجوز |
|---|---|---|
| کد برنامه و venv | `/opt/capitalpilot` | مالک root، سرویس فقط می‌خواند |
| تنظیمات و رازها | `/opt/capitalpilot/.env` | `600`، مالک `capitalpilot` |
| دیتابیس SQLite | `/var/lib/capitalpilot/capitalpilot.db` | `600` |
| کلید رمزنگاری (اگر `SECRET_KEY` خالی باشد) | `/var/lib/capitalpilot/.secret_key` | `600` |
| پشتیبان‌ها (غیرعمومی) | `/var/lib/capitalpilot/backups` | `700` |
| لاگ برنامه | `/var/log/capitalpilot` | `700` |
| واحدهای systemd | `/etc/systemd/system/capitalpilot*.{service,timer}` | — |
| نشانی‌های نصب (برای update/backup/restore) | `/opt/capitalpilot/.install.conf` | حذف نکنید |

## تنظیمات مهم `.env`

همهٔ کلیدها در `.env.example` توضیح دارند. مهم‌ترین‌ها برای production:

```ini
APP_ENV=production
DOCS_ENABLED=false                 # Swagger خاموش
ALLOWED_HOSTS=capital.example.com  # Trusted Hosts (localhost همیشه مجاز است)
CORS_ORIGINS=                      # خالی = CORS خاموش (امن‌ترین)
SECRET_KEY=<تصادفی بلند>           # کلید رمزنگاری کلیدهای API منابع قیمت — گم نکنید
BASIC_AUTH_USER=... / BASIC_AUTH_PASSWORD=...
SCHEDULER_ENABLED=true
```

بعد از تغییر `.env`: `sudo systemctl restart capitalpilot`.

> **فقط یک worker:** زمان‌بند دریافت قیمت داخل همان فرایند اجرا می‌شود؛ چند worker یعنی دریافت تکراری. واحد systemd عمداً `--workers 1` دارد.

## به‌روزرسانی

```bash
cd /opt/capitalpilot
sudo ./update.sh /tmp/CapitalPilot-v2.5.0-production.zip --sha256 /tmp/SHA256SUMS.txt
sudo ./update.sh --rollback              # بازگشت دستی به نسخهٔ قبلی (کد)
sudo ./update.sh --rollback --with-db    # همراه با دیتابیسِ پیش از به‌روزرسانی (داده‌های بعد از آن از بین می‌رود!)
```

`update.sh`: SHA256 ← پشتیبان دیتابیس (Online Backup) + `.env` + کد فعلی ← توقف ← جایگزینی کد (`.env`، `.venv`، داده و `.install.conf` دست‌نخورده) ← وابستگی‌ها ← `check` و migration ← راه‌اندازی ←
بررسی سلامت با تطبیق نسخه. اگر هر مرحلهٔ پس از جایگزینی شکست بخورد: کد و دیتابیس قبلی و وابستگی‌هایش برگردانده می‌شود و سرویس قبلی دوباره بالا می‌آید. پشتیبان‌ها در `…/backups/releases` می‌مانند (۵ نسخهٔ آخر).

## حذف

```bash
sudo systemctl disable --now capitalpilot capitalpilot-backup.timer
sudo rm /etc/systemd/system/capitalpilot*.service /etc/systemd/system/capitalpilot-backup.timer && sudo systemctl daemon-reload
# داده را فقط وقتی پاک کنید که پشتیبان بیرونی دارید:
# sudo rm -rf /opt/capitalpilot /var/lib/capitalpilot /var/log/capitalpilot && sudo userdel capitalpilot
```

## عیب‌یابی

| نشانه | بررسی |
|---|---|
| `install.sh`: «Python 3.11+ پیدا نشد» | `sudo apt install -y python3 python3-venv` |
| سرویس بالا نمی‌آید | `journalctl -u capitalpilot -n 50`؛ معمولاً مسیر داده قابل‌نوشتن نیست یا پورت اشغال است |
| ۴۰۰ برای همهٔ درخواست‌ها | دامنه در `ALLOWED_HOSTS` نیست (Host header) |
| ۴۰۱ | Basic Auth فعال است؛ از `-u` یا مرورگر استفاده کنید |
| `/api/docs` ← ۴۰۴ | عمدی است (`DOCS_ENABLED=false`) |
| منبع قیمت خطا می‌دهد | [PRICE-SOURCES.md](PRICE-SOURCES.md) |
