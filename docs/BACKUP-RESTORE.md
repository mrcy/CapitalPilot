# پشتیبان‌گیری و بازیابی CapitalPilot

> **اصل مهم:** دیتابیس و پشتیبان‌ها شامل اطلاعات مالی شما هستند. هرگز در ZIP برنامه، Git یا پوشهٔ عمومی وب قرار نگیرند. پوشهٔ پشتیبان `700` است و هیچ مسیر وبی به آن اشاره نمی‌کند.

## چه چیزهایی باید پشتیبان گرفته شود؟

| مورد | مسیر پیش‌فرض | توضیح |
|---|---|---|
| دیتابیس (دارایی‌ها، تراکنش‌ها، قیمت‌ها، منابع) | `/var/lib/capitalpilot/capitalpilot.db` | **ضروری.** با SQLite Online Backup بدون توقف سرویس گرفته می‌شود |
| `.env` | `/opt/capitalpilot/.env` | تنظیمات و رازها (Basic Auth، `SECRET_KEY`) |
| کلید رمزنگاری | `SECRET_KEY` در `.env` یا `/var/lib/capitalpilot/.secret_key` | **بدون آن کلیدهای API ذخیره‌شدهٔ منابع قیمت قابل‌بازیابی نیستند** (باید دوباره وارد شوند؛ دادهٔ مالی از دست نمی‌رود) |

کلیدهای API در پشتیبان JSON برنامه (تنظیمات ← پشتیبان) **نیستند**؛ دیتابیس آن‌ها را به‌صورت رمزشده دارد.

## پشتیبان خودکار

* `capitalpilot-backup.timer` هر شب ≈۰۳:۳۰ (با تأخیر تصادفی تا ۱۵ دقیقه) یک نسخه با برچسب `daily` می‌سازد و ۱۴ نسخهٔ آخر را نگه می‌دارد: `systemctl list-timers capitalpilot-backup.timer`
* پیش از هر migration و هر `update.sh`، پشتیبان خودکار گرفته می‌شود. پیش از بازیابی/پاک‌سازی از داخل برنامه هم همین‌طور.
* پشتیبان‌های روی همان سرور محافظ خرابی دیسک نیستند؛ **حتماً نسخه‌ای بیرون از سرور نگه دارید** (پایین).

## پشتیبان دستی

```bash
# فقط دیتابیس (سریع، سازگار با WAL، مجوز 600)
sudo -u capitalpilot env CAPITALPILOT_ENV_FILE=/opt/capitalpilot/.env /opt/capitalpilot/.venv/bin/python -m app.manage backup --label manual

# بستهٔ قابل‌انتقال: دیتابیس + manifest + sha256
sudo /opt/capitalpilot/backup.sh --out /root/cp-backups

# با .env و کلید رمزنگاری، و رمزنگاری AES-256 (توصیه‌شده برای هر خروجی که از سرور بیرون می‌رود)
sudo BACKUP_PASSPHRASE='یک-عبارت-طولانی' /opt/capitalpilot/backup.sh --out /root/cp-backups --with-secrets --encrypt
# اگر BACKUP_PASSPHRASE ندهید، رمز تعاملی پرسیده می‌شود (روی صفحه دیده نمی‌شود)
```

خروجی: `capitalpilot-backup-<نسخه>-<تاریخ>.tar.gz[.enc]` و فایل `.sha256` کنارش (مجوز 600). رمز را در جایی جدا از فایل نگه دارید؛ **رمز گم‌شده قابل‌بازیابی نیست.**

## انتقال امن به بیرون از سرور

```bash
scp -p user@SERVER:/root/cp-backups/capitalpilot-backup-2.4.0-*.tar.gz.enc ./
sha256sum -c capitalpilot-backup-2.4.0-*.tar.gz.enc.sha256      # در همان پوشه
```
یا با `rsync -e ssh`/`restic`/`borg` به یک دیسک یا سرور دیگر. از ایمیل، پیام‌رسان یا سرویس‌های عمومی برای فایل بدون رمزنگاری استفاده نکنید.

## بازیابی

```bash
cd /opt/capitalpilot
sudo ./restore.sh /root/cp-backups/capitalpilot-backup-2.4.0-20261104-030000.tar.gz.enc            # فقط دیتابیس
sudo ./restore.sh FILE --restore-secrets                                                      # همراه .env و کلید رمزنگاری (سرور جدید)
sudo ./restore.sh /var/lib/capitalpilot/backups/capitalpilot-daily-20261104-033012.db         # یک فایل .db خام
```

مراحل (همه خودکار): بررسی SHA256 و رمزگشایی ← `PRAGMA integrity_check` روی فایل ← پرسش تأیید (یا `--yes`) ← توقف سرویس ← **نسخهٔ ایمنی از دیتابیس فعلی** (`capitalpilot-before-restore-*.db`) ←
(اختیاری) بازگرداندن `.env`/کلید با نگه‌داشتن نسخهٔ قبلی با پسوند `.pre-restore-<زمان>` ← جایگزینی دیتابیس ← migration (اگر پشتیبان از نسخهٔ قدیمی‌تر باشد، طرح‌واره به‌روز می‌شود) ← راه‌اندازی و بررسی سلامت.
اگر هر مرحله خطا بدهد، دیتابیس قبلی برگردانده می‌شود.

### انتقال به سرور جدید

1. روی سرور جدید طبق [INSTALL-UBUNTU-24.04.md](INSTALL-UBUNTU-24.04.md) نصب کنید (همان نسخه یا جدیدتر).
2. فایل پشتیبان (ساخته‌شده با `--with-secrets --encrypt`) را منتقل و با `restore.sh FILE --restore-secrets --yes` بازیابی کنید.
3. در `.env` مقدار `ALLOWED_HOSTS` را برای دامنهٔ جدید تنظیم و سرویس را restart کنید؛ HTTPS را با certbot بگیرید.

### بازیابی از داخل برنامه (JSON)

«تنظیمات ← پشتیبان» فایل JSON می‌دهد (بدون کلیدهای API). بازیابی آن نیازمند تأیید است و پیش از آن خودکار پشتیبان فایل دیتابیس گرفته می‌شود. برای انتقال کامل (شامل منابع و تنظیمات رمزشده) از `backup.sh` استفاده کنید.

## آزمودن پشتیبان (ماهی یک‌بار)

```bash
sudo python3 - <<'PY'
import sqlite3,glob,os
f=sorted(glob.glob('/var/lib/capitalpilot/backups/capitalpilot-daily-*.db'))[-1]
c=sqlite3.connect(f'file:{f}?mode=ro',uri=True)
print(f, c.execute('pragma integrity_check').fetchone(), c.execute('select count(*) from transactions').fetchone())
PY
```

## نگهداری

* نسخه‌های `before-restore` و `pre-update` و `daily` خودکار هرس می‌شوند (۱۰/۱۰/۱۴ نسخهٔ آخر)؛ نسخه‌های `manual` و `export` را خودتان پاک کنید.
* فضای مصرفی را ببینید: `sudo du -sh /var/lib/capitalpilot/backups`.
