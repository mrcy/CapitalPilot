#!/usr/bin/env bash
# نصب CapitalPilot روی Ubuntu 24.04 (Python 3.12 + systemd).  اجرا از داخل پوشهٔ استخراج‌شدهٔ ZIP، مثلاً /opt/capitalpilot:
#
#   sudo ./install.sh --domain capital.example.com
#
# این اسکریپت idempotent است و هرگز فایل .env، دیتابیس یا یک سرویس ویرایش‌شدهٔ موجود را بدون اجازهٔ شما بازنویسی نمی‌کند.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/common.sh
. "$APP_DIR/deploy/common.sh"

SERVICE_USER="capitalpilot"
PORT="8000"
DOMAIN=""
DATA_DIR="/var/lib/capitalpilot"
BACKUP_DIR=""
LOG_DIR="/var/log/capitalpilot"
ENV_FILE=""
ASSUME_YES=0
NO_START=0
BASIC_AUTH_USER_ARG=""
GEN_BASIC=0
INSTALL_NGINX=0
BACKUP_TIMER=1

usage() {
  cat <<USAGE
استفاده:  sudo ./install.sh [گزینه‌ها]

  --domain NAME         دامنه (برای ALLOWED_HOSTS و نمونهٔ Nginx)؛ پیشنهاد می‌شود حتماً بدهید
  --port N              پورت داخلی برنامه روی 127.0.0.1 (پیش‌فرض ${PORT})
  --user NAME           کاربر سیستمی سرویس (پیش‌فرض ${SERVICE_USER})
  --data-dir DIR        مسیر دیتابیس و کلید رمزنگاری (پیش‌فرض ${DATA_DIR})
  --backup-dir DIR      مسیر پشتیبان‌ها، غیرعمومی (پیش‌فرض DATA_DIR/backups)
  --log-dir DIR         مسیر لاگ برنامه (پیش‌فرض ${LOG_DIR})
  --env-file FILE       مسیر .env (پیش‌فرض APP_DIR/.env)
  --basic-auth USER     ساخت Basic Auth با رمز تصادفی (رمز فقط یک‌بار نمایش داده می‌شود)
  --nginx               نوشتن نمونهٔ تنظیم Nginx در /etc/nginx/sites-available (فعال نمی‌شود و بازنویسی نمی‌کند)
  --no-backup-timer     بدون تایمر پشتیبان شبانه
  --no-systemd          بدون ساخت سرویس systemd (فقط آماده‌سازی؛ اجرا دستی)
  --no-start            سرویس ساخته شود ولی راه‌اندازی نشود
  -y, --yes             بدون پرسش (پاسخ پیش‌فرض: بازنویسی نکن)
  -h, --help
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --domain) DOMAIN="${2:?}"; shift 2;;
    --port) PORT="${2:?}"; shift 2;;
    --user) SERVICE_USER="${2:?}"; shift 2;;
    --data-dir) DATA_DIR="${2:?}"; shift 2;;
    --backup-dir) BACKUP_DIR="${2:?}"; shift 2;;
    --log-dir) LOG_DIR="${2:?}"; shift 2;;
    --env-file) ENV_FILE="${2:?}"; shift 2;;
    --basic-auth) BASIC_AUTH_USER_ARG="${2:?}"; GEN_BASIC=1; shift 2;;
    --nginx) INSTALL_NGINX=1; shift;;
    --no-backup-timer) BACKUP_TIMER=0; shift;;
    --no-systemd) CP_NO_SYSTEMD=1; export CP_NO_SYSTEMD; shift;;
    --no-start) NO_START=1; shift;;
    -y|--yes) ASSUME_YES=1; shift;;
    -h|--help) usage; exit 0;;
    *) usage; die "گزینهٔ ناشناخته: $1";;
  esac
