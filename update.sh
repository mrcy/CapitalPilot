#!/usr/bin/env bash
# به‌روزرسانی امن CapitalPilot از روی ZIP نسخهٔ جدید (یا پوشهٔ استخراج‌شده)، با پشتیبان، Migration، بررسی سلامت و بازگشت خودکار.
#
#   sudo ./update.sh /root/CapitalPilot-v2.5.0-production.zip [--sha256 SHA256SUMS.txt]
#   sudo ./update.sh --rollback [--with-db]          # بازگشت به نسخهٔ پیش از آخرین به‌روزرسانی
#
# هرگز .env، .venv، .install.conf و پوشهٔ داده را تغییر نمی‌دهد. اگر Migration یا راه‌اندازی شکست بخورد،
# کد قبلی و دیتابیس قبلی برگردانده و سرویس قبلی دوباره بالا می‌آید.
set -euo pipefail

SELF="${BASH_SOURCE[0]}"
APP_DIR="${CP_APP_DIR:-$(cd "$(dirname "$SELF")" && pwd)}"
# اسکریپت خودش را در پوشهٔ موقت کپی و از آنجا اجرا می‌کند تا جایگزینی فایل‌ها وسط اجرا مشکل نسازد.
if [ -z "${CP_UPDATE_REEXEC:-}" ]; then
  T="$(mktemp -d)"; mkdir -p "$T/deploy"
  cp "$APP_DIR/update.sh" "$T/update.sh"; cp "$APP_DIR/deploy/common.sh" "$T/deploy/common.sh"
  CP_UPDATE_REEXEC=1 CP_APP_DIR="$APP_DIR" CP_TMP_SELF="$T" exec bash "$T/update.sh" "$@"
fi
# shellcheck source=deploy/common.sh
. "$CP_TMP_SELF/deploy/common.sh"
trap 'rm -rf "$CP_TMP_SELF"' EXIT

SRC=""; SHA_FILE=""; ASSUME_YES=0; ROLLBACK=0; WITH_DB=0; ALLOW_DOWNGRADE=0; KEEP_SNAPSHOTS=5
while [ $# -gt 0 ]; do
  case "$1" in
    --sha256) SHA_FILE="${2:?}"; shift 2;;
    --rollback) ROLLBACK=1; shift;;
    --with-db) WITH_DB=1; shift;;
    --allow-downgrade) ALLOW_DOWNGRADE=1; shift;;
    --no-systemd) CP_NO_SYSTEMD=1; export CP_NO_SYSTEMD; shift;;
    -y|--yes) ASSUME_YES=1; shift;;
    -h|--help) sed -n '2,10p' "$CP_TMP_SELF/update.sh"; exit 0;;
    -*) die "گزینهٔ ناشناخته: $1";;
    *) SRC="$1"; shift;;
  esac
done

need_root "$@"
load_install_conf "$APP_DIR"
for t in unzip tar sha256sum curl; do command -v "$t" >/dev/null 2>&1 || die "$t لازم است (sudo apt install -y $t)"; done
DATA_DIR="$(env_get "$ENV_FILE" DATA_DIR)"; DATA_DIR="${DATA_DIR:-$APP_DIR/data}"
BACKUP_DIR="$(env_get "$ENV_FILE" BACKUP_DIR)"; BACKUP_DIR="${BACKUP_DIR:-$DATA_DIR/backups}"
SNAP_DIR="$BACKUP_DIR/releases"; mkdir -p "$SNAP_DIR"; chmod 700 "$SNAP_DIR"
USE_SYSTEMD=1; systemd_usable || USE_SYSTEMD=0
CUR="$(app_version "$APP_DIR")"
# مسیرهای مدیریت‌شدهٔ بسته؛ هر چیز دیگر (.env، .venv، .install.conf، data) دست‌نخورده می‌ماند.
MANAGED=(app deploy docs tests tools README.md VERSION RELEASE_NOTES_fa.md CHANGELOG.md requirements.txt requirements-dev.txt requirements.lock pyproject.toml Dockerfile docker-compose.yml .dockerignore .env.example install.sh update.sh backup.sh restore.sh run.sh)

