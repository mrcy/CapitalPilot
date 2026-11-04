#!/usr/bin/env bash
# توابع مشترک install.sh / update.sh / backup.sh / restore.sh — این فایل را مستقیم اجرا نکنید.
# shellcheck shell=bash

if [ -t 1 ]; then C_R=$'\e[31m'; C_G=$'\e[32m'; C_Y=$'\e[33m'; C_B=$'\e[1m'; C_0=$'\e[0m'; else C_R=""; C_G=""; C_Y=""; C_B=""; C_0=""; fi
log()  { printf '%s[CapitalPilot]%s %s\n' "$C_B" "$C_0" "$*"; }
ok()   { printf '  %s✓%s %s\n' "$C_G" "$C_0" "$*"; }
warn() { printf '  %s⚠%s %s\n' "$C_Y" "$C_0" "$*" >&2; }
die()  { printf '  %s✗ %s%s\n' "$C_R" "$*" "$C_0" >&2; exit 1; }

# ---- مسیرها و مقادیر پیش‌فرض (همه با متغیر محیطی یا گزینهٔ خط فرمان قابل تغییرند)
CP_UNIT_DIR="${CP_UNIT_DIR:-/etc/systemd/system}"
SERVICE_NAME="${SERVICE_NAME:-capitalpilot}"

need_root() { [ "$(id -u)" -eq 0 ] || die "این دستور باید با دسترسی root اجرا شود:  sudo $0 ${*:-}"; }

as_user() {   # as_user USER cmd...   (اجرای دستور با کاربر سرویس)
  local u="$1"; shift
  if [ "$(id -un)" = "$u" ]; then "$@"; elif command -v runuser >/dev/null 2>&1; then runuser -u "$u" -- "$@"; else sudo -u "$u" -- "$@"; fi
}

# ---- خواندن/نوشتن .env (بدون source کردن؛ مقدارها هرگز اجرا نمی‌شوند)
env_get() {   # env_get FILE KEY
  [ -f "$1" ] || return 0
  local line; line="$(grep -E "^[[:space:]]*$2=" "$1" | tail -n1 || true)"
  line="${line#*=}"; line="${line%%[[:space:]]#*}"; line="${line%\"}"; line="${line#\"}"
  printf '%s' "$line"
}
env_set() {   # env_set FILE KEY VALUE  — کلید موجود را به‌روز یا اضافه می‌کند (فقط هنگام ساخت اولیهٔ .env صدا زده می‌شود)
  local f="$1" k="$2" v="$3" tmp
  tmp="$(mktemp)"
  if grep -qE "^[#[:space:]]*$k=" "$f"; then
    awk -v k="$k" -v v="$v" 'BEGIN{done=0} { if (!done && $0 ~ "^[#[:space:]]*" k "=") { print k "=" v; done=1 } else print }' "$f" > "$tmp"
  else
    { cat "$f"; printf '%s=%s\n' "$k" "$v"; } > "$tmp"
  fi
  cat "$tmp" > "$f"; rm -f "$tmp"
}

# ---- Python
find_python() {   # نخستین مفسر ۳٫۱۲، وگرنه ۳٫۱۱+ ؛ خروجی: مسیر
  local c v
  for c in "${PYTHON:-}" python3.12 python3.13 python3 python3.11; do
    [ -n "$c" ] || continue
    command -v "$c" >/dev/null 2>&1 || continue
    v="$("$c" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || true)"
    case "$v" in 3.11|3.12|3.13|3.14) command -v "$c"; return 0;; esac
  done
  return 1
}

# ---- systemd
systemd_usable() {
  [ "${CP_NO_SYSTEMD:-0}" = "1" ] && return 1
  command -v systemctl >/dev/null 2>&1 || return 1
  systemctl is-system-running >/dev/null 2>&1 || systemctl show --property=Version >/dev/null 2>&1
}
svc() { systemctl "$@" "$SERVICE_NAME" ; }

render() {    # render TEMPLATE  KEY=VALUE...   (جای‌گذاری @KEY@)
  local tpl="$1"; shift
  local out; out="$(cat "$tpl")"
  local kv k v
  for kv in "$@"; do k="${kv%%=*}"; v="${kv#*=}"; out="${out//@$k@/$v}"; done
  printf '%s\n' "$out"
}

# ---- بررسی سلامت: نسخهٔ مورد انتظار را هم کنترل می‌کند
health_check() {   # health_check PORT [EXPECTED_VERSION] [TRIES]
  local port="$1" want="${2:-}" tries="${3:-40}" i body bu bp
  bu="$(env_get "${ENV_FILE:-}" BASIC_AUTH_USER)"; bp="$(env_get "${ENV_FILE:-}" BASIC_AUTH_PASSWORD)"
  for i in $(seq 1 "$tries"); do
    # اگر Basic Auth فعال است، اطلاعات آن از .env خوانده می‌شود و از طریق stdin به curl می‌رسد (در فهرست فرایندها دیده نمی‌شود)
    if [ -n "$bu" ] && [ -n "$bp" ]; then
      body="$(printf 'user = "%s:%s"\n' "$bu" "$bp" | curl -fsS --max-time 3 -K - "http://127.0.0.1:${port}/api/health" 2>/dev/null || true)"
    else
      body="$(curl -fsS --max-time 3 "http://127.0.0.1:${port}/api/health" 2>/dev/null || true)"
    fi
    if [ -n "$body" ] && grep -q '"status"[[:space:]]*:[[:space:]]*"ok"' <<<"$body"; then
      if [ -z "$want" ] || grep -q "\"version\"[[:space:]]*:[[:space:]]*\"$want\"" <<<"$body"; then
        printf '%s' "$body"; return 0
      fi
    fi
    sleep 1
  done
  return 1
}

app_version() { [ -f "$1/VERSION" ] && tr -d '[:space:]' < "$1/VERSION" || echo "unknown"; }

load_install_conf() {   # load_install_conf APP_DIR  → SERVICE_USER PORT ENV_FILE
  local f="$1/.install.conf"
  [ -f "$f" ] || die "نصب قبلی پیدا نشد ($f). ابتدا install.sh را اجرا کنید."
  SERVICE_USER="$(env_get "$f" SERVICE_USER)"; PORT="$(env_get "$f" PORT)"; ENV_FILE="$(env_get "$f" ENV_FILE)"
  SERVICE_NAME="$(env_get "$f" SERVICE_NAME)"; SERVICE_NAME="${SERVICE_NAME:-capitalpilot}"
  [ -n "$SERVICE_USER" ] && [ -n "$PORT" ] && [ -n "$ENV_FILE" ] || die "فایل $f ناقص است."
}

runtime_env() {   # متغیرهای محیطیِ لازم برای اجرای app.manage با همان .env سرویس
  printf 'CAPITALPILOT_ENV_FILE=%s PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=%s' "$ENV_FILE" "$APP_DIR"
}
manage() {   # manage ARGS...  (با کاربر سرویس و .env همان نصب)
  ( cd "$APP_DIR" && as_user "$SERVICE_USER" env "CAPITALPILOT_ENV_FILE=$ENV_FILE" PYTHONDONTWRITEBYTECODE=1 "$APP_DIR/.venv/bin/python" -m app.manage "$@" )
}
