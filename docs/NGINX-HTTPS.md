# Nginx و HTTPS (Let's Encrypt) برای CapitalPilot

برنامه فقط روی `127.0.0.1:8000` گوش می‌دهد. Nginx درخواست‌ها را از بیرون می‌گیرد، HTTPS را تمام می‌کند و به برنامه می‌فرستد.

## ۱) پیکربندی Nginx

اگر `install.sh --nginx --domain …` را اجرا کرده باشید، فایل آماده است. در غیر این صورت:

```bash
cd /opt/capitalpilot
sed -e 's/@DOMAIN@/capital.example.com/g' -e 's/@PORT@/8000/g' deploy/nginx-capitalpilot.conf.tmpl | sudo tee /etc/nginx/sites-available/capitalpilot >/dev/null
```

فعال‌سازی:

```bash
sudo ln -s /etc/nginx/sites-available/capitalpilot /etc/nginx/sites-enabled/capitalpilot
sudo rm -f /etc/nginx/sites-enabled/default        # سایت پیش‌فرض (اختیاری)
sudo nginx -t && sudo systemctl reload nginx
curl -I http://capital.example.com/api/health      # ۲۰۰ یا ۴۰۱ (اگر Basic Auth دارید)
```

آنچه در نمونه هست: `proxy_pass` به upstream محلی، `server_tokens off`، محدودیت نرخ درخواست `/api/` (۲۰ درخواست در ثانیه، burst ۶۰)،
`client_max_body_size 50m` (بازیابی پشتیبان JSON)، timeout ۱۲۰ ثانیه برای دریافت دستی قیمت/گزارش، کش ۷ روزه برای `/static/vendor/`،
**بستن Swagger** (`/api/docs|redoc|openapi.json` فقط از `allow`‌های لیست)، و ممنوعیت فایل‌های مخفی.

## ۲) گواهی HTTPS با Let's Encrypt

پیش‌شرط: رکورد DNS دامنه به سرور اشاره کند و پورت‌های ۸۰/۴۴۳ باز باشند.

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d capital.example.com --redirect -m you@example.com --agree-tos
sudo certbot renew --dry-run                      # تمدید خودکار با systemd timer نصب‌شده توسط certbot
systemctl list-timers | grep certbot
```

certbot بخش `listen 443 ssl` و ریدایرکت HTTP→HTTPS را خودش به فایل اضافه می‌کند.

## ۳) HSTS و هدرها

* برنامه در `APP_ENV=production` روی اتصال HTTPS خودش `Strict-Transport-Security: max-age=31536000` می‌فرستد (Nginx مقدار `X-Forwarded-Proto` را از `proxy_params` پاس می‌دهد و Uvicorn با `--proxy-headers` آن را می‌فهمد).
* هدرهای `X-Content-Type-Options`، `X-Frame-Options`، `Referrer-Policy` و `Permissions-Policy` هم از برنامه و هم از Nginx ارسال می‌شود.
* پس از اطمینان از کارکرد HTTPS می‌توانید خط `add_header Strict-Transport-Security …` را در فایل Nginx باز کنید.

## ۴) Basic Auth و محدودکردن دسترسی

دو راه (یکی کافی است):

1. **در خود برنامه:** `BASIC_AUTH_USER` و `BASIC_AUTH_PASSWORD` در `.env` (یا `install.sh --basic-auth admin`) ← `sudo systemctl restart capitalpilot`.
2. **در Nginx:**
   ```bash
   sudo apt install -y apache2-utils
   sudo htpasswd -c /etc/nginx/.capitalpilot.htpasswd admin
   # در server { ... }  →   auth_basic "CapitalPilot"; auth_basic_user_file /etc/nginx/.capitalpilot.htpasswd;
   ```
   برای محدودیت بر پایهٔ IP یا VPN، `allow 203.0.113.10; deny all;` را در `location /` بگذارید.

> **هشدار:** برنامه چندکاربره نیست و داده‌های مالی دارد؛ بدون Basic Auth/VPN آن را روی اینترنت عمومی باز نگذارید. Basic Auth بدون HTTPS رمز را آشکار می‌فرستد.

## ۵) دسترسی به Swagger (مدیر)

پیش‌فرض خاموش است. برای دیدن موقت:

```bash
# ۱) در .env: DOCS_ENABLED=true  ← sudo systemctl restart capitalpilot
# ۲) در فایل Nginx داخل location ~ ^/api/(docs|redoc|openapi\.json): خط  allow <IP شما>;  را باز کنید ← sudo nginx -t && sudo systemctl reload nginx
# پایان کار: DOCS_ENABLED=false و restart
```
یا بدون باز کردن برای اینترنت: `ssh -L 8000:127.0.0.1:8000 user@SERVER` و باز کردن `http://127.0.0.1:8000/api/docs` (در `.env` باید `DOCS_ENABLED=true` باشد).

## ۶) عیب‌یابی

| نشانه | علت/راه‌حل |
|---|---|
| ۴۰۰ Invalid host header | دامنه در `ALLOWED_HOSTS` نیست |
| ۵۰۲ | سرویس بالا نیست: `systemctl status capitalpilot`، پورت `upstream` با `--port` یکی باشد |
| ریدایرکت بی‌نهایت | `X-Forwarded-Proto` ارسال نمی‌شود؛ `include /etc/nginx/proxy_params;` را نگه دارید |
| بازیابی پشتیبان بزرگ ۴۱۳ | `client_max_body_size` را افزایش دهید |
| IP کاربر در لاگ ۱۲۷٫۰٫۰٫۱ | عادی است؛ `--forwarded-allow-ips=127.0.0.1` فقط به Nginx محلی اعتماد می‌کند |
