# اجرای CapitalPilot با Docker

روش پیشنهادی برای Ubuntu 24.04 اسکریپت `install.sh` + systemd است ([راهنما](INSTALL-UBUNTU-24.04.md)). Docker جایگزین مستند و پشتیبانی‌شده است.

> **صادقانه:** `Dockerfile` و `docker-compose.yml` در محیط ساخت (بدون Docker) **اجرا نشدند**. پیکربندی با همان تنظیمات محیطی که روی سرور آزموده شده نوشته شده و
> `docker-compose.yml` با parser معتبر است، ولی `docker build` را اولین‌بار روی سرور خودتان می‌بینید.

## اجرا

```bash
sudo apt install -y docker.io docker-compose-v2        # Ubuntu 24.04
cd /opt/capitalpilot                                   # پوشهٔ استخراج‌شدهٔ ZIP
cp .env.example .env && chmod 600 .env
nano .env     # حداقل: ALLOWED_HOSTS=دامنه ، BASIC_AUTH_USER/PASSWORD ، SECRET_KEY=<تصادفی بلند>
docker compose up -d --build
docker compose ps && curl -s -u USER:PASS http://127.0.0.1:8000/api/health
```

* پورت فقط روی `127.0.0.1` میزبان منتشر می‌شود؛ Nginx روی میزبان جلوی آن قرار می‌گیرد ([NGINX-HTTPS.md](NGINX-HTTPS.md)؛ `@PORT@`=۸۰۰۰).
* داده در volume به نام `capitalpilot-data` (داخل کانتینر `/data`) است: دیتابیس، `backups/`، `logs/` و `.secret_key`. کانتینر با کاربر غیر root اجرا می‌شود.
* در `.env` برای Docker **مسیرهای `DATA_DIR`/`BACKUP_DIR`/`LOG_DIR`/`DATABASE_URL` را تنظیم نکنید** (داخل تصویر ثابت‌اند). اگر `SECRET_KEY` خالی باشد کلید در volume ساخته می‌شود؛ ولی باید آن را هم پشتیبان بگیرید.
* migration هنگام راه‌اندازی خودکار اجرا می‌شود (با پشتیبان پیش از migration).
* `--forwarded-allow-ips=*` فقط چون پورت روی میزبان به `127.0.0.1` بسته است امن است؛ پورت را روی `0.0.0.0` منتشر نکنید.

## پشتیبان و بازیابی

```bash
docker compose exec capitalpilot python -m app.manage backup --label manual     # فایل در /data/backups
docker compose cp capitalpilot:/data/backups/. ./cp-backups/                     # کپی به میزبان (سپس رمزنگاری و انتقال امن)
docker compose stop capitalpilot
docker compose run --rm -v "$PWD/cp-backups:/restore:ro" capitalpilot python -m app.manage restore /restore/capitalpilot-manual-XXXX.db --yes
docker compose up -d
```

## به‌روزرسانی

```bash
# ZIP جدید را در پوشهٔ جدید استخراج کنید، .env را کپی کنید، سپس:
docker compose up -d --build        # volume داده دست‌نخورده می‌ماند؛ پیش از migration پشتیبان خودکار گرفته می‌شود
docker compose logs -f capitalpilot
```
بازگشت: تصویر قبلی را با برچسب نگه دارید (`docker tag capitalpilot:2.4.0 capitalpilot:2.4.0-prev`) و دیتابیس را با روش بالا از پشتیبان بازگردانید.
`update.sh`/`install.sh` مخصوص نصب systemd هستند و با Docker استفاده نمی‌شوند.