done
BACKUP_DIR="${BACKUP_DIR:-$DATA_DIR/backups}"
ENV_FILE="${ENV_FILE:-$APP_DIR/.env}"
[[ "$PORT" =~ ^[0-9]+$ ]] && [ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] || die "پورت نامعتبر: $PORT"
[[ "$SERVICE_USER" =~ ^[a-z_][a-z0-9_-]*$ ]] || die "نام کاربر نامعتبر: $SERVICE_USER"
[ -z "$DOMAIN" ] || [[ "$DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]] || die "دامنهٔ نامعتبر: $DOMAIN"

ask() {   # ask "سؤال" → 0 اگر بله؛ با --yes همیشه «نه» (امن‌ترین پاسخ)
  [ "$ASSUME_YES" -eq 1 ] && return 1
  [ -t 0 ] || return 1
  local a; read -r -p "$1 [y/N] " a; [[ "$a" =~ ^[yY]$ ]]
}

# ───────────────────────── ۱) پیش‌نیازها
log "۱/۹ بررسی پیش‌نیازها"
[ -f "$APP_DIR/app/main.py" ] && [ -f "$APP_DIR/requirements.txt" ] || die "این اسکریپت باید داخل پوشهٔ استخراج‌شدهٔ CapitalPilot اجرا شود."
need_root "$@"
if [ -r /etc/os-release ]; then
  . /etc/os-release
  if [ "${ID:-}" = "ubuntu" ] && [ "${VERSION_ID:-}" = "24.04" ]; then ok "Ubuntu 24.04"; else warn "سیستم‌عامل ${PRETTY_NAME:-نامشخص}؛ آزمون اصلی روی Ubuntu 24.04 است."; fi
fi
PY="$(find_python)" || die "Python 3.11+ پیدا نشد. روی Ubuntu 24.04:  sudo apt install -y python3 python3-venv python3-pip"
PYV="$("$PY" -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])')"
case "$PYV" in 3.12.*|3.13.*) ok "Python $PYV";; *) warn "Python $PYV (پیشنهادی ۳٫۱۲)";; esac
TMPV="$(mktemp -d)"; "$PY" -m venv "$TMPV/v" >/dev/null 2>&1 || { rm -rf "$TMPV"; die "ماژول venv نصب نیست:  sudo apt install -y python3-venv"; }
rm -rf "$TMPV"; ok "ماژول venv"
"$PY" -m pip --version >/dev/null 2>&1 || warn "pip سیستمی نیست (داخل venv ساخته می‌شود)."
command -v curl >/dev/null 2>&1 || die "curl لازم است:  sudo apt install -y curl"
FREE_KB="$(df -Pk "$APP_DIR" | awk 'NR==2{print $4}')"
[ "${FREE_KB:-0}" -gt 500000 ] || die "فضای آزاد دیسک کمتر از ۵۰۰ مگابایت است."
ok "فضای دیسک و curl"
LISTEN="$(command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | awk '{print $4}' || true)"
if grep -qE "[:.]${PORT}\$" <<<"$LISTEN"; then
  if systemd_usable && systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then ok "پورت $PORT را همین سرویس (نصب قبلی) دارد"; else die "پورت $PORT اشغال است؛ با --port پورت دیگری بدهید."; fi