stop_service()  { [ "$USE_SYSTEMD" -eq 1 ] && systemctl stop "$SERVICE_NAME" || true; }
start_service() { [ "$USE_SYSTEMD" -eq 1 ] && systemctl restart "$SERVICE_NAME" || true; }
verify_health() { [ "$USE_SYSTEMD" -eq 1 ] || { warn "systemd نیست؛ بررسی سلامت انجام نشد."; return 0; }; health_check "$PORT" "$1" 45 >/dev/null; }

put_code() {   # put_code DIR  — مسیرهای مدیریت‌شده را از DIR به APP_DIR می‌آورد
  local from="$1" p
  for p in "${MANAGED[@]}"; do
    rm -rf "${APP_DIR:?}/$p"
    [ -e "$from/$p" ] && cp -a "$from/$p" "$APP_DIR/$p"
  done
  chown -R root:root "$APP_DIR/app" "$APP_DIR/deploy" 2>/dev/null || true
  chmod -R go-w "$APP_DIR/app" "$APP_DIR/deploy"; chmod +x "$APP_DIR"/*.sh 2>/dev/null || true
}
snapshot_code() {   # snapshot_code LABEL
  local items=() p
  for p in "${MANAGED[@]}"; do [ -e "$APP_DIR/$p" ] && items+=("$p"); done
  tar -C "$APP_DIR" -czf "$SNAP_DIR/code-$1.tgz" "${items[@]}"
  chmod 600 "$SNAP_DIR/code-$1.tgz"
}
restore_code() {    # restore_code TGZ
  local t; t="$(mktemp -d)"; tar -C "$t" -xzf "$1"; put_code "$t"; rm -rf "$t"
}

reinstall_deps() {   # پس از بازگشت کد، وابستگی‌های همان نسخه را هم برمی‌گرداند (best-effort)
  local c=(); [ -f "$APP_DIR/requirements.lock" ] && c=(-c "$APP_DIR/requirements.lock")
  "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt" "${c[@]}" >/dev/null 2>&1 || "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt" >/dev/null 2>&1 || warn "بازگرداندن وابستگی‌های نسخهٔ قبلی ناموفق بود."
}

# ───────────────────────── بازگشت دستی
if [ "$ROLLBACK" -eq 1 ]; then
  LAST="$(ls -1t "$SNAP_DIR"/code-*.tgz 2>/dev/null | head -n1 || true)"
  [ -n "$LAST" ] || die "هیچ نسخهٔ قبلی برای بازگشت پیدا نشد ($SNAP_DIR)."
  log "بازگشت به $(basename "$LAST")"
  if [ "$WITH_DB" -eq 1 ]; then
    DBB="$(cat "${LAST%.tgz}.dbpath" 2>/dev/null || true)"
    [ -n "$DBB" ] && [ -f "$DBB" ] || die "پشتیبان دیتابیسِ متناظر پیدا نشد."
    warn "بازگردانی دیتابیس، همهٔ داده‌های ثبت‌شده بعد از به‌روزرسانی را حذف می‌کند (از وضعیت فعلی هم یک نسخهٔ ایمنی گرفته می‌شود)."
    [ "$ASSUME_YES" -eq 1 ] || { read -r -p "ادامه؟ [y/N] " a; [[ "$a" =~ ^[yY]$ ]] || die "لغو شد."; }
  fi
  manage backup --label before-rollback --keep 10 >/dev/null
  stop_service
  restore_code "$LAST"; reinstall_deps
  [ "$WITH_DB" -eq 1 ] && manage restore "$DBB" --yes
  start_service
  NEW="$(app_version "$APP_DIR")"
  verify_health "$NEW" && ok "بازگشت انجام شد؛ نسخهٔ فعال: $NEW" || die "پس از بازگشت سلامت برنامه تأیید نشد؛ journalctl -u $SERVICE_NAME"
  exit 0
fi

# ───────────────────────── ۱) آماده‌سازی بستهٔ جدید
[ -n "$SRC" ] || die "مسیر ZIP یا پوشهٔ نسخهٔ جدید را بدهید.  sudo ./update.sh CapitalPilot-vX.Y.Z-production.zip"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK" "$CP_TMP_SELF"' EXIT
if [ -d "$SRC" ]; then NEWROOT="$(cd "$SRC" && pwd)"
else
  [ -f "$SRC" ] || die "فایل پیدا نشد: $SRC"
  if [ -n "$SHA_FILE" ]; then
    log "بررسی SHA256"
    ( cd "$(dirname "$SRC")" && grep -F "$(basename "$SRC")" "$SHA_FILE" | sha256sum -c - ) >/dev/null 2>&1 || die "SHA256 فایل ZIP با $SHA_FILE نمی‌خواند؛ فایل خراب یا دستکاری شده است."
    ok "SHA256 تأیید شد"
  else warn "--sha256 داده نشد؛ سلامت ZIP بررسی نشد."; fi
  unzip -tq "$SRC" >/dev/null || die "ZIP معتبر نیست."
  unzip -q "$SRC" -d "$WORK/x"
  NEWROOT="$(find "$WORK/x" -maxdepth 3 -type f -path '*/app/main.py' -print -quit | xargs -r dirname | xargs -r dirname)"
fi
[ -n "${NEWROOT:-}" ] && [ -f "$NEWROOT/app/main.py" ] && [ -f "$NEWROOT/requirements.txt" ] || die "ساختار بستهٔ جدید معتبر نیست (app/main.py یا requirements.txt نیست)."
NEWV="$(app_version "$NEWROOT")"; [ "$NEWV" != "unknown" ] || die "فایل VERSION در بستهٔ جدید نیست."
# هیچ فایل حساس یا دیتابیسی نباید همراه بسته باشد
if [ -n "$(find "$NEWROOT" \( -name '.env' -o -name '*.db' -o -name '*.sqlite*' -o -name '.secret_key' \) -not -path '*/node_modules/*' -print -quit)" ]; then
  die "بستهٔ جدید حاوی فایل حساس/دیتابیس است (.env، *.db یا .secret_key)؛ به‌روزرسانی متوقف شد."
fi
log "به‌روزرسانی $CUR → $NEWV"
if [ "$CUR" = "$NEWV" ] && [ "$ASSUME_YES" -ne 1 ]; then warn "نسخهٔ جدید با نسخهٔ نصب‌شده یکی است."; read -r -p "باز هم ادامه می‌دهید؟ [y/N] " a; [[ "$a" =~ ^[yY]$ ]] || die "لغو شد."; fi
if [ "$(printf '%s\n%s\n' "$CUR" "$NEWV" | sort -V | head -n1)" != "$CUR" ] && [ "$CUR" != "$NEWV" ] && [ "$ALLOW_DOWNGRADE" -ne 1 ]; then die "نسخهٔ جدید ($NEWV) قدیمی‌تر از نسخهٔ نصب‌شده ($CUR) است؛ با --allow-downgrade (و ترجیحاً --rollback) اقدام کنید."; fi

# ───────────────────────── ۲) پشتیبان
STAMP="$(date +%Y%m%d-%H%M%S)"
log "۱/۶ پشتیبان دیتابیس، تنظیمات و کد فعلی"
DBBACKUP=""
if [ -f "$DATA_DIR/capitalpilot.db" ]; then
  DBBACKUP="$(manage backup --label pre-update --keep 10 | tail -n1)"
  ok "دیتابیس: $DBBACKUP"
fi
CFG="$SNAP_DIR/config-$STAMP"; mkdir -p "$CFG"; chmod 700 "$CFG"
cp -p "$ENV_FILE" "$CFG/env" 2>/dev/null || true
[ -f "$DATA_DIR/.secret_key" ] && cp -p "$DATA_DIR/.secret_key" "$CFG/secret_key" || true
cp -p "$APP_DIR/.install.conf" "$CFG/install.conf"; chmod -R go-rwx "$CFG"
snapshot_code "$CUR-$STAMP"
[ -z "$DBBACKUP" ] || { printf '%s\n' "$DBBACKUP" > "$SNAP_DIR/code-$CUR-$STAMP.dbpath"; chmod 600 "$SNAP_DIR/code-$CUR-$STAMP.dbpath"; }
ok "تنظیمات و کد فعلی: $SNAP_DIR (نگهداری ${KEEP_SNAPSHOTS} نسخهٔ آخر)"

rollback() {
  set +e
  warn "بازگشت به نسخهٔ قبلی ($CUR) ..."
  stop_service
  restore_code "$SNAP_DIR/code-$CUR-$STAMP.tgz"; reinstall_deps
  if [ -n "$DBBACKUP" ] && [ -f "$DBBACKUP" ]; then manage restore "$DBBACKUP" --yes >/dev/null && ok "دیتابیس قبلی برگردانده شد"; fi
  start_service
  if verify_health "$CUR"; then ok "نسخهٔ قبلی ($CUR) دوباره فعال و سالم است؛ داده‌ها حفظ شد."; else warn "سلامت نسخهٔ قبلی هم تأیید نشد؛ journalctl -u $SERVICE_NAME را ببینید. پشتیبان‌ها: $SNAP_DIR و $BACKUP_DIR"; fi
}

# ───────────────────────── ۳ تا ۶) جایگزینی، وابستگی‌ها، Migration، راه‌اندازی
log "۲/۶ توقف سرویس و جایگزینی کد"
stop_service
put_code "$NEWROOT"
ok "کد نسخهٔ $NEWV جایگزین شد (.env و داده دست‌نخورده)"

log "۳/۶ وابستگی‌ها"
CONSTRAINT=(); [ -f "$APP_DIR/requirements.lock" ] && CONSTRAINT=(-c "$APP_DIR/requirements.lock")
if ! "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt" "${CONSTRAINT[@]}" 2>"$WORK/pip.err" && ! "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt" 2>>"$WORK/pip.err"; then
  cat "$WORK/pip.err" >&2; warn "نصب وابستگی‌ها ناموفق بود."; rollback; exit 1
fi
"$APP_DIR/.venv/bin/python" -m compileall -q "$APP_DIR/app" >/dev/null 2>&1 || true
ok "وابستگی‌ها"

log "۴/۶ Migration دیتابیس"
if ! manage check >/dev/null || ! manage migrate; then warn "Migration/بررسی ناموفق بود."; rollback; exit 1; fi
ok "Migration انجام شد"

log "۵/۶ راه‌اندازی سرویس"
if [ "$USE_SYSTEMD" -eq 1 ]; then
  # واحدهای systemd از روی قالب‌های جدید ساخته می‌شوند فقط اگر خودِ کاربر ویرایششان نکرده باشد
  for u in "$SERVICE_NAME.service:capitalpilot.service.tmpl" "$SERVICE_NAME-backup.service:capitalpilot-backup.service.tmpl" "$SERVICE_NAME-backup.timer:capitalpilot-backup.timer.tmpl"; do
    f="$CP_UNIT_DIR/${u%%:*}"; [ -f "$f" ] || continue
    render "$APP_DIR/deploy/${u##*:}" APP_DIR="$APP_DIR" USER="$SERVICE_USER" PORT="$PORT" ENV_FILE="$ENV_FILE" DATA_DIR="$DATA_DIR" BACKUP_DIR="$BACKUP_DIR" LOG_DIR="$(env_get "$ENV_FILE" LOG_DIR)" > "$WORK/unit.new"
    cmp -s "$WORK/unit.new" "$f" || { install -m 644 "$WORK/unit.new" "$f.new"; warn "$f با قالب جدید فرق دارد؛ بازنویسی نشد. نسخهٔ پیشنهادی: $f.new"; }
  done
  systemctl daemon-reload
fi
start_service
log "۶/۶ بررسی سلامت"
if ! verify_health "$NEWV"; then
  journalctl -u "$SERVICE_NAME" -n 30 --no-pager 2>/dev/null || true
  warn "برنامهٔ نسخهٔ $NEWV سالم بالا نیامد."; rollback; exit 1
fi
ok "سلامت تأیید شد: نسخهٔ $NEWV"

# نگه‌داشتن فقط چند نسخهٔ آخر
ls -1t "$SNAP_DIR"/code-*.tgz 2>/dev/null | tail -n +$((KEEP_SNAPSHOTS + 1)) | while read -r f; do rm -f "$f" "${f%.tgz}.dbpath"; done
ls -1dt "$SNAP_DIR"/config-* 2>/dev/null | tail -n +$((KEEP_SNAPSHOTS + 1)) | xargs -r rm -rf
printf '\n%sبه‌روزرسانی %s → %s با موفقیت انجام شد.%s\n  بازگشت در صورت نیاز: sudo ./update.sh --rollback [--with-db]\n  پشتیبان پیش از به‌روزرسانی: %s\n' "$C_G" "$CUR" "$NEWV" "$C_0" "${DBBACKUP:-—}"
