#!/usr/bin/env bash
# پشتیبان کامل برای انتقال یا نگه‌داری بیرونی: دیتابیس (سازگار با WAL) + مانیفست؛ با --with-secrets شامل .env و کلید رمزنگاری هم می‌شود.
#
#   sudo ./backup.sh [--out DIR] [--with-secrets] [--encrypt]
#
# --encrypt  : خروجی با AES-256 (openssl، PBKDF2) رمز می‌شود؛ رمز از متغیر BACKUP_PASSPHRASE یا پرسش تعاملی.
# هشدار: بدون --encrypt فایل شامل اطلاعات مالی (و با --with-secrets شامل رمزها) است؛ آن را فقط با روش امن (scp/sftp) منتقل کنید.
# پشتیبان‌ها را هرگز داخل ZIP برنامه، Git یا پوشهٔ عمومی وب نگذارید.
set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/common.sh
. "$APP_DIR/deploy/common.sh"
OUT=""; SECRETS=0; ENC=0
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="${2:?}"; shift 2;; --with-secrets) SECRETS=1; shift;; --encrypt) ENC=1; shift;;
    -h|--help) sed -n '2,9p' "$0"; exit 0;; *) die "گزینهٔ ناشناخته: $1";;
  esac
done
need_root "$@"
load_install_conf "$APP_DIR"
DATA_DIR="$(env_get "$ENV_FILE" DATA_DIR)"; DATA_DIR="${DATA_DIR:-$APP_DIR/data}"
BACKUP_DIR="$(env_get "$ENV_FILE" BACKUP_DIR)"; BACKUP_DIR="${BACKUP_DIR:-$DATA_DIR/backups}"
OUT="${OUT:-$BACKUP_DIR/export}"; mkdir -p "$OUT"; chmod 700 "$OUT"
STAMP="$(date +%Y%m%d-%H%M%S)"; W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT; chmod 700 "$W"; chown "$SERVICE_USER:$SERVICE_USER" "$W"
DB="$(manage backup --dir "$W" --label export | tail -n1)"
[ -f "$DB" ] || die "پشتیبان دیتابیس ساخته نشد."
VER="$(app_version "$APP_DIR")"
{ printf '{\n  "app": "CapitalPilot",\n  "version": "%s",\n  "created_at": "%s",\n  "database": "%s",\n  "sha256": "%s",\n  "includes_secrets": %s\n}\n' \
    "$VER" "$(date -Is)" "$(basename "$DB")" "$(sha256sum "$DB" | cut -d' ' -f1)" "$([ "$SECRETS" -eq 1 ] && echo true || echo false)"; } > "$W/manifest.json"
FILES=("$(basename "$DB")" manifest.json)
if [ "$SECRETS" -eq 1 ]; then
  cp -p "$ENV_FILE" "$W/env"; FILES+=(env)
  [ -f "$DATA_DIR/.secret_key" ] && { cp -p "$DATA_DIR/.secret_key" "$W/secret_key"; FILES+=(secret_key); }
  [ "$ENC" -eq 1 ] || warn "فایل شامل رمزها و کلید رمزنگاری است؛ حتماً --encrypt بزنید یا آن را امن نگه دارید."
fi
ARCHIVE="$OUT/capitalpilot-backup-$VER-$STAMP.tar.gz"
( umask 077; tar -C "$W" -czf "$ARCHIVE" "${FILES[@]}" )
if [ "$ENC" -eq 1 ]; then
  command -v openssl >/dev/null || die "openssl لازم است."
  if [ -z "${BACKUP_PASSPHRASE:-}" ]; then read -r -s -p "رمز رمزنگاری پشتیبان: " BACKUP_PASSPHRASE; echo; read -r -s -p "تکرار رمز: " P2; echo; [ "$BACKUP_PASSPHRASE" = "$P2" ] || die "رمزها یکی نیست."; fi
  export BACKUP_PASSPHRASE
  ( umask 077; openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -in "$ARCHIVE" -out "$ARCHIVE.enc" -pass env:BACKUP_PASSPHRASE )
  shred -u "$ARCHIVE" 2>/dev/null || rm -f "$ARCHIVE"; ARCHIVE="$ARCHIVE.enc"
fi
chmod 600 "$ARCHIVE"
( cd "$OUT" && sha256sum "$(basename "$ARCHIVE")" > "$(basename "$ARCHIVE").sha256" )
ok "پشتیبان ساخته شد: $ARCHIVE"
printf '  SHA256: %s\n  انتقال امن:  scp %s user@host:/safe/path/\n' "$(cut -d' ' -f1 "$ARCHIVE.sha256")" "$ARCHIVE"