fi
SCRATCH="$(mktemp -d)"; trap 'rm -rf "$SCRATCH"' EXIT; PIPERR="$SCRATCH/pip.err"; PROBELOG="$SCRATCH/probe.log"; chmod 755 "$SCRATCH"
case "$APP_DIR" in /home/*|/root/*) warn "برنامه زیر $APP_DIR است؛ سرویس systemd با ProtectHome اجرا می‌شود و به آن دسترسی ندارد. پیشنهاد: /opt/capitalpilot";; esac
USE_SYSTEMD=1; systemd_usable || { USE_SYSTEMD=0; warn "systemd در دسترس نیست یا --no-systemd داده شده؛ سرویس ساخته نمی‌شود."; }

# ───────────────────────── ۲) کاربر و پوشه‌ها
log "۲/۹ کاربر سرویس و پوشه‌ها"
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$DATA_DIR" --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
  ok "کاربر سیستمی $SERVICE_USER ساخته شد"
else ok "کاربر $SERVICE_USER از قبل هست"; fi
for d in "$DATA_DIR" "$BACKUP_DIR" "$LOG_DIR"; do mkdir -p "$d"; chown "$SERVICE_USER:$SERVICE_USER" "$d"; chmod 700 "$d"; done
ok "داده: $DATA_DIR | پشتیبان: $BACKUP_DIR | لاگ: $LOG_DIR (مجوز 700)"

# ───────────────────────── ۳ و ۴) محیط مجازی و وابستگی‌ها
log "۳/۹ محیط مجازی Python و وابستگی‌ها"
[ -x "$APP_DIR/.venv/bin/python" ] || "$PY" -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/python" -m pip install -q --upgrade pip
CONSTRAINT=()
[ -f "$APP_DIR/requirements.lock" ] && CONSTRAINT=(-c "$APP_DIR/requirements.lock")
if ! "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt" "${CONSTRAINT[@]}" 2>"$PIPERR"; then
  warn "نصب با نسخه‌های قفل‌شده ناموفق بود؛ تلاش بدون requirements.lock"
  "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt" || { cat "$PIPERR" >&2; die "نصب وابستگی‌ها ناموفق بود."; }
fi
"$APP_DIR/.venv/bin/python" -m compileall -q "$APP_DIR/app" >/dev/null 2>&1 || true   # کامپایل تحت root؛ سرویس به‌صورت فقط‌خواندنی اجرا می‌شود
ok "وابستگی‌ها نصب شد ($("$APP_DIR/.venv/bin/python" -c 'import fastapi,sqlalchemy;print("fastapi",fastapi.__version__,"sqlalchemy",sqlalchemy.__version__)'))"

# ───────────────────────── ۵) .env
log "۴/۹ فایل تنظیمات .env"
GENERATED_BASIC_PASS=""
if [ -f "$ENV_FILE" ]; then
  ok ".env موجود است و دست‌نخورده می‌ماند: $ENV_FILE"
  [ -z "$BASIC_AUTH_USER_ARG" ] || warn "--basic-auth نادیده گرفته شد چون .env از قبل وجود دارد."
else
  mkdir -p "$(dirname "$ENV_FILE")"
  ( umask 077; cp "$APP_DIR/.env.example" "$ENV_FILE" )
  SECRET="$("$PY" -c 'import secrets;print(secrets.token_urlsafe(48))')"
  env_set "$ENV_FILE" APP_ENV production
  env_set "$ENV_FILE" DOCS_ENABLED false
  env_set "$ENV_FILE" DATABASE_URL "sqlite:///$DATA_DIR/capitalpilot.db"
  env_set "$ENV_FILE" DATA_DIR "$DATA_DIR"
  env_set "$ENV_FILE" BACKUP_DIR "$BACKUP_DIR"
  env_set "$ENV_FILE" LOG_DIR "$LOG_DIR"
  env_set "$ENV_FILE" SECRET_KEY "$SECRET"
  [ -z "$DOMAIN" ] || env_set "$ENV_FILE" ALLOWED_HOSTS "$DOMAIN"
  if [ "$GEN_BASIC" -eq 1 ]; then
    GENERATED_BASIC_PASS="$("$PY" -c 'import secrets;print(secrets.token_urlsafe(18))')"
    env_set "$ENV_FILE" BASIC_AUTH_USER "$BASIC_AUTH_USER_ARG"
    env_set "$ENV_FILE" BASIC_AUTH_PASSWORD "$GENERATED_BASIC_PASS"
  fi
  ok ".env ساخته شد (مجوز 600؛ SECRET_KEY تصادفی، APP_ENV=production، DOCS_ENABLED=false)"
fi
# مسیرهای واقعی را از .env بخوان (اگر کاربر قبلاً تغییرشان داده باشد همان‌ها معتبرند)
DATA_DIR="$(env_get "$ENV_FILE" DATA_DIR)"; DATA_DIR="${DATA_DIR:-$APP_DIR/data}"
BACKUP_DIR="$(env_get "$ENV_FILE" BACKUP_DIR)"; BACKUP_DIR="${BACKUP_DIR:-$DATA_DIR/backups}"
LOG_DIR="$(env_get "$ENV_FILE" LOG_DIR)"; LOG_DIR="${LOG_DIR:-$DATA_DIR/logs}"
for d in "$DATA_DIR" "$BACKUP_DIR" "$LOG_DIR"; do mkdir -p "$d"; chown "$SERVICE_USER:$SERVICE_USER" "$d"; chmod 700 "$d"; done

# ───────────────────────── ۶) مجوزها
log "۵/۹ مجوزهای فایل"
chown "$SERVICE_USER:$SERVICE_USER" "$ENV_FILE"; chmod 600 "$ENV_FILE"
chown -R root:root "$APP_DIR/app" "$APP_DIR/deploy" 2>/dev/null || true
chmod -R go-w "$APP_DIR/app" "$APP_DIR/deploy"
chmod 755 "$APP_DIR"; chmod +x "$APP_DIR"/*.sh 2>/dev/null || true
# مسیر ENV_FILE باید برای کاربر سرویس قابل پیمایش باشد
case "$ENV_FILE" in "$APP_DIR"/*) :;; *) chmod 750 "$(dirname "$ENV_FILE")" 2>/dev/null || true; chgrp "$SERVICE_USER" "$(dirname "$ENV_FILE")" 2>/dev/null || true;; esac
[ -f "$DATA_DIR/capitalpilot.db" ] && chmod 600 "$DATA_DIR"/capitalpilot.db* 2>/dev/null || true
[ -f "$DATA_DIR/.secret_key" ] && chmod 600 "$DATA_DIR/.secret_key" || true
ok ".env=600 (مالک $SERVICE_USER)، پوشه‌های داده/پشتیبان=700، کد فقط‌خواندنی برای سرویس"
{
  printf '# ساخته‌شده توسط install.sh — برای update.sh/backup.sh/restore.sh لازم است. این فایل را حذف نکنید.\n'
  printf 'SERVICE_USER=%s\nSERVICE_NAME=%s\nPORT=%s\nENV_FILE=%s\nDOMAIN=%s\n' "$SERVICE_USER" "$SERVICE_NAME" "$PORT" "$ENV_FILE" "$DOMAIN"
} > "$APP_DIR/.install.conf"
chmod 644 "$APP_DIR/.install.conf"

# ───────────────────────── ۷) Migration
log "۶/۹ بررسی تنظیمات و Migration دیتابیس"
manage check || die "بررسی تنظیمات ناموفق بود (خروجی بالا را ببینید)."
[ ! -s "$DATA_DIR/capitalpilot.db" ] || ok "دیتابیس موجود است؛ پیش از هر تغییر طرح‌واره پشتیبان خودکار گرفته می‌شود"
manage migrate
ok "Migration انجام شد"

# ───────────────────────── ۸) systemd
write_unit() {   # write_unit DEST TEMPLATE
  local dest="$1" tpl="$2" tmp; tmp="$(mktemp)"
  render "$tpl" APP_DIR="$APP_DIR" USER="$SERVICE_USER" PORT="$PORT" ENV_FILE="$ENV_FILE" DATA_DIR="$DATA_DIR" BACKUP_DIR="$BACKUP_DIR" LOG_DIR="$LOG_DIR" > "$tmp"
  if [ ! -f "$dest" ]; then install -m 644 "$tmp" "$dest"; ok "ساخته شد: $dest"
  elif cmp -s "$tmp" "$dest"; then ok "بدون تغییر: $dest"
  elif ask "فایل $dest با نسخهٔ جدید فرق دارد (احتمالاً ویرایش کرده‌اید). بازنویسی شود؟"; then cp "$dest" "$dest.bak.$(date +%Y%m%d%H%M%S)"; install -m 644 "$tmp" "$dest"; ok "بازنویسی شد (نسخهٔ قبلی با پسوند .bak نگه داشته شد)"
  else install -m 644 "$tmp" "$dest.new"; warn "$dest را تغییر ندادم؛ نسخهٔ پیشنهادی در $dest.new است."; fi
  rm -f "$tmp"
}
log "۷/۹ سرویس systemd"
if [ "$USE_SYSTEMD" -eq 1 ]; then
  write_unit "$CP_UNIT_DIR/$SERVICE_NAME.service" "$APP_DIR/deploy/capitalpilot.service.tmpl"
  if [ "$BACKUP_TIMER" -eq 1 ]; then
    write_unit "$CP_UNIT_DIR/$SERVICE_NAME-backup.service" "$APP_DIR/deploy/capitalpilot-backup.service.tmpl"
    write_unit "$CP_UNIT_DIR/$SERVICE_NAME-backup.timer" "$APP_DIR/deploy/capitalpilot-backup.timer.tmpl"
  fi
  systemctl daemon-reload
  systemctl enable "$SERVICE_NAME" >/dev/null 2>&1 || true
  [ "$BACKUP_TIMER" -eq 1 ] && { systemctl enable --now "$SERVICE_NAME-backup.timer" >/dev/null 2>&1 || warn "فعال‌سازی تایمر پشتیبان ناموفق بود."; }
else
  warn "اجرای دستی:  sudo -u $SERVICE_USER env CAPITALPILOT_ENV_FILE=$ENV_FILE $APP_DIR/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port $PORT --workers 1 --proxy-headers"
fi

# ───────────────────────── Nginx (اختیاری، بدون فعال‌سازی)
if [ "$INSTALL_NGINX" -eq 1 ]; then
  [ -n "$DOMAIN" ] || die "--nginx نیازمند --domain است."
  NGX="/etc/nginx/sites-available/capitalpilot"
  if [ -d /etc/nginx/sites-available ]; then
    if [ -f "$NGX" ]; then warn "$NGX از قبل هست و بازنویسی نشد."; else render "$APP_DIR/deploy/nginx-capitalpilot.conf.tmpl" DOMAIN="$DOMAIN" PORT="$PORT" > "$NGX"; ok "نمونهٔ Nginx نوشته شد: $NGX (فعال‌سازی و HTTPS: docs/NGINX-HTTPS.md)"; fi
  else warn "Nginx نصب نیست؛ ابتدا: sudo apt install -y nginx"; fi
fi

# ───────────────────────── ۹) راه‌اندازی و بررسی وضعیت
log "۸/۹ راه‌اندازی سرویس"
VER="$(app_version "$APP_DIR")"
if [ "$USE_SYSTEMD" -eq 1 ] && [ "$NO_START" -eq 0 ]; then
  systemctl restart "$SERVICE_NAME"
  ok "سرویس راه‌اندازی شد"
elif [ "$NO_START" -eq 1 ]; then warn "--no-start: سرویس راه‌اندازی نشد."; fi
log "۹/۹ بررسی وضعیت"
if [ "$USE_SYSTEMD" -eq 1 ] && [ "$NO_START" -eq 0 ]; then
  if body="$(health_check "$PORT" "$VER" 45)"; then ok "سلامت برنامه: $body"
  else
    journalctl -u "$SERVICE_NAME" -n 30 --no-pager 2>/dev/null || true
    die "برنامه پس از راه‌اندازی پاسخ سالم نداد؛ لاگ بالا را ببینید (journalctl -u $SERVICE_NAME)."
  fi
  systemctl is-active --quiet "$SERVICE_NAME" && ok "systemd: active" || die "سرویس active نیست."
else
  # بدون systemd: یک اجرای آزمایشی کوتاه برای اطمینان از سالم بودن نصب
  as_user "$SERVICE_USER" env "CAPITALPILOT_ENV_FILE=$ENV_FILE" PYTHONDONTWRITEBYTECODE=1 "$APP_DIR/.venv/bin/uvicorn" app.main:app --host 127.0.0.1 --port "$PORT" --workers 1 >"$PROBELOG" 2>&1 &
  PROBE=$!
  stop_probe() { kill "$PROBE" 2>/dev/null || true; pkill -u "$SERVICE_USER" -f "uvicorn app.main:app --host 127.0.0.1 --port $PORT" 2>/dev/null || true; wait "$PROBE" 2>/dev/null || true; }
  if body="$(health_check "$PORT" "$VER" 30)"; then ok "اجرای آزمایشی سالم بود: $body"; else stop_probe; cat "$PROBELOG" >&2; die "اجرای آزمایشی ناموفق بود."; fi
  stop_probe
fi

cat <<DONE

${C_G}نصب CapitalPilot ${VER} کامل شد.${C_0}
  آدرس داخلی : http://127.0.0.1:${PORT}   (برای دسترسی بیرونی Nginx + HTTPS را طبق docs/NGINX-HTTPS.md تنظیم کنید)
  تنظیمات    : ${ENV_FILE}   (فقط روی همین سرور؛ پشتیبان بگیرید ولی در Git/ZIP نگذارید)
  داده       : ${DATA_DIR}   پشتیبان: ${BACKUP_DIR}
  وضعیت      : systemctl status ${SERVICE_NAME}  |  لاگ: journalctl -u ${SERVICE_NAME} -f
DONE
if [ -n "$GENERATED_BASIC_PASS" ]; then
  printf '\n%sBasic Auth ساخته شد (فقط همین یک‌بار نمایش داده می‌شود؛ در .env هم ذخیره شد):%s\n  کاربر: %s\n  رمز  : %s\n' "$C_Y" "$C_0" "$BASIC_AUTH_USER_ARG" "$GENERATED_BASIC_PASS"
fi
