# امنیت و بازبینی Production — CapitalPilot 2.4.0

## چه چیزی پیاده شده است

| موضوع | وضعیت |
|---|---|
| `.env` فقط روی سرور | در ZIP و Git نیست (`.gitignore`، `.dockerignore`، و آزمون خودکار). `install.sh` آن را از `.env.example` می‌سازد، `SECRET_KEY` تصادفی می‌گذارد و مجوز `600` می‌دهد. `update.sh` هرگز آن را عوض نمی‌کند |
| کلید API به فرانت‌اند نمی‌رسد | کلیدها با Fernet رمز و فقط‌نوشتنی‌اند؛ پاسخ API فقط `has_api_key` دارد؛ در پشتیبان JSON و در جاوااسکریپت نیستند (آزمون‌های موجود) |
| دیتابیس | مجوز `600` (برنامه در هر راه‌اندازی اعمال می‌کند)، پوشهٔ داده `700` در production، `UMask=0077` در واحد systemd |
| مسیر Backup غیرعمومی | پوشهٔ `700` بیرون از `app/static`؛ تنها مسیر ایستا `/static` است؛ `manage check` در production اگر پشتیبان زیر static باشد خطا می‌دهد. دانلود پشتیبان JSON فقط از `/api` (پشت Basic Auth) |
| Debug خاموش | برنامه هیچ حالت debug/reload ندارد؛ واحد systemd بدون `--reload`، بدون access-log و با `--no-server-header` |
| خطاهای حساس | خطای ۵۰۰ پیام عمومی فارسی می‌دهد و traceback فقط در لاگ است؛ خطاهای اعتبارسنجی بدون جزئیات داخلی (آزمون: `tests/test_release.py`) |
| Trusted Hosts | `ALLOWED_HOSTS` (ویرگول‌جدا). خالی = بدون محدودیت (فقط هشدار در لاگ production). `localhost`/`127.0.0.1` همیشه مجازند (برای health check). `install.sh --domain` آن را تنظیم می‌کند |
| CORS | پیش‌فرض **بسته** (رابط کاربری با همان سرور سرو می‌شود و CORS لازم ندارد). فقط مبداهای صریح در `CORS_ORIGINS`؛ `*` نادیده گرفته می‌شود؛ بدون credentials |
| Swagger | `DOCS_ENABLED=false` (مسیرها ۴۰۴)؛ در Nginx هم با `allow/deny` بسته است؛ دسترسی مدیر با تونل SSH یا IP مجاز |
| HTTPS | HSTS روی اتصال HTTPS در production؛ گواهی با certbot |
| سربرگ‌ها | `X-Content-Type-Options`، `X-Frame-Options`، `Referrer-Policy`، `Permissions-Policy`، `Cache-Control: no-store` برای `/api/` |
| Basic Auth | اختیاری، مقایسهٔ زمان‌ثابت؛ برای سرور عمومی **حتماً** فعال کنید (یا VPN/IP allow) |
| سخت‌سازی systemd | کاربر غیر root بدون shell، `NoNewPrivileges`، `ProtectSystem=strict` (فقط پوشه‌های داده/پشتیبان/لاگ قابل‌نوشتن)، `ProtectHome`، `PrivateTmp`، `CapabilityBoundingSet` خالی، فقط `127.0.0.1` |
| SSRF منابع قیمت | آدرس‌های داخلی مسدود، فهرست میزبان مجاز اختیاری |
| بدون معامله خودکار | هیچ سفارش خرید/فروشی ساخته یا ارسال نمی‌شود؛ جست‌وجو و اتصال بدون تأیید صریح دادهٔ مالی را تغییر نمی‌دهند |

## محدودیت‌های شناخته‌شده (صادقانه)

* برنامه **تک‌کاربره** است؛ احراز هویت فقط Basic Auth (یک جفت کاربر/رمز) است و قفل‌شدن پس از تلاش ناموفق ندارد. محدودیت نرخ فقط در Nginx (`limit_req`) است. روی اینترنت عمومی حتماً HTTPS و رمز قوی (یا VPN) استفاده کنید.
* CSRF مخصوص ندارد؛ چون Basic Auth در مرورگر ارسال خودکار می‌شود، CORS بسته می‌ماند و `X-Frame-Options` فعال است. اگر نگرانید، دسترسی را با VPN/IP محدود کنید.
* پشتیبان‌های روی دیسک رمزنگاری نیستند (فقط مجوز فایل). برای خروجی‌های خارج از سرور از `backup.sh --encrypt` استفاده کنید و دیسک سرور را رمز کنید (LUKS) اگر لازم است.
* بررسی امنیتی خودکار وابستگی‌ها انجام نشد؛ `requirements.lock` نسخه‌ها را ثابت می‌کند. دوره‌ای `pip list --outdated` و به‌روزرسانی امنیتی Ubuntu (`unattended-upgrades`) را انجام دهید.
* Python 3.12 / Ubuntu 24.04 / Nginx / certbot / Docker در محیط ساخت اجرا نشدند (راهنماها را اولین‌بار با دقت اجرا کنید).

## فهرست بازبینی قبل از باز کردن به اینترنت

```bash
sudo -u capitalpilot env CAPITALPILOT_ENV_FILE=/opt/capitalpilot/.env /opt/capitalpilot/.venv/bin/python -m app.manage check   # هشدارهای «⚠» نباید باقی بماند
stat -c '%a %U %n' /opt/capitalpilot/.env /var/lib/capitalpilot /var/lib/capitalpilot/capitalpilot.db /var/lib/capitalpilot/backups   # 600 / 700 / 600 / 700
curl -sI https://DOMAIN/api/docs | head -1        # 404 یا 403
curl -sI -H 'Host: evil.example' http://SERVER_IP/ | head -1   # 400
curl -s https://DOMAIN/api/health                 # بدون رمز: 401
sudo ss -ltnp | grep 8000                         # فقط 127.0.0.1:8000
```
