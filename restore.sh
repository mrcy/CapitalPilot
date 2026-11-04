#!/usr/bin/env bash
# بازیابی دیتابیس از یک پشتیبان (فایل .db، یا آرشیو backup.sh با پسوند .tar.gz / .tar.gz.enc).
#
#   sudo ./restore.sh /path/to/capitalpilot-backup-2.4.0-....tar.gz[.enc] [--restore-secrets] [--yes]
#   sudo ./restore.sh /var/lib/capitalpilot/backups/capitalpilot-daily-....db
#
# مراحل: بررسی سلامت فایل ← توقف سرویس ← نسخهٔ ایمنی از دیتابیس فعلی ← جایگزینی ← migrate ← راه‌اندازی ← بررسی سلامت.
# اگر بازیابی/راه‌اندازی شکست بخورد، دیتابیس قبلی خودکار برگردانده می‌شود.
set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/common.sh
. "$APP_DIR/deploy/common.sh"
SRC=""; YES=0; RSEC=0
while [ $# -gt 0 ]; do
  case "$1" in --yes|-y) YES=1; shift;; --restore-secrets) RSEC=1; shift;; --no-systemd) CP_NO_SYSTEMD=1; export CP_NO_SYSTEMD; shift;;
    -h|--help) sed -n '2,9p' "$0"; exit 0;; -*) die "گزینهٔ ناشناخته: $1";; *) SRC="$1"; shift;; esac
done
[ -f "$SRC" ] || die "فایل پشتیبان را بدهید.  sudo ./restore.sh FILE"
need_root "$@"
load_install_conf "$APP_DIR"
DATA_DIR="$(env_get "$ENV_FILE" DATA_DIR)"; DATA_DIR="${DATA_DIR:-$APP_DIR/data}"
USE_SYSTEMD=1; systemd_usable || USE_SYSTEMD=0
W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT; chmod 755 "$W"
FILE="$SRC"
if [[ "$FILE" == *.enc ]]; then
  [ -n "${BACKUP_PASSPHRASE:-}" ] || { read -r -s -p "رمز پشتیبان: " BACKUP_PASSPHRASE; echo; }; export BACKUP_PASSPHRASE
  openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -in "$FILE" -out "$W/a.tar.gz" -pass env:BACKUP_PASSPHRASE 2>/dev/null || die "رمزگشایی ناموفق (رمز اشتباه یا فایل خراب)."
  FILE="$W/a.tar.gz"
fi
if [[ "$FILE" == *.tar.gz ]]; then
  [ ! -f "$SRC.sha256" ] || ( cd "$(dirname "$SRC")" && sha256sum -c "$(basename "$SRC").sha256" >/dev/null ) || die "SHA256 پشتیبان نمی‌خواند."
  tar -C "$W" -xzf "$FILE"
  DB="$(ls "$W"/*.db 2>/dev/null | head -n1 || true)"; [ -n "$DB" ] || die "داخل آرشیو فایل .db پیدا نشد."
  if [ -f "$W/manifest.json" ]; then ok "پشتیبان نسخهٔ $(grep -o '"version": *"[^"]*"' "$W/manifest.json" | cut -d'"' -f4) ساخته‌شده در $(grep -o '"created_at": *"[^"]*"' "$W/manifest.json" | cut -d'"' -f4)"; fi
else DB="$FILE"; fi
chmod 644 "$DB"
if [ "$YES" -ne 1 ]; then
  warn "دیتابیس فعلی با این پشتیبان جایگزین می‌شود (از وضعیت فعلی نسخهٔ ایمنی گرفته می‌شود)."
  read -r -p "ادامه؟ [y/N] " a; [[ "$a" =~ ^[yY]$ ]] || die "لغو شد."
fi
# اعتبارسنجی اولیهٔ فایل پیش از توقف سرویس (بدون --yes فقط سلامت فایل را می‌سنجد و عمداً خطا می‌دهد)
PRECHECK="$(manage restore "$DB" 2>&1 || true)"
case "$PRECHECK" in *--yes*) ;; *) die "فایل پشتیبان سالم نیست یا خوانده نشد: $PRECHECK";; esac
ok "فایل پشتیبان سالم است"
STAMP="$(date +%Y%m%d-%H%M%S)"
log "توقف سرویس"
[ "$USE_SYSTEMD" -eq 1 ] && systemctl stop "$SERVICE_NAME" || true
SAFETY="$(manage backup --label before-restore --keep 10 2>/dev/null | tail -n1 || true)"
[ -z "$SAFETY" ] || ok "نسخهٔ ایمنی دیتابیس فعلی: $SAFETY"
rollback() {
  set +e
  warn "بازیابی ناموفق بود؛ دیتابیس قبلی برگردانده می‌شود"
  [ -n "$SAFETY" ] && [ -f "$SAFETY" ] && manage restore "$SAFETY" --yes >/dev/null
  [ "$USE_SYSTEMD" -eq 1 ] && systemctl restart "$SERVICE_NAME"
}
if [ "$RSEC" -eq 1 ]; then
  if [ -f "$W/env" ]; then
    cp -p "$ENV_FILE" "$ENV_FILE.pre-restore-$STAMP" 2>/dev/null || true
    ( umask 077; cp "$W/env" "$ENV_FILE" ); chown "$SERVICE_USER:$SERVICE_USER" "$ENV_FILE"; chmod 600 "$ENV_FILE"
    ok ".env بازگردانده شد (نسخهٔ قبلی: $ENV_FILE.pre-restore-$STAMP)"
  else warn "آرشیو شامل .env نیست (با --with-secrets ساخته نشده)."; fi
  if [ -f "$W/secret_key" ]; then
    [ ! -f "$DATA_DIR/.secret_key" ] || cp -p "$DATA_DIR/.secret_key" "$DATA_DIR/.secret_key.pre-restore-$STAMP"
    ( umask 077; cp "$W/secret_key" "$DATA_DIR/.secret_key" ); chown "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR/.secret_key"; chmod 600 "$DATA_DIR/.secret_key"
    ok "کلید رمزنگاری بازگردانده شد"
  fi
fi
if ! manage restore "$DB" --yes; then rollback; die "بازیابی ناموفق بود."; fi
if ! manage migrate; then rollback; die "Migration پس از بازیابی ناموفق بود؛ دیتابیس قبلی برگردانده شد."; fi
[ "$USE_SYSTEMD" -eq 1 ] && systemctl restart "$SERVICE_NAME" || true
if [ "$USE_SYSTEMD" -eq 1 ]; then
  if health_check "$PORT" "$(app_version "$APP_DIR")" 45 >/dev/null; then ok "سرویس سالم است"; else rollback; die "سرویس پس از بازیابی سالم بالا نیامد؛ دیتابیس قبلی برگردانده شد."; fi
fi
ok "بازیابی کامل شد. اگر از Basic Auth/کلید دیگری استفاده می‌کردید، به SECRET_KEY توجه کنید (docs/BACKUP-RESTORE.md)."
